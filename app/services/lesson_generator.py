import json
import yaml
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings
from app.models.lesson import (
    LessonContent,
    WarmUp,
    Presentation,
    ControlledPractice,
    FreePractice,
    WrapUp,
)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str) -> dict:
    with open(PROMPTS_DIR / name, "r") as f:
        return yaml.safe_load(f)


async def generate_lesson(
    student_id: int,
    profile: dict,
    progress_history: list[dict],
    session_number: int,
    current_level: str,
    previous_topics: list[str] | None = None,
    recall_weak_areas: list[str] | None = None,
) -> LessonContent:
    lesson_prompt = load_prompt("lesson_generator.yaml")

    system_prompt = lesson_prompt["system_prompt"]
    user_template = lesson_prompt["user_template"]

    progress_text = "No previous lessons." if not progress_history else json.dumps(progress_history, indent=2)
    topics_text = "None (first lesson)." if not previous_topics else ", ".join(previous_topics)

    recall_text = "None." if not recall_weak_areas else ", ".join(recall_weak_areas)

    user_message = user_template.format(
        session_number=session_number,
        current_level=current_level,
        profile_summary=profile.get("profile_summary", "No profile summary available"),
        priorities=", ".join(profile.get("priorities", [])),
        gaps=json.dumps(profile.get("gaps", []), indent=2),
        progress_history=progress_text,
        previous_topics=topics_text,
        recall_weak_areas=recall_text,
    )

    client = AsyncOpenAI(api_key=settings.api_key)

    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    result_text = response.choices[0].message.content
    result = json.loads(result_text)

    # Build 5-phase sub-models from AI response (if present)
    warm_up = None
    if result.get("warm_up"):
        warm_up = WarmUp(**result["warm_up"])

    presentation = None
    if result.get("presentation"):
        presentation = Presentation(**result["presentation"])

    controlled_practice = None
    if result.get("controlled_practice"):
        controlled_practice = ControlledPractice(**result["controlled_practice"])

    free_practice = None
    if result.get("free_practice"):
        free_practice = FreePractice(**result["free_practice"])

    wrap_up = None
    if result.get("wrap_up"):
        wrap_up = WrapUp(**result["wrap_up"])

    return LessonContent(
        objective=result.get("objective", ""),
        polish_explanation=result.get("polish_explanation", ""),
        exercises=result.get("exercises", []),
        conversation_prompts=result.get("conversation_prompts", []),
        win_activity=result.get("win_activity", ""),
        difficulty=result.get("difficulty", current_level),
        warm_up=warm_up,
        presentation=presentation,
        controlled_practice=controlled_practice,
        free_practice=free_practice,
        wrap_up=wrap_up,
    )
