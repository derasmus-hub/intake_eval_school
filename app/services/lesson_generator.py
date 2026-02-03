import json
import yaml
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings
from app.models.lesson import LessonContent

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
) -> LessonContent:
    lesson_prompt = load_prompt("lesson_generator.yaml")

    system_prompt = lesson_prompt["system_prompt"]
    user_template = lesson_prompt["user_template"]

    progress_text = "No previous lessons." if not progress_history else json.dumps(progress_history, indent=2)
    topics_text = "None (first lesson)." if not previous_topics else ", ".join(previous_topics)

    user_message = user_template.format(
        session_number=session_number,
        current_level=current_level,
        profile_summary=profile.get("profile_summary", "No profile summary available"),
        priorities=", ".join(profile.get("priorities", [])),
        gaps=json.dumps(profile.get("gaps", []), indent=2),
        progress_history=progress_text,
        previous_topics=topics_text,
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

    return LessonContent(
        objective=result.get("objective", ""),
        polish_explanation=result.get("polish_explanation", ""),
        exercises=result.get("exercises", []),
        conversation_prompts=result.get("conversation_prompts", []),
        win_activity=result.get("win_activity", ""),
        difficulty=result.get("difficulty", current_level),
    )
