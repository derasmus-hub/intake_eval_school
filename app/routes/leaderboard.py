from fastapi import APIRouter, Depends, Request
from app.db.database import get_db
from app.services.xp_engine import get_title_for_level
from app.routes.auth import get_current_user

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("/weekly")
async def weekly_leaderboard(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    org_id = user.get("org_id")

    if org_id:
        cursor = await db.execute(
            """SELECT s.id, s.name, s.xp_level, s.avatar_id, s.display_title,
                      COALESCE(SUM(x.amount), 0) as weekly_xp
               FROM users s
               LEFT JOIN xp_log x ON s.id = x.student_id
                   AND x.created_at >= datetime('now', '-7 days')
               WHERE s.org_id = ?
               GROUP BY s.id
               ORDER BY weekly_xp DESC
               LIMIT 20""",
            (org_id,),
        )
    else:
        cursor = await db.execute(
            """SELECT s.id, s.name, s.xp_level, s.avatar_id, s.display_title,
                      COALESCE(SUM(x.amount), 0) as weekly_xp
               FROM users s
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


@router.get("/alltime")
async def alltime_leaderboard(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    org_id = user.get("org_id")

    if org_id:
        cursor = await db.execute(
            """SELECT id, name, total_xp, xp_level, avatar_id, display_title
               FROM users WHERE org_id = ?
               ORDER BY total_xp DESC
               LIMIT 20""",
            (org_id,),
        )
    else:
        cursor = await db.execute(
            """SELECT id, name, total_xp, xp_level, avatar_id, display_title
               FROM users
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


@router.get("/streak")
async def streak_leaderboard(request: Request, db=Depends(get_db)):
    user = await get_current_user(request, db)
    org_id = user.get("org_id")

    if org_id:
        cursor = await db.execute(
            """SELECT id, name, streak, xp_level, avatar_id, display_title
               FROM users
               WHERE streak > 0 AND org_id = ?
               ORDER BY streak DESC
               LIMIT 20""",
            (org_id,),
        )
    else:
        cursor = await db.execute(
            """SELECT id, name, streak, xp_level, avatar_id, display_title
               FROM users
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
