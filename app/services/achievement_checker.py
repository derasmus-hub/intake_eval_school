import json
from app.db.database import get_db
from app.services.xp_engine import award_xp

ACHIEVEMENT_DEFINITIONS = [
    # Progress category
    {"type": "first_lesson", "title": "First Steps", "title_pl": "Pierwsze kroki", "description": "Complete your first lesson", "category": "progress", "xp_reward": 20, "icon": "foot"},
    {"type": "five_lessons", "title": "Getting Going", "title_pl": "Rozpedzam sie", "description": "Complete 5 lessons", "category": "progress", "xp_reward": 50, "icon": "rocket"},
    {"type": "ten_lessons", "title": "Dedicated Learner", "title_pl": "Pilny uczen", "description": "Complete 10 lessons", "category": "progress", "xp_reward": 100, "icon": "book"},
    {"type": "twenty_five_lessons", "title": "Quarter Century", "title_pl": "Cwierc setki", "description": "Complete 25 lessons", "category": "progress", "xp_reward": 200, "icon": "trophy"},
    {"type": "fifty_lessons", "title": "Half Way Hero", "title_pl": "Bohater polowy", "description": "Complete 50 lessons", "category": "progress", "xp_reward": 500, "icon": "star"},

    # Mastery category
    {"type": "high_scorer", "title": "High Achiever", "title_pl": "Prymus", "description": "Average score above 85%", "category": "mastery", "xp_reward": 75, "icon": "target"},
    {"type": "perfect_score", "title": "Perfection!", "title_pl": "Perfekcja!", "description": "Score 100% on a lesson", "category": "mastery", "xp_reward": 50, "icon": "sparkle"},
    {"type": "perfect_recall", "title": "Total Recall", "title_pl": "Pamiec absolutna", "description": "Score 100% on a recall quiz", "category": "mastery", "xp_reward": 40, "icon": "brain"},
    {"type": "level_up_b1", "title": "Intermediate!", "title_pl": "Sredniozaawansowany!", "description": "Reach B1 level", "category": "mastery", "xp_reward": 150, "icon": "medal"},
    {"type": "level_up_b2", "title": "Upper Intermediate!", "title_pl": "Wyzszy sredni!", "description": "Reach B2 level", "category": "mastery", "xp_reward": 300, "icon": "crown"},

    # Dedication category
    {"type": "streak_3", "title": "On a Roll", "title_pl": "Jestem na fali", "description": "3-day study streak", "category": "dedication", "xp_reward": 30, "icon": "fire"},
    {"type": "streak_7", "title": "Week Warrior", "title_pl": "Tygodniowy wojownik", "description": "7-day study streak", "category": "dedication", "xp_reward": 75, "icon": "flame"},
    {"type": "streak_14", "title": "Fortnight Fighter", "title_pl": "Dwutygodniowy biegacz", "description": "14-day study streak", "category": "dedication", "xp_reward": 150, "icon": "lightning"},
    {"type": "streak_30", "title": "Monthly Master", "title_pl": "Mistrz miesiaca", "description": "30-day study streak", "category": "dedication", "xp_reward": 300, "icon": "diamond"},
    {"type": "xp_level_10", "title": "Double Digits", "title_pl": "Podwojne cyfry", "description": "Reach XP level 10", "category": "dedication", "xp_reward": 100, "icon": "up"},
    {"type": "xp_level_25", "title": "Quarter Master", "title_pl": "Cwierc mistrz", "description": "Reach XP level 25", "category": "dedication", "xp_reward": 250, "icon": "gem"},

    # Vocabulary category
    {"type": "vocab_10", "title": "Word Collector", "title_pl": "Zbieracz slow", "description": "Learn 10 vocabulary words", "category": "vocabulary", "xp_reward": 25, "icon": "cards"},
    {"type": "vocab_50", "title": "Wordsmith", "title_pl": "Slownikarz", "description": "Learn 50 vocabulary words", "category": "vocabulary", "xp_reward": 75, "icon": "scroll"},
    {"type": "vocab_100", "title": "Lexicon Lord", "title_pl": "Wladca leksykonu", "description": "Learn 100 vocabulary words", "category": "vocabulary", "xp_reward": 200, "icon": "castle"},
    {"type": "vocab_mastered_10", "title": "Memory Master", "title_pl": "Mistrz pamieci", "description": "Master 10 vocabulary words", "category": "vocabulary", "xp_reward": 100, "icon": "lock"},

    # Secret category
    {"type": "night_owl", "title": "Night Owl", "title_pl": "Nocna sowa", "description": "Study after midnight", "category": "secret", "xp_reward": 25, "icon": "moon"},
    {"type": "early_bird", "title": "Early Bird", "title_pl": "Ranny ptaszek", "description": "Study before 6 AM", "category": "secret", "xp_reward": 25, "icon": "sun"},
    {"type": "game_master", "title": "Game Master", "title_pl": "Mistrz gier", "description": "Play all 4 mini-games", "category": "secret", "xp_reward": 50, "icon": "controller"},
    {"type": "comeback_kid", "title": "Comeback Kid", "title_pl": "Wielki powrot", "description": "Return after 7+ days away", "category": "secret", "xp_reward": 40, "icon": "refresh"},
]


