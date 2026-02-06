"""Quiz endpoints: student quiz taking, submission, and teacher results view."""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Optional
from app.db.database import get_db
from app.db import learning_loop as ll
from app.routes.auth import get_current_user
from app.services.quiz_scorer import (
    score_quiz_attempt,
    get_attempt_summary,
    get_pending_quizzes_for_student,
)
from app.services.plan_updater import on_quiz_submitted
import json

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quiz"])


# ── Request / response models ───────────────────────────────────────

class QuizSubmission(BaseModel):
    answers: Dict[str, str]  # question_id -> student_answer


# ── Helpers ──────────────────────────────────────────────────────────

async def _require_student(request: Request) -> dict:
    user = await get_current_user(request)
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Students only")
    return user


async def _require_teacher(request: Request) -> dict:
    user = await get_current_user(request)
    if user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")
    return user


# ── Student endpoints ────────────────────────────────────────────────

@router.get("/api/student/quizzes/pending")
async def student_pending_quizzes(request: Request):
    """Get list of pending quizzes for the student (not yet attempted)."""
    user = await _require_student(request)
    student_id = user["id"]

    quizzes = await get_pending_quizzes_for_student(student_id)

    return {
        "quizzes": quizzes,
        "count": len(quizzes),
    }


@router.get("/api/student/quizzes/{quiz_id}")
async def student_get_quiz(quiz_id: int, request: Request):
    """Get a specific quiz for the student to take."""
    user = await _require_student(request)
    student_id = user["id"]

    db = await get_db()
    try:
        quiz = await ll.get_quiz(db, quiz_id)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        if quiz["student_id"] != student_id:
            raise HTTPException(status_code=403, detail="Not your quiz")

        # Check if already attempted
        cursor = await db.execute(
            "SELECT id, score, submitted_at FROM quiz_attempts WHERE quiz_id = ? AND student_id = ?",
            (quiz_id, student_id)
        )
        attempt = await cursor.fetchone()

        quiz_json = quiz.get("quiz_json", {})
        if isinstance(quiz_json, str):
            quiz_json = json.loads(quiz_json)

        # Remove correct answers if not yet submitted
        questions = quiz_json.get("questions", [])
        if not attempt:
            # Hide answers for unanswered quiz
            for q in questions:
                q.pop("correct_answer", None)
                q.pop("explanation", None)

        return {
            "quiz_id": quiz_id,
            "title": quiz_json.get("title", "Pre-Class Quiz"),
            "title_pl": quiz_json.get("title_pl"),
            "description": quiz_json.get("description"),
            "estimated_time_minutes": quiz_json.get("estimated_time_minutes", 5),
            "questions": questions,
            "already_attempted": attempt is not None,
            "previous_score": round((attempt["score"] or 0) * 100) if attempt else None,
        }
    finally:
        await db.close()


@router.post("/api/student/quizzes/{quiz_id}/start")
async def student_start_quiz(quiz_id: int, request: Request):
    """
    Optional: Mark a quiz as started (creates attempt record).
    Can be used to track time spent.
    """
    user = await _require_student(request)
    student_id = user["id"]

    db = await get_db()
    try:
        quiz = await ll.get_quiz(db, quiz_id)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        if quiz["student_id"] != student_id:
            raise HTTPException(status_code=403, detail="Not your quiz")

        # Check if already has an unsubmitted attempt
        cursor = await db.execute(
            """SELECT id FROM quiz_attempts
               WHERE quiz_id = ? AND student_id = ? AND submitted_at IS NULL""",
            (quiz_id, student_id)
        )
        existing = await cursor.fetchone()

        if existing:
            return {
                "attempt_id": existing["id"],
                "status": "already_started",
                "message": "Quiz already in progress",
            }

        # Check if already submitted
        cursor = await db.execute(
            """SELECT id FROM quiz_attempts
               WHERE quiz_id = ? AND student_id = ? AND submitted_at IS NOT NULL""",
            (quiz_id, student_id)
        )
        submitted = await cursor.fetchone()

        if submitted:
            raise HTTPException(
                status_code=409,
                detail="Quiz already completed. Cannot start again."
            )

        # Create new attempt (will be completed on submit)
        # Note: We don't create attempt here - it's created on submit
        # This endpoint is optional for tracking purposes

        return {
            "quiz_id": quiz_id,
            "status": "ready",
            "message": "Quiz ready to take. Submit answers when complete.",
        }
    finally:
        await db.close()


