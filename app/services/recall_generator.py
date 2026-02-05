import json
import yaml
from pathlib import Path
from datetime import datetime
from openai import AsyncOpenAI
from app.config import settings
from app.db.database import get_db
from app.services.srs_engine import sm2_update

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(name: str) -> dict:
    with open(PROMPTS_DIR / name, "r") as f:
        return yaml.safe_load(f)


async def get_points_due_for_review(student_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM learning_points
               WHERE student_id = ?
                 AND (next_review_date <= datetime('now')
                      OR last_recall_score < 70
                      OR times_reviewed = 0)
               ORDER BY
                 CASE WHEN last_recall_score IS NULL THEN 0 ELSE last_recall_score END ASC,
                 next_review_date ASC
               LIMIT 10""",
            (student_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "student_id": row["student_id"],
                "lesson_id": row["lesson_id"],
                "point_type": row["point_type"],
                "content": row["content"],
                "polish_explanation": row["polish_explanation"],
                "example_sentence": row["example_sentence"],
                "importance_weight": row["importance_weight"],
                "times_reviewed": row["times_reviewed"],
                "last_recall_score": row["last_recall_score"],
            }
            for row in rows
        ]
    finally:
        await db.close()


async def generate_recall_questions(points: list[dict], student_level: str) -> dict:
    prompt = load_prompt("generate_recall_questions.yaml")

    system_prompt = prompt["system_prompt"]
    user_template = prompt["user_template"]

    points_text = ""
    for p in points:
        points_text += f"- ID: {p['id']}, Type: {p['point_type']}, Content: {p['content']}"
        if p.get("polish_explanation"):
            points_text += f", Polish: {p['polish_explanation']}"
        if p.get("example_sentence"):
            points_text += f", Example: {p['example_sentence']}"
        points_text += "\n"

    user_message = user_template.format(
        student_level=student_level,
        learning_points_text=points_text,
    )

    client = AsyncOpenAI(api_key=settings.api_key)

    response = await client.chat.completions.create(
        model=settings.model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.5,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    return result


async def evaluate_recall_answers(questions: list[dict], answers: list, student_level: str) -> dict:
    prompt = load_prompt("evaluate_recall.yaml")

    system_prompt = prompt["system_prompt"]
    user_template = prompt["user_template"]

    qa_text = ""
    for i, q in enumerate(questions):
        # Support both formats: list of strings or list of dicts with point_id
        if i < len(answers):
            ans = answers[i]
            if isinstance(ans, dict):
                student_answer = ans.get("answer", "(no answer)")
            else:
                student_answer = str(ans)
        else:
            student_answer = "(no answer)"

        qa_text += f"Question (point_id={q.get('point_id')}): {q.get('question_text', '')}\n"
        qa_text += f"  Type: {q.get('question_type', '')}\n"
        qa_text += f"  Correct answer: {q.get('correct_answer', '')}\n"
        qa_text += f"  Student answer: {student_answer}\n\n"

    user_message = user_template.format(
        student_level=student_level,
        qa_text=qa_text,
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
    return result


def _score_to_quality(score: float) -> int:
    if score < 30:
        return 0
    elif score < 50:
        return 1
    elif score < 60:
        return 2
    elif score < 70:
        return 3
    elif score < 85:
        return 4
    else:
        return 5


async def update_review_schedule(point_id: int, score: float):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT ease_factor, interval_days, repetitions, times_reviewed FROM learning_points WHERE id = ?",
            (point_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return

        quality = _score_to_quality(score)
        updated = sm2_update(
            ease_factor=row["ease_factor"],
            interval_days=row["interval_days"],
            repetitions=row["repetitions"],
            quality=quality,
        )

        await db.execute(
            """UPDATE learning_points
               SET ease_factor = ?,
                   interval_days = ?,
                   repetitions = ?,
                   times_reviewed = ?,
                   last_recall_score = ?,
                   next_review_date = ?
               WHERE id = ?""",
            (
                updated["ease_factor"],
                updated["interval_days"],
                updated["repetitions"],
                row["times_reviewed"] + 1,
                score,
                updated["next_review"],
                point_id,
            ),
        )
        await db.commit()
    finally:
        await db.close()