async def check_achievements(student_id: int, context: dict = None) -> list[dict]:
    """
    Check and award any newly earned achievements.
    context: optional dict with keys like 'action', 'score', 'hour', etc.
    Returns list of newly earned achievement dicts.
    """
    context = context or {}
    db = await get_db()
    try:
        # Get existing achievements
        cursor = await db.execute(
            "SELECT type FROM achievements WHERE student_id = ?", (student_id,)
        )
        earned_types = {row["type"] for row in await cursor.fetchall()}

        # Get student stats
        cursor = await db.execute(
            "SELECT total_xp, xp_level, streak, current_level FROM students WHERE id = ?",
            (student_id,),
        )
        student = await cursor.fetchone()
        if not student:
            return []

        xp_level = student["xp_level"] or 1
        streak = student["streak"] or 0
        current_level = student["current_level"] or "A1"

        # Progress stats
        cursor = await db.execute(
            "SELECT COUNT(*) as total, AVG(score) as avg_score, MAX(score) as max_score FROM progress WHERE student_id = ?",
            (student_id,),
        )
        stats = await cursor.fetchone()
        total_lessons = stats["total"] or 0
        avg_score = stats["avg_score"] or 0
        max_score = stats["max_score"] or 0

        # Vocab stats
        cursor = await db.execute(
            "SELECT COUNT(*) as total FROM vocabulary_cards WHERE student_id = ?",
            (student_id,),
        )
        vocab_total = (await cursor.fetchone())["total"]

        cursor = await db.execute(
            "SELECT COUNT(*) as mastered FROM vocabulary_cards WHERE student_id = ? AND repetitions >= 5",
            (student_id,),
        )
        vocab_mastered = (await cursor.fetchone())["mastered"]

        # Recall stats
        cursor = await db.execute(
            "SELECT MAX(overall_score) as max_recall FROM recall_sessions WHERE student_id = ? AND status = 'completed'",
            (student_id,),
        )
        recall_row = await cursor.fetchone()
        max_recall = recall_row["max_recall"] if recall_row else 0

        # Game stats
        cursor = await db.execute(
            "SELECT DISTINCT game_type FROM game_scores WHERE student_id = ?",
            (student_id,),
        )
        game_types_played = {row["game_type"] for row in await cursor.fetchall()}

        # Check conditions
        hour = context.get("hour", datetime_hour())

        conditions = {
            "first_lesson": total_lessons >= 1,
            "five_lessons": total_lessons >= 5,
            "ten_lessons": total_lessons >= 10,
            "twenty_five_lessons": total_lessons >= 25,
            "fifty_lessons": total_lessons >= 50,
            "high_scorer": total_lessons >= 3 and avg_score > 85,
            "perfect_score": max_score >= 100,
            "perfect_recall": max_recall and max_recall >= 100,
            "level_up_b1": current_level in ("B1", "B2", "C1", "C2"),
            "level_up_b2": current_level in ("B2", "C1", "C2"),
            "streak_3": streak >= 3,
            "streak_7": streak >= 7,
            "streak_14": streak >= 14,
            "streak_30": streak >= 30,
            "xp_level_10": xp_level >= 10,
            "xp_level_25": xp_level >= 25,
            "vocab_10": vocab_total >= 10,
            "vocab_50": vocab_total >= 50,
            "vocab_100": vocab_total >= 100,
            "vocab_mastered_10": vocab_mastered >= 10,
            "night_owl": 0 <= hour < 4,
            "early_bird": 4 <= hour < 6,
            "game_master": len(game_types_played) >= 4,
            "comeback_kid": context.get("comeback", False),
        }

        newly_earned = []
        for ach_def in ACHIEVEMENT_DEFINITIONS:
            atype = ach_def["type"]
            if atype in earned_types:
                continue
            if conditions.get(atype, False):
                await db.execute(
                    "INSERT INTO achievements (student_id, type, title, description, category, xp_reward, icon) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (student_id, atype, ach_def["title"], ach_def["description"],
                     ach_def["category"], ach_def["xp_reward"], ach_def["icon"]),
                )
                newly_earned.append(ach_def)

        if newly_earned:
            await db.commit()

            # Award XP for each achievement
            for ach in newly_earned:
                if ach["xp_reward"] > 0:
                    await award_xp(student_id, ach["xp_reward"], "achievement", ach["title"])

        return newly_earned
    finally:
        await db.close()


def datetime_hour() -> int:
    from datetime import datetime
    return datetime.now().hour
