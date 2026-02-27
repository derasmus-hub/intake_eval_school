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
from app.services.lesson_generator import generate_lesson
from app.services.difficulty_engine import get_skill_difficulty_profile
from app.services.learning_dna import get_or_compute_dna
from app.services.l1_interference import get_student_interference_profile
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

    # Get previous lesson skill tags from lessons table (structured, not free-form)
    cursor = await db.execute(
        """SELECT lst.tag_type, lst.tag_value, lst.cefr_level
           FROM lesson_skill_tags lst
           JOIN lessons l ON l.id = lst.lesson_id
           WHERE l.student_id = ?
           ORDER BY l.created_at DESC
           LIMIT 10""",
        (student_id,)
    )
    tag_rows = await cursor.fetchall()
    context["previous_skill_tags"] = [
        f"{r['tag_type']}\u2192{r['tag_value']} ({r['cefr_level']})"
        for r in tag_rows
    ]

    # Also extract skill tags from lesson_artifacts.topics_json (session automation path)
    cursor = await db.execute(
        """SELECT topics_json FROM lesson_artifacts
           WHERE student_id = ?
           ORDER BY created_at DESC
           LIMIT 5""",
        (student_id,)
    )
    for row in await cursor.fetchall():
        topics = row["topics_json"]
        if topics:
            try:
                topics_dict = json.loads(topics) if isinstance(topics, str) else topics
                if isinstance(topics_dict, dict):
                    for key, topic_list in topics_dict.items():
                        if isinstance(topic_list, list):
                            for t in topic_list:
                                if t and t not in context["previous_skill_tags"]:
                                    context["previous_skill_tags"].append(t)
            except Exception:
                pass

    # Get previous lessons with quiz scores (structured topic + performance data)
    cursor = await db.execute(
        """SELECT la.id, la.lesson_json, la.topics_json,
                  qa.score as quiz_score
           FROM lesson_artifacts la
           LEFT JOIN next_quizzes nq ON nq.derived_from_lesson_artifact_id = la.id
           LEFT JOIN quiz_attempts qa ON qa.quiz_id = nq.id
           WHERE la.student_id = ?
           ORDER BY la.created_at DESC
           LIMIT 5""",
        (student_id,)
    )
    artifact_rows = await cursor.fetchall()
    lessons_with_scores = []
    for row in artifact_rows:
        lesson = row["lesson_json"]
        if lesson:
            try:
                lesson_dict = json.loads(lesson) if isinstance(lesson, str) else lesson
                objective = lesson_dict.get("objective", "Unknown")[:80]
            except Exception:
                objective = "Unknown"
        else:
            objective = "Unknown"
        score = f"{int(row['quiz_score'] * 100)}%" if row["quiz_score"] is not None else "not yet tested"
        lessons_with_scores.append(f"- {objective} \u2192 Quiz: {score}")
        context["previous_topics"].append(objective)
    context["previous_lessons_with_scores"] = "\n".join(lessons_with_scores) or "No previous lessons."

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


