from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.db.database import get_db
from app.services.xp_engine import get_student_xp_profile, award_xp, update_streak
from app.services.achievement_checker import check_achievements, ACHIEVEMENT_DEFINITIONS

router = APIRouter(prefix="/api/gamification", tags=["gamification"])

AVATARS = [
    {"id": "default", "name": "Student", "name_pl": "Uczen", "unlocked_at": 1},
    {"id": "fox", "name": "Clever Fox", "name_pl": "Sprytny lis", "unlocked_at": 1},
    {"id": "owl", "name": "Wise Owl", "name_pl": "Madra sowa", "unlocked_at": 5},
    {"id": "eagle", "name": "Bold Eagle", "name_pl": "Odwazny orzel", "unlocked_at": 10},
    {"id": "wolf", "name": "Lone Wolf", "name_pl": "Samotny wilk", "unlocked_at": 15},
    {"id": "bear", "name": "Strong Bear", "name_pl": "Silny niedzwiedz", "unlocked_at": 20},
    {"id": "dragon", "name": "Wise Dragon", "name_pl": "Madry smok", "unlocked_at": 25},
    {"id": "phoenix", "name": "Phoenix", "name_pl": "Feniks", "unlocked_at": 30},
    {"id": "unicorn", "name": "Unicorn", "name_pl": "Jednorozec", "unlocked_at": 35},
    {"id": "lion", "name": "Golden Lion", "name_pl": "Zloty lew", "unlocked_at": 40},
    {"id": "star", "name": "Superstar", "name_pl": "Supergwiazda", "unlocked_at": 45},
]


class ProfileUpdate(BaseModel):
    avatar_id: Optional[str] = None
    theme_preference: Optional[str] = None
    display_title: Optional[str] = None


@router.get("/{student_id}/profile")
async def get_profile(student_id: int):
    profile = await get_student_xp_profile(student_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Student not found")

    # Get available avatars based on level
    level = profile["level"]
    available_avatars = [a for a in AVATARS if a["unlocked_at"] <= level]
    locked_avatars = [a for a in AVATARS if a["unlocked_at"] > level]

    # Get achievements
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM achievements WHERE student_id = ? ORDER BY earned_at DESC",
            (student_id,),
        )
        achievements = [
            {
                "type": row["type"],
                "title": row["title"],
                "description": row["description"],
                "category": row["category"],
                "xp_reward": row["xp_reward"],
                "icon": row["icon"],
                "earned_at": row["earned_at"],
            }
            for row in await cursor.fetchall()
        ]

        # Weekly summary
        cursor = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) as weekly_xp FROM xp_log WHERE student_id = ? AND created_at >= datetime('now', '-7 days')",
            (student_id,),
        )
        weekly_xp = (await cursor.fetchone())["weekly_xp"]

        cursor = await db.execute(
            "SELECT COUNT(*) as lessons_this_week FROM progress WHERE student_id = ? AND completed_at >= datetime('now', '-7 days')",
            (student_id,),
        )
        lessons_week = (await cursor.fetchone())["lessons_this_week"]

    finally:
        await db.close()

    profile["achievements"] = achievements
    profile["available_avatars"] = available_avatars
    profile["locked_avatars"] = locked_avatars
    profile["weekly_summary"] = {
        "xp_earned": weekly_xp,
        "lessons_completed": lessons_week,
    }

    return profile


@router.put("/{student_id}/profile")
async def update_profile(student_id: int, update: ProfileUpdate):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        if update.avatar_id:
            # Validate avatar is unlocked
            level = student["xp_level"] or 1
            avatar = next((a for a in AVATARS if a["id"] == update.avatar_id), None)
            if not avatar:
                raise HTTPException(status_code=400, detail="Invalid avatar")
            if avatar["unlocked_at"] > level:
                raise HTTPException(status_code=403, detail="Avatar not yet unlocked")
            await db.execute(
                "UPDATE students SET avatar_id = ? WHERE id = ?",
                (update.avatar_id, student_id),
            )

        if update.theme_preference and update.theme_preference in ("light", "dark", "blue"):
            await db.execute(
                "UPDATE students SET theme_preference = ? WHERE id = ?",
                (update.theme_preference, student_id),
            )

        if update.display_title is not None:
            await db.execute(
                "UPDATE students SET display_title = ? WHERE id = ?",
                (update.display_title, student_id),
            )

        await db.commit()
        return {"updated": True}
    finally:
        await db.close()


@router.post("/{student_id}/check-achievements")
async def trigger_achievement_check(student_id: int, body: dict = None):
    context = body or {}
    newly_earned = await check_achievements(student_id, context)
    return {
        "newly_earned": [
            {"type": a["type"], "title": a["title"], "title_pl": a["title_pl"],
             "description": a["description"], "xp_reward": a["xp_reward"], "icon": a["icon"]}
            for a in newly_earned
        ]
    }


@router.post("/{student_id}/activity")
async def record_activity(student_id: int):
    """Record that a student was active today. Updates streak."""
    streak_result = await update_streak(student_id)
    achievements = await check_achievements(student_id)
    return {
        "streak": streak_result,
        "new_achievements": [
            {"title": a["title"], "title_pl": a["title_pl"], "xp_reward": a["xp_reward"], "icon": a["icon"]}
            for a in achievements
        ],
    }


@router.get("/{student_id}/weekly-summary")
async def get_weekly_summary(student_id: int):
    db = await get_db()
    try:
        # XP earned this week
        cursor = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) as xp FROM xp_log WHERE student_id = ? AND created_at >= datetime('now', '-7 days')",
            (student_id,),
        )
        weekly_xp = (await cursor.fetchone())["xp"]

        # Lessons completed this week
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM progress WHERE student_id = ? AND completed_at >= datetime('now', '-7 days')",
            (student_id,),
        )
        lessons = (await cursor.fetchone())["cnt"]

        # Vocab reviewed
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM vocabulary_cards WHERE student_id = ? AND next_review > datetime('now', '-7 days')",
            (student_id,),
        )
        vocab_reviewed = (await cursor.fetchone())["cnt"]

        # Games played
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM game_scores WHERE student_id = ? AND played_at >= datetime('now', '-7 days')",
            (student_id,),
        )
        games = (await cursor.fetchone())["cnt"]

        # Streak
        cursor = await db.execute(
            "SELECT streak FROM students WHERE id = ?", (student_id,)
        )
        streak = (await cursor.fetchone())["streak"] or 0

        # Achievements earned this week
        cursor = await db.execute(
            "SELECT title, icon FROM achievements WHERE student_id = ? AND earned_at >= datetime('now', '-7 days')",
            (student_id,),
        )
        new_achievements = [{"title": r["title"], "icon": r["icon"]} for r in await cursor.fetchall()]

        # Encouragement messages (Polish)
        encouragements = []
        if weekly_xp > 200:
            encouragements.append("Niesamowity tydzien! Tak trzymaj!")
        if lessons >= 5:
            encouragements.append("Pilny uczen! 5 lekcji w tydzien to swietny wynik!")
        if streak >= 7:
            encouragements.append(f"Seria {streak} dni! Jestes niezlomny!")
        if not encouragements:
            encouragements.append("Kazdy krok sie liczy. Kontynuuj nauke!")

        return {
            "student_id": student_id,
            "weekly_xp": weekly_xp,
            "lessons_completed": lessons,
            "vocab_reviewed": vocab_reviewed,
            "games_played": games,
            "current_streak": streak,
            "new_achievements": new_achievements,
            "encouragements": encouragements,
        }
    finally:
        await db.close()