@router.post("/api/student/quizzes/{quiz_id}/submit")
async def student_submit_quiz(quiz_id: int, body: QuizSubmission, request: Request):
    """
    Submit quiz answers and receive scored results.

    Request body:
    {
        "answers": {
            "q1": "student answer for q1",
            "q2": "student answer for q2",
            ...
        }
    }
    """
    user = await _require_student(request)
    student_id = user["id"]

    # Verify quiz ownership
    db = await get_db()
    try:
        quiz = await ll.get_quiz(db, quiz_id)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        if quiz["student_id"] != student_id:
            raise HTTPException(status_code=403, detail="Not your quiz")

        # Check if already submitted
        cursor = await db.execute(
            """SELECT id, score FROM quiz_attempts
               WHERE quiz_id = ? AND student_id = ? AND submitted_at IS NOT NULL""",
            (quiz_id, student_id)
        )
        existing = await cursor.fetchone()

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Quiz already submitted. Score: " + str(round((existing["score"] or 0) * 100)) + "%"
            )
    finally:
        await db.close()

    # Score the quiz
    result = await score_quiz_attempt(
        quiz_id=quiz_id,
        student_id=student_id,
        answers=body.answers,
        session_id=quiz.get("session_id")
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Failed to score quiz")
        )

    # Trigger learning plan update (fail-soft, don't block response)
    try:
        await on_quiz_submitted(
            student_id=student_id,
            quiz_id=quiz_id,
            attempt_id=result["attempt_id"]
        )
    except Exception as e:
        # Log but don't fail the quiz submission
        logger.warning(f"Plan update failed after quiz {quiz_id}: {e}")

    return {
        "quiz_id": quiz_id,
        "attempt_id": result["attempt_id"],
        "score": result["score"],
        "correct_count": result["correct_count"],
        "total_questions": result["total_questions"],
        "items": result["items"],
        "weak_areas": result["weak_areas"],
        "message": f"Quiz completed! Score: {result['score']}%",
        "message_pl": f"Quiz ukończony! Wynik: {result['score']}%",
    }


@router.get("/api/student/quizzes/{quiz_id}/results")
async def student_get_quiz_results(quiz_id: int, request: Request):
    """Get the student's results for a completed quiz."""
    user = await _require_student(request)
    student_id = user["id"]

    db = await get_db()
    try:
        # Verify ownership
        quiz = await ll.get_quiz(db, quiz_id)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        if quiz["student_id"] != student_id:
            raise HTTPException(status_code=403, detail="Not your quiz")

        # Get attempt
        cursor = await db.execute(
            """SELECT * FROM quiz_attempts
               WHERE quiz_id = ? AND student_id = ?
               ORDER BY submitted_at DESC
               LIMIT 1""",
            (quiz_id, student_id)
        )
        attempt = await cursor.fetchone()

        if not attempt:
            raise HTTPException(status_code=404, detail="No attempt found for this quiz")

        attempt_dict = dict(attempt)

        # Get items
        items = await ll.get_quiz_attempt_items(db, attempt_dict["id"])

        # Parse results
        results_json = attempt_dict.get("results_json", {})
        if isinstance(results_json, str):
            results_json = json.loads(results_json)

        # Get quiz questions for context
        quiz_json = quiz.get("quiz_json", {})
        if isinstance(quiz_json, str):
            quiz_json = json.loads(quiz_json)
        questions = {q["id"]: q for q in quiz_json.get("questions", [])}

        # Build detailed items
        detailed_items = []
        for item in items:
            q = questions.get(item["question_id"], {})
            detailed_items.append({
                "question_id": item["question_id"],
                "question_text": q.get("text", ""),
                "question_type": q.get("type", ""),
                "student_answer": item["student_answer"],
                "is_correct": bool(item["is_correct"]),
                "expected_answer": item["expected_answer"],
                "explanation": q.get("explanation", ""),
                "skill_tag": item["skill_tag"],
            })

        return {
            "quiz_id": quiz_id,
            "attempt_id": attempt_dict["id"],
            "score": round((attempt_dict.get("score") or 0) * 100),
            "submitted_at": attempt_dict.get("submitted_at"),
            "total_questions": results_json.get("total_questions", len(items)),
            "correct_count": results_json.get("correct_count"),
            "items": detailed_items,
            "weak_areas": results_json.get("weak_areas", []),
            "skill_breakdown": results_json.get("skill_breakdown", {}),
        }
    finally:
        await db.close()


