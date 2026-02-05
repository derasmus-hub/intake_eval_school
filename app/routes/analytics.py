import json
from fastapi import APIRouter, HTTPException
from app.db.database import get_db
from app.services.achievement_checker import check_achievements

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/{student_id}/skills")
async def get_skill_analytics(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM progress WHERE student_id = ? ORDER BY completed_at",
            (student_id,),
        )
        rows = await cursor.fetchall()

        skill_data: dict[str, list[float]] = {}
        for row in rows:
            score = row["score"] or 0.0
            areas_improved = json.loads(row["areas_improved"]) if row["areas_improved"] else []
            areas_struggling = json.loads(row["areas_struggling"]) if row["areas_struggling"] else []

            for area in areas_improved:
                skill_data.setdefault(area, []).append(score)
            for area in areas_struggling:
                skill_data.setdefault(area, []).append(max(0, score - 20))

        # Also pull lesson content for topic-based skills
        cursor = await db.execute(
            "SELECT l.content, p.score FROM lessons l JOIN progress p ON l.id = p.lesson_id WHERE l.student_id = ? AND p.score IS NOT NULL",
            (student_id,),
        )
        lesson_rows = await cursor.fetchall()
        for lr in lesson_rows:
            if lr["content"]:
                content = json.loads(lr["content"])
                difficulty = content.get("difficulty", "")
                if difficulty:
                    skill_data.setdefault(f"level_{difficulty}", []).append(lr["score"] or 0)

        skills = {}
        for skill, scores in skill_data.items():
            skills[skill] = {
                "average": round(sum(scores) / len(scores), 1),
                "count": len(scores),
                "trend": "improving" if len(scores) >= 2 and scores[-1] > scores[0] else "stable",
            }

        return {"student_id": student_id, "skills": skills}
    finally:
        await db.close()


@router.get("/{student_id}/timeline")
async def get_timeline(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT p.*, l.session_number, l.objective FROM progress p JOIN lessons l ON p.lesson_id = l.id WHERE p.student_id = ? ORDER BY p.completed_at",
            (student_id,),
        )
        rows = await cursor.fetchall()

        entries = []
        for row in rows:
            entries.append({
                "lesson_id": row["lesson_id"],
                "session_number": row["session_number"],
                "objective": row["objective"],
                "score": row["score"],
                "completed_at": row["completed_at"],
            })

        scores = [e["score"] for e in entries if e["score"] is not None]
        moving_avg = []
        window = 3
        for i in range(len(scores)):
            start = max(0, i - window + 1)
            moving_avg.append(round(sum(scores[start:i + 1]) / len(scores[start:i + 1]), 1))

        return {
            "student_id": student_id,
            "entries": entries,
            "moving_average": moving_avg,
        }
    finally:
        await db.close()


@router.get("/{student_id}/achievements")
async def get_achievements(student_id: int):
    # Check for new achievements using the comprehensive checker
    newly_earned = await check_achievements(student_id)

    db = await get_db()
    try:
        # Return all achievements
        cursor = await db.execute(
            "SELECT * FROM achievements WHERE student_id = ? ORDER BY earned_at",
            (student_id,),
        )
        all_achievements = await cursor.fetchall()

        return {
            "student_id": student_id,
            "achievements": [
                {
                    "id": row["id"],
                    "type": row["type"],
                    "title": row["title"],
                    "description": row["description"],
                    "category": row["category"],
                    "xp_reward": row["xp_reward"],
                    "icon": row["icon"],
                    "earned_at": row["earned_at"],
                }
                for row in all_achievements
            ],
            "newly_earned": [
                {"title": a["title"], "title_pl": a["title_pl"], "xp_reward": a["xp_reward"], "icon": a["icon"]}
                for a in newly_earned
            ],
        }
    finally:
        await db.close()


@router.get("/{student_id}/streak")
async def get_streak(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT DISTINCT DATE(completed_at) as day FROM progress WHERE student_id = ? ORDER BY day DESC",
            (student_id,),
        )
        days = [row["day"] for row in await cursor.fetchall()]
        streak = _calculate_streak(days)

        cursor = await db.execute(
            "SELECT COUNT(*) as total FROM progress WHERE student_id = ?",
            (student_id,),
        )
        total = (await cursor.fetchone())["total"]

        return {
            "student_id": student_id,
            "current_streak": streak,
            "total_lessons": total,
            "study_days": len(days),
        }
    finally:
        await db.close()


def _calculate_streak(days: list[str]) -> int:
    if not days:
        return 0
    from datetime import datetime, timedelta

    streak = 1
    for i in range(1, len(days)):
        prev = datetime.strptime(days[i - 1], "%Y-%m-%d").date()
        curr = datetime.strptime(days[i], "%Y-%m-%d").date()
        if prev - curr == timedelta(days=1):
            streak += 1
        else:
            break
    return streak
