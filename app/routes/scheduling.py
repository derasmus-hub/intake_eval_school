"""Scheduling endpoints: session requests, teacher confirm/cancel, availability."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.db.database import get_db
from app.routes.auth import get_current_user

router = APIRouter(tags=["scheduling"])


# ── Request / response models ───────────────────────────────────────

class SessionRequest(BaseModel):
    scheduled_at: str  # ISO datetime
    duration_min: int = 60
    notes: str | None = None


class AvailabilitySlot(BaseModel):
    start_at: str  # ISO datetime
    end_at: str    # ISO datetime
    recurrence_rule: str | None = None


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

@router.get("/api/student/me/dashboard")
async def student_dashboard(request: Request):
    """Aggregated student dashboard data."""
    user = await _require_student(request)
    sid = user["id"]
    db = await get_db()
    try:
        # Basic student info
        cur = await db.execute(
            "SELECT id, name, current_level FROM students WHERE id = ?", (sid,)
        )
        student = await cur.fetchone()

        # Upcoming sessions
        cur = await db.execute(
            """SELECT s.id, s.scheduled_at, s.duration_min, s.status, s.notes,
                      t.name as teacher_name
               FROM sessions s
               LEFT JOIN students t ON t.id = s.teacher_id
               WHERE s.student_id = ? AND s.status IN ('requested','confirmed')
               ORDER BY s.scheduled_at""",
            (sid,),
        )
        sessions = [dict(row) for row in await cur.fetchall()]

        return {
            "student": dict(student) if student else None,
            "sessions": sessions,
        }
    finally:
        await db.close()


@router.get("/api/student/me/sessions")
async def student_sessions(request: Request):
    """List the student's sessions."""
    user = await _require_student(request)
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT s.id, s.scheduled_at, s.duration_min, s.status, s.notes,
                      t.name as teacher_name
               FROM sessions s
               LEFT JOIN students t ON t.id = s.teacher_id
               WHERE s.student_id = ?
               ORDER BY s.scheduled_at DESC""",
            (user["id"],),
        )
        return {"sessions": [dict(row) for row in await cur.fetchall()]}
    finally:
        await db.close()


@router.post("/api/student/me/sessions/request")
async def student_request_session(body: SessionRequest, request: Request):
    """Student requests a new class session."""
    user = await _require_student(request)
    if not body.scheduled_at:
        raise HTTPException(status_code=422, detail="scheduled_at is required")
    if body.duration_min < 15 or body.duration_min > 180:
        raise HTTPException(status_code=422, detail="duration_min must be 15-180")

    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO sessions (student_id, scheduled_at, duration_min, notes, status)
               VALUES (?, ?, ?, ?, 'requested')""",
            (user["id"], body.scheduled_at, body.duration_min, body.notes),
        )
        await db.commit()
        session_id = cur.lastrowid
        return {
            "id": session_id,
            "status": "requested",
            "scheduled_at": body.scheduled_at,
            "duration_min": body.duration_min,
        }
    finally:
        await db.close()


# ── Teacher endpoints ────────────────────────────────────────────────

@router.get("/api/teacher/sessions")
async def teacher_sessions(request: Request, status: str | None = None):
    """List sessions visible to the teacher, optionally filtered by status."""
    user = await _require_teacher(request)
    db = await get_db()
    try:
        if status:
            cur = await db.execute(
                """SELECT s.id, s.student_id, s.scheduled_at, s.duration_min,
                          s.status, s.notes, s.teacher_id,
                          st.name as student_name, st.current_level
                   FROM sessions s
                   JOIN students st ON st.id = s.student_id
                   WHERE s.status = ?
                   ORDER BY s.scheduled_at""",
                (status,),
            )
        else:
            cur = await db.execute(
                """SELECT s.id, s.student_id, s.scheduled_at, s.duration_min,
                          s.status, s.notes, s.teacher_id,
                          st.name as student_name, st.current_level
                   FROM sessions s
                   JOIN students st ON st.id = s.student_id
                   WHERE s.status IN ('requested','confirmed')
                   ORDER BY s.scheduled_at""",
            )
        return {"sessions": [dict(row) for row in await cur.fetchall()]}
    finally:
        await db.close()


@router.post("/api/teacher/sessions/{session_id}/confirm")
async def teacher_confirm_session(session_id: int, request: Request):
    """Teacher confirms a requested session."""
    user = await _require_teacher(request)
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, status FROM sessions WHERE id = ?", (session_id,)
        )
        session = await cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session["status"] != "requested":
            raise HTTPException(
                status_code=409,
                detail=f"Session is '{session['status']}', not 'requested'",
            )

        await db.execute(
            "UPDATE sessions SET status = 'confirmed', teacher_id = ? WHERE id = ?",
            (user["id"], session_id),
        )
        await db.commit()
        return {"id": session_id, "status": "confirmed", "teacher_id": user["id"]}
    finally:
        await db.close()


@router.post("/api/teacher/sessions/{session_id}/cancel")
async def teacher_cancel_session(session_id: int, request: Request):
    """Teacher cancels a session."""
    user = await _require_teacher(request)
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, status FROM sessions WHERE id = ?", (session_id,)
        )
        session = await cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session["status"] not in ("requested", "confirmed"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel session with status '{session['status']}'",
            )

        await db.execute(
            "UPDATE sessions SET status = 'cancelled' WHERE id = ?",
            (session_id,),
        )
        await db.commit()
        return {"id": session_id, "status": "cancelled"}
    finally:
        await db.close()


# ── Availability endpoints (groundwork for calendar UI) ──────────────

@router.get("/api/teacher/availability")
async def get_availability(request: Request):
    """Teacher views their own availability slots."""
    user = await _require_teacher(request)
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id, start_at, end_at, recurrence_rule, is_available
               FROM teacher_availability
               WHERE teacher_id = ? AND is_available = 1
               ORDER BY start_at""",
            (user["id"],),
        )
        return {"slots": [dict(row) for row in await cur.fetchall()]}
    finally:
        await db.close()


@router.post("/api/teacher/availability")
async def add_availability(body: AvailabilitySlot, request: Request):
    """Teacher adds an availability slot."""
    user = await _require_teacher(request)
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO teacher_availability
               (teacher_id, start_at, end_at, recurrence_rule)
               VALUES (?, ?, ?, ?)""",
            (user["id"], body.start_at, body.end_at, body.recurrence_rule),
        )
        await db.commit()
        return {"id": cur.lastrowid, "start_at": body.start_at, "end_at": body.end_at}
    finally:
        await db.close()


@router.get("/api/booking/slots")
async def booking_slots(request: Request, from_date: str = "", to_date: str = ""):
    """Public slot list for booking UI (returns available teacher time blocks)."""
    db = await get_db()
    try:
        query = """SELECT ta.id, ta.start_at, ta.end_at, t.name as teacher_name
                   FROM teacher_availability ta
                   JOIN students t ON t.id = ta.teacher_id
                   WHERE ta.is_available = 1"""
        params = []
        if from_date:
            query += " AND ta.start_at >= ?"
            params.append(from_date)
        if to_date:
            query += " AND ta.end_at <= ?"
            params.append(to_date)
        query += " ORDER BY ta.start_at"

        cur = await db.execute(query, params)
        return {"slots": [dict(row) for row in await cur.fetchall()]}
    finally:
        await db.close()
