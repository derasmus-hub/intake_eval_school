import json
import random
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from app.db.database import get_db
from app.services.xp_engine import award_xp, XP_AWARDS

router = APIRouter(prefix="/api/challenges", tags=["challenges"])

CHALLENGE_TEMPLATES = [
    {"type": "complete_lesson", "title": "Complete a Lesson", "title_pl": "Ukoncz lekcje", "description": "Complete any lesson today", "target": 1, "reward_xp": 30},
    {"type": "review_vocab", "title": "Vocab Review", "title_pl": "Powtorka slowek", "description": "Review 5 vocabulary cards", "target": 5, "reward_xp": 25},
    {"type": "practice_conversation", "title": "Chat Practice", "title_pl": "Cwiczenie rozmowy", "description": "Send 3 messages in conversation", "target": 3, "reward_xp": 30},
    {"type": "perfect_recall", "title": "Perfect Recall", "title_pl": "Perfekcyjna pamiec", "description": "Score 80%+ on a recall quiz", "target": 1, "reward_xp": 40},
    {"type": "play_game", "title": "Game Time", "title_pl": "Czas na gre", "description": "Play any mini-game", "target": 1, "reward_xp": 25},
    {"type": "high_score", "title": "High Scorer", "title_pl": "Rekord", "description": "Score 90%+ on a lesson", "target": 1, "reward_xp": 35},
    {"type": "vocab_add", "title": "Word Hunter", "title_pl": "Lowca slow", "description": "Add 3 new vocabulary words", "target": 3, "reward_xp": 25},
    {"type": "two_lessons", "title": "Double Down", "title_pl": "Podwojnie", "description": "Complete 2 lessons today", "target": 2, "reward_xp": 50},
]


@router.get("/{student_id}/today")
async def get_today_challenges(student_id: int):
    db = await get_db()
    try:
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check if challenges exist for today
        cursor = await db.execute(
            "SELECT * FROM daily_challenges WHERE student_id = ? AND expires_at > ? ORDER BY id",
            (student_id, now.isoformat()),
        )
        challenges = await cursor.fetchall()

        if len(challenges) == 0:
            # Generate 3 new challenges
            templates = random.sample(CHALLENGE_TEMPLATES, min(3, len(CHALLENGE_TEMPLATES)))
            expires = (today_start + timedelta(days=1)).isoformat()

            for tmpl in templates:
                await db.execute(
                    """INSERT INTO daily_challenges
                       (student_id, challenge_type, title, title_pl, description, target, reward_xp, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (student_id, tmpl["type"], tmpl["title"], tmpl["title_pl"],
                     tmpl["description"], tmpl["target"], tmpl["reward_xp"], expires),
                )
            await db.commit()

            cursor = await db.execute(
                "SELECT * FROM daily_challenges WHERE student_id = ? AND expires_at > ? ORDER BY id",
                (student_id, now.isoformat()),
            )
            challenges = await cursor.fetchall()

        result = []
        all_completed = True
        for ch in challenges:
            completed = ch["completed"] == 1
            claimed = ch["claimed"] == 1
            if not completed:
                all_completed = False
            result.append({
                "id": ch["id"],
                "type": ch["challenge_type"],
                "title": ch["title"],
                "title_pl": ch["title_pl"],
                "description": ch["description"],
                "target": ch["target"],
                "progress": ch["progress"],
                "reward_xp": ch["reward_xp"],
                "completed": completed,
                "claimed": claimed,
                "expires_at": ch["expires_at"],
            })

        # Check bonus eligibility
        all_claimed = all(ch["claimed"] == 1 for ch in challenges)

        return {
            "student_id": student_id,
            "challenges": result,
            "all_completed": all_completed,
            "bonus_available": all_completed and not all_claimed,
            "bonus_xp": XP_AWARDS["daily_challenge_bonus"],
        }
    finally:
        await db.close()


@router.post("/{challenge_id}/claim")
async def claim_challenge(challenge_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM daily_challenges WHERE id = ?", (challenge_id,)
        )
        challenge = await cursor.fetchone()
        if not challenge:
            raise HTTPException(status_code=404, detail="Challenge not found")

        if not challenge["completed"]:
            raise HTTPException(status_code=400, detail="Challenge not yet completed")

        if challenge["claimed"]:
            raise HTTPException(status_code=400, detail="Already claimed")

        student_id = challenge["student_id"]

        await db.execute(
            "UPDATE daily_challenges SET claimed = 1 WHERE id = ?", (challenge_id,)
        )
        await db.commit()

        # Award XP
        xp_result = await award_xp(
            student_id, challenge["reward_xp"], "daily_challenge", challenge["title"]
        )

        return {"claimed": True, "xp_result": xp_result}
    finally:
        await db.close()


@router.post("/{student_id}/claim-bonus")
async def claim_bonus(student_id: int):
    db = await get_db()
    try:
        now = datetime.utcnow()
        cursor = await db.execute(
            "SELECT * FROM daily_challenges WHERE student_id = ? AND expires_at > ?",
            (student_id, now.isoformat()),
        )
        challenges = await cursor.fetchall()

        if not challenges:
            raise HTTPException(status_code=404, detail="No challenges found")

        all_completed = all(ch["completed"] == 1 for ch in challenges)
        if not all_completed:
            raise HTTPException(status_code=400, detail="Not all challenges completed")

        all_claimed = all(ch["claimed"] == 1 for ch in challenges)
        if all_claimed:
            raise HTTPException(status_code=400, detail="Bonus already claimed")

        # Mark all as claimed
        for ch in challenges:
            if not ch["claimed"]:
                await db.execute(
                    "UPDATE daily_challenges SET claimed = 1 WHERE id = ?", (ch["id"],)
                )
        await db.commit()

        xp_result = await award_xp(
            student_id, XP_AWARDS["daily_challenge_bonus"], "daily_challenge_bonus", "All daily challenges completed"
        )

        return {"bonus_claimed": True, "xp_result": xp_result}
    finally:
        await db.close()


async def update_challenge_progress(student_id: int, challenge_type: str, increment: int = 1):
    """Called by other routes when a relevant action happens."""
    db = await get_db()
    try:
        now = datetime.utcnow()
        cursor = await db.execute(
            """SELECT * FROM daily_challenges
               WHERE student_id = ? AND challenge_type = ? AND expires_at > ? AND completed = 0""",
            (student_id, challenge_type, now.isoformat()),
        )
        challenges = await cursor.fetchall()

        for ch in challenges:
            new_progress = min(ch["progress"] + increment, ch["target"])
            completed = 1 if new_progress >= ch["target"] else 0
            await db.execute(
                "UPDATE daily_challenges SET progress = ?, completed = ? WHERE id = ?",
                (new_progress, completed, ch["id"]),
            )

        if challenges:
            await db.commit()
    finally:
        await db.close()
