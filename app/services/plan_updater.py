"""
plan_updater.py - Learning plan update service

Analyzes quiz results and teacher notes to generate updated learning plans.
"""

import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
import yaml

from openai import AsyncOpenAI
from app.config import settings
from app.db.database import get_db
from app.db import learning_loop as ll

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str) -> dict:
    """Load a prompt YAML file."""
    with open(PROMPTS_DIR / name, "r") as f:
        return yaml.safe_load(f)


async def gather_quiz_analysis(db, student_id: int, limit: int = 10) -> Dict[str, Any]:
    """
    Gather and analyze recent quiz data for a student.

    Returns:
        dict with: quiz_count, average_score, skill_breakdown, recent_mistakes
    """
    # Get recent quiz attempts
    cursor = await db.execute(
        """SELECT qa.id, qa.quiz_id, qa.score, qa.submitted_at, qa.results_json
           FROM quiz_attempts qa
           WHERE qa.student_id = ? AND qa.submitted_at IS NOT NULL
           ORDER BY qa.submitted_at DESC
           LIMIT ?""",
        (student_id, limit)
    )
    attempts = await cursor.fetchall()

    if not attempts:
        return {
            "quiz_count": 0,
            "average_score": 0,
            "skill_breakdown": {},
            "recent_mistakes": []
        }

    # Aggregate scores
    scores = []
    skill_totals = {}  # skill -> {correct, total}
    recent_mistakes = []

    for attempt in attempts:
        attempt_dict = dict(attempt)
        if attempt_dict["score"] is not None:
            scores.append(attempt_dict["score"])

        results = attempt_dict.get("results_json")
        if results:
            if isinstance(results, str):
                results = json.loads(results)

            # Aggregate skill breakdown
            for skill, data in results.get("skill_breakdown", {}).items():
                if skill not in skill_totals:
                    skill_totals[skill] = {"correct": 0, "total": 0}
                skill_totals[skill]["correct"] += data.get("correct", 0)
                skill_totals[skill]["total"] += data.get("total", 0)

        # Get items for mistakes
        cursor = await db.execute(
            """SELECT question_id, is_correct, student_answer, expected_answer, skill_tag
               FROM quiz_attempt_items
               WHERE attempt_id = ? AND is_correct = 0""",
            (attempt_dict["id"],)
        )
        items = await cursor.fetchall()
        for item in items:
            recent_mistakes.append({
                "skill_tag": item["skill_tag"],
                "student_answer": item["student_answer"],
                "expected_answer": item["expected_answer"],
            })

    # Calculate skill breakdown with accuracy
    skill_breakdown = {}
    for skill, totals in skill_totals.items():
        if totals["total"] > 0:
            accuracy = round((totals["correct"] / totals["total"]) * 100)
            skill_breakdown[skill] = {
                "accuracy": accuracy,
                "correct": totals["correct"],
                "total": totals["total"],
                "status": "weak" if accuracy < 60 else "ok" if accuracy < 80 else "strong"
            }

    average_score = round(sum(scores) / len(scores) * 100) if scores else 0

    return {
        "quiz_count": len(attempts),
        "average_score": average_score,
        "skill_breakdown": skill_breakdown,
        "recent_mistakes": recent_mistakes[:20]  # Limit mistakes
    }


