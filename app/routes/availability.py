"""Teacher availability management endpoints.

Teachers can manage their weekly recurring windows and date overrides.
Students can query a teacher's availability for a date range.
"""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from app.db.database import get_db
from app.routes.auth import get_current_user

router = APIRouter(tags=["availability"])

# ── Constants ────────────────────────────────────────────────────────
DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_TO_INDEX = {d: i for i, d in enumerate(DAYS_OF_WEEK)}


# ── Request / Response Models ────────────────────────────────────────

class WeeklyWindow(BaseModel):
    """A recurring weekly time window."""
    day_of_week: str = Field(..., description="Day name: monday, tuesday, etc.")
    start_time: str = Field(..., description="Start time HH:MM (24h format)")
    end_time: str = Field(..., description="End time HH:MM (24h format)")


class WeeklySchedule(BaseModel):
    """Full weekly schedule (replaces all existing windows)."""
    windows: list[WeeklyWindow]


class DateOverride(BaseModel):
    """A date-specific override (unavailable or custom hours)."""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    is_available: bool = Field(True, description="False = fully unavailable that day")
    windows: list[dict] | None = Field(
        None,
        description="Custom windows for this date [{start_time, end_time}]. If null, uses weekly default."
    )
    reason: str | None = Field(None, description="Optional reason (vacation, sick, etc.)")


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


def _validate_time_format(time_str: str) -> bool:
    """Validate HH:MM format."""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return False
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except (ValueError, AttributeError):
        return False


