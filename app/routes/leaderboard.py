from fastapi import APIRouter
from app.db.database import get_db
from app.services.xp_engine import get_title_for_level

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("/weekly")
async def weekly_leaderboard():
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT s.id, s.name, s.xp_level, s.avatar_id, s.display_title,
                      COALESCE(SUM(x.amount), 0) as weekly_xp
               FROM students s
               LEFT JOIN xp_log x ON s.id = x.student_id
                   AND x.created_at >= datetime('now', '-7 days')
               GROUP BY s.id
               ORDER BY weekly_xp DESC
               LIMIT 20"""
        )
        rows = await cursor.fetchall()

        entries = []
        for i, row in enumerate(rows):
            title_pl, title_en = get_title_for_level(row["xp_level"] or 1)
            entries.append({
                "rank": i + 1,
                "student_id": row["id"],
                "name": row["name"],
                "level": row["xp_level"] or 1,
                "title": title_en,
                "title_pl": title_pl,
                "avatar_id": row["avatar_id"] or "default",
                "display_title": row["display_title"],
                "xp": row["weekly_xp"],
            })

        return {"period": "weekly", "entries": entries}
    finally:
        await db.close()


@router.get("/alltime")
async def alltime_leaderboard():
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, name, total_xp, xp_level, avatar_id, display_title
               FROM students
               ORDER BY total_xp DESC
               LIMIT 20"""
        )
        rows = await cursor.fetchall()

        entries = []
        for i, row in enumerate(rows):
            title_pl, title_en = get_title_for_level(row["xp_level"] or 1)
            entries.append({
                "rank": i + 1,
                "student_id": row["id"],
                "name": row["name"],
                "level": row["xp_level"] or 1,
                "title": title_en,
                "title_pl": title_pl,
                "avatar_id": row["avatar_id"] or "default",
                "display_title": row["display_title"],
                "xp": row["total_xp"] or 0,
            })

        return {"period": "alltime", "entries": entries}
    finally:
        await db.close()


@router.get("/streak")
async def streak_leaderboard():
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, name, streak, xp_level, avatar_id, display_title
               FROM students
               WHERE streak > 0
               ORDER BY streak DESC
               LIMIT 20"""
        )
        rows = await cursor.fetchall()

        entries = []
        for i, row in enumerate(rows):
            title_pl, title_en = get_title_for_level(row["xp_level"] or 1)
            entries.append({
                "rank": i + 1,
                "student_id": row["id"],
                "name": row["name"],
                "level": row["xp_level"] or 1,
                "title": title_en,
                "title_pl": title_pl,
                "avatar_id": row["avatar_id"] or "default",
                "display_title": row["display_title"],
                "streak": row["streak"],
            })

        return {"period": "streak", "entries": entries}
    finally:
        await db.close()
