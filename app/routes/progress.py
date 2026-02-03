import json
from fastapi import APIRouter, HTTPException
from app.models.lesson import ProgressEntry, ProgressResponse, ProgressSummary
from app.db.database import get_db

router = APIRouter(prefix="/api", tags=["progress"])


@router.post("/progress/{lesson_id}", response_model=ProgressResponse)
async def submit_progress(lesson_id: int, entry: ProgressEntry):
    db = await get_db()
    try:
        # Verify lesson exists
        cursor = await db.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,))
        lesson = await cursor.fetchone()
        if not lesson:
            raise HTTPException(status_code=404, detail="Lesson not found")

        # Prevent duplicate progress submissions
        cursor = await db.execute(
            "SELECT id FROM progress WHERE lesson_id = ? AND student_id = ?",
            (lesson_id, entry.student_id),
        )
        if await cursor.fetchone():
            raise HTTPException(status_code=409, detail="Progress already submitted for this lesson")

        cursor = await db.execute(
            """INSERT INTO progress (student_id, lesson_id, score, notes, areas_improved, areas_struggling)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.student_id,
                lesson_id,
                entry.score,
                entry.notes,
                json.dumps(entry.areas_improved),
                json.dumps(entry.areas_struggling),
            ),
        )
        await db.commit()

        # Update lesson status
        await db.execute("UPDATE lessons SET status = 'completed' WHERE id = ?", (lesson_id,))
        await db.commit()

        progress_id = cursor.lastrowid
        return ProgressResponse(
            id=progress_id,
            student_id=entry.student_id,
            lesson_id=lesson_id,
            score=entry.score,
            notes=entry.notes,
            areas_improved=entry.areas_improved,
            areas_struggling=entry.areas_struggling,
        )
    finally:
        await db.close()


@router.get("/progress/{student_id}", response_model=ProgressSummary)
async def get_progress(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM progress WHERE student_id = ? ORDER BY completed_at",
            (student_id,),
        )
        rows = await cursor.fetchall()

        entries = []
        total_score = 0.0
        skill_scores: dict[str, list[float]] = {}

        for row in rows:
            areas_improved = json.loads(row["areas_improved"]) if row["areas_improved"] else []
            areas_struggling = json.loads(row["areas_struggling"]) if row["areas_struggling"] else []
            score = row["score"] or 0.0

            entries.append(
                ProgressResponse(
                    id=row["id"],
                    student_id=row["student_id"],
                    lesson_id=row["lesson_id"],
                    score=score,
                    notes=row["notes"],
                    areas_improved=areas_improved,
                    areas_struggling=areas_struggling,
                    completed_at=row["completed_at"],
                )
            )
            total_score += score

            for area in areas_improved:
                skill_scores.setdefault(area, []).append(score)
            for area in areas_struggling:
                skill_scores.setdefault(area, []).append(max(0, score - 20))

        total_lessons = len(entries)
        avg_score = total_score / total_lessons if total_lessons > 0 else 0.0
        skill_averages = {k: sum(v) / len(v) for k, v in skill_scores.items()}

        return ProgressSummary(
            student_id=student_id,
            total_lessons=total_lessons,
            average_score=round(avg_score, 1),
            entries=entries,
            skill_averages={k: round(v, 1) for k, v in skill_averages.items()},
        )
    finally:
        await db.close()