def _validate_date_format(date_str: str) -> bool:
    """Validate YYYY-MM-DD format."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _time_to_minutes(time_str: str) -> int:
    """Convert HH:MM to minutes since midnight."""
    h, m = map(int, time_str.split(":"))
    return h * 60 + m


# ── Teacher Endpoints ────────────────────────────────────────────────

@router.get("/api/teacher/availability")
async def get_teacher_availability(request: Request, db=Depends(get_db)):
    """
    Get the current teacher's weekly schedule and overrides.

    Returns:
        {
            "windows": [{"day_of_week": "monday", "start_time": "09:00", "end_time": "12:00"}, ...],
            "overrides": [{"date": "2026-02-14", "is_available": false, "reason": "vacation"}, ...]
        }
    """
    user = await _require_teacher(request, db)

    # Get weekly windows
    cur = await db.execute(
        """SELECT id, day_of_week, start_time, end_time
           FROM teacher_weekly_windows
           WHERE teacher_id = ?
           ORDER BY
               CASE day_of_week
                   WHEN 'monday' THEN 0
                   WHEN 'tuesday' THEN 1
                   WHEN 'wednesday' THEN 2
                   WHEN 'thursday' THEN 3
                   WHEN 'friday' THEN 4
                   WHEN 'saturday' THEN 5
                   WHEN 'sunday' THEN 6
               END, start_time""",
        (user["id"],),
    )
    windows = [dict(row) for row in await cur.fetchall()]

    # Get overrides (only future + last 7 days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    cur = await db.execute(
        """SELECT id, date, is_available, custom_windows, reason
           FROM teacher_availability_overrides
           WHERE teacher_id = ? AND date >= ?
           ORDER BY date""",
        (user["id"], cutoff),
    )
    overrides_raw = await cur.fetchall()

    import json
    overrides = []
    for row in overrides_raw:
        o = dict(row)
        if o.get("custom_windows"):
            try:
                o["windows"] = json.loads(o["custom_windows"])
            except Exception:
                o["windows"] = None
        else:
            o["windows"] = None
        del o["custom_windows"]
        o["is_available"] = bool(o["is_available"])
        overrides.append(o)

    return {"windows": windows, "overrides": overrides}


@router.post("/api/teacher/availability")
async def set_teacher_availability(body: WeeklySchedule, request: Request, db=Depends(get_db)):
    """
    Replace the teacher's entire weekly schedule (idempotent).

    All existing windows are deleted and replaced with the new ones.
    """
    user = await _require_teacher(request, db)

    # Validate windows
    for w in body.windows:
        day = w.day_of_week.lower()
        if day not in DAYS_OF_WEEK:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid day_of_week: {w.day_of_week}. Must be one of {DAYS_OF_WEEK}"
            )
        if not _validate_time_format(w.start_time):
            raise HTTPException(status_code=422, detail=f"Invalid start_time format: {w.start_time}")
        if not _validate_time_format(w.end_time):
            raise HTTPException(status_code=422, detail=f"Invalid end_time format: {w.end_time}")
        if _time_to_minutes(w.start_time) >= _time_to_minutes(w.end_time):
            raise HTTPException(
                status_code=422,
                detail=f"start_time ({w.start_time}) must be before end_time ({w.end_time})"
            )

    # Delete all existing windows for this teacher
    await db.execute(
        "DELETE FROM teacher_weekly_windows WHERE teacher_id = ?",
        (user["id"],),
    )

    # Insert new windows
    for w in body.windows:
        await db.execute(
            """INSERT INTO teacher_weekly_windows (teacher_id, day_of_week, start_time, end_time)
               VALUES (?, ?, ?, ?)""",
            (user["id"], w.day_of_week.lower(), w.start_time, w.end_time),
        )

    await db.commit()
    return {
        "message": "Weekly schedule updated",
        "windows_count": len(body.windows),
    }


@router.put("/api/teacher/availability")
async def update_teacher_availability(body: WeeklySchedule, request: Request, db=Depends(get_db)):
    """Alias for POST (same idempotent behavior)."""
    return await set_teacher_availability(body, request, db)


@router.delete("/api/teacher/availability/windows/{window_id}")
async def delete_availability_window(window_id: int, request: Request, db=Depends(get_db)):
    """
    Delete a specific weekly availability window by ID.

    Use GET /api/teacher/availability to see window IDs.
    """
    user = await _require_teacher(request, db)

    # Verify the window belongs to this teacher
    cur = await db.execute(
        "SELECT id FROM teacher_weekly_windows WHERE id = ? AND teacher_id = ?",
        (window_id, user["id"]),
    )
    if not await cur.fetchone():
        raise HTTPException(status_code=404, detail="Window not found")

    await db.execute(
        "DELETE FROM teacher_weekly_windows WHERE id = ? AND teacher_id = ?",
        (window_id, user["id"]),
    )
    await db.commit()

    return {"message": "Window deleted", "window_id": window_id}


@router.post("/api/teacher/availability/overrides")
async def add_or_update_override(body: DateOverride, request: Request, db=Depends(get_db)):
    """
    Add or update a date-specific override.

    If an override already exists for that date, it is replaced.
    """
    user = await _require_teacher(request, db)

    # Validate date
    if not _validate_date_format(body.date):
        raise HTTPException(status_code=422, detail=f"Invalid date format: {body.date}. Use YYYY-MM-DD")

    # Validate custom windows if provided
    import json
    custom_windows_json = None
    if body.windows:
        for w in body.windows:
            st = w.get("start_time", "")
            et = w.get("end_time", "")
            if not _validate_time_format(st) or not _validate_time_format(et):
                raise HTTPException(status_code=422, detail=f"Invalid window time format in {w}")
            if _time_to_minutes(st) >= _time_to_minutes(et):
                raise HTTPException(status_code=422, detail=f"start_time must be before end_time in {w}")
        custom_windows_json = json.dumps(body.windows)

    # Upsert: delete existing override for this date, then insert
    await db.execute(
        "DELETE FROM teacher_availability_overrides WHERE teacher_id = ? AND date = ?",
        (user["id"], body.date),
    )
    await db.execute(
        """INSERT INTO teacher_availability_overrides
           (teacher_id, date, is_available, custom_windows, reason)
           VALUES (?, ?, ?, ?, ?)""",
        (user["id"], body.date, 1 if body.is_available else 0, custom_windows_json, body.reason),
    )
    await db.commit()

    return {
        "message": "Override saved",
        "date": body.date,
        "is_available": body.is_available,
    }


@router.delete("/api/teacher/availability/overrides")
async def delete_override(request: Request, db=Depends(get_db), date: str = Query(..., description="Date YYYY-MM-DD")):
    """
    Remove a date override (reverts to weekly schedule for that date).
    """
    user = await _require_teacher(request, db)

    if not _validate_date_format(date):
        raise HTTPException(status_code=422, detail=f"Invalid date format: {date}. Use YYYY-MM-DD")

    cur = await db.execute(
        "DELETE FROM teacher_availability_overrides WHERE teacher_id = ? AND date = ?",
        (user["id"], date),
    )
    await db.commit()

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"No override found for {date}")

    return {"message": "Override removed", "date": date}


# ── Student Endpoints ────────────────────────────────────────────────

@router.get("/api/students/teacher-availability")
async def get_teacher_availability_for_student(
    request: Request,
    db=Depends(get_db),
    teacher_id: int = Query(..., description="Teacher ID"),
    from_date: str = Query(..., alias="from", description="Start date YYYY-MM-DD"),
    to_date: str = Query(..., alias="to", description="End date YYYY-MM-DD"),
):
    """
    Student views a teacher's availability for a date range.

    Returns a day-by-day structure suitable for calendar UI:
    [
        {"date": "2026-02-10", "windows": [{"start": "09:00", "end": "12:00"}], "available": true},
        {"date": "2026-02-11", "windows": [], "available": false}
    ]

    Max range: 90 days.
    """
    await _require_student(request, db)

    # Validate dates
    if not _validate_date_format(from_date):
        raise HTTPException(status_code=400, detail=f"Invalid 'from' date format: {from_date}")
    if not _validate_date_format(to_date):
        raise HTTPException(status_code=400, detail=f"Invalid 'to' date format: {to_date}")

    start = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d")

    if end < start:
        raise HTTPException(status_code=400, detail="'to' date must be >= 'from' date")
    if (end - start).days > 90:
        raise HTTPException(status_code=400, detail="Date range cannot exceed 90 days")

    # Verify teacher exists and is a teacher
    cur = await db.execute(
        "SELECT id, name FROM users WHERE id = ? AND role = 'teacher'",
        (teacher_id,),
    )
    teacher = await cur.fetchone()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    # Get weekly windows
    cur = await db.execute(
        """SELECT day_of_week, start_time, end_time
           FROM teacher_weekly_windows
           WHERE teacher_id = ?""",
        (teacher_id,),
    )
    weekly_rows = await cur.fetchall()

    # Build lookup: day_name -> list of {start, end}
    weekly_schedule = {d: [] for d in DAYS_OF_WEEK}
    for row in weekly_rows:
        day = row["day_of_week"].lower()
        weekly_schedule[day].append({
            "start": row["start_time"],
            "end": row["end_time"],
        })

    # Get overrides in range
    cur = await db.execute(
        """SELECT date, is_available, custom_windows
           FROM teacher_availability_overrides
           WHERE teacher_id = ? AND date >= ? AND date <= ?""",
        (teacher_id, from_date, to_date),
    )
    override_rows = await cur.fetchall()

    import json
    overrides = {}
    for row in override_rows:
        o = dict(row)
        windows = None
        if o["custom_windows"]:
            try:
                windows = json.loads(o["custom_windows"])
            except Exception:
                pass
        overrides[o["date"]] = {
            "is_available": bool(o["is_available"]),
            "windows": windows,
        }

    # Build day-by-day result
    result = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        day_name = DAYS_OF_WEEK[current.weekday()]

        if date_str in overrides:
            # Use override
            ovr = overrides[date_str]
            if not ovr["is_available"]:
                result.append({"date": date_str, "windows": [], "available": False})
            elif ovr["windows"]:
                # Custom windows for this date
                result.append({
                    "date": date_str,
                    "windows": [{"start": w["start_time"], "end": w["end_time"]} for w in ovr["windows"]],
                    "available": True,
                })
            else:
                # Override says available but no custom windows = use weekly
                windows = weekly_schedule.get(day_name, [])
                result.append({
                    "date": date_str,
                    "windows": windows,
                    "available": len(windows) > 0,
                })
        else:
            # Use weekly schedule
            windows = weekly_schedule.get(day_name, [])
            result.append({
                "date": date_str,
                "windows": windows,
                "available": len(windows) > 0,
            })

        current += timedelta(days=1)

    return {
        "teacher_id": teacher_id,
        "teacher_name": teacher["name"],
        "from": from_date,
        "to": to_date,
        "days": result,
    }


@router.get("/api/students/teachers")
async def list_teachers_for_students(request: Request, db=Depends(get_db)):
    """
    Student gets a list of all teachers (for selecting whose availability to view).

    Returns minimal info: id, name.
    """
    await _require_student(request, db)

    cur = await db.execute(
        "SELECT id, name FROM users WHERE role = 'teacher' ORDER BY name"
    )
    teachers = [{"id": row["id"], "name": row["name"]} for row in await cur.fetchall()]
    return {"teachers": teachers}
