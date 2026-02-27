"""Scheduling endpoints: session requests, teacher confirm/cancel, availability."""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.db.database import get_db
from app.routes.auth import get_current_user
from app.services.session_automation import (
    on_session_confirmed,
    get_session_lesson,
    get_session_quiz,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scheduling"])


# -- Request / response models -------------------------------------------

class SessionRequest(BaseModel):
    scheduled_at: str  # ISO datetime
    duration_min: int = 60
    notes: str | None = None
    teacher_id: int | None = None


# -- Helpers --------------------------------------------------------------

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


# -- Student endpoints ----------------------------------------------------

@router.get("/api/student/me/dashboard")
async def student_dashboard(request: Request, db=Depends(get_db)):
    """Aggregated student dashboard data."""
    user = await _require_student(request, db)
    sid = user["id"]
    # Basic student info
    cur = await db.execute(
        "SELECT id, name, current_level FROM users WHERE id = ?", (sid,)
    )
    student = await cur.fetchone()

    # Upcoming sessions
    cur = await db.execute(
        """SELECT s.id, s.scheduled_at, s.duration_min, s.status, s.notes,
                  t.name as teacher_name
           FROM sessions s
           LEFT JOIN users t ON t.id = s.teacher_id
           WHERE s.student_id = ? AND s.status IN ('requested','confirmed')
           ORDER BY s.scheduled_at""",
        (sid,),
    )
    sessions = [dict(row) for row in await cur.fetchall()]

    return {
        "student": dict(student) if student else None,
        "sessions": sessions,
    }


@router.get("/api/student/me/sessions")
async def student_sessions(request: Request, db=Depends(get_db)):
    """List the student's sessions. Includes homework/summary but NOT teacher_notes."""
    user = await _require_student(request, db)
    cur = await db.execute(
        """SELECT s.id, s.scheduled_at, s.duration_min, s.status, s.notes,
                  s.homework, s.session_summary,
                  t.name as teacher_name
           FROM sessions s
           LEFT JOIN users t ON t.id = s.teacher_id
           WHERE s.student_id = ?
           ORDER BY s.scheduled_at DESC""",
        (user["id"],),
    )
    return {"sessions": [dict(row) for row in await cur.fetchall()]}


@router.post("/api/student/me/sessions/request")
async def student_request_session(body: SessionRequest, request: Request, db=Depends(get_db)):
    """Student requests a new class session."""
    user = await _require_student(request, db)
    if not body.scheduled_at:
        raise HTTPException(status_code=422, detail="scheduled_at is required")
    if body.duration_min < 15 or body.duration_min > 180:
        raise HTTPException(status_code=422, detail="duration_min must be 15-180")

    if body.teacher_id is not None:
        tcur = await db.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'teacher'", (body.teacher_id,)
        )
        if not await tcur.fetchone():
            raise HTTPException(status_code=404, detail="Teacher not found")

    cur = await db.execute(
        """INSERT INTO sessions (student_id, teacher_id, scheduled_at, duration_min, notes, status)
           VALUES (?, ?, ?, ?, ?, 'requested')""",
        (user["id"], body.teacher_id, body.scheduled_at, body.duration_min, body.notes),
    )
    await db.commit()
    session_id = cur.lastrowid
    return {
        "id": session_id,
        "status": "requested",
        "scheduled_at": body.scheduled_at,
        "duration_min": body.duration_min,
        "teacher_id": body.teacher_id,
    }


@router.get("/api/students/teacher-sessions")
async def student_teacher_sessions(
    request: Request,
    teacher_id: int = 0,
    from_date: str = "",
    to_date: str = "",
    db=Depends(get_db),
):
    """Student fetches their own sessions with a specific teacher for a date range."""
    user = await _require_student(request, db)
    if not teacher_id:
        raise HTTPException(status_code=422, detail="teacher_id is required")

    params: list = [user["id"], teacher_id]
    query = """SELECT id, scheduled_at, status, duration_min, notes
               FROM sessions
               WHERE student_id = ? AND teacher_id = ?
                 AND status IN ('requested', 'confirmed')"""
    if from_date:
        query += " AND scheduled_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND scheduled_at <= ?"
        params.append(to_date + "T23:59:59")
    query += " ORDER BY scheduled_at"

    cur = await db.execute(query, params)
    return {"sessions": [dict(row) for row in await cur.fetchall()]}


class StudentProgressEntry(BaseModel):
    lesson_id: int
    score: float
    skill_tags: list[str] | None = None
    notes: str | None = None


