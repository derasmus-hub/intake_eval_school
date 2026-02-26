import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from app.models.lesson import LessonResponse, LessonContent
from app.services.lesson_generator import generate_lesson
from app.services.learning_point_extractor import extract_learning_points
from app.services.difficulty_engine import get_skill_difficulty_profile
from app.services.reassessment import trigger_reassessment
from app.services.lesson_suggestions import get_lesson_suggestions
from app.db.database import get_db
from app.routes.auth import get_current_user, require_student_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["lessons"])


@router.post("/lessons/{student_id}/generate", response_model=LessonResponse)
async def generate_next_lesson(student_id: int, request: Request, db=Depends(get_db)):
    user = await require_student_owner(request, student_id, db)
    # Verify student exists
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (student_id,))
    student = await cursor.fetchone()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Get learner profile
    cursor = await db.execute(
        "SELECT * FROM learner_profiles WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
        (student_id,),
    )
    profile_row = await cursor.fetchone()
    if not profile_row:
        raise HTTPException(status_code=400, detail="Run diagnostic first before generating lessons")

    profile_data = {
        "gaps": json.loads(profile_row["gaps"]) if profile_row["gaps"] else [],
        "priorities": json.loads(profile_row["priorities"]) if profile_row["priorities"] else [],
        "profile_summary": profile_row["profile_summary"] or "",
        "recommended_start_level": profile_row["recommended_start_level"],
    }

    # Get progress history (last 10 for context, not entire history)
    cursor = await db.execute(
        "SELECT * FROM progress WHERE student_id = ? ORDER BY completed_at DESC LIMIT 10",
        (student_id,),
    )
    progress_rows = await cursor.fetchall()
    progress_history = [
        {
            "lesson_id": row["lesson_id"],
            "score": row["score"],
            "areas_improved": json.loads(row["areas_improved"]) if row["areas_improved"] else [],
            "areas_struggling": json.loads(row["areas_struggling"]) if row["areas_struggling"] else [],
        }
        for row in progress_rows
    ]

    # Get session count
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM lessons WHERE student_id = ?",
        (student_id,),
    )
    count_row = await cursor.fetchone()
    session_number = (count_row["cnt"] if count_row else 0) + 1

    # Get recent lesson topics (last 10, not all)
    cursor = await db.execute(
        "SELECT objective, content FROM lessons WHERE student_id = ? ORDER BY session_number DESC LIMIT 10",
        (student_id,),
    )
    lesson_rows = await cursor.fetchall()

    # Extract previous lesson topics from objectives
    previous_topics = []
    for lr in lesson_rows:
        obj = lr["objective"] or ""
        if lr["content"]:
            try:
                c = json.loads(lr["content"])
                obj = c.get("objective", obj)
            except (json.JSONDecodeError, TypeError):
                pass
        if obj:
            previous_topics.append(obj)

    # Check for recall weak areas from most recent completed recall session
    recall_weak_areas = None
    cursor = await db.execute(
        """SELECT weak_areas FROM recall_sessions
           WHERE student_id = ? AND status = 'completed'
           ORDER BY completed_at DESC LIMIT 1""",
        (student_id,),
    )
    recall_row = await cursor.fetchone()
    if recall_row and recall_row["weak_areas"]:
        try:
            recall_weak_areas = json.loads(recall_row["weak_areas"])
            if not recall_weak_areas:
                recall_weak_areas = None
        except (json.JSONDecodeError, TypeError):
            recall_weak_areas = None

    # Fetch teacher session notes from most recent completed session
    cursor = await db.execute(
        """SELECT session_summary, teacher_notes
           FROM sessions
           WHERE student_id = ? AND status = 'completed'
           ORDER BY scheduled_at DESC LIMIT 1""",
        (student_id,),
    )
    session_row = await cursor.fetchone()
    teacher_session_notes = None
    if session_row:
        parts = []
        if session_row["session_summary"]:
            parts.append(session_row["session_summary"])
        if session_row["teacher_notes"]:
            parts.append(f"Teacher notes: {session_row['teacher_notes']}")
        teacher_session_notes = "\n".join(parts) if parts else None

    # Fetch skill observations from last 3 sessions
    cursor = await db.execute(
        """SELECT skill, score, cefr_level, notes
           FROM session_skill_observations
           WHERE student_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (student_id,),
    )
    skill_obs = [dict(r) for r in await cursor.fetchall()]

    # CEFR progression (last 3 entries)
    cursor = await db.execute(
        """SELECT level, grammar_level, vocabulary_level, speaking_level,
                  reading_level, writing_level, recorded_at
           FROM cefr_history
           WHERE student_id = ? ORDER BY recorded_at DESC LIMIT 3""",
        (student_id,),
    )
    cefr_hist = [dict(r) for r in await cursor.fetchall()]

    # Vocabulary cards due for review
    cursor = await db.execute(
        """SELECT word FROM vocabulary_cards
           WHERE student_id = ? AND next_review <= datetime('now')
           ORDER BY ease_factor ASC LIMIT 10""",
        (student_id,),
    )
    vocab_due = [r["word"] for r in await cursor.fetchall()]

    # Adaptive difficulty from SM-2 data
    difficulty_profile = await get_skill_difficulty_profile(student_id, db)

    # Fetch Learning DNA (cached or recomputed)
    from app.services.learning_dna import get_or_compute_dna
    learning_dna = await get_or_compute_dna(student_id, db)

    # Fetch L1 interference profile
    from app.services.l1_interference import get_student_interference_profile
    l1_interference_profile = await get_student_interference_profile(student_id, db)

    # Generate lesson
    lesson_content = await generate_lesson(
        student_id=student_id,
        profile=profile_data,
        progress_history=progress_history,
        session_number=session_number,
        current_level=student["current_level"],
        previous_topics=previous_topics,
        recall_weak_areas=recall_weak_areas,
        teacher_session_notes=teacher_session_notes,
        teacher_skill_observations=skill_obs or None,
        cefr_history=cefr_hist or None,
        vocabulary_due_for_review=vocab_due or None,
        difficulty_profile=difficulty_profile or None,
        learning_dna=learning_dna or None,
        l1_interference_profile=l1_interference_profile or None,
    )

    # Save to database
    cursor = await db.execute(
        """INSERT INTO lessons (student_id, session_number, objective, content, difficulty, status)
           VALUES (?, ?, ?, ?, ?, 'generated')""",
        (
            student_id,
            session_number,
            lesson_content.objective,
            json.dumps(lesson_content.model_dump()),
            lesson_content.difficulty,
        ),
    )
    await db.commit()
    lesson_id = cursor.lastrowid

    # Store skill tags returned by the AI
    for tag in getattr(lesson_content, "_skill_tags", []):
        if isinstance(tag, dict) and tag.get("type") and tag.get("value"):
            await db.execute(
                """INSERT INTO lesson_skill_tags (lesson_id, tag_type, tag_value, cefr_level)
                   VALUES (?, ?, ?, ?)""",
                (lesson_id, tag["type"], tag["value"], tag.get("cefr_level")),
            )
    await db.commit()

    return LessonResponse(
        id=lesson_id,
        student_id=student_id,
        session_number=session_number,
        objective=lesson_content.objective,
        content=lesson_content,
        difficulty=lesson_content.difficulty,
        status="generated",
    )


@router.get("/lessons/{student_id}", response_model=list[LessonResponse])
async def list_lessons(student_id: int, request: Request, db=Depends(get_db)):
    user = await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        "SELECT * FROM lessons WHERE student_id = ? ORDER BY session_number",
        (student_id,),
    )
    rows = await cursor.fetchall()
    results = []
    for row in rows:
        content = None
        if row["content"]:
            content = LessonContent(**json.loads(row["content"]))
        results.append(
            LessonResponse(
                id=row["id"],
                student_id=row["student_id"],
                session_number=row["session_number"],
                objective=row["objective"],
                content=content,
                difficulty=row["difficulty"],
                status=row["status"],
                created_at=str(row["created_at"]) if row["created_at"] else None,
            )
        )
    return results


@router.get("/lessons/{student_id}/{lesson_id}", response_model=LessonResponse)
async def get_lesson(student_id: int, lesson_id: int, request: Request, db=Depends(get_db)):
    user = await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        "SELECT * FROM lessons WHERE id = ? AND student_id = ?",
        (lesson_id, student_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lesson not found")

    content = None
    if row["content"]:
        content = LessonContent(**json.loads(row["content"]))

    return LessonResponse(
        id=row["id"],
        student_id=row["student_id"],
        session_number=row["session_number"],
        objective=row["objective"],
        content=content,
        difficulty=row["difficulty"],
        status=row["status"],
        created_at=str(row["created_at"]) if row["created_at"] else None,
    )


@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(lesson_id: int, request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    cursor = await db.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,))
    lesson = await cursor.fetchone()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    student_id = lesson["student_id"]

    if user["role"] == "student" and user["id"] != student_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Idempotency guard — prevent double-completion
    if lesson["status"] == "completed":
        raise HTTPException(status_code=409, detail="Lesson already completed")

    # Mark lesson as completed
    await db.execute(
        "UPDATE lessons SET status = 'completed' WHERE id = ?", (lesson_id,)
    )
    await db.commit()

    # Get student level
    cursor = await db.execute(
        "SELECT current_level FROM users WHERE id = ?", (student_id,)
    )
    student = await cursor.fetchone()
    student_level = student["current_level"] if student else "A1"

    # Parse lesson content
    content = {}
    if lesson["content"]:
        try:
            content = json.loads(lesson["content"])
        except (json.JSONDecodeError, TypeError):
            content = {"objective": lesson["objective"] or ""}

    # Extract learning points via AI
    points = await extract_learning_points(content, student_level)

    # Insert each point into learning_points table
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    inserted_points = []
    for p in points:
        cursor = await db.execute(
            """INSERT INTO learning_points
               (student_id, lesson_id, point_type, content, polish_explanation,
                example_sentence, importance_weight, next_review_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                student_id,
                lesson_id,
                p.get("point_type", "grammar_rule"),
                p.get("content", ""),
                p.get("polish_explanation", ""),
                p.get("example_sentence", ""),
                p.get("importance_weight", 3),
                tomorrow,
            ),
        )
        point_id = cursor.lastrowid
        inserted_points.append({**p, "id": point_id})

    await db.commit()

    # Periodic CEFR reassessment: trigger after every 10 completed lessons
    reassessment_result = None
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM progress WHERE student_id = ?",
        (student_id,),
    )
    count_row = await cursor.fetchone()
    lesson_count = count_row["cnt"] if count_row else 0

    if lesson_count > 0 and lesson_count % 10 == 0:
        logger.info(
            "Triggering periodic CEFR reassessment for student %d (lesson count: %d)",
            student_id, lesson_count,
        )
        try:
            reassessment_result = await trigger_reassessment(student_id, db)
        except Exception:
            logger.exception(
                "Periodic reassessment failed for student %d", student_id
            )

    # Recompute Learning DNA after lesson completion
    try:
        from app.services.learning_dna import compute_learning_dna
        await compute_learning_dna(student_id, db, trigger_event="lesson_complete")
    except Exception:
        logger.exception("Learning DNA recompute failed for student %d", student_id)

    result = {
        "lesson_id": lesson_id,
        "points_extracted": len(inserted_points),
        "points": inserted_points,
    }
    if reassessment_result:
        result["reassessment"] = {
            "triggered": True,
            "new_level": reassessment_result.get("determined_level"),
            "confidence": reassessment_result.get("confidence_score"),
            "trajectory": reassessment_result.get("trajectory"),
        }

    return result


@router.get("/students/{student_id}/lesson-suggestions")
async def lesson_suggestions(student_id: int, request: Request, db=Depends(get_db)):
    """
    Returns 3 lesson topic suggestions before teacher confirms next session:
    1. Review-focused (based on weak areas)
    2. Progression-focused (next natural topic)
    3. Interest-based (based on student goals)
    Each with: title, rationale, estimated difficulty, key vocabulary preview
    """
    user = await require_student_owner(request, student_id, db)

    # Verify student exists
    cursor = await db.execute("SELECT id FROM users WHERE id = ?", (student_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Student not found")

    result = await get_lesson_suggestions(student_id, db)

    return {
        "student_id": student_id,
        "suggestions": result.get("suggestions", []),
    }
