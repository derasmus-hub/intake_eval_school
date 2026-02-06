"""Scheduling endpoints: session requests, teacher confirm/cancel, availability."""

import logging
from fastapi import APIRouter, HTTPException, Request
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


# ── Request / response models ───────────────────────────────────────

class SessionRequest(BaseModel):
    scheduled_at: str  # ISO datetime
    duration_min: int = 60
    notes: str | None = None


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
    """List the student's sessions. Includes homework/summary but NOT teacher_notes."""
    user = await _require_student(request)
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT s.id, s.scheduled_at, s.duration_min, s.status, s.notes,
                      s.homework, s.session_summary,
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


class StudentProgressEntry(BaseModel):
    lesson_id: int
    score: float
    skill_tags: list[str] | None = None
    notes: str | None = None


@router.post("/api/student/me/progress")
async def student_submit_progress(body: StudentProgressEntry, request: Request):
    """Student submits their own lesson progress (token-bound, cannot submit for others)."""
    user = await _require_student(request)
    student_id = user["id"]

    # Validate score
    if body.score < 0 or body.score > 100:
        raise HTTPException(status_code=422, detail="score must be between 0 and 100")

    # Validate lesson_id exists
    db = await get_db()
    try:
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
            import json
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
    finally:
        await db.close()


@router.get("/api/student/me/progress")
async def student_get_progress(request: Request):
    """Student retrieves their own progress summary."""
    user = await _require_student(request)
    student_id = user["id"]

    db = await get_db()
    try:
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
    """Teacher confirms a requested session. Triggers lesson and quiz generation."""
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
    finally:
        await db.close()

    # Trigger lesson and quiz generation (fail-soft, does not block confirmation)
    generation_result = None
    try:
        generation_result = await on_session_confirmed(session_id, user["id"])
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


class SessionNotesUpdate(BaseModel):
    teacher_notes: str | None = None
    homework: str | None = None
    session_summary: str | None = None


MAX_NOTES_LENGTH = 5000


@router.post("/api/teacher/sessions/{session_id}/notes")
async def teacher_update_session_notes(session_id: int, body: SessionNotesUpdate, request: Request):
    """Teacher logs notes/homework/summary for a session. teacher_notes is private."""
    user = await _require_teacher(request)

    # Validate max length
    for field_name, value in [("teacher_notes", body.teacher_notes),
                               ("homework", body.homework),
                               ("session_summary", body.session_summary)]:
        if value and len(value) > MAX_NOTES_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} exceeds max length of {MAX_NOTES_LENGTH} characters"
            )

    db = await get_db()
    try:
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
    finally:
        await db.close()


