import json
import yaml
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str) -> dict:
    with open(PROMPTS_DIR / name, "r") as f:
        return yaml.safe_load(f)


async def extract_learning_points(lesson_content: dict, student_level: str) -> list[dict]:
    prompt = load_prompt("extract_learning_points.yaml")

    system_prompt = prompt["system_prompt"]
    user_template = prompt["user_template"]

    # Build presentation text
    presentation_text = ""
    if lesson_content.get("presentation"):
        p = lesson_content["presentation"]
        if isinstance(p, dict):
            presentation_text = f"Presentation Topic: {p.get('topic', '')}\n"
            presentation_text += f"Explanation: {p.get('explanation', '')}\n"
            presentation_text += f"Polish Explanation: {p.get('polish_explanation', '')}\n"
            examples = p.get("examples", [])
            if examples:
                presentation_text += "Examples: " + "; ".join(examples)

    # Build exercises text
    exercises_text = ""
    exercises = lesson_content.get("exercises", [])
    if not exercises and lesson_content.get("controlled_practice"):
        cp = lesson_content["controlled_practice"]
        if isinstance(cp, dict):
            exercises = cp.get("exercises", [])
    if exercises:
        exercises_text = "Exercises:\n"
        for i, ex in enumerate(exercises, 1):
            if isinstance(ex, dict):
                exercises_text += f"  {i}. [{ex.get('type', '')}] {ex.get('instruction', '')} — {ex.get('content', '')} (Answer: {ex.get('answer', '')})\n"

    # Build conversation text
    conversation_text = ""
    prompts = lesson_content.get("conversation_prompts", [])
    if prompts:
        conversation_text = "Conversation Prompts: " + "; ".join(prompts)
    if lesson_content.get("free_practice"):
        fp = lesson_content["free_practice"]
        if isinstance(fp, dict):
            conversation_text += f"\nFree Practice: {fp.get('description', '')}"

    user_message = user_template.format(
        student_level=student_level,
        objective=lesson_content.get("objective", ""),
        presentation_text=presentation_text or "No presentation data.",
        exercises_text=exercises_text or "No exercises data.",
        conversation_text=conversation_text or "No conversation data.",
    )

    client = AsyncOpenAI(api_key=settings.api_key)

    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    return result.get("learning_points", [])