async def get_teacher_observations(db, student_id: int) -> list[dict]:
    """Get recent teacher skill observations."""
    cursor = await db.execute(
        """SELECT skill, score, cefr_level, notes
           FROM session_skill_observations
           WHERE student_id = ?
           ORDER BY created_at DESC
           LIMIT 10""",
        (student_id,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_cefr_history(db, student_id: int) -> list[dict]:
    """Get CEFR level progression."""
    cursor = await db.execute(
        """SELECT level, grammar_level, vocabulary_level, reading_level,
                  speaking_level, writing_level, recorded_at
           FROM cefr_history
           WHERE student_id = ?
           ORDER BY recorded_at DESC
           LIMIT 5""",
        (student_id,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_vocabulary_due(db, student_id: int) -> list[str]:
    """Get vocabulary cards due for review (SM-2 schedule)."""
    cursor = await db.execute(
        """SELECT word FROM vocabulary_cards
           WHERE student_id = ? AND next_review <= datetime('now')
           ORDER BY ease_factor ASC
           LIMIT 10""",
        (student_id,)
    )
    rows = await cursor.fetchall()
    return [r["word"] for r in rows]


async def get_teacher_notes_for_lesson(db, student_id: int) -> str | None:
    """Get the most recent teacher session notes."""
    cursor = await db.execute(
        """SELECT session_summary, teacher_notes FROM sessions
           WHERE student_id = ? AND teacher_notes IS NOT NULL
           ORDER BY scheduled_at DESC
           LIMIT 1""",
        (student_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    parts = []
    if row["session_summary"]:
        parts.append(row["session_summary"])
    if row["teacher_notes"]:
        parts.append(f"Teacher notes: {row['teacher_notes']}")
    return "\n".join(parts) if parts else None


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

        session_number = context["session_count"] + 1

        # Gather rich context for the full lesson generator
        teacher_obs = await get_teacher_observations(db, student_id)
        cefr_hist = await get_cefr_history(db, student_id)
        vocab_due = await get_vocabulary_due(db, student_id)
        teacher_notes = await get_teacher_notes_for_lesson(db, student_id)
        learning_dna = await get_or_compute_dna(student_id, db)
        l1_profile = await get_student_interference_profile(student_id, db)
        difficulty_profile = await get_skill_difficulty_profile(student_id, db)

        # Call the full lesson generator with ALL context
        lesson = await generate_lesson(
            student_id=student_id,
            profile=profile,
            progress_history=context["progress_history"],
            session_number=session_number,
            current_level=current_level,
            previous_topics=context["previous_topics"] or None,
            recall_weak_areas=context["quiz_weak_areas"] or None,
            teacher_session_notes=teacher_notes,
            teacher_skill_observations=teacher_obs or None,
            cefr_history=cefr_hist or None,
            vocabulary_due_for_review=vocab_due or None,
            difficulty_profile=difficulty_profile or None,
            learning_dna=learning_dna or None,
            l1_interference_profile=l1_profile or None,
        )

        # Serialize LessonContent to JSON dict
        lesson_json = lesson.model_dump()
        # Ensure difficulty is present at top level
        if not lesson_json.get("difficulty"):
            lesson_json["difficulty"] = current_level

        # Extract topics for indexing
        topics_json = {}
        presentation = lesson_json.get("presentation") or {}
        if isinstance(presentation, dict) and presentation.get("topic"):
            topics_json["main_topic"] = [presentation["topic"]]
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

        # Enrich topics_json with skill tags from lesson generator
        skill_tags = getattr(lesson, "_skill_tags", [])
        if skill_tags:
            topics_json["skill_tags"] = [
                f"{t['type']}\u2192{t['value']} ({t.get('cefr_level', '')})"
                for t in skill_tags
                if isinstance(t, dict) and t.get("type") and t.get("value")
            ]
            # Update the artifact's topics_json with enriched data
            await db.execute(
                "UPDATE lesson_artifacts SET topics_json = ? WHERE id = ?",
                (json.dumps(topics_json), artifact_id)
            )
            await db.commit()

        logger.info(f"Created lesson artifact {artifact_id} for session {session_id}")
        return {"success": True, "artifact_id": artifact_id}

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error building lesson for session {session_id}: {e}")
        return {"success": False, "error": "Service temporarily unavailable"}
    except Exception as e:
        logger.error(f"Error building lesson for session {session_id}: {e}")
        return {"success": False, "error": "Service temporarily unavailable"}


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
        return {"success": False, "error": "Service temporarily unavailable"}
    except Exception as e:
        logger.error(f"Error building quiz for session {session_id}: {e}")
        return {"success": False, "error": "Service temporarily unavailable"}


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

    # Attempt lesson generation with retry
    for attempt in range(2):
        try:
            timeout = 60.0 if attempt == 0 else 45.0  # Generous first attempt
            lesson_result = await asyncio.wait_for(
                build_lesson_for_session(db, session_id),
                timeout=timeout
            )

            if lesson_result.get("success"):
                result["lesson"] = {
                    "status": STATUS_COMPLETED,
                    "artifact_id": lesson_result.get("artifact_id"),
                    "already_existed": lesson_result.get("already_existed", False)
                }
                break
            else:
                result["lesson"] = {
                    "status": STATUS_FAILED,
                    "error": lesson_result.get("error")
                }
                logger.warning(f"Lesson generation failed for session {session_id}: {lesson_result.get('error')}")

        except asyncio.TimeoutError:
            if attempt == 0:
                logger.warning(f"Lesson gen attempt 1 timed out for session {session_id}, retrying...")
                continue
            result["lesson"] = {"status": STATUS_FAILED, "error": "Generation timed out after retry"}
            logger.warning(f"Lesson generation timed out after retry for session {session_id}")
        except Exception as e:
            result["lesson"] = {"status": STATUS_FAILED, "error": "Service temporarily unavailable"}
            logger.error(f"Lesson generation error for session {session_id}: {e}")
            break

    # Only generate quiz if lesson succeeded
    if result["lesson"]["status"] == STATUS_COMPLETED:
        for attempt in range(2):
            try:
                timeout = 60.0 if attempt == 0 else 45.0
                quiz_result = await asyncio.wait_for(
                    build_next_quiz_from_lesson(db, session_id),
                    timeout=timeout
                )

                if quiz_result.get("success"):
                    result["quiz"] = {
                        "status": STATUS_COMPLETED,
                        "quiz_id": quiz_result.get("quiz_id"),
                        "already_existed": quiz_result.get("already_existed", False)
                    }
                    break
                else:
                    result["quiz"] = {
                        "status": STATUS_FAILED,
                        "error": quiz_result.get("error")
                    }
                    logger.warning(f"Quiz generation failed for session {session_id}: {quiz_result.get('error')}")

            except asyncio.TimeoutError:
                if attempt == 0:
                    logger.warning(f"Quiz gen attempt 1 timed out for session {session_id}, retrying...")
                    continue
                result["quiz"] = {"status": STATUS_FAILED, "error": "Generation timed out after retry"}
                logger.warning(f"Quiz generation timed out after retry for session {session_id}")
            except Exception as e:
                result["quiz"] = {"status": STATUS_FAILED, "error": "Service temporarily unavailable"}
                logger.error(f"Quiz generation error for session {session_id}: {e}")
                break

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
