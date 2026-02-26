"""Smart pre-class preparation engine.

Generates personalized warm-up packages before scheduled sessions:
- Vocabulary review (SM-2 due items prioritized by lesson relevance)
- Grammar micro-exercise targeting weakest current pattern
- Short reading prompt related to next lesson topic
- Confidence self-assessment question
"""

import json
import logging
from datetime import datetime, timedelta
from app.services.ai_client import ai_chat

logger = logging.getLogger(__name__)


async def generate_warmup(student_id: int, session_id: int, db) -> dict:
    """Generate a personalized warm-up package for a student before a session.

    Pulls vocabulary due for SM-2 review, weakest learning points, recent error
    patterns, learning DNA, and the upcoming lesson objective to build a 5-minute
    AI-generated warm-up package.
    """

    # --- Fetch student info ---
    cursor = await db.execute(
        "SELECT name, current_level, goals FROM users WHERE id = ?",
        (student_id,),
    )
    student = await cursor.fetchone()
    if not student:
        raise ValueError(f"Student {student_id} not found")

    student_name = student[0]
    current_level = student[1]
    goals = student[2]

    # --- Fetch the session ---
    cursor = await db.execute(
        "SELECT id, scheduled_at, lesson_id FROM sessions WHERE id = ?",
        (session_id,),
    )
    session = await cursor.fetchone()
    if not session:
        raise ValueError(f"Session {session_id} not found")

    session_scheduled_at = session[1]
    lesson_id = session[2]

    # --- Fetch vocabulary due for review (SM-2) ---
    cursor = await db.execute(
        """
        SELECT word, translation, ease_factor FROM vocabulary_cards
        WHERE student_id = ? AND next_review <= datetime('now')
        ORDER BY ease_factor ASC LIMIT 8
        """,
        (student_id,),
    )
    vocab_rows = await cursor.fetchall()
    vocab_due = [
        {"word": row[0], "translation": row[1], "ease_factor": row[2]}
        for row in vocab_rows
    ]

    # --- Fetch weakest learning points ---
    cursor = await db.execute(
        """
        SELECT point_type, content, polish_explanation FROM learning_points
        WHERE student_id = ? AND (last_recall_score < 60 OR last_recall_score IS NULL)
        ORDER BY CASE WHEN last_recall_score IS NULL THEN 0 ELSE last_recall_score END ASC
        LIMIT 5
        """,
        (student_id,),
    )
    weak_rows = await cursor.fetchall()
    weak_points = [
        {"point_type": row[0], "content": row[1], "polish_explanation": row[2]}
        for row in weak_rows
    ]

    # --- Fetch recent error patterns from progress ---
    cursor = await db.execute(
        """
        SELECT areas_struggling FROM progress
        WHERE student_id = ? ORDER BY completed_at DESC LIMIT 3
        """,
        (student_id,),
    )
    progress_rows = await cursor.fetchall()

    error_counts: dict[str, int] = {}
    for row in progress_rows:
        raw = row[0]
        if not raw:
            continue
        try:
            areas = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(areas, list):
                for area in areas:
                    error_counts[area] = error_counts.get(area, 0) + 1
            elif isinstance(areas, dict):
                for area in areas.keys():
                    error_counts[area] = error_counts.get(area, 0) + 1
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Could not parse areas_struggling for student %s", student_id
            )

    top_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)

    # --- Fetch latest learning DNA if available ---
    cursor = await db.execute(
        """
        SELECT dna_json FROM learning_dna
        WHERE student_id = ? ORDER BY created_at DESC LIMIT 1
        """,
        (student_id,),
    )
    dna_row = await cursor.fetchone()
    learning_dna = None
    if dna_row and dna_row[0]:
        try:
            learning_dna = (
                json.loads(dna_row[0]) if isinstance(dna_row[0], str) else dna_row[0]
            )
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse learning_dna for student %s", student_id)

    # --- Fetch lesson objective if a lesson is linked ---
    lesson_objective = None
    lesson_content = None
    if lesson_id:
        cursor = await db.execute(
            "SELECT objective, content FROM lessons WHERE id = ?",
            (lesson_id,),
        )
        lesson_row = await cursor.fetchone()
        if lesson_row:
            lesson_objective = lesson_row[0]
            lesson_content = lesson_row[1]

    # --- Build the AI prompt ---
    system_prompt = (
        "You are a pre-class warm-up generator for Polish-speaking English students. "
        "Generate a 5-minute warm-up package that reviews due vocabulary, practises the "
        "weakest grammar pattern, and includes a short reading prompt related to the "
        "upcoming lesson topic. All Polish translations and instructions should be "
        "natural and helpful for a native Polish speaker.\n\n"
        "Return ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "vocabulary_review": [\n'
        '    {"word": "...", "translation": "...", "exercise": "fill-in/translate/match"}\n'
        "  ],\n"
        '  "grammar_exercise": {\n'
        '    "instruction": "...",\n'
        '    "instruction_pl": "...",\n'
        '    "sentences": ["..."],\n'
        '    "answers": ["..."]\n'
        "  },\n"
        '  "reading_prompt": {\n'
        '    "text": "...",\n'
        '    "question": "...",\n'
        '    "question_pl": "..."\n'
        "  },\n"
        '  "estimated_minutes": 5\n'
        "}"
    )

    user_parts: list[str] = [
        f"Student: {student_name}",
        f"Level: {current_level or 'unknown'}",
    ]

    if goals:
        user_parts.append(f"Goals: {goals}")

    if vocab_due:
        user_parts.append(
            "Vocabulary due for review:\n"
            + json.dumps(vocab_due, ensure_ascii=False, indent=2)
        )
    else:
        user_parts.append("No vocabulary currently due for review.")

    if weak_points:
        user_parts.append(
            "Weakest learning points:\n"
            + json.dumps(weak_points, ensure_ascii=False, indent=2)
        )

    if top_errors:
        user_parts.append(
            "Recent error patterns (area -> count): "
            + ", ".join(f"{area} ({cnt})" for area, cnt in top_errors)
        )

    if learning_dna:
        user_parts.append(
            "Learning DNA profile:\n"
            + json.dumps(learning_dna, ensure_ascii=False, indent=2)
        )

    if lesson_objective:
        user_parts.append(f"Next lesson objective: {lesson_objective}")

    if lesson_content:
        # Include a truncated preview so the AI can tie the warm-up to the topic
        preview = lesson_content[:500] if isinstance(lesson_content, str) else ""
        if preview:
            user_parts.append(f"Next lesson content preview: {preview}")

    user_parts.append(
        "Generate a warm-up package (JSON only) that the student can complete "
        "in about 5 minutes before the session."
    )

    user_message = "\n\n".join(user_parts)

    # --- Call the AI ---
    logger.info(
        "Generating warm-up for student %s, session %s", student_id, session_id
    )

    try:
        ai_response = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="cheap",
            temperature=0.5,
            json_mode=True,
        )
    except Exception as exc:
        logger.error(
            "AI call failed for warmup (student=%s, session=%s): %s",
            student_id,
            session_id,
            exc,
        )
        raise ValueError("AI did not return valid warm-up JSON") from exc

    try:
        warmup_data = json.loads(ai_response)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(
            "AI returned invalid JSON for warmup (student=%s, session=%s): %s",
            student_id,
            session_id,
            exc,
        )
        raise ValueError("AI did not return valid warm-up JSON") from exc

    # --- Save to pre_class_warmups table ---
    warmup_json_str = json.dumps(warmup_data, ensure_ascii=False)
    cursor = await db.execute(
        """
        INSERT INTO pre_class_warmups (session_id, student_id, warmup_json, status)
        VALUES (?, ?, ?, 'generated')
        """,
        (session_id, student_id, warmup_json_str),
    )
    await db.commit()

    warmup_id = cursor.lastrowid

    logger.info(
        "Warm-up %s generated for student %s, session %s",
        warmup_id,
        student_id,
        session_id,
    )

    return {
        "warmup_id": warmup_id,
        "session_id": session_id,
        "student_id": student_id,
        "status": "generated",
        **warmup_data,
    }


