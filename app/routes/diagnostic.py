import json
from fastapi import APIRouter, HTTPException
from app.models.student import LearnerProfileResponse
from app.services.diagnostic_agent import run_diagnostic
from app.db.database import get_db

router = APIRouter(prefix="/api", tags=["diagnostic"])


@router.post("/diagnostic/{student_id}", response_model=LearnerProfileResponse)
async def create_diagnostic(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        intake_data = json.loads(student["intake_data"]) if student["intake_data"] else {}
        profile = await run_diagnostic(student_id, intake_data)

        cursor = await db.execute(
            """INSERT INTO learner_profiles (student_id, gaps, priorities, profile_summary, recommended_start_level)
               VALUES (?, ?, ?, ?, ?)""",
            (
                student_id,
                json.dumps(profile.identified_gaps),
                json.dumps(profile.priority_areas),
                profile.profile_summary,
                profile.recommended_start_level,
            ),
        )
        await db.commit()
        profile_id = cursor.lastrowid

        return LearnerProfileResponse(
            id=profile_id,
            student_id=student_id,
            gaps=profile.identified_gaps,
            priorities=profile.priority_areas,
            profile_summary=profile.profile_summary,
            recommended_start_level=profile.recommended_start_level,
        )
    finally:
        await db.close()


@router.get("/diagnostic/{student_id}", response_model=LearnerProfileResponse)
async def get_diagnostic(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM learner_profiles WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
            (student_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No diagnostic profile found for this student")

        return LearnerProfileResponse(
            id=row["id"],
            student_id=row["student_id"],
            gaps=json.loads(row["gaps"]) if row["gaps"] else [],
            priorities=json.loads(row["priorities"]) if row["priorities"] else [],
            profile_summary=row["profile_summary"] or "",
            recommended_start_level=row["recommended_start_level"],
            created_at=row["created_at"],
        )
    finally:
        await db.close()
