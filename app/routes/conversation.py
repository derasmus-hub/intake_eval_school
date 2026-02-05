import json
import yaml
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from openai import AsyncOpenAI
from app.config import settings
from app.db.database import get_db
from app.services.xp_engine import award_xp
from app.routes.challenges import update_challenge_progress

router = APIRouter(prefix="/api/conversation", tags=["conversation"])

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

_conversation_prompt = None


def _load_prompt():
    global _conversation_prompt
    if _conversation_prompt is None:
        with open(PROMPTS_DIR / "conversation_partner.yaml", "r") as f:
            _conversation_prompt = yaml.safe_load(f)
    return _conversation_prompt


class ChatMessage(BaseModel):
    message: str
    scenario_title: Optional[str] = None
    scenario_description: Optional[str] = None
    history: list[dict] = []


@router.get("/{student_id}/scenarios")
async def get_scenarios(student_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT current_level FROM students WHERE id = ?", (student_id,))
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        level = student["current_level"] or "A1"
        prompt_data = _load_prompt()
        scenarios = prompt_data.get("scenarios", {})

        # Map level to scenario bracket
        if level in ("A1", "A2"):
            bracket = "beginner"
        elif level in ("B1", "B2"):
            bracket = "intermediate"
        else:
            bracket = "advanced"

        available = scenarios.get(bracket, scenarios.get("beginner", []))

        return {
            "student_id": student_id,
            "level": level,
            "bracket": bracket,
            "scenarios": available,
        }
    finally:
        await db.close()


@router.post("/{student_id}/chat")
async def chat(student_id: int, msg: ChatMessage):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM students WHERE id = ?", (student_id,))
        student = await cursor.fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        level = student["current_level"] or "A1"
        name = student["name"]

        # Get weak areas from latest profile
        weak_areas = "None identified"
        cursor = await db.execute(
            "SELECT priorities FROM learner_profiles WHERE student_id = ? ORDER BY created_at DESC LIMIT 1",
            (student_id,),
        )
        profile = await cursor.fetchone()
        if profile and profile["priorities"]:
            priorities = json.loads(profile["priorities"])
            weak_areas = ", ".join(priorities) if priorities else "None identified"
    finally:
        await db.close()

    prompt_data = _load_prompt()
    system_prompt = prompt_data["system_prompt"]
    user_template = prompt_data["user_template"]

    context = user_template.format(
        level=level,
        name=name,
        scenario_title=msg.scenario_title or "Free conversation",
        scenario_description=msg.scenario_description or "Have a free conversation with the student.",
        weak_areas=weak_areas,
    )

    messages = [
        {"role": "system", "content": system_prompt + "\n\n" + context},
    ]
    for h in msg.history:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": msg.message})

    # Award XP for conversation practice (every message)
    await award_xp(student_id, 25, "conversation", msg.scenario_title or "Free conversation")
    await update_challenge_progress(student_id, "practice_conversation")

    client = AsyncOpenAI(api_key=settings.api_key)

    async def generate():
        stream = await client.chat.completions.create(
            model=settings.model_name,
            messages=messages,
            temperature=0.8,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                data = json.dumps({"content": chunk.choices[0].delta.content})
                yield f"data: {data}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
