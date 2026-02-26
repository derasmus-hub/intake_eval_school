import json
import yaml
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from app.services.ai_client import ai_chat
from app.db.database import get_db
from app.services.xp_engine import award_xp
from app.routes.challenges import update_challenge_progress
from app.routes.auth import require_student_owner

router = APIRouter(prefix="/api/writing", tags=["writing"])

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

_writing_prompt = None
_polish_struggles = None


def _load_prompt():
    global _writing_prompt
    if _writing_prompt is None:
        with open(PROMPTS_DIR / "writing_evaluator.yaml", "r") as f:
            _writing_prompt = yaml.safe_load(f)
    return _writing_prompt


def _load_polish_struggles():
    global _polish_struggles
    if _polish_struggles is None:
        with open(PROMPTS_DIR / "polish_struggles.yaml", "r") as f:
            _polish_struggles = yaml.safe_load(f)
    return _polish_struggles


class WritingSubmission(BaseModel):
    text: str
    prompt_topic: Optional[str] = None


@router.post("/{student_id}/submit")
async def submit_writing(
    student_id: int,
    body: WritingSubmission,
    request: Request,
    db=Depends(get_db),
):
    """
    Student submits a paragraph. AI marks:
    - Grammar errors (with corrections)
    - Vocabulary suggestions (upgrade basic words)
    - Coherence/structure feedback
    - CEFR benchmark ("This writing is at B1 level because...")
    - Polish L1 interference patterns detected
    """
    user = await require_student_owner(request, student_id, db)

    # Validate text length
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    if len(text) > 10000:
        raise HTTPException(status_code=400, detail="Text exceeds maximum length of 10000 characters")

    # Fetch student info
    cursor = await db.execute(
        "SELECT id, name, current_level FROM users WHERE id = ?",
        (student_id,),
    )
    student = await cursor.fetchone()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    current_level = student["current_level"] or "A1"
    name = student["name"]

    # Load prompts
    prompt_data = _load_prompt()
    polish_struggles = _load_polish_struggles()

    user_message = prompt_data["user_template"].format(
        student_id=student_id,
        name=name,
        current_level=current_level,
        prompt_topic=body.prompt_topic or "Free writing (no specific topic)",
        text=text,
        polish_struggles=yaml.dump(
            polish_struggles, default_flow_style=False, allow_unicode=True
        ),
    )

    result_text = await ai_chat(
        messages=[
            {"role": "system", "content": prompt_data["system_prompt"]},
            {"role": "user", "content": user_message},
        ],
        use_case="assessment",
        temperature=0.3,
        json_mode=True,
    )

    evaluation = json.loads(result_text)

    cefr_level = evaluation.get("cefr_level", current_level)
    overall_score = evaluation.get("overall_score", 0)

    # Store submission and evaluation
    cursor = await db.execute(
        """INSERT INTO writing_submissions
           (student_id, prompt_topic, submitted_text, evaluation_json, cefr_level, overall_score)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            student_id,
            body.prompt_topic,
            text,
            json.dumps(evaluation),
            cefr_level,
            overall_score,
        ),
    )
    await db.commit()
    submission_id = cursor.lastrowid

    # Award XP for writing practice
    xp_amount = 40
    if overall_score >= 80:
        xp_amount = 60
    await award_xp(db, student_id, xp_amount, "writing_submit", body.prompt_topic or "Free writing")
    await update_challenge_progress(db, student_id, "practice_writing")

    return {
        "id": submission_id,
        "student_id": student_id,
        "prompt_topic": body.prompt_topic,
        "evaluation": evaluation,
    }


@router.get("/{student_id}/history")
async def get_writing_history(
    student_id: int,
    request: Request,
    db=Depends(get_db),
):
    """Get all writing submissions for a student."""
    user = await require_student_owner(request, student_id, db)

    cursor = await db.execute(
        """SELECT id, prompt_topic, submitted_text, evaluation_json,
                  cefr_level, overall_score, created_at
           FROM writing_submissions
           WHERE student_id = ?
           ORDER BY created_at DESC""",
        (student_id,),
    )
    rows = await cursor.fetchall()

    submissions = []
    for row in rows:
        evaluation = None
        if row["evaluation_json"]:
            try:
                evaluation = json.loads(row["evaluation_json"])
            except (json.JSONDecodeError, TypeError):
                evaluation = None

        submissions.append({
            "id": row["id"],
            "prompt_topic": row["prompt_topic"],
            "submitted_text": row["submitted_text"],
            "evaluation": evaluation,
            "cefr_level": row["cefr_level"],
            "overall_score": row["overall_score"],
            "created_at": row["created_at"],
        })

    return {
        "student_id": student_id,
        "total": len(submissions),
        "submissions": submissions,
    }


@router.get("/{student_id}/{submission_id}")
async def get_writing_submission(
    student_id: int,
    submission_id: int,
    request: Request,
    db=Depends(get_db),
):
    """Get a single writing submission by ID."""
    user = await require_student_owner(request, student_id, db)

    cursor = await db.execute(
        """SELECT id, prompt_topic, submitted_text, evaluation_json,
                  cefr_level, overall_score, created_at
           FROM writing_submissions
           WHERE id = ? AND student_id = ?""",
        (submission_id, student_id),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Writing submission not found")

    evaluation = None
    if row["evaluation_json"]:
        try:
            evaluation = json.loads(row["evaluation_json"])
        except (json.JSONDecodeError, TypeError):
            evaluation = None

    return {
        "id": row["id"],
        "student_id": student_id,
        "prompt_topic": row["prompt_topic"],
        "submitted_text": row["submitted_text"],
        "evaluation": evaluation,
        "cefr_level": row["cefr_level"],
        "overall_score": row["overall_score"],
        "created_at": row["created_at"],
    }
