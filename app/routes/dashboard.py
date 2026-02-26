"""Student progress dashboard endpoints.

Provides read-only analytics data for the student dashboard UI:
level history, skill radar, quiz trend, attendance, weak areas,
streak, vocabulary stats, and a composite weekly study summary.
"""

from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app.db.database import get_db
from app.routes.auth import require_student_owner

router = APIRouter(prefix="/api/students", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CEFREntry(BaseModel):
    date: str
    overall: str
    grammar: str | None = None
    vocabulary: str | None = None
    reading: str | None = None
    speaking: str | None = None
    writing: str | None = None


class SkillProfile(BaseModel):
    grammar: float | None = None
    vocabulary: float | None = None
    speaking: float | None = None
    listening: float | None = None
    writing: float | None = None
    reading: float | None = None


class QuizTrendEntry(BaseModel):
    date: str
    score: float


class AttendanceStats(BaseModel):
    total_booked: int
    attended: int
    no_show: int
    cancelled: int
    rate: float


class WeakArea(BaseModel):
    point_type: str
    content: str
    ease_factor: float
    times_reviewed: int


class StreakInfo(BaseModel):
    current: int
    longest: int
    freeze_tokens: int
    last_activity_date: str | None = None


class VocabularyStats(BaseModel):
    mastered: int
    learning: int
    new: int
    due_today: int
    total: int


class StudySummary(BaseModel):
    week_start: str
    lessons_completed: int
    xp_earned: int
    vocab_reviewed: int
    games_played: int
    quizzes_taken: int
    current_streak: int
    achievements_earned: int
    average_score: float | None = None


# ---------------------------------------------------------------------------
# 1. Level history
# ---------------------------------------------------------------------------

@router.get("/{student_id}/level-history", response_model=list[CEFREntry])
async def get_level_history(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        """SELECT level, grammar_level, vocabulary_level, reading_level,
                  speaking_level, writing_level, recorded_at
           FROM cefr_history
           WHERE student_id = ?
           ORDER BY recorded_at ASC""",
        (student_id,),
    )
    rows = await cursor.fetchall()
    return [
        CEFREntry(
            date=row["recorded_at"] or "",
            overall=row["level"],
            grammar=row["grammar_level"],
            vocabulary=row["vocabulary_level"],
            reading=row["reading_level"],
            speaking=row["speaking_level"],
            writing=row["writing_level"],
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 2. Skill profile (radar chart data)
# ---------------------------------------------------------------------------

@router.get("/{student_id}/skill-profile", response_model=SkillProfile)
async def get_skill_profile(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        """SELECT skill, AVG(score) as avg_score
           FROM session_skill_observations
           WHERE student_id = ? AND score IS NOT NULL
           GROUP BY skill""",
        (student_id,),
    )
    rows = await cursor.fetchall()
    averages = {row["skill"]: round(row["avg_score"], 1) for row in rows}
    return SkillProfile(**averages)


# ---------------------------------------------------------------------------
# 3. Quiz trend (last 20 recall sessions)
# ---------------------------------------------------------------------------

@router.get("/{student_id}/quiz-trend", response_model=list[QuizTrendEntry])
async def get_quiz_trend(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        """SELECT overall_score, completed_at
           FROM recall_sessions
           WHERE student_id = ? AND status = 'completed' AND overall_score IS NOT NULL
           ORDER BY completed_at DESC
           LIMIT 20""",
        (student_id,),
    )
    rows = await cursor.fetchall()
    # Return chronological order (oldest first) for charting
    return [
        QuizTrendEntry(date=row["completed_at"] or "", score=row["overall_score"])
        for row in reversed(rows)
    ]


# ---------------------------------------------------------------------------
# 4. Attendance
# ---------------------------------------------------------------------------

@router.get("/{student_id}/attendance", response_model=AttendanceStats)
async def get_attendance(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        """SELECT
             COUNT(*) as total_booked,
             SUM(CASE WHEN attended = 1 THEN 1 ELSE 0 END) as attended,
             SUM(CASE WHEN attended = -1 THEN 1 ELSE 0 END) as no_show,
             SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
           FROM sessions
           WHERE student_id = ?""",
        (student_id,),
    )
    row = await cursor.fetchone()
    total = row["total_booked"] or 0
    attended = row["attended"] or 0
    no_show = row["no_show"] or 0
    cancelled = row["cancelled"] or 0
    rate = round(attended / total * 100, 1) if total > 0 else 0.0

    return AttendanceStats(
        total_booked=total,
        attended=attended,
        no_show=no_show,
        cancelled=cancelled,
        rate=rate,
    )


# ---------------------------------------------------------------------------
# 5. Weak areas (learning points with low ease_factor)
# ---------------------------------------------------------------------------

@router.get("/{student_id}/weak-areas", response_model=list[WeakArea])
async def get_weak_areas(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        """SELECT point_type, content, ease_factor, times_reviewed
           FROM learning_points
           WHERE student_id = ? AND ease_factor < 2.0
           ORDER BY ease_factor ASC
           LIMIT 5""",
        (student_id,),
    )
    rows = await cursor.fetchall()
    return [
        WeakArea(
            point_type=row["point_type"],
            content=row["content"],
            ease_factor=round(row["ease_factor"], 2),
            times_reviewed=row["times_reviewed"] or 0,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 6. Streak (current + longest)
# ---------------------------------------------------------------------------

@router.get("/{student_id}/streak", response_model=StreakInfo)
async def get_streak(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        "SELECT streak, freeze_tokens, last_activity_date FROM users WHERE id = ?",
        (student_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")

    current_streak = row["streak"] or 0
    freeze_tokens = row["freeze_tokens"] or 0
    last_activity = row["last_activity_date"]

    # Compute longest streak from xp_log streak_bonus entries.
    # Each streak_bonus detail contains "Day N streak" — extract N.
    cursor = await db.execute(
        """SELECT detail FROM xp_log
           WHERE student_id = ? AND source = 'streak_bonus'
           ORDER BY created_at ASC""",
        (student_id,),
    )
    xp_rows = await cursor.fetchall()
    longest = current_streak  # current streak is at least a candidate
    for xp_row in xp_rows:
        detail = xp_row["detail"] or ""
        # Format: "Day 7 streak"
        if detail.startswith("Day "):
            try:
                day_num = int(detail.split()[1])
                if day_num > longest:
                    longest = day_num
            except (IndexError, ValueError):
                pass

    return StreakInfo(
        current=current_streak,
        longest=longest,
        freeze_tokens=freeze_tokens,
        last_activity_date=last_activity,
    )


# ---------------------------------------------------------------------------
# 7. Vocabulary stats
# ---------------------------------------------------------------------------

@router.get("/{student_id}/vocabulary-stats", response_model=VocabularyStats)
async def get_vocabulary_stats(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)
    cursor = await db.execute(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN interval_days >= 21 THEN 1 ELSE 0 END) as mastered,
             SUM(CASE WHEN interval_days > 0 AND interval_days < 21 THEN 1 ELSE 0 END) as learning,
             SUM(CASE WHEN interval_days = 0 THEN 1 ELSE 0 END) as new_cards,
             SUM(CASE WHEN next_review <= datetime('now') THEN 1 ELSE 0 END) as due_today
           FROM vocabulary_cards
           WHERE student_id = ?""",
        (student_id,),
    )
    row = await cursor.fetchone()
    return VocabularyStats(
        mastered=row["mastered"] or 0,
        learning=row["learning"] or 0,
        new=row["new_cards"] or 0,
        due_today=row["due_today"] or 0,
        total=row["total"] or 0,
    )


# ---------------------------------------------------------------------------
# 8. Weekly study summary (composite)
# ---------------------------------------------------------------------------

@router.get("/{student_id}/study-summary", response_model=StudySummary)
async def get_study_summary(student_id: int, request: Request, db=Depends(get_db)):
    await require_student_owner(request, student_id, db)

    # Determine the Monday of the current week
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    # Lessons completed this week
    cursor = await db.execute(
        """SELECT COUNT(*) as cnt, AVG(score) as avg
           FROM progress
           WHERE student_id = ? AND completed_at >= datetime('now', '-7 days')""",
        (student_id,),
    )
    row = await cursor.fetchone()
    lessons_completed = row["cnt"] or 0
    avg_score = round(row["avg"], 1) if row["avg"] is not None else None

    # XP earned this week
    cursor = await db.execute(
        """SELECT COALESCE(SUM(amount), 0) as xp
           FROM xp_log
           WHERE student_id = ? AND created_at >= datetime('now', '-7 days')""",
        (student_id,),
    )
    xp_earned = (await cursor.fetchone())["xp"]

    # Vocab reviewed this week
    cursor = await db.execute(
        """SELECT COUNT(*) as cnt
           FROM vocabulary_cards
           WHERE student_id = ? AND review_count > 0
             AND next_review > datetime('now', '-7 days')""",
        (student_id,),
    )
    vocab_reviewed = (await cursor.fetchone())["cnt"]

    # Games played this week
    cursor = await db.execute(
        """SELECT COUNT(*) as cnt
           FROM game_scores
           WHERE student_id = ? AND played_at >= datetime('now', '-7 days')""",
        (student_id,),
    )
    games_played = (await cursor.fetchone())["cnt"]

    # Quizzes taken this week
    cursor = await db.execute(
        """SELECT COUNT(*) as cnt
           FROM recall_sessions
           WHERE student_id = ? AND status = 'completed'
             AND completed_at >= datetime('now', '-7 days')""",
        (student_id,),
    )
    quizzes_taken = (await cursor.fetchone())["cnt"]

    # Current streak
    cursor = await db.execute(
        "SELECT streak FROM users WHERE id = ?", (student_id,)
    )
    streak = (await cursor.fetchone())["streak"] or 0

    # Achievements earned this week
    cursor = await db.execute(
        """SELECT COUNT(*) as cnt
           FROM achievements
           WHERE student_id = ? AND earned_at >= datetime('now', '-7 days')""",
        (student_id,),
    )
    achievements = (await cursor.fetchone())["cnt"]

    return StudySummary(
        week_start=week_start,
        lessons_completed=lessons_completed,
        xp_earned=xp_earned,
        vocab_reviewed=vocab_reviewed,
        games_played=games_played,
        quizzes_taken=quizzes_taken,
        current_streak=streak,
        achievements_earned=achievements,
        average_score=avg_score,
    )