async def gather_teacher_notes(db, student_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Gather recent teacher notes from sessions.
    """
    cursor = await db.execute(
        """SELECT id, scheduled_at, teacher_notes, homework, session_summary
           FROM sessions
           WHERE student_id = ?
             AND status IN ('confirmed', 'completed')
             AND (teacher_notes IS NOT NULL OR homework IS NOT NULL OR session_summary IS NOT NULL)
           ORDER BY scheduled_at DESC
           LIMIT ?""",
        (student_id, limit)
    )
    rows = await cursor.fetchall()

    notes = []
    for row in rows:
        session = dict(row)
        if session.get("teacher_notes") or session.get("session_summary") or session.get("homework"):
            notes.append({
                "session_id": session["id"],
                "date": session["scheduled_at"],
                "notes": session.get("teacher_notes"),
                "summary": session.get("session_summary"),
                "homework": session.get("homework"),
            })

    return notes


async def gather_session_history(db, student_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Gather recent session history.
    """
    cursor = await db.execute(
        """SELECT s.id, s.scheduled_at, s.duration_min, s.status,
                  la.difficulty, la.topics_json
           FROM sessions s
           LEFT JOIN lesson_artifacts la ON la.session_id = s.id
           WHERE s.student_id = ? AND s.status IN ('confirmed', 'completed')
           ORDER BY s.scheduled_at DESC
           LIMIT ?""",
        (student_id, limit)
    )
    rows = await cursor.fetchall()

    history = []
    for row in rows:
        session = dict(row)
        topics = session.get("topics_json")
        if topics and isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except:
                topics = {}

        history.append({
            "session_id": session["id"],
            "date": session["scheduled_at"],
            "duration": session["duration_min"],
            "difficulty": session.get("difficulty"),
            "topics": topics,
        })

    return history


async def update_learning_plan(
    student_id: int,
    trigger: str = "quiz_submission",
    session_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Generate an updated learning plan for a student based on recent data.

    Args:
        student_id: The student ID
        trigger: What triggered this update (quiz_submission, teacher_notes, manual)
        session_id: Optional session ID if triggered from a session

    Returns:
        dict with: success, plan_id, plan (if successful), error (if failed)
    """
    db = await get_db()
    try:
        # Get student info
        cursor = await db.execute(
            """SELECT id, name, current_level, goals, problem_areas
               FROM students WHERE id = ?""",
            (student_id,)
        )
        student = await cursor.fetchone()
        if not student:
            return {"success": False, "error": "Student not found"}

        student_dict = dict(student)
        goals = student_dict.get("goals")
        if goals and isinstance(goals, str):
            try:
                goals = json.loads(goals)
            except:
                goals = [goals] if goals else []

        # Get previous plan
        previous_plan = await ll.get_latest_learning_plan(db, student_id)
        previous_plan_summary = "No previous plan exists."
        if previous_plan:
            plan_json = previous_plan.get("plan_json", {})
            if isinstance(plan_json, str):
                plan_json = json.loads(plan_json)
            previous_plan_summary = plan_json.get("summary", previous_plan.get("summary", "Previous plan exists but no summary available."))

        # Gather analysis data
        quiz_analysis = await gather_quiz_analysis(db, student_id)
        teacher_notes = await gather_teacher_notes(db, student_id)
        session_history = await gather_session_history(db, student_id)

        # Format data for prompt
        skill_breakdown_text = "\n".join([
            f"- {skill}: {data['accuracy']}% accuracy ({data['correct']}/{data['total']}) - {data['status']}"
            for skill, data in quiz_analysis["skill_breakdown"].items()
        ]) or "No skill data available yet."

        mistakes_text = "\n".join([
            f"- [{m['skill_tag']}] Expected: '{m['expected_answer']}', Got: '{m['student_answer']}'"
            for m in quiz_analysis["recent_mistakes"][:10]
        ]) or "No mistakes recorded."

        notes_text = "\n".join([
            f"- Session {n['date']}: {n.get('notes') or n.get('summary') or 'No notes'}"
            + (f"\n  Homework: {n['homework']}" if n.get('homework') else "")
            for n in teacher_notes
        ]) or "No teacher notes available."

        homework_status = "Homework assigned in recent sessions." if any(n.get("homework") for n in teacher_notes) else "No recent homework."

        history_text = "\n".join([
            f"- {h['date']}: {h.get('difficulty', 'N/A')} level"
            + (f", Topics: {h['topics']}" if h.get('topics') else "")
            for h in session_history
        ]) or "No session history."

        # Load prompt
        prompt_data = load_prompt("plan_update.yaml")

        user_message = prompt_data["user_template"].format(
            student_name=student_dict.get("name", "Student"),
            current_level=student_dict.get("current_level", "pending"),
            learning_goals=", ".join(goals) if goals else "Not specified",
            previous_plan_summary=previous_plan_summary,
            quiz_count=quiz_analysis["quiz_count"],
            average_score=quiz_analysis["average_score"],
            skill_breakdown=skill_breakdown_text,
            recent_mistakes=mistakes_text,
            teacher_notes=notes_text,
            homework_status=homework_status,
            session_history=history_text,
        )

        # Call OpenAI
        client = AsyncOpenAI(api_key=settings.api_key)
        response = await client.chat.completions.create(
            model=settings.model_name,
            messages=[
                {"role": "system", "content": prompt_data["system_prompt"]},
                {"role": "user", "content": user_message},
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
        )

        result_text = response.choices[0].message.content
        plan_json = json.loads(result_text)

        # Extract summary for storage
        summary = plan_json.get("summary", "Learning plan updated based on recent performance.")

        # Store the new plan
        plan_id = await ll.create_learning_plan(
            db,
            student_id=student_id,
            plan_json=plan_json,
            summary=summary,
            source_intake_id=None  # This is from quiz results, not intake
        )

        logger.info(f"Created learning plan {plan_id} for student {student_id} (trigger: {trigger})")

        return {
            "success": True,
            "plan_id": plan_id,
            "plan": plan_json,
            "summary": summary,
            "trigger": trigger,
        }

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error updating plan for student {student_id}: {e}")
        return {"success": False, "error": f"Invalid JSON response: {str(e)}"}
    except Exception as e:
        logger.error(f"Error updating plan for student {student_id}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        await db.close()


async def get_student_learning_plan(student_id: int) -> Optional[Dict[str, Any]]:
    """
    Get the latest learning plan for a student.
    """
    db = await get_db()
    try:
        plan = await ll.get_latest_learning_plan(db, student_id)
        if not plan:
            return None

        # Get all versions count
        plans = await ll.get_learning_plans_by_student(db, student_id)

        return {
            "id": plan["id"],
            "student_id": plan["student_id"],
            "version": plan["version"],
            "total_versions": len(plans),
            "plan": plan.get("plan_json", {}),
            "summary": plan.get("summary"),
            "created_at": plan.get("created_at"),
        }
    finally:
        await db.close()


async def get_plan_history(student_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get learning plan version history for a student.
    """
    db = await get_db()
    try:
        plans = await ll.get_learning_plans_by_student(db, student_id)

        history = []
        for plan in plans[:limit]:
            plan_json = plan.get("plan_json", {})
            if isinstance(plan_json, str):
                plan_json = json.loads(plan_json)

            history.append({
                "id": plan["id"],
                "version": plan["version"],
                "summary": plan.get("summary") or plan_json.get("summary"),
                "created_at": plan.get("created_at"),
                "goals": plan_json.get("goals_next_2_weeks", []),
            })

        return history
    finally:
        await db.close()


async def on_quiz_submitted(student_id: int, quiz_id: int, attempt_id: int) -> Dict[str, Any]:
    """
    Hook called after a quiz is submitted.
    Updates the learning plan based on new quiz results.

    This runs asynchronously and doesn't block the quiz submission response.
    """
    logger.info(f"Quiz {quiz_id} submitted by student {student_id}, triggering plan update")

    try:
        result = await update_learning_plan(
            student_id=student_id,
            trigger="quiz_submission"
        )

        if result.get("success"):
            logger.info(f"Plan updated for student {student_id}: plan_id={result.get('plan_id')}")
        else:
            logger.warning(f"Plan update failed for student {student_id}: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error in on_quiz_submitted hook: {e}")
        return {"success": False, "error": str(e)}


async def on_teacher_notes_added(student_id: int, session_id: int) -> Dict[str, Any]:
    """
    Hook called after teacher adds notes to a session.
    Optionally updates the learning plan.
    """
    logger.info(f"Teacher notes added for session {session_id}, student {student_id}")

    # Only update if we have significant notes
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT teacher_notes, session_summary
               FROM sessions WHERE id = ?""",
            (session_id,)
        )
        session = await cursor.fetchone()

        if not session:
            return {"success": False, "error": "Session not found"}

        notes = session["teacher_notes"] or ""
        summary = session["session_summary"] or ""

        # Only trigger update if notes are substantial
        if len(notes) + len(summary) < 50:
            logger.info(f"Notes too short for plan update, skipping")
            return {"success": True, "skipped": True, "reason": "notes_too_short"}

    finally:
        await db.close()

    try:
        result = await update_learning_plan(
            student_id=student_id,
            trigger="teacher_notes",
            session_id=session_id
        )

        return result

    except Exception as e:
        logger.error(f"Error in on_teacher_notes_added hook: {e}")
        return {"success": False, "error": str(e)}
