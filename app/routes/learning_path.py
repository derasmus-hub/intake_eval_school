import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.db.database import get_db
from app.services.learning_path_generator import generate_learning_path

router = APIRouter(prefix="/api/learning-path", tags=["learning_path"])


class WeekUpdate(BaseModel):
    week: int
    status: str  # "completed", "in_progress", "skipped"
    notes: Optional[str] = None


@router.post("/{student_id}/generate")
async def generate_path(student_id: int):
    """Generate a 12-week learning path using assessment + profile data."""
    db = await get_db()
    try:
        # Get student
        cursor = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        student_info = {
            "name": student["name"],
            "age": student["age"],
            "current_level": student["current_level"],
            "goals": json.loads(student["goals"]) if student["goals"] else [],
            "problem_areas": json.loads(student["problem_areas"]) if student["problem_areas"] else [],
        }

        # Get latest assessment (optional)
        assessment_data = None
        cursor = await db.execute(
            "SELECT * FROM assessments WHERE student_id = ? AND status = 'completed' ORDER BY created_at DESC LIMIT 1",
            (student_id,),
        )
        assessment_row = await cursor.fetchone()
        if assessment_row:
            assessment_data = {
                "determined_level": assessment_row["determined_level"],
                "confidence_score": assessment_row["confidence_score"],
                "sub_skill_breakdown": json.loads(assessment_row["sub_skill_breakdown"]) if assessment_row["sub_skill_breakdown"] else None,
                "weak_areas": json.loads(assessment_row["weak_areas"]) if assessment_row["weak_areas"] else None,
                "ai_analysis": json.loads(assessment_row["ai_analysis"]) if assessment_row["ai_analysis"] else None,
            }

        # Get latest diagnostic profile (optional)
        profile_data = None
        cursor = await db.execute(
            "SELECT * FROM learner_profiles WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
            (student_id,),
        )
        profile_row = await cursor.fetchone()
        if profile_row:
            profile_data = {
                "gaps": json.loads(profile_row["gaps"]) if profile_row["gaps"] else [],
                "priorities": json.loads(profile_row["priorities"]) if profile_row["priorities"] else [],
                "profile_summary": profile_row["profile_summary"] or "",
                "recommended_start_level": profile_row["recommended_start_level"],
            }

        # Generate the learning path via AI
        path_result = await generate_learning_path(
            student_info=student_info,
            assessment_data=assessment_data,
            profile_data=profile_data,
        )

        # Deactivate any existing active paths for this student
        await db.execute(
            "UPDATE learning_paths SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE student_id = ? AND status = 'active'",
            (student_id,),
        )

        # Save to database
        cursor = await db.execute(
            """INSERT INTO learning_paths
               (student_id, title, target_level, current_level, overview, weeks, milestones, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                student_id,
                path_result.get("title", "Learning Path"),
                path_result.get("target_level"),
                path_result.get("current_level"),
                path_result.get("overview"),
                json.dumps(path_result.get("weeks", [])),
                json.dumps(path_result.get("milestones", [])),
            ),
        )
        await db.commit()
        path_id = cursor.lastrowid

        return {
            "id": path_id,
            "student_id": student_id,
            "title": path_result.get("title"),
            "target_level": path_result.get("target_level"),
            "current_level": path_result.get("current_level"),
            "overview": path_result.get("overview"),
            "weeks": path_result.get("weeks", []),
            "milestones": path_result.get("milestones", []),
            "week_progress": {},
            "status": "active",
        }
    finally:
        await db.close()


@router.get("/{student_id}")
async def get_learning_path(student_id: int):
    """Retrieve the latest active learning path for a student."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM learning_paths
               WHERE student_id = ? AND status = 'active'
               ORDER BY created_at DESC LIMIT 1""",
            (student_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {"exists": False, "items": []}

        return {
            "exists": True,
            "id": row["id"],
            "student_id": row["student_id"],
            "title": row["title"],
            "target_level": row["target_level"],
            "current_level": row["current_level"],
            "overview": row["overview"],
            "weeks": json.loads(row["weeks"]) if row["weeks"] else [],
            "milestones": json.loads(row["milestones"]) if row["milestones"] else [],
            "week_progress": json.loads(row["week_progress"]) if row["week_progress"] else {},
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        await db.close()


@router.put("/{student_id}/week")
async def update_week_progress(student_id: int, body: WeekUpdate):
    """Update progress for a specific week in the learning path."""
    db = await get_db()
    try:
        # Find active learning path
        cursor = await db.execute(
            """SELECT id, week_progress FROM learning_paths
               WHERE student_id = ? AND status = 'active'
               ORDER BY created_at DESC LIMIT 1""",
            (student_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="No active learning path found for this student",
            )

        # Update week progress
        week_progress = json.loads(row["week_progress"]) if row["week_progress"] else {}
        week_key = str(body.week)
        week_progress[week_key] = {
            "status": body.status,
            "notes": body.notes,
        }

        await db.execute(
            "UPDATE learning_paths SET week_progress = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(week_progress), row["id"]),
        )
        await db.commit()

        return {
            "learning_path_id": row["id"],
            "week": body.week,
            "status": body.status,
            "week_progress": week_progress,
        }
    finally:
        await db.close()
