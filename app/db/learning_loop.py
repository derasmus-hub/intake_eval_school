"""
learning_loop.py - Database helper queries for the Learning Loop feature

Provides insert/fetch functions for:
- learning_plans
- lesson_artifacts
- next_quizzes
- quiz_attempts
- quiz_attempt_items
"""

import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import aiosqlite


# ══════════════════════════════════════════════════════════════════════════════
# LEARNING PLANS
# ══════════════════════════════════════════════════════════════════════════════

async def create_learning_plan(
    db: aiosqlite.Connection,
    student_id: int,
    plan_json: Dict[str, Any],
    summary: Optional[str] = None,
    source_intake_id: Optional[int] = None,
    version: Optional[int] = None
) -> int:
    """Create a new learning plan for a student. Returns the new plan ID."""
    # Auto-increment version if not provided
    if version is None:
        cursor = await db.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM learning_plans WHERE student_id = ?",
            (student_id,)
        )
        row = await cursor.fetchone()
        version = row[0] if row else 1

    cursor = await db.execute(
        """INSERT INTO learning_plans (student_id, version, plan_json, summary, source_intake_id)
           VALUES (?, ?, ?, ?, ?)""",
        (student_id, version, json.dumps(plan_json), summary, source_intake_id)
    )
    await db.commit()
    return cursor.lastrowid