async def complete_warmup(
    warmup_id: int, db, results: dict, confidence: int
) -> dict:
    """Mark a warm-up as completed with the student's results and confidence rating."""

    results_json_str = json.dumps(results, ensure_ascii=False)
    await db.execute(
        """
        UPDATE pre_class_warmups
        SET results_json = ?, confidence_rating = ?, status = 'completed', completed_at = datetime('now')
        WHERE id = ?
        """,
        (results_json_str, confidence, warmup_id),
    )
    await db.commit()

    logger.info("Warm-up %s completed (confidence=%s)", warmup_id, confidence)

    return {"status": "completed", "warmup_id": warmup_id}


async def get_warmup_for_session(
    session_id: int, student_id: int, db
) -> dict | None:
    """Retrieve the most recent warm-up for a given session and student."""

    cursor = await db.execute(
        """
        SELECT * FROM pre_class_warmups
        WHERE session_id = ? AND student_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (session_id, student_id),
    )
    row = await cursor.fetchone()
    if not row:
        return None

    # Build a dict from the row — aiosqlite Row objects support index access.
    # Expected columns: id, session_id, student_id, warmup_json, results_json,
    #                    confidence_rating, status, created_at, completed_at
    warmup = {
        "warmup_id": row[0],
        "session_id": row[1],
        "student_id": row[2],
        "status": row[6],
        "created_at": row[7],
        "completed_at": row[8],
    }

    # Parse the warmup JSON payload
    if row[3]:
        try:
            warmup_data = (
                json.loads(row[3]) if isinstance(row[3], str) else row[3]
            )
            warmup.update(warmup_data)
        except (json.JSONDecodeError, TypeError):
            warmup["warmup_json_raw"] = row[3]

    # Parse the results JSON payload
    if row[4]:
        try:
            results_data = (
                json.loads(row[4]) if isinstance(row[4], str) else row[4]
            )
            warmup["results"] = results_data
        except (json.JSONDecodeError, TypeError):
            warmup["results_raw"] = row[4]

    if row[5] is not None:
        warmup["confidence_rating"] = row[5]

    return warmup


async def generate_pending_warmups(db) -> list[dict]:
    """Find all sessions in the next 24 hours without warm-ups and generate them.

    Handles both individual sessions (student_id on the session row) and group
    sessions (students listed in session_students).  Each generation is wrapped
    in try/except so a single failure does not block others.
    """

    # --- Find confirmed sessions in the next 24 hours lacking a warm-up ---
    cursor = await db.execute(
        """
        SELECT s.id as session_id, s.student_id, s.scheduled_at
        FROM sessions s
        WHERE s.status IN ('confirmed')
          AND s.scheduled_at > datetime('now')
          AND s.scheduled_at <= datetime('now', '+1 day')
          AND NOT EXISTS (
              SELECT 1 FROM pre_class_warmups pw
              WHERE pw.session_id = s.id AND pw.student_id = s.student_id
          )
        """,
    )
    pending_sessions = await cursor.fetchall()

    # Collect (session_id, student_id) pairs to process
    pairs: list[tuple[int, int]] = []

    for row in pending_sessions:
        sid = row[0]
        student_id = row[1]
        if student_id:
            pairs.append((sid, student_id))

        # Also check for group-session participants
        cursor = await db.execute(
            "SELECT student_id FROM session_students WHERE session_id = ?",
            (sid,),
        )
        group_rows = await cursor.fetchall()
        for grow in group_rows:
            group_student_id = grow[0]
            if (sid, group_student_id) not in pairs:
                pairs.append((sid, group_student_id))

    # --- Generate a warm-up for every pair ---
    results: list[dict] = []

    for s_id, st_id in pairs:
        try:
            warmup = await generate_warmup(
                student_id=st_id, session_id=s_id, db=db
            )
            results.append(
                {
                    "session_id": s_id,
                    "student_id": st_id,
                    "status": "generated",
                    "warmup_id": warmup.get("warmup_id"),
                }
            )
            logger.info(
                "Pending warm-up generated for session %s, student %s", s_id, st_id
            )
        except Exception:
            logger.exception(
                "Failed to generate warm-up for session %s, student %s", s_id, st_id
            )
            results.append(
                {
                    "session_id": s_id,
                    "student_id": st_id,
                    "status": "error",
                    "warmup_id": None,
                }
            )

    logger.info(
        "Pending warm-up generation complete: %d processed, %d succeeded",
        len(results),
        sum(1 for r in results if r["status"] == "generated"),
    )

    return results
