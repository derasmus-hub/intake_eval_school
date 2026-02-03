import json
from fastapi import APIRouter, HTTPException
from app.models.student import StudentIntake, StudentResponse
from app.db.database import get_db

router = APIRouter(prefix="/api", tags=["intake"])


@router.post("/intake", response_model=dict)
async def submit_intake(intake: StudentIntake):
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO students (name, age, current_level, goals, problem_areas, intake_data, filler, additional_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intake.name,
                intake.age,
                intake.current_level.value,
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