# ── Teacher endpoints ────────────────────────────────────────────────

@router.get("/api/teacher/quizzes/{quiz_id}/attempts/latest")
async def teacher_get_latest_attempt(
    quiz_id: int,
    request: Request,
    student_id: Optional[int] = None
):
    """
    Teacher retrieves the latest attempt summary for a quiz.

    Query params:
    - student_id: Optional filter by student (required if quiz has multiple students)
    """
    await _require_teacher(request)

    db = await get_db()
    try:
        # Get the quiz first
        quiz = await ll.get_quiz(db, quiz_id)
        if not quiz:
            raise HTTPException(status_code=404, detail="Quiz not found")

        # If student_id provided, filter by it; otherwise use quiz's student_id
        target_student_id = student_id or quiz["student_id"]

        # Get the latest attempt
        cursor = await db.execute(
            """SELECT * FROM quiz_attempts
               WHERE quiz_id = ? AND student_id = ?
               ORDER BY submitted_at DESC
               LIMIT 1""",
            (quiz_id, target_student_id)
        )
        attempt = await cursor.fetchone()

        if not attempt:
            raise HTTPException(
                status_code=404,
                detail="No attempt found for this quiz"
            )

        # Get full summary
        summary = await get_attempt_summary(attempt["id"])

        if not summary:
            raise HTTPException(status_code=404, detail="Could not load attempt summary")

        # Add student info
        cursor = await db.execute(
            "SELECT id, name, current_level FROM students WHERE id = ?",
            (target_student_id,)
        )
        student = await cursor.fetchone()

        summary["student"] = dict(student) if student else {"id": target_student_id}

        return summary

    finally:
        await db.close()


@router.get("/api/teacher/students/{student_id}/quiz-history")
async def teacher_student_quiz_history(student_id: int, request: Request):
    """Teacher views a student's quiz history and performance trends."""
    await _require_teacher(request)

    db = await get_db()
    try:
        # Get recent attempts
        cursor = await db.execute(
            """SELECT qa.id, qa.quiz_id, qa.score, qa.submitted_at, qa.results_json,
                      nq.quiz_json
               FROM quiz_attempts qa
               JOIN next_quizzes nq ON nq.id = qa.quiz_id
               WHERE qa.student_id = ? AND qa.submitted_at IS NOT NULL
               ORDER BY qa.submitted_at DESC
               LIMIT 20""",
            (student_id,)
        )
        rows = await cursor.fetchall()

        attempts = []
        skill_totals = {}  # skill -> {correct, total}

        for row in rows:
            attempt = dict(row)

            # Parse JSONs
            results = attempt.get("results_json", {})
            if isinstance(results, str):
                results = json.loads(results)

            quiz_json = attempt.get("quiz_json", {})
            if isinstance(quiz_json, str):
                quiz_json = json.loads(quiz_json)

            # Aggregate skill performance
            skill_breakdown = results.get("skill_breakdown", {})
            for skill, data in skill_breakdown.items():
                if skill not in skill_totals:
                    skill_totals[skill] = {"correct": 0, "total": 0}
                skill_totals[skill]["correct"] += data.get("correct", 0)
                skill_totals[skill]["total"] += data.get("total", 0)

            attempts.append({
                "attempt_id": attempt["id"],
                "quiz_id": attempt["quiz_id"],
                "quiz_title": quiz_json.get("title", "Quiz"),
                "score": round((attempt.get("score") or 0) * 100),
                "submitted_at": attempt.get("submitted_at"),
                "weak_areas": results.get("weak_areas", []),
            })

        # Calculate overall skill performance
        skill_performance = {}
        for skill, totals in skill_totals.items():
            if totals["total"] > 0:
                skill_performance[skill] = {
                    "accuracy": round((totals["correct"] / totals["total"]) * 100),
                    "correct": totals["correct"],
                    "total": totals["total"],
                }

        # Identify weakest skills
        weakest_skills = sorted(
            [
                {"skill": skill, **data}
                for skill, data in skill_performance.items()
            ],
            key=lambda x: x["accuracy"]
        )[:5]

        return {
            "student_id": student_id,
            "attempts": attempts,
            "total_attempts": len(attempts),
            "skill_performance": skill_performance,
            "weakest_skills": weakest_skills,
        }

    finally:
        await db.close()