async def get_learning_plan(db: aiosqlite.Connection, plan_id: int) -> Optional[Dict[str, Any]]:
    """Get a learning plan by ID."""
    cursor = await db.execute(
        "SELECT * FROM learning_plans WHERE id = ?",
        (plan_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_dict(row, parse_json_fields=['plan_json'])


async def get_latest_learning_plan(db: aiosqlite.Connection, student_id: int) -> Optional[Dict[str, Any]]:
    """Get the most recent learning plan for a student."""
    cursor = await db.execute(
        """SELECT * FROM learning_plans
           WHERE student_id = ?
           ORDER BY version DESC, created_at DESC
           LIMIT 1""",
        (student_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_dict(row, parse_json_fields=['plan_json'])


async def get_learning_plans_by_student(db: aiosqlite.Connection, student_id: int) -> List[Dict[str, Any]]:
    """Get all learning plans for a student, ordered by version descending."""
    cursor = await db.execute(
        "SELECT * FROM learning_plans WHERE student_id = ? ORDER BY version DESC",
        (student_id,)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r, parse_json_fields=['plan_json']) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# LESSON ARTIFACTS
# ══════════════════════════════════════════════════════════════════════════════

async def create_lesson_artifact(
    db: aiosqlite.Connection,
    student_id: int,
    lesson_json: Dict[str, Any],
    session_id: Optional[int] = None,
    teacher_id: Optional[int] = None,
    topics_json: Optional[Dict[str, Any]] = None,
    difficulty: Optional[str] = None,
    prompt_version: Optional[str] = None
) -> int:
    """Create a new lesson artifact. Returns the new artifact ID."""
    cursor = await db.execute(
        """INSERT INTO lesson_artifacts
           (session_id, student_id, teacher_id, lesson_json, topics_json, difficulty, prompt_version)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            student_id,
            teacher_id,
            json.dumps(lesson_json),
            json.dumps(topics_json) if topics_json else None,
            difficulty,
            prompt_version
        )
    )
    await db.commit()
    return cursor.lastrowid


async def get_lesson_artifact(db: aiosqlite.Connection, artifact_id: int) -> Optional[Dict[str, Any]]:
    """Get a lesson artifact by ID."""
    cursor = await db.execute(
        "SELECT * FROM lesson_artifacts WHERE id = ?",
        (artifact_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_dict(row, parse_json_fields=['lesson_json', 'topics_json'])


async def get_lesson_artifacts_by_student(
    db: aiosqlite.Connection,
    student_id: int,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get lesson artifacts for a student, ordered by creation date descending."""
    cursor = await db.execute(
        "SELECT * FROM lesson_artifacts WHERE student_id = ? ORDER BY created_at DESC LIMIT ?",
        (student_id, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r, parse_json_fields=['lesson_json', 'topics_json']) for r in rows]


async def get_lesson_artifacts_by_session(
    db: aiosqlite.Connection,
    session_id: int
) -> List[Dict[str, Any]]:
    """Get lesson artifacts for a specific session."""
    cursor = await db.execute(
        "SELECT * FROM lesson_artifacts WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r, parse_json_fields=['lesson_json', 'topics_json']) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# NEXT QUIZZES
# ══════════════════════════════════════════════════════════════════════════════

async def create_quiz(
    db: aiosqlite.Connection,
    student_id: int,
    quiz_json: Dict[str, Any],
    session_id: Optional[int] = None,
    derived_from_lesson_artifact_id: Optional[int] = None
) -> int:
    """Create a new quiz. Returns the new quiz ID."""
    cursor = await db.execute(
        """INSERT INTO next_quizzes
           (session_id, student_id, quiz_json, derived_from_lesson_artifact_id)
           VALUES (?, ?, ?, ?)""",
        (session_id, student_id, json.dumps(quiz_json), derived_from_lesson_artifact_id)
    )
    await db.commit()
    return cursor.lastrowid


async def get_quiz(db: aiosqlite.Connection, quiz_id: int) -> Optional[Dict[str, Any]]:
    """Get a quiz by ID."""
    cursor = await db.execute(
        "SELECT * FROM next_quizzes WHERE id = ?",
        (quiz_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_dict(row, parse_json_fields=['quiz_json'])


async def get_quizzes_by_student(
    db: aiosqlite.Connection,
    student_id: int,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get quizzes for a student, ordered by creation date descending."""
    cursor = await db.execute(
        "SELECT * FROM next_quizzes WHERE student_id = ? ORDER BY created_at DESC LIMIT ?",
        (student_id, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r, parse_json_fields=['quiz_json']) for r in rows]


async def get_quizzes_from_lesson_artifact(
    db: aiosqlite.Connection,
    lesson_artifact_id: int
) -> List[Dict[str, Any]]:
    """Get quizzes derived from a specific lesson artifact."""
    cursor = await db.execute(
        """SELECT * FROM next_quizzes
           WHERE derived_from_lesson_artifact_id = ?
           ORDER BY created_at DESC""",
        (lesson_artifact_id,)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r, parse_json_fields=['quiz_json']) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# QUIZ ATTEMPTS
# ══════════════════════════════════════════════════════════════════════════════

async def create_quiz_attempt(
    db: aiosqlite.Connection,
    quiz_id: int,
    student_id: int,
    session_id: Optional[int] = None
) -> int:
    """Create a new quiz attempt. Returns the new attempt ID."""
    cursor = await db.execute(
        """INSERT INTO quiz_attempts (quiz_id, student_id, session_id)
           VALUES (?, ?, ?)""",
        (quiz_id, student_id, session_id)
    )
    await db.commit()
    return cursor.lastrowid


async def submit_quiz_attempt(
    db: aiosqlite.Connection,
    attempt_id: int,
    score: float,
    results_json: Optional[Dict[str, Any]] = None
) -> None:
    """Mark a quiz attempt as submitted with score and results."""
    await db.execute(
        """UPDATE quiz_attempts
           SET submitted_at = ?, score = ?, results_json = ?
           WHERE id = ?""",
        (datetime.now(timezone.utc).isoformat(), score, json.dumps(results_json) if results_json else None, attempt_id)
    )
    await db.commit()


async def get_quiz_attempt(db: aiosqlite.Connection, attempt_id: int) -> Optional[Dict[str, Any]]:
    """Get a quiz attempt by ID."""
    cursor = await db.execute(
        "SELECT * FROM quiz_attempts WHERE id = ?",
        (attempt_id,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_dict(row, parse_json_fields=['results_json'])


async def get_quiz_attempts_by_quiz(
    db: aiosqlite.Connection,
    quiz_id: int
) -> List[Dict[str, Any]]:
    """Get all attempts for a specific quiz."""
    cursor = await db.execute(
        "SELECT * FROM quiz_attempts WHERE quiz_id = ? ORDER BY started_at DESC",
        (quiz_id,)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r, parse_json_fields=['results_json']) for r in rows]


async def get_quiz_attempts_by_student(
    db: aiosqlite.Connection,
    student_id: int,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get quiz attempts for a student, ordered by start time descending."""
    cursor = await db.execute(
        "SELECT * FROM quiz_attempts WHERE student_id = ? ORDER BY started_at DESC LIMIT ?",
        (student_id, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r, parse_json_fields=['results_json']) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# QUIZ ATTEMPT ITEMS
# ══════════════════════════════════════════════════════════════════════════════

async def create_quiz_attempt_item(
    db: aiosqlite.Connection,
    attempt_id: int,
    question_id: str,
    is_correct: bool,
    student_answer: Optional[str] = None,
    expected_answer: Optional[str] = None,
    skill_tag: Optional[str] = None,
    time_spent: Optional[int] = None
) -> int:
    """Create a new quiz attempt item. Returns the new item ID."""
    cursor = await db.execute(
        """INSERT INTO quiz_attempt_items
           (attempt_id, question_id, is_correct, student_answer, expected_answer, skill_tag, time_spent)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (attempt_id, question_id, 1 if is_correct else 0, student_answer, expected_answer, skill_tag, time_spent)
    )
    await db.commit()
    return cursor.lastrowid


async def create_quiz_attempt_items_batch(
    db: aiosqlite.Connection,
    attempt_id: int,
    items: List[Dict[str, Any]]
) -> List[int]:
    """Create multiple quiz attempt items in a batch. Returns list of new item IDs."""
    item_ids = []
    for item in items:
        cursor = await db.execute(
            """INSERT INTO quiz_attempt_items
               (attempt_id, question_id, is_correct, student_answer, expected_answer, skill_tag, time_spent)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt_id,
                item.get('question_id'),
                1 if item.get('is_correct') else 0,
                item.get('student_answer'),
                item.get('expected_answer'),
                item.get('skill_tag'),
                item.get('time_spent')
            )
        )
        item_ids.append(cursor.lastrowid)
    await db.commit()
    return item_ids


async def get_quiz_attempt_items(
    db: aiosqlite.Connection,
    attempt_id: int
) -> List[Dict[str, Any]]:
    """Get all items for a quiz attempt."""
    cursor = await db.execute(
        "SELECT * FROM quiz_attempt_items WHERE attempt_id = ?",
        (attempt_id,)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def get_items_by_skill_tag(
    db: aiosqlite.Connection,
    student_id: int,
    skill_tag: str,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Get quiz attempt items for a specific skill tag across all attempts for a student."""
    cursor = await db.execute(
        """SELECT qai.* FROM quiz_attempt_items qai
           JOIN quiz_attempts qa ON qai.attempt_id = qa.id
           WHERE qa.student_id = ? AND qai.skill_tag = ?
           ORDER BY qa.started_at DESC
           LIMIT ?""",
        (student_id, skill_tag, limit)
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _row_to_dict(row: aiosqlite.Row, parse_json_fields: List[str] = None) -> Dict[str, Any]:
    """Convert a database row to a dictionary, optionally parsing JSON fields."""
    if row is None:
        return None

    result = dict(row)

    if parse_json_fields:
        for field in parse_json_fields:
            if field in result and result[field]:
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass  # Keep original value if JSON parsing fails

    return result
