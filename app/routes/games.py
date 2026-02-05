import json
import yaml
import random
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from openai import AsyncOpenAI
from app.config import settings
from app.db.database import get_db
from app.services.xp_engine import award_xp
from app.routes.challenges import update_challenge_progress

router = APIRouter(prefix="/api/games", tags=["games"])

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class GameSubmission(BaseModel):
    game_type: str
    score: int
    data: Optional[dict] = None


@router.get("/{student_id}/word-match")
async def generate_word_match(student_id: int):
    """Generate a word matching game from the student's vocabulary."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT current_level FROM students WHERE id = ?", (student_id,)
        )
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        # Get vocabulary cards
        cursor = await db.execute(
            "SELECT word, translation FROM vocabulary_cards WHERE student_id = ? ORDER BY RANDOM() LIMIT 8",
            (student_id,),
        )
        cards = await cursor.fetchall()

        if len(cards) < 4:
            # Generate fallback pairs using AI
            pairs = await _generate_word_pairs(student["current_level"] or "A1", 8)
        else:
            pairs = [{"word": c["word"], "translation": c["translation"]} for c in cards]

        # Shuffle translations separately for matching
        words = [p["word"] for p in pairs]
        translations = [p["translation"] for p in pairs]
        random.shuffle(translations)

        return {
            "game_type": "word_match",
            "pairs": pairs,
            "words": words,
            "translations_shuffled": translations,
            "time_limit": 60,
        }
    finally:
        await db.close()


@router.get("/{student_id}/sentence-builder")
async def generate_sentence_builder(student_id: int):
    """Generate a sentence building game."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT current_level FROM students WHERE id = ?", (student_id,)
        )
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        level = student["current_level"] or "A1"
        sentences = await _generate_sentences(level, 5)

        return {
            "game_type": "sentence_builder",
            "sentences": sentences,
            "time_limit": 120,
        }
    finally:
        await db.close()


@router.get("/{student_id}/error-hunt")
async def generate_error_hunt(student_id: int):
    """Generate an error hunting game."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT current_level FROM students WHERE id = ?", (student_id,)
        )
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        level = student["current_level"] or "A1"
        sentences = await _generate_error_sentences(level, 6)

        return {
            "game_type": "error_hunt",
            "sentences": sentences,
            "time_limit": 90,
        }
    finally:
        await db.close()


@router.get("/{student_id}/speed-translate")
async def generate_speed_translate(student_id: int):
    """Generate a speed translation game."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT current_level FROM students WHERE id = ?", (student_id,)
        )
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        level = student["current_level"] or "A1"
        phrases = await _generate_translation_phrases(level, 8)

        return {
            "game_type": "speed_translate",
            "phrases": phrases,
            "time_limit": 90,
        }
    finally:
        await db.close()


@router.post("/{student_id}/submit")
async def submit_game_score(student_id: int, submission: GameSubmission):
    db = await get_db()
    try:
        # Calculate XP based on score
        if submission.score >= 90:
            xp = 50
        elif submission.score >= 70:
            xp = 30
        elif submission.score >= 50:
            xp = 20
        else:
            xp = 15

        await db.execute(
            "INSERT INTO game_scores (student_id, game_type, score, xp_earned, data) VALUES (?, ?, ?, ?, ?)",
            (student_id, submission.game_type, submission.score, xp,
             json.dumps(submission.data) if submission.data else None),
        )
        await db.commit()

        xp_result = await award_xp(student_id, xp, "game_complete", f"{submission.game_type}: {submission.score}%")

        # Update challenge progress
        await update_challenge_progress(student_id, "play_game")

        return {
            "score": submission.score,
            "xp_earned": xp,
            "xp_result": xp_result,
        }
    finally:
        await db.close()


@router.get("/{student_id}/history")
async def get_game_history(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM game_scores WHERE student_id = ? ORDER BY played_at DESC LIMIT 20",
            (student_id,),
        )
        rows = await cursor.fetchall()

        # Best scores per game type
        cursor = await db.execute(
            "SELECT game_type, MAX(score) as best, COUNT(*) as times_played FROM game_scores WHERE student_id = ? GROUP BY game_type",
            (student_id,),
        )
        best_scores = {row["game_type"]: {"best": row["best"], "times_played": row["times_played"]}
                       for row in await cursor.fetchall()}

        return {
            "student_id": student_id,
            "recent": [
                {"game_type": r["game_type"], "score": r["score"], "xp_earned": r["xp_earned"], "played_at": r["played_at"]}
                for r in rows
            ],
            "best_scores": best_scores,
        }
    finally:
        await db.close()


async def _generate_word_pairs(level: str, count: int) -> list[dict]:
    client = AsyncOpenAI(api_key=settings.api_key)
    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": "Generate English-Polish word pairs for a matching game. Return JSON."},
            {"role": "user", "content": f"Generate {count} English words with Polish translations for a {level} level student. Return JSON: {{\"pairs\": [{{\"word\": \"...\", \"translation\": \"...\"}}]}}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("pairs", [])[:count]


async def _generate_sentences(level: str, count: int) -> list[dict]:
    client = AsyncOpenAI(api_key=settings.api_key)
    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": "Generate English sentences for a word-ordering game. Return JSON."},
            {"role": "user", "content": f"Generate {count} English sentences appropriate for {level} level. Each sentence should be 5-10 words. Return JSON: {{\"sentences\": [{{\"sentence\": \"The cat sat on the mat\", \"translation_pl\": \"Kot siedzial na macie\", \"hint\": \"A common phrase about a pet\"}}]}}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("sentences", [])[:count]


async def _generate_error_sentences(level: str, count: int) -> list[dict]:
    client = AsyncOpenAI(api_key=settings.api_key)
    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": "Generate sentences with errors typical of Polish speakers learning English. Return JSON."},
            {"role": "user", "content": f"Generate {count} sentences for {level} level. Some should have errors (common Polish-speaker mistakes), some should be correct. Return JSON: {{\"sentences\": [{{\"sentence\": \"I am go to school\", \"has_error\": true, \"corrected\": \"I am going to school\", \"explanation\": \"Missing -ing form after 'am'\", \"explanation_pl\": \"Brak formy -ing po 'am'\"}}]}}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("sentences", [])[:count]


async def _generate_translation_phrases(level: str, count: int) -> list[dict]:
    client = AsyncOpenAI(api_key=settings.api_key)
    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": "Generate Polish phrases with English translations for a speed translation game. Return JSON."},
            {"role": "user", "content": f"Generate {count} short Polish phrases/sentences ({level} level) with their English translations. Include common phrases. Return JSON: {{\"phrases\": [{{\"polish\": \"Jak sie masz?\", \"english\": \"How are you?\", \"hint\": \"A greeting\"}}]}}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("phrases", [])[:count]
