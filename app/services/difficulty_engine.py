"""Adaptive difficulty engine based on SM-2 spaced-repetition data.

Aggregates ease_factor per skill domain from learning_points to determine
where a student is struggling vs mastering, then produces per-skill
difficulty guidance for the lesson generator.
"""

import aiosqlite


async def get_skill_difficulty_profile(student_id: int, db: aiosqlite.Connection) -> dict:
    """Return per-skill difficulty adjustment based on SM-2 performance.

    ease_factor < 1.8  → "simplify"   (student is struggling)
    ease_factor > 2.8  → "challenge"  (student is mastering)
    otherwise          → "maintain"   (appropriate level)

    Returns dict like {"grammar_rule": "simplify", "vocabulary": "challenge", ...}
    Only includes skills with at least 3 data points.
    """
    cursor = await db.execute(
        """SELECT point_type, AVG(ease_factor) as avg_ease, COUNT(*) as count
           FROM learning_points
           WHERE student_id = ?
           GROUP BY point_type""",
        (student_id,),
    )

    profile = {}
    for row in await cursor.fetchall():
        # Require a minimum sample size to avoid noisy signals
        if row["count"] < 3:
            continue
        avg_ease = row["avg_ease"]
        if avg_ease < 1.8:
            profile[row["point_type"]] = "simplify"
        elif avg_ease > 2.8:
            profile[row["point_type"]] = "challenge"
        else:
            profile[row["point_type"]] = "maintain"

    return profile