@router.post("/api/student/me/progress")
async def student_submit_progress(body: StudentProgressEntry, request: Request, db=Depends(get_db)):
    """Student submits their own lesson progress (token-bound, cannot submit for others)."""
    user = await _require_student(request, db)
    student_id = user["id"]

    # Validate score
    if body.score < 0 or body.score > 100:
        raise HTTPException(status_code=422, detail="score must be between 0 and 100")

    # Validate lesson_id exists
    cur = await db.execute("SELECT id FROM lessons WHERE id = ?", (body.lesson_id,))
    if not await cur.fetchone():
        raise HTTPException(status_code=404, detail="Lesson not found")

    # Prevent duplicate submissions
    cur = await db.execute(
        "SELECT id FROM progress WHERE lesson_id = ? AND student_id = ?",
        (body.lesson_id, student_id),
    )
    if await cur.fetchone():
        raise HTTPException(status_code=409, detail="Progress already submitted for this lesson")

    # Insert progress record
    skill_tags_json = None
    if body.skill_tags:
        skill_tags_json = json.dumps(body.skill_tags)

    cur = await db.execute(
        """INSERT INTO progress (student_id, lesson_id, score, notes, areas_improved, areas_struggling)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (student_id, body.lesson_id, body.score, body.notes, skill_tags_json, None),
    )
    await db.commit()
    progress_id = cur.lastrowid

    # Update lesson status to completed
    await db.execute("UPDATE lessons SET status = 'completed' WHERE id = ?", (body.lesson_id,))
    await db.commit()

    return {
        "id": progress_id,
        "student_id": student_id,
        "lesson_id": body.lesson_id,
        "score": body.score,
        "message": "Progress recorded",
    }


@router.get("/api/student/me/progress")
async def student_get_progress(request: Request, db=Depends(get_db)):
    """Student retrieves their own progress summary."""
    user = await _require_student(request, db)
    student_id = user["id"]

    cur = await db.execute(
        """SELECT id, lesson_id, score, notes, areas_improved, completed_at
           FROM progress WHERE student_id = ?
           ORDER BY completed_at DESC LIMIT 20""",
        (student_id,),
    )
    rows = await cur.fetchall()

    entries = []
    total_score = 0.0
    for row in rows:
        entries.append({
            "id": row["id"],
            "lesson_id": row["lesson_id"],
            "score": row["score"],
            "completed_at": row["completed_at"],
        })
        total_score += row["score"] or 0

    avg_score = round(total_score / len(entries), 1) if entries else 0

    return {
        "student_id": student_id,
        "total_lessons": len(entries),
        "average_score": avg_score,
        "entries": entries,
    }


# -- Teacher endpoints ----------------------------------------------------

@router.get("/api/teacher/sessions")
async def teacher_sessions(
    request: Request,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    db=Depends(get_db),
):
    """List sessions visible to the teacher, optionally filtered by status and date range.

    Scoped to the teacher's organization.
    """
    user = await _require_teacher(request, db)
    org_id = user.get("org_id")

    base = """SELECT s.id, s.student_id, s.scheduled_at, s.duration_min,
                     s.status, s.notes, s.teacher_id,
                     st.name as student_name, st.current_level
              FROM sessions s
              JOIN users st ON st.id = s.student_id"""
    conditions = []
    params = []

    if status:
        conditions.append("s.status = ?")
        params.append(status)
    else:
        conditions.append("s.status IN ('requested','confirmed')")

    if org_id:
        conditions.append("st.org_id = ?")
        params.append(org_id)

    if from_date:
        conditions.append("s.scheduled_at >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("s.scheduled_at <= ?")
        params.append(to_date + "T23:59:59")

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    cur = await db.execute(base + where + " ORDER BY s.scheduled_at", params)
    return {"sessions": [dict(row) for row in await cur.fetchall()]}


@router.post("/api/teacher/sessions/{session_id}/confirm")
async def teacher_confirm_session(session_id: int, request: Request, db=Depends(get_db)):
    """Teacher confirms a requested session. Triggers lesson and quiz generation."""
    user = await _require_teacher(request, db)
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

    # Trigger lesson and quiz generation (fail-soft, does not block confirmation)
    generation_result = None
    try:
        generation_result = await on_session_confirmed(db, session_id, user["id"])
        logger.info(f"Session {session_id} confirmed. Generation: {generation_result}")
    except Exception as e:
        # Log but don't fail the confirmation
        logger.error(f"Generation failed for session {session_id}: {e}")
        generation_result = {"lesson": {"status": "failed"}, "quiz": {"status": "failed"}}

    # Return confirmation with generation status (backward compatible: existing fields preserved)
    return {
        "id": session_id,
        "status": "confirmed",
        "teacher_id": user["id"],
        "generation": generation_result,
    }


@router.post("/api/teacher/sessions/{session_id}/cancel")
async def teacher_cancel_session(session_id: int, request: Request, db=Depends(get_db)):
    """Teacher cancels a session."""
    user = await _require_teacher(request, db)
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


class SessionCompleteRequest(BaseModel):
    teacher_notes: str | None = None
    homework: str | None = None
    session_summary: str | None = None


@router.post("/api/teacher/sessions/{session_id}/complete")
async def complete_session(
    session_id: int,
    body: SessionCompleteRequest,
    request: Request,
    db=Depends(get_db),
):
    """Teacher marks a session as completed. Triggers post-class hooks:
    1. Stores teacher notes/homework/summary
    2. Extracts learning points from the session's lesson artifact
    3. Triggers plan update if notes are substantial
    """
    user = await _require_teacher(request, db)

    # Verify session exists and is in a completable state
    cur = await db.execute(
        "SELECT id, student_id, teacher_id, status FROM sessions WHERE id = ?",
        (session_id,),
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] not in ("confirmed",):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot complete session with status '{session['status']}'",
        )

    student_id = session["student_id"]

    # Update session to completed with notes
    await db.execute(
        """UPDATE sessions
           SET status = 'completed',
               teacher_notes = COALESCE(?, teacher_notes),
               homework = COALESCE(?, homework),
               session_summary = COALESCE(?, session_summary),
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (body.teacher_notes, body.homework, body.session_summary, session_id),
    )
    await db.commit()

    # Post-class hook 1: Extract learning points from lesson artifact
    points_extracted = 0
    try:
        artifact = await get_session_lesson(db, session_id)
        if artifact and artifact.get("lesson_json"):
            from app.services.learning_point_extractor import extract_learning_points

            lesson_content = artifact["lesson_json"]
            cur = await db.execute(
                "SELECT current_level FROM users WHERE id = ?", (student_id,)
            )
            student_row = await cur.fetchone()
            student_level = student_row["current_level"] if student_row else "A1"

            points = await extract_learning_points(lesson_content, student_level)
            from datetime import datetime, timedelta, timezone

            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            for p in points:
                await db.execute(
                    """INSERT INTO learning_points
                       (student_id, lesson_id, point_type, content,
                        polish_explanation, example_sentence,
                        importance_weight, next_review_date)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        student_id,
                        artifact["id"],
                        p.get("point_type", "grammar_rule"),
                        p.get("content", ""),
                        p.get("polish_explanation", ""),
                        p.get("example_sentence", ""),
                        p.get("importance_weight", 3),
                        tomorrow,
                    ),
                )
            await db.commit()
            points_extracted = len(points)
    except Exception as e:
        logger.error(f"Learning point extraction failed for session {session_id}: {e}")

    # Post-class hook 2: Trigger plan update if notes are substantial
    plan_updated = False
    try:
        from app.services.plan_updater import on_teacher_notes_added

        result = await on_teacher_notes_added(db, student_id, session_id)
        plan_updated = result.get("success", False) and not result.get("skipped", False)
    except Exception as e:
        logger.error(f"Plan update failed for session {session_id}: {e}")

    return {
        "id": session_id,
        "status": "completed",
        "learning_points_extracted": points_extracted,
        "plan_updated": plan_updated,
    }


class AttendanceUpdate(BaseModel):
    attended: int  # 1 = attended, -1 = no-show, 0 = unknown
    lesson_id: int | None = None
    # For group sessions: per-student attendance list
    group_attendance: list[dict] | None = None


@router.post("/api/teacher/sessions/{session_id}/attendance")
async def teacher_update_attendance(
    session_id: int, body: AttendanceUpdate, request: Request, db=Depends(get_db)
):
    """Teacher marks attendance for a session and optionally links a lesson.

    For group sessions, pass group_attendance: [{"student_id": 1, "attended": 1}, ...]
    For 1-on-1, pass attended: 1/-1/0 as before.
    """
    user = await _require_teacher(request, db)

    if body.attended not in (-1, 0, 1):
        raise HTTPException(status_code=422, detail="attended must be -1, 0, or 1")

    cur = await db.execute(
        "SELECT id, status, is_group FROM sessions WHERE id = ?", (session_id,)
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate lesson_id if provided
    if body.lesson_id is not None:
        cur = await db.execute("SELECT id FROM lessons WHERE id = ?", (body.lesson_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Lesson not found")

    # Update session-level fields
    updates = ["attended = ?", "updated_at = CURRENT_TIMESTAMP"]
    params: list = [body.attended]
    if body.lesson_id is not None:
        updates.append("lesson_id = ?")
        params.append(body.lesson_id)
    params.append(session_id)

    await db.execute(
        f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?", params
    )

    # If attended, also mark session as completed
    if body.attended == 1 and session["status"] == "confirmed":
        await db.execute(
            "UPDATE sessions SET status = 'completed' WHERE id = ?", (session_id,)
        )

    # Handle group attendance
    group_updated = []
    if session["is_group"] and body.group_attendance:
        for entry in body.group_attendance:
            sid = entry.get("student_id")
            att = entry.get("attended", 0)
            if sid is None:
                continue
            await db.execute(
                "UPDATE session_students SET attended = ? WHERE session_id = ? AND student_id = ?",
                (att, session_id, sid),
            )
            group_updated.append({"student_id": sid, "attended": att})

    await db.commit()

    result = {
        "id": session_id,
        "attended": body.attended,
        "lesson_id": body.lesson_id,
        "message": "Attendance updated",
    }
    if group_updated:
        result["group_attendance"] = group_updated
    return result


class SessionNotesUpdate(BaseModel):
    teacher_notes: str | None = None
    homework: str | None = None
    session_summary: str | None = None


MAX_NOTES_LENGTH = 5000


@router.post("/api/teacher/sessions/{session_id}/notes")
async def teacher_update_session_notes(session_id: int, body: SessionNotesUpdate, request: Request, db=Depends(get_db)):
    """Teacher logs notes/homework/summary for a session. teacher_notes is private."""
    user = await _require_teacher(request, db)

    # Validate max length
    for field_name, value in [("teacher_notes", body.teacher_notes),
                               ("homework", body.homework),
                               ("session_summary", body.session_summary)]:
        if value and len(value) > MAX_NOTES_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} exceeds max length of {MAX_NOTES_LENGTH} characters"
            )

    cur = await db.execute(
        "SELECT id, status, student_id FROM sessions WHERE id = ?", (session_id,)
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update the notes fields
    await db.execute(
        """UPDATE sessions
           SET teacher_notes = COALESCE(?, teacher_notes),
               homework = COALESCE(?, homework),
               session_summary = COALESCE(?, session_summary),
               updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (body.teacher_notes, body.homework, body.session_summary, session_id),
    )
    await db.commit()

    return {
        "id": session_id,
        "message": "Notes updated",
        "teacher_notes": body.teacher_notes,
        "homework": body.homework,
        "session_summary": body.session_summary,
    }


