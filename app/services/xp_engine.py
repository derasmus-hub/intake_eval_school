import json
from datetime import datetime, date
from app.db.database import get_db

# XP awards for different activities
XP_AWARDS = {
    "lesson_complete": 50,
    "perfect_recall": 30,
    "recall_complete": 15,
    "vocab_review": 10,
    "conversation": 25,
    "streak_bonus": 20,
    "game_complete": 15,
    "daily_challenge": 30,
    "daily_challenge_bonus": 100,
    "achievement": 0,  # varies per achievement
}

# Level thresholds: level -> cumulative XP needed
LEVEL_THRESHOLDS = {}
for i in range(1, 51):
    if i == 1:
        LEVEL_THRESHOLDS[i] = 0
    elif i <= 5:
        LEVEL_THRESHOLDS[i] = (i - 1) * 100
    elif i <= 10:
        LEVEL_THRESHOLDS[i] = 400 + (i - 5) * 200
    elif i <= 20:
        LEVEL_THRESHOLDS[i] = 1400 + (i - 10) * 350
    elif i <= 30:
        LEVEL_THRESHOLDS[i] = 4900 + (i - 20) * 500
    elif i <= 40:
        LEVEL_THRESHOLDS[i] = 9900 + (i - 30) * 750
    else:
        LEVEL_THRESHOLDS[i] = 17400 + (i - 40) * 1000

# Polish titles by level range
LEVEL_TITLES = {
    (1, 5): ("Poczatkujacy", "Beginner"),
    (6, 10): ("Uczen", "Student"),
    (11, 15): ("Adept", "Apprentice"),
    (16, 20): ("Student", "Scholar"),
    (21, 25): ("Znawca", "Expert"),
    (26, 30): ("Specjalista", "Specialist"),
    (31, 35): ("Mistrz", "Master"),
    (36, 40): ("Ekspert", "Authority"),
    (41, 45): ("Wirtuoz", "Virtuoso"),
    (46, 50): ("Legenda", "Legend"),
}


def get_level_for_xp(total_xp: int) -> int:
    level = 1
    for lvl in sorted(LEVEL_THRESHOLDS.keys()):
        if total_xp >= LEVEL_THRESHOLDS[lvl]:
            level = lvl
        else:
            break
    return level


def get_title_for_level(level: int) -> tuple[str, str]:
    for (low, high), titles in LEVEL_TITLES.items():
        if low <= level <= high:
            return titles
    return ("Legenda", "Legend")


def get_xp_for_next_level(level: int, total_xp: int) -> dict:
    next_level = level + 1
    if next_level > 50:
        return {"current_xp": total_xp, "next_level_xp": total_xp, "progress": 1.0}
    current_threshold = LEVEL_THRESHOLDS.get(level, 0)
    next_threshold = LEVEL_THRESHOLDS.get(next_level, total_xp)
    range_xp = next_threshold - current_threshold
    progress_xp = total_xp - current_threshold
    progress = min(1.0, progress_xp / range_xp) if range_xp > 0 else 1.0
    return {
        "current_xp": total_xp,
        "level_start_xp": current_threshold,
        "next_level_xp": next_threshold,
        "progress": round(progress, 3),
    }


