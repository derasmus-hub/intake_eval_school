import json
from app.db.database import get_db


async def get_skill_averages(student_id: int) -> dict[str, float]:
    """Calculate running averages per skill area from progress history."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM progress WHERE student_id = ? ORDER BY completed_at",
            (student_id,),
        )
        rows = await cursor.fetchall()

        skill_scores: dict[str, list[float]] = {}

        for row in rows:
            score = row["score"] or 0.0
            areas_improved = json.loads(row["areas_improved"]) if row["areas_improved"] else []
            areas_struggling = json.loads(row["areas_struggling"]) if row["areas_struggling"] else []

            for area in areas_improved:
                skill_scores.setdefault(area, []).append(score)
            for area in areas_struggling:
                skill_scores.setdefault(area, []).append(max(0, score - 20))

        return {k: round(sum(v) / len(v), 1) for k, v in skill_scores.items()}
    finally:
        await db.close()


async def get_next_focus_area(student_id: int, priority_areas: list[str]) -> str | None:
    """Determine which area to focus on next based on progress data."""
    averages = await get_skill_averages(student_id)

    if not averages:
        return priority_areas[0] if priority_areas else None

    # Find lowest-scoring priority area
    lowest_area = None
    lowest_score = float("inf")

    for area in priority_areas:
        area_score = averages.get(area, 0.0)
        if area_score < lowest_score:
            lowest_score = area_score
            lowest_area = area

    return lowest_area
