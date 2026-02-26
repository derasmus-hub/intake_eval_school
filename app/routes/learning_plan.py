"""Learning plan endpoints: view and manage student learning plans."""

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from app.db.database import get_db
from app.routes.auth import get_current_user
from app.services.plan_updater import (
    get_student_learning_plan,
    get_plan_history,
    update_learning_plan,
)
from app.db import learning_loop as ll

router = APIRouter(tags=["learning-plan"])


# ── Helpers ──────────────────────────────────────────────────────────

async def _require_student(request: Request, db) -> dict:
    user = await get_current_user(request, db)
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Students only")
    return user


async def _require_teacher(request: Request, db) -> dict:
    user = await get_current_user(request, db)
    if user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Teachers only")
    return user


# ── Student endpoints ────────────────────────────────────────────────

@router.get("/api/student/learning-plan/latest")
async def student_get_latest_plan(request: Request, db=Depends(get_db)):
    """
    Get the student's latest learning plan.

    Returns the most recent plan with goals, weaknesses, and recommendations.
    """
    user = await _require_student(request, db)
    student_id = user["id"]

    plan = await get_student_learning_plan(db, student_id)

    if not plan:
        return {
            "exists": False,
            "message": "No learning plan yet. Complete a quiz to generate your first plan.",
            "message_pl": "Brak planu nauki. Ukończ quiz, aby wygenerować pierwszy plan.",
        }

    return {
        "exists": True,
        "plan_id": plan["id"],
        "version": plan["version"],
        "total_versions": plan["total_versions"],
        "summary": plan.get("summary"),
        "plan": plan.get("plan", {}),
        "created_at": plan.get("created_at"),
    }


@router.get("/api/student/learning-plan/history")
async def student_get_plan_history(request: Request, db=Depends(get_db), limit: int = 10):
    """
    Get the student's learning plan version history.
    """
    user = await _require_student(request, db)
    student_id = user["id"]

    history = await get_plan_history(db, student_id, limit=limit)

    return {
        "student_id": student_id,
        "plans": history,
        "total": len(history),
    }


@router.get("/api/student/learning-plan/{plan_id}")
async def student_get_specific_plan(plan_id: int, request: Request, db=Depends(get_db)):
    """
    Get a specific learning plan by ID.
    """
    user = await _require_student(request, db)
    student_id = user["id"]

    plan = await ll.get_learning_plan(db, plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan["student_id"] != student_id:
        raise HTTPException(status_code=403, detail="Not your plan")

    return {
        "id": plan["id"],
        "version": plan["version"],
        "summary": plan.get("summary"),
        "plan": plan.get("plan_json", {}),
        "created_at": plan.get("created_at"),
    }


# ── Teacher endpoints ────────────────────────────────────────────────

@router.get("/api/teacher/students/{student_id}/learning-plan/latest")
async def teacher_get_student_plan(student_id: int, request: Request, db=Depends(get_db)):
    """
    Teacher views a student's latest learning plan.

    Includes additional teacher-specific guidance.
    """
    await _require_teacher(request, db)

    # Verify student exists
    cursor = await db.execute(
        "SELECT id, name, current_level FROM users WHERE id = ? AND role = 'student'",
        (student_id,)
    )
    student = await cursor.fetchone()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    plan = await get_student_learning_plan(db, student_id)

    if not plan:
        return {
            "exists": False,
            "student": dict(student),
            "message": "No learning plan for this student yet.",
        }

    return {
        "exists": True,
        "student": dict(student),
        "plan_id": plan["id"],
        "version": plan["version"],
        "total_versions": plan["total_versions"],
        "summary": plan.get("summary"),
        "plan": plan.get("plan", {}),
        "created_at": plan.get("created_at"),
    }


@router.get("/api/teacher/students/{student_id}/learning-plan/history")
async def teacher_get_student_plan_history(
    student_id: int,
    request: Request,
    limit: int = 10,
    db=Depends(get_db),
):
    """
    Teacher views a student's learning plan version history.
    """
    await _require_teacher(request, db)

    # Verify student exists
    cursor = await db.execute(
        "SELECT id FROM users WHERE id = ? AND role = 'student'",
        (student_id,)
    )
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Student not found")

    history = await get_plan_history(db, student_id, limit=limit)

    return {
        "student_id": student_id,
        "plans": history,
        "total": len(history),
    }


@router.post("/api/teacher/students/{student_id}/learning-plan/refresh")
async def teacher_refresh_student_plan(student_id: int, request: Request, db=Depends(get_db)):
    """
    Teacher manually triggers a learning plan update for a student.

    This is useful after adding session notes or when wanting to
    incorporate recent progress data.
    """
    await _require_teacher(request, db)

    # Verify student exists
    cursor = await db.execute(
        "SELECT id, name FROM users WHERE id = ? AND role = 'student'",
        (student_id,)
    )
    student = await cursor.fetchone()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    result = await update_learning_plan(
        db,
        student_id=student_id,
        trigger="teacher_manual_refresh"
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to update plan")
        )

    return {
        "success": True,
        "plan_id": result.get("plan_id"),
        "summary": result.get("summary"),
        "message": f"Learning plan updated for {student['name']}",
    }


@router.get("/api/teacher/students/{student_id}/learning-plan/{plan_id}")
async def teacher_get_specific_student_plan(
    student_id: int,
    plan_id: int,
    request: Request,
    db=Depends(get_db),
):
    """
    Teacher views a specific learning plan version for a student.
    """
    await _require_teacher(request, db)

    plan = await ll.get_learning_plan(db, plan_id)

    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan["student_id"] != student_id:
        raise HTTPException(status_code=400, detail="Plan does not belong to this student")

    # Get student info
    cursor = await db.execute(
        "SELECT id, name, current_level FROM users WHERE id = ?",
        (student_id,)
    )
    student = await cursor.fetchone()

    return {
        "id": plan["id"],
        "version": plan["version"],
        "student": dict(student) if student else {"id": student_id},
        "summary": plan.get("summary"),
        "plan": plan.get("plan_json", {}),
        "created_at": plan.get("created_at"),
    }