async def award_xp(student_id: int, amount: int, source: str, detail: str = None) -> dict:
    db = await get_db()
    try:
        # Log XP
        await db.execute(
            "INSERT INTO xp_log (student_id, amount, source, detail) VALUES (?, ?, ?, ?)",
            (student_id, amount, source, detail),
        )

        # Update total
        await db.execute(
            "UPDATE students SET total_xp = total_xp + ? WHERE id = ?",
            (amount, student_id),
        )
        await db.commit()

        # Get new total
        cursor = await db.execute(
            "SELECT total_xp, xp_level FROM students WHERE id = ?", (student_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"xp_gained": amount, "total_xp": 0, "level": 1, "leveled_up": False}

        total_xp = row["total_xp"]
        old_level = row["xp_level"]
        new_level = get_level_for_xp(total_xp)

        leveled_up = new_level > old_level
        if leveled_up:
            await db.execute(
                "UPDATE students SET xp_level = ? WHERE id = ?",
                (new_level, student_id),
            )
            await db.commit()

        title_pl, title_en = get_title_for_level(new_level)
        progress = get_xp_for_next_level(new_level, total_xp)

        return {
            "xp_gained": amount,
            "total_xp": total_xp,
            "level": new_level,
            "leveled_up": leveled_up,
            "old_level": old_level if leveled_up else None,
            "title": title_en,
            "title_pl": title_pl,
            "progress": progress,
        }
    finally:
        await db.close()


async def update_streak(student_id: int) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT streak, last_activity_date, freeze_tokens FROM students WHERE id = ?",
            (student_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {"streak": 0, "streak_bonus": 0}

        today = date.today().isoformat()
        last_date = row["last_activity_date"]
        current_streak = row["streak"] or 0
        freeze_tokens = row["freeze_tokens"] or 0

        streak_bonus = 0

        if last_date == today:
            # Already active today
            return {"streak": current_streak, "streak_bonus": 0, "already_active": True}

        yesterday = date.today().isoformat()
        from datetime import timedelta
        yesterday_date = (date.today() - timedelta(days=1)).isoformat()

        if last_date == yesterday_date:
            # Continuing streak
            current_streak += 1
            streak_bonus = XP_AWARDS["streak_bonus"]
        elif last_date and last_date < yesterday_date:
            # Missed a day — check freeze tokens
            days_missed = (date.today() - date.fromisoformat(last_date)).days - 1
            if days_missed == 1 and freeze_tokens > 0:
                # Use freeze token
                current_streak += 1
                freeze_tokens -= 1
                await db.execute(
                    "UPDATE students SET freeze_tokens = ? WHERE id = ?",
                    (freeze_tokens, student_id),
                )
                streak_bonus = XP_AWARDS["streak_bonus"]
            else:
                # Streak broken
                current_streak = 1
        else:
            # First activity ever
            current_streak = 1

        await db.execute(
            "UPDATE students SET streak = ?, last_activity_date = ? WHERE id = ?",
            (current_streak, today, student_id),
        )
        await db.commit()

        # Award streak bonus XP
        if streak_bonus > 0:
            await award_xp(student_id, streak_bonus, "streak_bonus", f"Day {current_streak} streak")

        return {
            "streak": current_streak,
            "streak_bonus": streak_bonus,
            "freeze_tokens_remaining": freeze_tokens,
        }
    finally:
        await db.close()


async def get_student_xp_profile(student_id: int) -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT total_xp, xp_level, streak, freeze_tokens, last_activity_date, avatar_id, theme_preference, display_title, name FROM students WHERE id = ?",
            (student_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        total_xp = row["total_xp"] or 0
        level = row["xp_level"] or 1
        title_pl, title_en = get_title_for_level(level)
        progress = get_xp_for_next_level(level, total_xp)

        # Recent XP log
        cursor = await db.execute(
            "SELECT * FROM xp_log WHERE student_id = ? ORDER BY created_at DESC LIMIT 20",
            (student_id,),
        )
        xp_history = [
            {"amount": r["amount"], "source": r["source"], "detail": r["detail"], "date": r["created_at"]}
            for r in await cursor.fetchall()
        ]

        return {
            "student_id": student_id,
            "name": row["name"],
            "total_xp": total_xp,
            "level": level,
            "title": title_en,
            "title_pl": title_pl,
            "progress": progress,
            "streak": row["streak"] or 0,
            "freeze_tokens": row["freeze_tokens"] or 0,
            "last_activity_date": row["last_activity_date"],
            "avatar_id": row["avatar_id"] or "default",
            "theme_preference": row["theme_preference"] or "light",
            "display_title": row["display_title"],
            "xp_history": xp_history,
        }
    finally:
        await db.close()
