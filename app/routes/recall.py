import json
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.db.database import get_db
from app.services.recall_generator import (
    get_points_due_for_review,
    generate_recall_questions,
    evaluate_recall_answers,
    update_review_schedule,
)
from app.services.xp_engine import award_xp
from app.routes.challenges import update_challenge_progress

router = APIRouter(prefix="/api/recall", tags=["recall"])


@router.get("/{student_id}/check")
async def check_recall(student_id: int):
    points = await get_points_due_for_review(student_id)
    count = len(points)
    estimated_minutes = max(1, round(count * 0.5))
    return {
        "has_pending_recall": count > 0,
        "points_count": count,
        "estimated_time_minutes": estimated_minutes,
    }


@router.post("/{student_id}/start")
async def start_recall(student_id: int):
    db = await get_db()
    try:
        # Verify student exists
        cursor = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        student_level = student["current_level"]

        # Get points due for review
        points = await get_points_due_for_review(student_id)
        if not points:
            return {
                "session_id": None,
                "questions": [],
                "encouragement": "All caught up! No review needed right now.",
            }

        # Limit to 5 points for the quiz
        quiz_points = points[:5]

        # Generate questions
        result = await generate_recall_questions(quiz_points, student_level)
        questions = result.get("questions", [])
        encouragement = result.get("encouragement", "Let's warm up!")
        encouragement_pl = result.get("encouragement_pl", "Rozgrzejmy sie!")

        # Create recall session
        cursor = await db.execute(
            """INSERT INTO recall_sessions (student_id, questions, status)
               VALUES (?, ?, 'in_progress')""",
            (student_id, json.dumps(questions)),
        )
        await db.commit()
        session_id = cursor.lastrowid

        return {
            "session_id": session_id,
            "questions": questions,
            "encouragement": encouragement,
            "encouragement_pl": encouragement_pl,
        }
    finally:
        await db.close()


@router.post("/{session_id}/submit")
async def submit_recall(session_id: int, body: dict):
    db = await get_db()
    try:
        # Fetch session
        cursor = await db.execute(
            "SELECT * FROM recall_sessions WHERE id = ?", (session_id,)
        )
        session = await cursor.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Recall session not found")

        if session["status"] == "completed":
            raise HTTPException(status_code=400, detail="Session already completed")

        student_id = session["student_id"]
        questions = json.loads(session["questions"]) if session["questions"] else []
        answers = body.get("answers", [])

        # Get student level
        cursor = await db.execute(
            "SELECT current_level FROM students WHERE id = ?", (student_id,)
        )
        student = await cursor.fetchone()
        student_level = student["current_level"] if student else "A1"

        # AI evaluate
        evaluation = await evaluate_recall_answers(questions, answers, student_level)

        overall_score = evaluation.get("overall_score", 0)
        evaluations = evaluation.get("evaluations", [])
        weak_areas = evaluation.get("weak_areas", [])
        encouragement = evaluation.get("encouragement", "")
        encouragement_pl = evaluation.get("encouragement_pl", "")

        # Update session
        await db.execute(
            """UPDATE recall_sessions
               SET answers = ?, overall_score = ?, evaluations = ?,
                   weak_areas = ?, status = 'completed',
                   completed_at = datetime('now')
               WHERE id = ?""",
            (
                json.dumps(answers),
                overall_score,
                json.dumps(evaluations),
                json.dumps(weak_areas),
                session_id,
            ),
        )
        await db.commit()

        # Update review schedules for each evaluated point
        for ev in evaluations:
            point_id = ev.get("point_id")
            score = ev.get("score", 0)
            if point_id:
                await update_review_schedule(point_id, score)

        # Award XP for recall completion
        if overall_score >= 100:
            await award_xp(student_id, 30, "perfect_recall", f"Perfect recall session {session_id}")
            await update_challenge_progress(student_id, "perfect_recall")
        else:
            await award_xp(student_id, 15, "recall_complete", f"Recall session {session_id}: {overall_score}%")
        if overall_score >= 80:
            await update_challenge_progress(student_id, "perfect_recall")

        return {
            "overall_score": overall_score,
            "evaluations": evaluations,
            "weak_areas": weak_areas,
            "encouragement": encouragement,
            "encouragement_pl": encouragement_pl,
        }
    finally:
        await db.close()
