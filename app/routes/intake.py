import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.models.student import StudentIntake, StudentResponse
from app.db.database import get_db

router = APIRouter(prefix="/api", tags=["intake"])


@router.post("/intake", response_model=dict)
async def submit_intake(intake: StudentIntake):
    db = await get_db()
    try:
        # Store level as its value, or "pending" if not provided
        level_value = intake.current_level.value if intake.current_level else "pending"

        cursor = await db.execute(
            """INSERT INTO students (name, age, current_level, goals, problem_areas, intake_data, filler, additional_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intake.name,
                intake.age,
                level_value,
                json.dumps(intake.goals),
                json.dumps(intake.problem_areas),
                json.dumps(intake.model_dump()),
                intake.filler,
                intake.additional_notes,
            ),
        )
        await db.commit()
        student_id = cursor.lastrowid
        return {"student_id": student_id, "message": "Intake submitted successfully"}
    finally:
        await db.close()


class LevelUpdate(BaseModel):
    level: str


@router.put("/intake/{student_id}/level")
async def update_student_level(student_id: int, body: LevelUpdate):
    """Update a student's level after assessment completes."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM students WHERE id = ?", (student_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Student not found")

        await db.execute(
            "UPDATE students SET current_level = ? WHERE id = ?",
            (body.level, student_id),
        )
        await db.commit()
        return {"student_id": student_id, "level": body.level, "message": "Level updated"}
    finally:
        await db.close()


class GoalsUpdate(BaseModel):
    goals: list[str] = []
    problem_areas: list[str] = []
    additional_notes: Optional[str] = None


@router.put("/intake/{student_id}/goals")
async def update_student_goals(student_id: int, body: GoalsUpdate):
    """Update a student's goals and problem areas (wizard step 3)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, intake_data FROM students WHERE id = ?", (student_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found")

        # Merge into intake_data JSON
        existing_intake = json.loads(row["intake_data"]) if row["intake_data"] else {}
        existing_intake["goals"] = body.goals
        existing_intake["problem_areas"] = body.problem_areas
        if body.additional_notes is not None:
            existing_intake["additional_notes"] = body.additional_notes

        await db.execute(
            """UPDATE students
               SET goals = ?, problem_areas = ?, additional_notes = ?, intake_data = ?
               WHERE id = ?""",
            (
                json.dumps(body.goals),
                json.dumps(body.problem_areas),
                body.additional_notes,
                json.dumps(existing_intake),
                student_id,
            ),
        )
        await db.commit()
        return {"student_id": student_id, "message": "Goals updated"}
    finally:
        await db.close()


@router.get("/intake/{student_id}", response_model=StudentResponse)
async def get_intake(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found")
        return StudentResponse(
            id=row["id"],
            name=row["name"],
            age=row["age"],
            current_level=row["current_level"],
            goals=json.loads(row["goals"]) if row["goals"] else [],
            problem_areas=json.loads(row["problem_areas"]) if row["problem_areas"] else [],
            filler=row["filler"] or "student",
            additional_notes=row["additional_notes"],
            created_at=row["created_at"],
        )
    finally:
        await db.close()


@router.get("/students", response_model=list[StudentResponse])
async def list_students():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM students ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [
            StudentResponse(
                id=row["id"],
                name=row["name"],
                age=row["age"],
                current_level=row["current_level"],
                goals=json.loads(row["goals"]) if row["goals"] else [],
                problem_areas=json.loads(row["problem_areas"]) if row["problem_areas"] else [],
                filler=row["filler"] or "student",
                additional_notes=row["additional_notes"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    finally:
        await db.close()