@router.get("/api/teacher/sessions/{session_id}/notes")
async def teacher_get_session_notes(session_id: int, request: Request, db=Depends(get_db)):
    """Teacher retrieves full notes for a session (including private teacher_notes)."""
    await _require_teacher(request, db)
    cur = await db.execute(
        """SELECT id, teacher_notes, homework, session_summary, updated_at
           FROM sessions WHERE id = ?""",
        (session_id,),
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return dict(session)


# -- Skill Observations endpoint --------------------------------------------

VALID_SKILLS = {"grammar", "vocabulary", "speaking", "listening", "writing", "reading"}


class SkillObservationCreate(BaseModel):
    skill: str
    score: float | None = None
    cefr_level: str | None = None
    notes: str | None = None


@router.post("/api/sessions/{session_id}/observations")
async def submit_observations(
    session_id: int,
    observations: list[SkillObservationCreate],
    request: Request,
    db=Depends(get_db),
):
    """Teacher submits structured skill observations after a class session."""
    user = await _require_teacher(request, db)

    if not observations:
        raise HTTPException(status_code=422, detail="At least one observation required")

    # Validate skills
    for obs in observations:
        if obs.skill.lower() not in VALID_SKILLS:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid skill '{obs.skill}'. Must be one of: {', '.join(sorted(VALID_SKILLS))}",
            )
        if obs.score is not None and (obs.score < 0 or obs.score > 100):
            raise HTTPException(status_code=422, detail="score must be between 0 and 100")

    # Verify session exists and is confirmed/completed
    cur = await db.execute(
        "SELECT id, student_id, teacher_id, status FROM sessions WHERE id = ?",
        (session_id,),
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] not in ("confirmed", "completed"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot add observations to session with status '{session['status']}'",
        )

    student_id = session["student_id"]

    for obs in observations:
        await db.execute(
            """INSERT INTO session_skill_observations
               (session_id, student_id, teacher_id, skill, score, cefr_level, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                student_id,
                user["id"],
                obs.skill.lower(),
                obs.score,
                obs.cefr_level,
                obs.notes,
            ),
        )
    await db.commit()

    return {
        "session_id": session_id,
        "student_id": student_id,
        "count": len(observations),
        "message": "Observations recorded",
    }


@router.get("/api/sessions/{session_id}/observations")
async def get_observations(session_id: int, request: Request, db=Depends(get_db)):
    """Retrieve skill observations for a session (teacher or owning student)."""
    user = await get_current_user(request, db)

    # Verify session exists and user has access
    cur = await db.execute(
        "SELECT id, student_id, teacher_id FROM sessions WHERE id = ?",
        (session_id,),
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if user["role"] == "student" and user["id"] != session["student_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    cur = await db.execute(
        """SELECT id, skill, score, cefr_level, notes, created_at
           FROM session_skill_observations
           WHERE session_id = ?
           ORDER BY created_at""",
        (session_id,),
    )
    rows = await cur.fetchall()
    return {"session_id": session_id, "observations": [dict(r) for r in rows]}


# -- Booking slots endpoint ------------------------------------------------
# Note: Teacher availability management is handled by availability.py
# which uses the weekly windows + overrides system.

@router.get("/api/booking/slots")
async def booking_slots(request: Request, from_date: str = "", to_date: str = "", db=Depends(get_db)):
    """Public slot list for booking UI (returns available teacher time blocks)."""
    query = """SELECT ta.id, ta.start_at, ta.end_at, t.name as teacher_name
               FROM teacher_availability ta
               JOIN users t ON t.id = ta.teacher_id
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


# -- Teacher student overview endpoints ------------------------------------

@router.get("/api/teacher/students")
async def teacher_student_list(
    request: Request,
    q: str | None = None,
    needs_assessment: int | None = None,
    inactive_days: int | None = None,
    sort: str | None = None,
    db=Depends(get_db),
):
    """Teacher-only: list students with search, filters, and sorting (NO email, NO password).

    Query params:
    - q: search by name (case-insensitive)
    - needs_assessment=1: only students without completed assessment
    - inactive_days=N: only students with no activity in last N days
    - sort: name|created_at|last_assessment_at|next_session_at (default: next_session_at asc, nulls last)
    """
    user = await _require_teacher(request, db)
    org_id = user.get("org_id")

    # Build inner query with subqueries for derived fields
    inner_query = """
        SELECT s.id, s.name, s.age, s.current_level, s.created_at,
               (SELECT MAX(updated_at) FROM assessments
                WHERE student_id = s.id AND status = 'completed') as last_assessment_at,
               (SELECT scheduled_at FROM sessions
                WHERE student_id = s.id AND status IN ('requested','confirmed')
                ORDER BY scheduled_at LIMIT 1) as next_session_at,
               (SELECT status FROM sessions
                WHERE student_id = s.id AND status IN ('requested','confirmed')
                ORDER BY scheduled_at LIMIT 1) as session_status,
               (SELECT MAX(ts) FROM (
                   SELECT MAX(updated_at) as ts FROM assessments WHERE student_id = s.id
                   UNION ALL
                   SELECT MAX(completed_at) as ts FROM progress WHERE student_id = s.id
                   UNION ALL
                   SELECT MAX(created_at) as ts FROM sessions WHERE student_id = s.id
               ) AS _activity) as last_activity_at
        FROM users s
        WHERE s.role = 'student'
    """
    params = []

    # Org scope
    if org_id:
        inner_query += " AND s.org_id = ?"
        params.append(org_id)

    # Search filter
    if q:
        inner_query += " AND LOWER(s.name) LIKE ?"
        params.append(f"%{q.lower()}%")

    # Needs assessment filter
    if needs_assessment == 1:
        inner_query += """ AND NOT EXISTS (
            SELECT 1 FROM assessments a
            WHERE a.student_id = s.id AND a.status = 'completed'
        )"""

    # Inactive days filter
    if inactive_days and inactive_days > 0:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()
        inner_query += """ AND (
            SELECT MAX(ts) FROM (
                SELECT MAX(updated_at) as ts FROM assessments WHERE student_id = s.id
                UNION ALL
                SELECT MAX(completed_at) as ts FROM progress WHERE student_id = s.id
                UNION ALL
                SELECT MAX(created_at) as ts FROM sessions WHERE student_id = s.id
            ) AS _activity
        ) < ?
        """
        params.append(cutoff)

    # Wrap in subquery so column aliases are available in ORDER BY
    base_query = f"SELECT * FROM ({inner_query}) AS _students"

    # Sorting
    valid_sorts = {
        "name": "name ASC",
        "created_at": "created_at DESC",
        "last_assessment_at": "last_assessment_at DESC NULLS LAST",
        "next_session_at": "next_session_at ASC NULLS LAST",
    }
    if sort and sort in valid_sorts:
        base_query += f" ORDER BY {valid_sorts[sort]}"
    else:
        base_query += " ORDER BY next_session_at ASC NULLS LAST"

    cur = await db.execute(base_query, params)
    return {"students": [dict(row) for row in await cur.fetchall()]}


@router.get("/api/teacher/students/{student_id}/overview")
async def teacher_student_overview(student_id: int, request: Request, db=Depends(get_db)):
    """Teacher-only: detailed student overview (NO email, NO password)."""
    user = await _require_teacher(request, db)
    org_id = user.get("org_id")

    # 1. Student basic info (explicitly exclude email and password_hash)
    cur = await db.execute("""
        SELECT id, name, age, goals, problem_areas, current_level, org_id, created_at
        FROM users WHERE id = ? AND role = 'student'
    """, (student_id,))
    student_row = await cur.fetchone()
    if not student_row:
        raise HTTPException(status_code=404, detail="Student not found")
    if org_id and student_row["org_id"] != org_id:
        raise HTTPException(status_code=403, detail="Student is not in your organization")
    student = dict(student_row)

    # Parse JSON fields
    for field in ['goals', 'problem_areas']:
        if student.get(field) and isinstance(student[field], str):
            try:
                student[field] = json.loads(student[field])
            except (json.JSONDecodeError, ValueError):
                pass

    # 2. Latest completed assessment
    cur = await db.execute("""
        SELECT id, determined_level, confidence_score, sub_skill_breakdown,
               weak_areas, updated_at
        FROM assessments
        WHERE student_id = ? AND status = 'completed'
        ORDER BY updated_at DESC LIMIT 1
    """, (student_id,))
    assessment_row = await cur.fetchone()
    latest_assessment = None
    if assessment_row:
        latest_assessment = dict(assessment_row)
        for field in ['sub_skill_breakdown', 'weak_areas']:
            if latest_assessment.get(field) and isinstance(latest_assessment[field], str):
                try:
                    latest_assessment[field] = json.loads(latest_assessment[field])
                except (json.JSONDecodeError, ValueError):
                    pass

    # 3. Activity feed (derived from multiple tables, last 20 events)
    activity = []

    # Sessions
    cur = await db.execute("""
        SELECT 'session_' || status as type,
               CASE status
                   WHEN 'requested' THEN 'Requested ' || duration_min || 'min session'
                   WHEN 'confirmed' THEN 'Session confirmed for ' || scheduled_at
                   WHEN 'cancelled' THEN 'Session cancelled'
               END as detail,
               created_at as at
        FROM sessions WHERE student_id = ?
    """, (student_id,))
    activity.extend([dict(row) for row in await cur.fetchall()])

    # Assessments completed
    cur = await db.execute("""
        SELECT 'assessment_completed' as type,
               'Assessment completed: ' || COALESCE(determined_level, 'pending') as detail,
               updated_at as at
        FROM assessments WHERE student_id = ? AND status = 'completed'
    """, (student_id,))
    activity.extend([dict(row) for row in await cur.fetchall()])

    # Lessons completed (from progress table)
    cur = await db.execute("""
        SELECT 'lesson_completed' as type,
               'Completed lesson #' || lesson_id || ' (score: ' || CAST(score AS INTEGER) || '%)' as detail,
               completed_at as at
        FROM progress WHERE student_id = ?
    """, (student_id,))
    activity.extend([dict(row) for row in await cur.fetchall()])

    # Session notes updated
    cur = await db.execute("""
        SELECT 'session_notes_updated' as type,
               'Session notes updated for ' || scheduled_at as detail,
               updated_at as at
        FROM sessions
        WHERE student_id = ?
          AND updated_at IS NOT NULL
          AND (teacher_notes IS NOT NULL OR homework IS NOT NULL OR session_summary IS NOT NULL)
    """, (student_id,))
    activity.extend([dict(row) for row in await cur.fetchall()])

    # Sort by timestamp descending, limit 20
    activity.sort(key=lambda x: x.get('at') or '', reverse=True)
    activity = activity[:20]

    # 4. Last 10 progress entries with stats
    cur = await db.execute("""
        SELECT p.id, p.lesson_id, p.score, p.completed_at,
               l.objective as lesson_title
        FROM progress p
        LEFT JOIN lessons l ON l.id = p.lesson_id
        WHERE p.student_id = ?
        ORDER BY p.completed_at DESC
        LIMIT 10
    """, (student_id,))
    progress_rows = await cur.fetchall()
    progress_entries = [dict(row) for row in progress_rows]

    # Compute stats
    if progress_entries:
        scores = [p["score"] for p in progress_entries if p["score"] is not None]
        avg_score_last_10 = round(sum(scores) / len(scores), 1) if scores else 0
        last_progress_at = progress_entries[0]["completed_at"] if progress_entries else None
    else:
        avg_score_last_10 = 0
        last_progress_at = None

    return {
        "student": student,
        "latest_assessment": latest_assessment,
        "activity": activity,
        "progress": {
            "entries": progress_entries,
            "avg_score_last_10": avg_score_last_10,
            "last_progress_at": last_progress_at,
            "total_completed": len(progress_entries),
        }
    }


# -- Session Lesson/Quiz Endpoints ----------------------------------------


@router.get("/api/teacher/sessions/{session_id}/lesson")
async def teacher_get_session_lesson(session_id: int, request: Request, db=Depends(get_db)):
    """Teacher retrieves the generated lesson for a session."""
    user = await _require_teacher(request, db)

    # Verify session exists and teacher has access
    cur = await db.execute(
        "SELECT id, teacher_id, status FROM sessions WHERE id = ?",
        (session_id,)
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    lesson = await get_session_lesson(db, session_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="No lesson generated for this session")

    return {
        "session_id": session_id,
        "artifact_id": lesson.get("id"),
        "lesson": lesson.get("lesson_json"),
        "topics": lesson.get("topics_json"),
        "difficulty": lesson.get("difficulty"),
        "created_at": lesson.get("created_at"),
    }


@router.get("/api/teacher/sessions/{session_id}/next-quiz")
async def teacher_get_session_quiz(session_id: int, request: Request, db=Depends(get_db)):
    """Teacher retrieves the generated quiz for a session."""
    user = await _require_teacher(request, db)

    # Verify session exists
    cur = await db.execute(
        "SELECT id, teacher_id, status FROM sessions WHERE id = ?",
        (session_id,)
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    quiz = await get_session_quiz(db, session_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="No quiz generated for this session")

    return {
        "session_id": session_id,
        "quiz_id": quiz.get("id"),
        "quiz": quiz.get("quiz_json"),
        "derived_from_artifact_id": quiz.get("derived_from_lesson_artifact_id"),
        "created_at": quiz.get("created_at"),
    }


@router.get("/api/student/sessions/{session_id}/lesson")
async def student_get_session_lesson(session_id: int, request: Request, db=Depends(get_db)):
    """Student retrieves the lesson for their confirmed session.

    Note: Lesson is available once the session is confirmed.
    """
    user = await _require_student(request, db)
    student_id = user["id"]

    # Verify session exists and belongs to this student
    cur = await db.execute(
        "SELECT id, student_id, status, scheduled_at FROM sessions WHERE id = ?",
        (session_id,)
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["student_id"] != student_id:
        raise HTTPException(status_code=403, detail="Not your session")
    if session["status"] not in ("confirmed", "completed"):
        raise HTTPException(
            status_code=403,
            detail="Lesson not available until session is confirmed"
        )

    lesson = await get_session_lesson(db, session_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="No lesson available for this session")

    # Return lesson content (student view - same as teacher for now)
    return {
        "session_id": session_id,
        "lesson": lesson.get("lesson_json"),
        "difficulty": lesson.get("difficulty"),
        "scheduled_at": lesson.get("scheduled_at"),
    }


@router.get("/api/student/sessions/{session_id}/quiz")
async def student_get_session_quiz(session_id: int, request: Request, db=Depends(get_db)):
    """Student retrieves the pre-class quiz for their session.

    This quiz should be taken before class as a warm-up review.
    """
    user = await _require_student(request, db)
    student_id = user["id"]

    # Verify session exists and belongs to this student
    cur = await db.execute(
        "SELECT id, student_id, status, scheduled_at FROM sessions WHERE id = ?",
        (session_id,)
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["student_id"] != student_id:
        raise HTTPException(status_code=403, detail="Not your session")
    if session["status"] not in ("confirmed", "completed"):
        raise HTTPException(
            status_code=403,
            detail="Quiz not available until session is confirmed"
        )

    quiz = await get_session_quiz(db, session_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="No quiz available for this session")

    return {
        "session_id": session_id,
        "quiz_id": quiz.get("id"),
        "quiz": quiz.get("quiz_json"),
        "scheduled_at": quiz.get("scheduled_at"),
    }


# -- Group Class Endpoints ---------------------------------------------------


class CreateGroupSessionRequest(BaseModel):
    scheduled_at: str
    duration_min: int = 60
    max_students: int = 10
    student_ids: list[int] | None = None
    notes: str | None = None


class AddStudentToSessionRequest(BaseModel):
    student_id: int


@router.post("/api/teacher/sessions/group")
async def create_group_session(body: CreateGroupSessionRequest, request: Request, db=Depends(get_db)):
    """Create a group class session with optional initial student list."""
    user = await _require_teacher(request, db)

    if body.max_students < 2 or body.max_students > 50:
        raise HTTPException(status_code=422, detail="max_students must be 2-50")
    if body.duration_min < 15 or body.duration_min > 180:
        raise HTTPException(status_code=422, detail="duration_min must be 15-180")

    # Use first student_id as the primary student_id (for backward compat)
    primary_student_id = body.student_ids[0] if body.student_ids else None

    # If no students provided, use a placeholder (teacher can add later)
    if not primary_student_id:
        primary_student_id = user["id"]  # teacher as placeholder

    cur = await db.execute(
        """INSERT INTO sessions
           (student_id, teacher_id, scheduled_at, duration_min, notes, status, is_group, max_students)
           VALUES (?, ?, ?, ?, ?, 'confirmed', 1, ?)""",
        (primary_student_id, user["id"], body.scheduled_at, body.duration_min,
         body.notes, body.max_students),
    )
    await db.commit()
    session_id = cur.lastrowid

    # Add students to session_students junction table
    added = []
    for sid in (body.student_ids or []):
        try:
            await db.execute(
                "INSERT INTO session_students (session_id, student_id) VALUES (?, ?)",
                (session_id, sid),
            )
            added.append(sid)
        except Exception:
            pass  # Skip duplicates
    await db.commit()

    return {
        "id": session_id,
        "is_group": True,
        "max_students": body.max_students,
        "students_added": added,
        "status": "confirmed",
    }


@router.post("/api/teacher/sessions/{session_id}/students")
async def add_student_to_session(
    session_id: int, body: AddStudentToSessionRequest, request: Request, db=Depends(get_db)
):
    """Add a student to a group session."""
    user = await _require_teacher(request, db)

    # Verify session exists and is a group session
    cur = await db.execute(
        "SELECT id, is_group, max_students FROM sessions WHERE id = ?",
        (session_id,),
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session["is_group"]:
        raise HTTPException(status_code=400, detail="Cannot add students to a 1-on-1 session")

    # Check capacity
    cur = await db.execute(
        "SELECT COUNT(*) as cnt FROM session_students WHERE session_id = ?",
        (session_id,),
    )
    count_row = await cur.fetchone()
    current_count = count_row["cnt"] if count_row else 0
    if current_count >= (session["max_students"] or 10):
        raise HTTPException(status_code=409, detail="Session is full")

    # Check student exists
    cur = await db.execute(
        "SELECT id, org_id FROM users WHERE id = ? AND role = 'student'",
        (body.student_id,),
    )
    student = await cur.fetchone()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Org check
    org_id = user.get("org_id")
    if org_id and student["org_id"] != org_id:
        raise HTTPException(status_code=403, detail="Student is not in your organization")

    # Check not already enrolled
    cur = await db.execute(
        "SELECT id FROM session_students WHERE session_id = ? AND student_id = ?",
        (session_id, body.student_id),
    )
    if await cur.fetchone():
        raise HTTPException(status_code=409, detail="Student is already in this session")

    await db.execute(
        "INSERT INTO session_students (session_id, student_id) VALUES (?, ?)",
        (session_id, body.student_id),
    )
    await db.commit()

    return {
        "session_id": session_id,
        "student_id": body.student_id,
        "status": "added",
        "current_count": current_count + 1,
    }


@router.delete("/api/teacher/sessions/{session_id}/students/{student_id}")
async def remove_student_from_session(
    session_id: int, student_id: int, request: Request, db=Depends(get_db)
):
    """Remove a student from a group session."""
    await _require_teacher(request, db)

    cur = await db.execute(
        "SELECT id FROM session_students WHERE session_id = ? AND student_id = ?",
        (session_id, student_id),
    )
    if not await cur.fetchone():
        raise HTTPException(status_code=404, detail="Student not found in this session")

    await db.execute(
        "DELETE FROM session_students WHERE session_id = ? AND student_id = ?",
        (session_id, student_id),
    )
    await db.commit()

    return {"session_id": session_id, "student_id": student_id, "status": "removed"}


@router.get("/api/teacher/sessions/{session_id}/students")
async def list_session_students(session_id: int, request: Request, db=Depends(get_db)):
    """List all students enrolled in a session (works for both 1-on-1 and group)."""
    await _require_teacher(request, db)

    cur = await db.execute(
        "SELECT id, is_group, student_id, max_students FROM sessions WHERE id = ?",
        (session_id,),
    )
    session = await cur.fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    students = []

    if session["is_group"]:
        cur = await db.execute(
            """SELECT ss.student_id, ss.attended, ss.notes, ss.created_at,
                      u.name, u.current_level
               FROM session_students ss
               JOIN users u ON u.id = ss.student_id
               WHERE ss.session_id = ?
               ORDER BY u.name""",
            (session_id,),
        )
        students = [dict(row) for row in await cur.fetchall()]
    else:
        # 1-on-1: return the single student from sessions.student_id
        cur = await db.execute(
            "SELECT id as student_id, name, current_level FROM users WHERE id = ?",
            (session["student_id"],),
        )
        row = await cur.fetchone()
        if row:
            students = [dict(row)]

    return {
        "session_id": session_id,
        "is_group": bool(session["is_group"]),
        "max_students": session["max_students"] or 1,
        "students": students,
    }


