"""
session_automation.py - Automated lesson and quiz generation for confirmed sessions

Provides:
- build_lesson_for_session(session_id) - Generate personalized lesson when session confirmed
- build_next_quiz_from_lesson(session_id) - Generate quiz from lesson artifact
- on_session_confirmed(session_id, teacher_id) - Main hook for confirmation flow
"""

import json
import logging
import asyncio
from typing import Optional, Dict, Any

from app.services.ai_client import ai_chat
from app.services.prompts import load_prompt
import aiosqlite
from app.db import learning_loop as ll

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1.0.0"

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


async def get_session_details(db, session_id: int) -> Optional[Dict[str, Any]]:
    """Get full session details including student info."""
    cursor = await db.execute(
        """SELECT s.id, s.student_id, s.teacher_id, s.scheduled_at, s.duration_min,
                  s.status, s.notes,
                  st.name as student_name, st.current_level, st.goals, st.problem_areas
           FROM sessions s
           JOIN users st ON st.id = s.student_id
           WHERE s.id = ?""",
        (session_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return dict(row)


async def get_student_context(db, student_id: int) -> Dict[str, Any]:
    """Gather all context needed for lesson generation."""
    context = {
        "learning_plan": None,
        "profile": {},
        "progress_history": [],
        "previous_topics": [],
        "quiz_weak_areas": [],
        "session_count": 0,
    }

    # Get latest learning plan
    plan = await ll.get_latest_learning_plan(db, student_id)
    if plan:
        context["learning_plan"] = plan.get("plan_json", {})
        context["profile"]["profile_summary"] = plan.get("summary", "")

    # Get learner profile if no learning plan
    if not context["learning_plan"]:
        cursor = await db.execute(
            """SELECT gaps, priorities, profile_summary, recommended_start_level
               FROM learner_profiles WHERE student_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (student_id,)
        )
        profile_row = await cursor.fetchone()
        if profile_row:
            profile = dict(profile_row)
            for field in ['gaps', 'priorities']:
                if profile.get(field) and isinstance(profile[field], str):
                    try:
                        profile[field] = json.loads(profile[field])
                    except:
                        profile[field] = []
            context["profile"] = profile

    # Get progress history (last 10 lessons)
    cursor = await db.execute(
        """SELECT p.score, p.areas_improved, p.areas_struggling, p.completed_at,
                  l.objective, l.difficulty
           FROM progress p
           LEFT JOIN lessons l ON l.id = p.lesson_id
           WHERE p.student_id = ?
           ORDER BY p.completed_at DESC
           LIMIT 10""",
        (student_id,)
    )
    progress_rows = await cursor.fetchall()
    for row in progress_rows:
        entry = dict(row)
        for field in ['areas_improved', 'areas_struggling']:
            if entry.get(field) and isinstance(entry[field], str):
                try:
                    entry[field] = json.loads(entry[field])
                except:
                    entry[field] = []
        context["progress_history"].append(entry)

    # Get previous lesson topics from lesson_artifacts
    cursor = await db.execute(
        """SELECT topics_json, lesson_json FROM lesson_artifacts
           WHERE student_id = ?
           ORDER BY created_at DESC
           LIMIT 5""",
        (student_id,)
    )
    artifact_rows = await cursor.fetchall()
    for row in artifact_rows:
        topics = row["topics_json"]
        if topics:
            try:
                topics_dict = json.loads(topics) if isinstance(topics, str) else topics
                if isinstance(topics_dict, dict):
                    for topic_list in topics_dict.values():
                        if isinstance(topic_list, list):
                            context["previous_topics"].extend(topic_list)
            except:
                pass
        # Also extract from lesson_json objective
        lesson = row["lesson_json"]
        if lesson:
            try:
                lesson_dict = json.loads(lesson) if isinstance(lesson, str) else lesson
                if lesson_dict.get("objective"):
                    context["previous_topics"].append(lesson_dict["objective"][:50])
            except:
                pass

    # Get weak areas from recent quiz attempts
    cursor = await db.execute(
        """SELECT qai.skill_tag, qai.is_correct
           FROM quiz_attempt_items qai
           JOIN quiz_attempts qa ON qa.id = qai.attempt_id
           WHERE qa.student_id = ?
           ORDER BY qa.started_at DESC
           LIMIT 50""",
        (student_id,)
    )
    item_rows = await cursor.fetchall()
    skill_scores = {}
    for row in item_rows:
        tag = row["skill_tag"]
        if tag:
            if tag not in skill_scores:
                skill_scores[tag] = {"correct": 0, "total": 0}
            skill_scores[tag]["total"] += 1
            if row["is_correct"]:
                skill_scores[tag]["correct"] += 1

    # Skills with < 60% accuracy are weak areas
    for tag, scores in skill_scores.items():
        if scores["total"] >= 2:
            accuracy = scores["correct"] / scores["total"]
            if accuracy < 0.6:
                context["quiz_weak_areas"].append(tag)

    # Count total sessions for session_number
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM sessions WHERE student_id = ? AND status IN ('confirmed', 'completed')",
        (student_id,)
    )
    count_row = await cursor.fetchone()
    context["session_count"] = count_row["cnt"] if count_row else 0

    return context


async def lesson_artifact_exists_for_session(db, session_id: int) -> bool:
    """Check if a lesson artifact already exists for this session."""
    cursor = await db.execute(
        "SELECT id FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    return await cursor.fetchone() is not None


async def quiz_exists_for_session(db, session_id: int) -> bool:
    """Check if a quiz already exists for this session."""
    cursor = await db.execute(
        "SELECT id FROM next_quizzes WHERE session_id = ?",
        (session_id,)
    )
    return await cursor.fetchone() is not None


async def build_lesson_for_session(db: aiosqlite.Connection, session_id: int) -> Dict[str, Any]:
    """
    Generate a personalized lesson for the confirmed session.

    Returns:
        dict with keys: success, artifact_id, error (if any)
    """
    try:
        # Check idempotency - don't regenerate if already exists
        if await lesson_artifact_exists_for_session(db, session_id):
            cursor = await db.execute(
                "SELECT id FROM lesson_artifacts WHERE session_id = ?",
                (session_id,)
            )
            existing = await cursor.fetchone()
            logger.info(f"Lesson artifact already exists for session {session_id}")
            return {"success": True, "artifact_id": existing["id"], "already_existed": True}

        # Get session details
        session = await get_session_details(db, session_id)
        if not session:
            return {"success": False, "error": "Session not found"}

        student_id = session["student_id"]
        teacher_id = session["teacher_id"]
        current_level = session.get("current_level") or "A2"
        duration_min = session.get("duration_min") or 60

        # Gather student context
        context = await get_student_context(db, student_id)

        # Build profile dict for lesson generator
        profile = context.get("profile", {})
        if not profile.get("profile_summary") and context.get("learning_plan"):
            profile["profile_summary"] = json.dumps(context["learning_plan"])[:500]

        # Load lesson prompt
        lesson_prompt = load_prompt("lesson_generator.yaml")
        system_prompt = lesson_prompt["system_prompt"]
        user_template = lesson_prompt["user_template"]

        # Prepare template variables
        progress_text = "No previous lessons." if not context["progress_history"] else json.dumps(context["progress_history"][:5], indent=2)
        topics_text = "None (first lesson)." if not context["previous_topics"] else ", ".join(list(set(context["previous_topics"]))[:10])
        recall_text = "None." if not context["quiz_weak_areas"] else ", ".join(context["quiz_weak_areas"])

        session_number = context["session_count"] + 1

        user_message = user_template.format(
            session_number=session_number,
            current_level=current_level,
            profile_summary=profile.get("profile_summary", "No profile summary available"),
            priorities=", ".join(profile.get("priorities", [])),
            gaps=json.dumps(profile.get("gaps", []), indent=2),
            progress_history=progress_text,
            previous_topics=topics_text,
            recall_weak_areas=recall_text,
        )

        # Call AI
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="lesson",
            temperature=0.7,
            json_mode=True,
        )
        lesson_json = json.loads(result_text)

        # Extract topics for indexing
        topics_json = {}
        if lesson_json.get("presentation", {}).get("topic"):
            topics_json["main_topic"] = [lesson_json["presentation"]["topic"]]
        if lesson_json.get("objective"):
            topics_json["objective"] = [lesson_json["objective"]]

        # Store lesson artifact
        artifact_id = await ll.create_lesson_artifact(
            db,
            student_id=student_id,
            lesson_json=lesson_json,
            session_id=session_id,
            teacher_id=teacher_id,
            topics_json=topics_json,
            difficulty=lesson_json.get("difficulty", current_level),
            prompt_version=PROMPT_VERSION
        )

        logger.info(f"Created lesson artifact {artifact_id} for session {session_id}")
        return {"success": True, "artifact_id": artifact_id}

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error building lesson for session {session_id}: {e}")
        return {"success": False, "error": f"Invalid JSON response: {str(e)}"}
    except Exception as e:
        logger.error(f"Error building lesson for session {session_id}: {e}")
        return {"success": False, "error": str(e)}


async def build_next_quiz_from_lesson(db: aiosqlite.Connection, session_id: int) -> Dict[str, Any]:
    """
    Generate a quiz from the lesson artifact for this session.

    Returns:
        dict with keys: success, quiz_id, error (if any)
    """
    try:
        # Check idempotency
        if await quiz_exists_for_session(db, session_id):
            cursor = await db.execute(
                "SELECT id FROM next_quizzes WHERE session_id = ?",
                (session_id,)
            )
            existing = await cursor.fetchone()
            logger.info(f"Quiz already exists for session {session_id}")
            return {"success": True, "quiz_id": existing["id"], "already_existed": True}

        # Get the lesson artifact for this session
        cursor = await db.execute(
            "SELECT * FROM lesson_artifacts WHERE session_id = ?",
            (session_id,)
        )
        artifact_row = await cursor.fetchone()
        if not artifact_row:
            return {"success": False, "error": "No lesson artifact found for session"}

        artifact = dict(artifact_row)
        lesson_json = artifact["lesson_json"]
        if isinstance(lesson_json, str):
            lesson_json = json.loads(lesson_json)

        student_id = artifact["student_id"]
        artifact_id = artifact["id"]

        # Get student level
        cursor = await db.execute(
            "SELECT current_level FROM users WHERE id = ?",
            (student_id,)
        )
        student_row = await cursor.fetchone()
        current_level = student_row["current_level"] if student_row else "A2"

        # Load quiz prompt
        quiz_prompt = load_prompt("session_quiz.yaml")
        system_prompt = quiz_prompt["system_prompt"]
        user_template = quiz_prompt["user_template"]

        # Extract info from lesson
        objective = lesson_json.get("objective", "General English practice")
        difficulty = lesson_json.get("difficulty", current_level)

        # Topics
        topics = []
        if lesson_json.get("presentation", {}).get("topic"):
            topics.append(lesson_json["presentation"]["topic"])
        topics_text = ", ".join(topics) if topics else objective[:50]

        # Key concepts from presentation
        key_concepts = []
        if lesson_json.get("presentation", {}).get("explanation"):
            key_concepts.append(lesson_json["presentation"]["explanation"][:200])
        if lesson_json.get("polish_explanation"):
            key_concepts.append(f"Polish: {lesson_json['polish_explanation'][:100]}")
        key_concepts_text = "\n".join(key_concepts) if key_concepts else "See lesson objective"

        # Exercises summary
        exercises = lesson_json.get("exercises", [])
        if not exercises and lesson_json.get("controlled_practice", {}).get("exercises"):
            exercises = lesson_json["controlled_practice"]["exercises"]

        exercises_summary = []
        for i, ex in enumerate(exercises[:5], 1):
            ex_type = ex.get("type", "exercise")
            ex_content = ex.get("content", ex.get("instruction", ""))[:50]
            exercises_summary.append(f"{i}. [{ex_type}] {ex_content}")
        exercises_text = "\n".join(exercises_summary) if exercises_summary else "General practice exercises"

        user_message = user_template.format(
            objective=objective,
            difficulty=difficulty,
            topics=topics_text,
            key_concepts=key_concepts_text,
            exercises_summary=exercises_text,
            current_level=current_level,
        )

        # Call AI
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="lesson",
            temperature=0.7,
            json_mode=True,
        )
        quiz_json = json.loads(result_text)

        # Store quiz
        quiz_id = await ll.create_quiz(
            db,
            student_id=student_id,
            quiz_json=quiz_json,
            session_id=session_id,
            derived_from_lesson_artifact_id=artifact_id
        )

        logger.info(f"Created quiz {quiz_id} for session {session_id}")
        return {"success": True, "quiz_id": quiz_id}

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error building quiz for session {session_id}: {e}")
        return {"success": False, "error": f"Invalid JSON response: {str(e)}"}
    except Exception as e:
        logger.error(f"Error building quiz for session {session_id}: {e}")
        return {"success": False, "error": str(e)}


async def on_session_confirmed(db: aiosqlite.Connection, session_id: int, teacher_id: int) -> Dict[str, Any]:
    """
    Main hook called when a session is confirmed.
    Runs lesson and quiz generation with fail-soft behavior.

    Returns:
        dict with generation results (does not block confirmation)
    """
    result = {
        "lesson": {"status": STATUS_PENDING},
        "quiz": {"status": STATUS_PENDING}
    }

    try:
        # Generate lesson (with timeout to avoid blocking)
        lesson_result = await asyncio.wait_for(
            build_lesson_for_session(db, session_id),
            timeout=30.0  # 30 second timeout
        )

        if lesson_result.get("success"):
            result["lesson"] = {
                "status": STATUS_COMPLETED,
                "artifact_id": lesson_result.get("artifact_id"),
                "already_existed": lesson_result.get("already_existed", False)
            }
        else:
            result["lesson"] = {
                "status": STATUS_FAILED,
                "error": lesson_result.get("error")
            }
            logger.warning(f"Lesson generation failed for session {session_id}: {lesson_result.get('error')}")

    except asyncio.TimeoutError:
        result["lesson"] = {"status": STATUS_FAILED, "error": "Generation timed out"}
        logger.warning(f"Lesson generation timed out for session {session_id}")
    except Exception as e:
        result["lesson"] = {"status": STATUS_FAILED, "error": str(e)}
        logger.error(f"Lesson generation error for session {session_id}: {e}")

    # Only generate quiz if lesson succeeded
    if result["lesson"]["status"] == STATUS_COMPLETED:
        try:
            quiz_result = await asyncio.wait_for(
                build_next_quiz_from_lesson(db, session_id),
                timeout=30.0
            )

            if quiz_result.get("success"):
                result["quiz"] = {
                    "status": STATUS_COMPLETED,
                    "quiz_id": quiz_result.get("quiz_id"),
                    "already_existed": quiz_result.get("already_existed", False)
                }
            else:
                result["quiz"] = {
                    "status": STATUS_FAILED,
                    "error": quiz_result.get("error")
                }
                logger.warning(f"Quiz generation failed for session {session_id}: {quiz_result.get('error')}")

        except asyncio.TimeoutError:
            result["quiz"] = {"status": STATUS_FAILED, "error": "Generation timed out"}
            logger.warning(f"Quiz generation timed out for session {session_id}")
        except Exception as e:
            result["quiz"] = {"status": STATUS_FAILED, "error": str(e)}
            logger.error(f"Quiz generation error for session {session_id}: {e}")

    return result


async def get_session_lesson(db: aiosqlite.Connection, session_id: int) -> Optional[Dict[str, Any]]:
    """Get the lesson artifact for a session."""
    cursor = await db.execute(
        """SELECT la.*, s.scheduled_at, s.status as session_status
           FROM lesson_artifacts la
           JOIN sessions s ON s.id = la.session_id
           WHERE la.session_id = ?""",
        (session_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None

    result = dict(row)

    # Parse JSON fields
    for field in ['lesson_json', 'topics_json']:
        if result.get(field) and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except:
                pass

    return result


async def get_session_quiz(db: aiosqlite.Connection, session_id: int) -> Optional[Dict[str, Any]]:
    """Get the quiz for a session."""
    cursor = await db.execute(
        """SELECT nq.*, la.lesson_json, s.scheduled_at, s.status as session_status
           FROM next_quizzes nq
           LEFT JOIN lesson_artifacts la ON la.id = nq.derived_from_lesson_artifact_id
           JOIN sessions s ON s.id = nq.session_id
           WHERE nq.session_id = ?""",
        (session_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None

    result = dict(row)

    # Parse JSON fields
    for field in ['quiz_json', 'lesson_json']:
        if result.get(field) and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except:
                pass

    return result