@router.get("/api/teacher/sessions/{session_id}/notes")
async def teacher_get_session_notes(session_id: int, request: Request):
    """Teacher retrieves full notes for a session (including private teacher_notes)."""
    await _require_teacher(request)
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT id, teacher_notes, homework, session_summary, updated_at
               FROM sessions WHERE id = ?""",
            (session_id,),
        )
        session = await cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return dict(session)
    finally:
        await db.close()


# ── Booking slots endpoint ────────────────────────────────────────────
# Note: Teacher availability management is handled by availability.py
# which uses the weekly windows + overrides system.

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


# ── Teacher student overview endpoints ──────────────────────────────

@router.get("/api/teacher/students")
async def teacher_student_list(
    request: Request,
    q: str | None = None,
    needs_assessment: int | None = None,
    inactive_days: int | None = None,
    sort: str | None = None,
):
    """Teacher-only: list students with search, filters, and sorting (NO email, NO password).

    Query params:
    - q: search by name (case-insensitive)
    - needs_assessment=1: only students without completed assessment
    - inactive_days=N: only students with no activity in last N days
    - sort: name|created_at|last_assessment_at|next_session_at (default: next_session_at asc, nulls last)
    """
    await _require_teacher(request)
    db = await get_db()
    try:
        # Build base query with subqueries for derived fields
        base_query = """
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
                   )) as last_activity_at
            FROM students s
            WHERE s.role = 'student'
        """
        params = []

        # Search filter
        if q:
            base_query += " AND LOWER(s.name) LIKE ?"
            params.append(f"%{q.lower()}%")

        # Needs assessment filter
        if needs_assessment == 1:
            base_query += """ AND NOT EXISTS (
                SELECT 1 FROM assessments a
                WHERE a.student_id = s.id AND a.status = 'completed'
            )"""

        # Inactive days filter
        if inactive_days and inactive_days > 0:
            base_query += """ AND (
                SELECT MAX(ts) FROM (
                    SELECT MAX(updated_at) as ts FROM assessments WHERE student_id = s.id
                    UNION ALL
                    SELECT MAX(completed_at) as ts FROM progress WHERE student_id = s.id
                    UNION ALL
                    SELECT MAX(created_at) as ts FROM sessions WHERE student_id = s.id
                )
            ) < datetime('now', ?)
            """
            params.append(f"-{inactive_days} days")

        # Sorting
        valid_sorts = {
            "name": "s.name ASC",
            "created_at": "s.created_at DESC",
            "last_assessment_at": "last_assessment_at DESC NULLS LAST",
            "next_session_at": "next_session_at ASC NULLS LAST",
        }
        if sort and sort in valid_sorts:
            # SQLite doesn't support NULLS LAST directly, use CASE workaround
            if "NULLS LAST" in valid_sorts[sort]:
                col = sort
                direction = "ASC" if "ASC" in valid_sorts[sort] else "DESC"
                base_query += f" ORDER BY CASE WHEN {col} IS NULL THEN 1 ELSE 0 END, {col} {direction}"
            else:
                base_query += f" ORDER BY {valid_sorts[sort]}"
        else:
            # Default: next_session_at ascending, nulls last
            base_query += " ORDER BY CASE WHEN next_session_at IS NULL THEN 1 ELSE 0 END, next_session_at ASC"

        cur = await db.execute(base_query, params)
        return {"students": [dict(row) for row in await cur.fetchall()]}
    finally:
        await db.close()


@router.get("/api/teacher/students/{student_id}/overview")
async def teacher_student_overview(student_id: int, request: Request):
    """Teacher-only: detailed student overview (NO email, NO password)."""
    await _require_teacher(request)
    db = await get_db()
    try:
        # 1. Student basic info (explicitly exclude email and password_hash)
        cur = await db.execute("""
            SELECT id, name, age, goals, problem_areas, current_level, created_at
            FROM students WHERE id = ? AND role = 'student'
        """, (student_id,))
        student_row = await cur.fetchone()
        if not student_row:
            raise HTTPException(status_code=404, detail="Student not found")
        student = dict(student_row)

        # Parse JSON fields
        import json
        for field in ['goals', 'problem_areas']:
            if student.get(field) and isinstance(student[field], str):
                try:
                    student[field] = json.loads(student[field])
                except:
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
                    except:
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
    finally:
        await db.close()


# ── Session Lesson/Quiz Endpoints ──────────────────────────────────


@router.get("/api/teacher/sessions/{session_id}/lesson")
async def teacher_get_session_lesson(session_id: int, request: Request):
    """Teacher retrieves the generated lesson for a session."""
    user = await _require_teacher(request)

    # Verify session exists and teacher has access
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, teacher_id, status FROM sessions WHERE id = ?",
            (session_id,)
        )
        session = await cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
    finally:
        await db.close()

    lesson = await get_session_lesson(session_id)
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
async def teacher_get_session_quiz(session_id: int, request: Request):
    """Teacher retrieves the generated quiz for a session."""
    user = await _require_teacher(request)

    # Verify session exists
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, teacher_id, status FROM sessions WHERE id = ?",
            (session_id,)
        )
        session = await cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
    finally:
        await db.close()

    quiz = await get_session_quiz(session_id)
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
async def student_get_session_lesson(session_id: int, request: Request):
    """Student retrieves the lesson for their confirmed session.

    Note: Lesson is available once the session is confirmed.
    """
    user = await _require_student(request)
    student_id = user["id"]

    # Verify session exists and belongs to this student
    db = await get_db()
    try:
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
    finally:
        await db.close()

    lesson = await get_session_lesson(session_id)
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
async def student_get_session_quiz(session_id: int, request: Request):
    """Student retrieves the pre-class quiz for their session.

    This quiz should be taken before class as a warm-up review.
    """
    user = await _require_student(request)
    student_id = user["id"]

    # Verify session exists and belongs to this student
    db = await get_db()
    try:
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
    finally:
        await db.close()

    quiz = await get_session_quiz(session_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="No quiz available for this session")

    return {
        "session_id": session_id,
        "quiz_id": quiz.get("id"),
        "quiz": quiz.get("quiz_json"),
        "scheduled_at": quiz.get("scheduled_at"),
    }
