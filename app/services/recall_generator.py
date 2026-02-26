import json
import logging
from datetime import datetime
from app.services.ai_client import ai_chat
from app.services.prompts import load_prompt
import aiosqlite
from app.services.srs_engine import sm2_update

logger = logging.getLogger(__name__)


async def get_points_due_for_review(db: aiosqlite.Connection, student_id: int) -> list[dict]:
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

    try:
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="cheap",
            temperature=0.5,
            json_mode=True,
        )
    except Exception as exc:
        logger.error("AI call failed during recall question generation: %s", exc)
        raise ValueError("AI failed to generate recall questions") from exc

    try:
        result = json.loads(result_text)
    except json.JSONDecodeError as exc:
        logger.error("AI returned invalid JSON for recall questions: %s", exc)
        raise ValueError("AI failed to generate recall questions") from exc
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

    try:
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="cheap",
            temperature=0.3,
            json_mode=True,
        )
    except Exception as exc:
        logger.error("AI call failed during recall evaluation: %s", exc)
        raise ValueError("AI failed to evaluate recall answers") from exc

    try:
        result = json.loads(result_text)
    except json.JSONDecodeError as exc:
        logger.error("AI returned invalid JSON for recall evaluation: %s", exc)
        raise ValueError("AI failed to evaluate recall answers") from exc
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


async def update_review_schedule(db: aiosqlite.Connection, point_id: int, score: float):
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
