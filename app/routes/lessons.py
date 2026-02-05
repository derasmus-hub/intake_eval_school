import json
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from app.models.lesson import LessonResponse, LessonContent
from app.services.lesson_generator import generate_lesson
from app.services.learning_point_extractor import extract_learning_points
from app.db.database import get_db

router = APIRouter(prefix="/api", tags=["lessons"])


@router.post("/lessons/{student_id}/generate", response_model=LessonResponse)
async def generate_next_lesson(student_id: int):
    db = await get_db()
    try:
        # Verify student exists
        cursor = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
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

        # Get progress history
        cursor = await db.execute(
            "SELECT * FROM progress WHERE student_id = ? ORDER BY completed_at DESC",
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

        # Get existing lessons for session count and topic history
        cursor = await db.execute(
            "SELECT objective, content FROM lessons WHERE student_id = ? ORDER BY session_number",
            (student_id,),
        )
        lesson_rows = await cursor.fetchall()
        session_number = len(lesson_rows) + 1

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

        # Generate lesson
        lesson_content = await generate_lesson(
            student_id=student_id,
            profile=profile_data,
            progress_history=progress_history,
            session_number=session_number,
            current_level=student["current_level"],
            previous_topics=previous_topics,
            recall_weak_areas=recall_weak_areas,
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

        return LessonResponse(
            id=lesson_id,
            student_id=student_id,
            session_number=session_number,
            objective=lesson_content.objective,
            content=lesson_content,
            difficulty=lesson_content.difficulty,
            status="generated",
        )
    finally:
        await db.close()


@router.get("/lessons/{student_id}", response_model=list[LessonResponse])
async def list_lessons(student_id: int):
    db = await get_db()
    try:
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
                    created_at=row["created_at"],
                )
            )
        return results
    finally:
        await db.close()


@router.get("/lessons/{student_id}/{lesson_id}", response_model=LessonResponse)
async def get_lesson(student_id: int, lesson_id: int):
    db = await get_db()
    try:
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
            created_at=row["created_at"],
        )
    finally:
        await db.close()


@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(lesson_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,))
        lesson = await cursor.fetchone()
        if not lesson:
            raise HTTPException(status_code=404, detail="Lesson not found")

        student_id = lesson["student_id"]

        # Get student level
        cursor = await db.execute(
            "SELECT current_level FROM students WHERE id = ?", (student_id,)
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
        tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat()
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

        return {
            "lesson_id": lesson_id,
            "points_extracted": len(inserted_points),
            "points": inserted_points,
        }
    finally:
        await db.close()
