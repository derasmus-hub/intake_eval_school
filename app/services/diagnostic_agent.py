import json
import yaml
from pathlib import Path
from openai import AsyncOpenAI
from app.config import settings
from app.models.student import LearnerProfile

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str) -> dict:
    with open(PROMPTS_DIR / name, "r") as f:
        return yaml.safe_load(f)


async def run_diagnostic(student_id: int, intake_data: dict) -> LearnerProfile:
    diagnostic_prompt = load_prompt("diagnostic.yaml")
    polish_struggles = load_prompt("polish_struggles.yaml")

    system_prompt = diagnostic_prompt["system_prompt"]
    user_template = diagnostic_prompt["user_template"]

    user_message = user_template.format(
        name=intake_data.get("name", "Unknown"),
        age=intake_data.get("age", "Not specified"),
        current_level=intake_data.get("current_level", "Unknown"),
        goals=", ".join(intake_data.get("goals", [])),
        problem_areas=", ".join(intake_data.get("problem_areas", [])),
        filler=intake_data.get("filler", "student"),
        additional_notes=intake_data.get("additional_notes", "None"),
        polish_struggles=yaml.dump(polish_struggles, default_flow_style=False, allow_unicode=True),
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

    result_text = response.choices[0].message.content
    result = json.loads(result_text)

    return LearnerProfile(
        student_id=student_id,
        identified_gaps=result.get("identified_gaps", []),
        priority_areas=result.get("priority_areas", []),
        profile_summary=result.get("profile_summary", ""),
        recommended_start_level=result.get("recommended_start_level"),
    )
