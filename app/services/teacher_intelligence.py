"""Real-time teacher intelligence service.

Generates:
- Pre-class student briefings with predicted struggles
- Post-session targeted observation prompts
"""

import json
import logging
from datetime import datetime
from app.services.ai_client import ai_chat
from app.services.prompts import load_prompt

logger = logging.getLogger(__name__)


async def generate_teacher_briefing(session_id: int, db) -> dict:
    """Generate a comprehensive pre-class briefing for the teacher.

    Gathers all available student context -- previous sessions, learning DNA,
    warmup results, skill observations, L1 interference patterns, CEFR history
    -- and asks AI to produce a structured briefing with predicted struggles,
    focus areas, and recommended teaching approach.
    """

    # ── 1. Fetch session + student info ──────────────────────────────
    cursor = await db.execute(
        """SELECT s.*, u.name as student_name, u.current_level, u.goals,
                  u.problem_areas
           FROM sessions s
           JOIN users u ON u.id = s.student_id
           WHERE s.id = ?""",
        (session_id,),
    )
    session = await cursor.fetchone()
    if not session:
        return {"error": "Session not found"}
    session = dict(session)

    student_id = session["student_id"]
    student_name = session["student_name"]
    current_level = session.get("current_level") or "A1"

    # Parse JSON fields on the user row
    goals = []
    if session.get("goals"):
        try:
            goals = json.loads(session["goals"])
        except (json.JSONDecodeError, TypeError):
            goals = [session["goals"]] if session["goals"] else []

    problem_areas = []
    if session.get("problem_areas"):
        try:
            problem_areas = json.loads(session["problem_areas"])
        except (json.JSONDecodeError, TypeError):
            problem_areas = (
                [session["problem_areas"]] if session["problem_areas"] else []
            )

    # ── 2. Last completed session (with notes) ──────────────────────
    cursor = await db.execute(
        """SELECT session_summary, teacher_notes, homework, scheduled_at
           FROM sessions
           WHERE student_id = ? AND status = 'completed'
           ORDER BY scheduled_at DESC LIMIT 1""",
        (student_id,),
    )
    last_session_row = await cursor.fetchone()
    last_session = dict(last_session_row) if last_session_row else None

    # ── 3. Latest learning DNA ───────────────────────────────────────
    cursor = await db.execute(
        """SELECT dna_json FROM learning_dna
           WHERE student_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (student_id,),
    )
    dna_row = await cursor.fetchone()
    learning_dna = None
    if dna_row and dna_row["dna_json"]:
        try:
            learning_dna = (
                json.loads(dna_row["dna_json"])
                if isinstance(dna_row["dna_json"], str)
                else dna_row["dna_json"]
            )
        except (json.JSONDecodeError, TypeError):
            learning_dna = None

    # ── 4. Pre-class warmup results ──────────────────────────────────
    cursor = await db.execute(
        """SELECT warmup_json, results_json, confidence_rating
           FROM pre_class_warmups
           WHERE session_id = ? AND student_id = ? AND status = 'completed'
           ORDER BY created_at DESC LIMIT 1""",
        (session_id, student_id),
    )
    warmup_row = await cursor.fetchone()
    warmup_data = None
    if warmup_row:
        warmup_data = {}
        for field in ("warmup_json", "results_json"):
            val = warmup_row[field]
            if val:
                try:
                    warmup_data[field] = (
                        json.loads(val) if isinstance(val, str) else val
                    )
                except (json.JSONDecodeError, TypeError):
                    warmup_data[field] = val
        warmup_data["confidence_rating"] = warmup_row["confidence_rating"]

    # ── 5. Recent skill observations (last 5) ────────────────────────
    cursor = await db.execute(
        """SELECT skill, score, cefr_level, notes
           FROM session_skill_observations
           WHERE student_id = ?
           ORDER BY created_at DESC LIMIT 5""",
        (student_id,),
    )
    skill_observations = [dict(r) for r in await cursor.fetchall()]

    # ── 6. L1 interference patterns ──────────────────────────────────
    cursor = await db.execute(
        """SELECT pattern_category, pattern_detail, occurrences, status
           FROM l1_interference_tracking
           WHERE student_id = ?
           ORDER BY occurrences DESC LIMIT 10""",
        (student_id,),
    )
    l1_patterns = [dict(r) for r in await cursor.fetchall()]

    # ── 7. Linked lesson content ─────────────────────────────────────
    lesson_data = None
    lesson_id = session.get("lesson_id")
    if lesson_id:
        cursor = await db.execute(
            "SELECT objective, content FROM lessons WHERE id = ?",
            (lesson_id,),
        )
        lesson_row = await cursor.fetchone()
        if lesson_row:
            lesson_data = dict(lesson_row)
            if lesson_data.get("content") and isinstance(lesson_data["content"], str):
                try:
                    lesson_data["content"] = json.loads(lesson_data["content"])
                except (json.JSONDecodeError, TypeError):
                    pass

    # ── 8. CEFR history (last 3) ─────────────────────────────────────
    cursor = await db.execute(
        """SELECT level, grammar_level, vocabulary_level, speaking_level,
                  reading_level, writing_level, recorded_at
           FROM cefr_history
           WHERE student_id = ?
           ORDER BY recorded_at DESC LIMIT 3""",
        (student_id,),
    )
    cefr_history = [dict(r) for r in await cursor.fetchall()]

    # ── Build user message ───────────────────────────────────────────
    user_message = f"""Prepare a pre-class briefing for the teacher about to teach this student.

STUDENT: {student_name} (ID: {student_id})
CURRENT LEVEL: {current_level}
GOALS: {', '.join(goals) if goals else 'Not specified'}
PROBLEM AREAS: {', '.join(problem_areas) if problem_areas else 'Not specified'}

SESSION SCHEDULED AT: {session.get('scheduled_at', 'Unknown')}

LAST COMPLETED SESSION:
{json.dumps(last_session, indent=2, default=str) if last_session else 'No previous completed session.'}

LEARNING DNA (learning style/preferences):
{json.dumps(learning_dna, indent=2) if learning_dna else 'No learning DNA data yet.'}

PRE-CLASS WARMUP RESULTS:
{json.dumps(warmup_data, indent=2) if warmup_data else 'No warmup completed for this session.'}

RECENT SKILL OBSERVATIONS (teacher-rated, last 5):
{json.dumps(skill_observations, indent=2) if skill_observations else 'No skill observations yet.'}

L1 INTERFERENCE PATTERNS (Polish):
{json.dumps(l1_patterns, indent=2) if l1_patterns else 'No L1 interference patterns tracked yet.'}

LESSON PLAN FOR THIS SESSION:
{json.dumps(lesson_data, indent=2) if lesson_data else 'No lesson linked to this session yet.'}

CEFR HISTORY (last 3 assessments):
{json.dumps(cefr_history, indent=2, default=str) if cefr_history else 'No CEFR history yet.'}

Generate a comprehensive but concise pre-class briefing as JSON."""

    system_prompt = (
        "You are an AI teaching assistant preparing a briefing for an English "
        "teacher about to teach a Polish-speaking student. Generate a "
        "comprehensive but concise pre-class briefing.\n\n"
        "You MUST respond with valid JSON in this exact format:\n"
        "{\n"
        '  "student_summary": "Brief overview of student\'s current state",\n'
        '  "last_session_recap": "What was covered, what they struggled with",\n'
        '  "warmup_insights": "Pre-class warmup results if available, or null",\n'
        '  "focus_areas": ["area1", "area2", "area3"],\n'
        '  "predicted_struggles": [\n'
        '    {"topic": "...", "reason": "...", "scaffolding_suggestion": "..."}\n'
        "  ],\n"
        '  "conversation_starters": ["Based on their interests..."],\n'
        '  "l1_watch_points": ["Specific Polish interference to watch for"],\n'
        '  "cefr_comparison": "How they compare to typical students at this level",\n'
        '  "confidence_notes": "Student mood/confidence indicators",\n'
        '  "recommended_approach": "Overall teaching strategy suggestion"\n'
        "}"
    )

    # ── Call AI ──────────────────────────────────────────────────────
    try:
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="lesson",
            temperature=0.5,
            json_mode=True,
        )
    except Exception as exc:
        logger.error(
            "AI call failed for teacher briefing (session %s): %s", session_id, exc
        )
        return {"error": "AI service unavailable"}

    try:
        briefing = json.loads(result_text)
    except json.JSONDecodeError:
        logger.error(
            "Failed to parse teacher briefing JSON for session %s", session_id
        )
        return {"error": "Failed to parse AI response", "raw": result_text}

    return briefing


async def generate_post_session_prompts(session_id: int, db) -> dict:
    """Generate targeted post-session observation questions for the teacher.

    Instead of generic 'rate speaking 1-5' questions, this produces specific
    observation prompts tailored to the lesson content, the student's known
    L1 interference patterns, and their learning DNA.
    """

    # ── 1. Fetch session + student info ──────────────────────────────
    cursor = await db.execute(
        """SELECT s.*, u.name as student_name, u.current_level, u.goals,
                  u.problem_areas
           FROM sessions s
           JOIN users u ON u.id = s.student_id
           WHERE s.id = ?""",
        (session_id,),
    )
    session = await cursor.fetchone()
    if not session:
        return {"error": "Session not found"}
    session = dict(session)

    student_id = session["student_id"]
    student_name = session["student_name"]
    current_level = session.get("current_level") or "A1"

    goals = []
    if session.get("goals"):
        try:
            goals = json.loads(session["goals"])
        except (json.JSONDecodeError, TypeError):
            goals = [session["goals"]] if session["goals"] else []

    problem_areas = []
    if session.get("problem_areas"):
        try:
            problem_areas = json.loads(session["problem_areas"])
        except (json.JSONDecodeError, TypeError):
            problem_areas = (
                [session["problem_areas"]] if session["problem_areas"] else []
            )

    # ── 2. Linked lesson content ─────────────────────────────────────
    lesson_data = None
    lesson_id = session.get("lesson_id")
    if lesson_id:
        cursor = await db.execute(
            "SELECT objective, content FROM lessons WHERE id = ?",
            (lesson_id,),
        )
        lesson_row = await cursor.fetchone()
        if lesson_row:
            lesson_data = dict(lesson_row)
            if lesson_data.get("content") and isinstance(lesson_data["content"], str):
                try:
                    lesson_data["content"] = json.loads(lesson_data["content"])
                except (json.JSONDecodeError, TypeError):
                    pass

    # ── 3. L1 interference patterns ──────────────────────────────────
    cursor = await db.execute(
        """SELECT pattern_category, pattern_detail, occurrences, status
           FROM l1_interference_tracking
           WHERE student_id = ?
           ORDER BY occurrences DESC LIMIT 10""",
        (student_id,),
    )
    l1_patterns = [dict(r) for r in await cursor.fetchall()]

    # ── 4. Latest learning DNA ───────────────────────────────────────
    cursor = await db.execute(
        """SELECT dna_json FROM learning_dna
           WHERE student_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (student_id,),
    )
    dna_row = await cursor.fetchone()
    learning_dna = None
    if dna_row and dna_row["dna_json"]:
        try:
            learning_dna = (
                json.loads(dna_row["dna_json"])
                if isinstance(dna_row["dna_json"], str)
                else dna_row["dna_json"]
            )
        except (json.JSONDecodeError, TypeError):
            learning_dna = None

    # ── Build user message ───────────────────────────────────────────
    user_message = f"""Generate targeted post-session observation questions for the teacher who just taught this student.

STUDENT: {student_name} (ID: {student_id})
CURRENT LEVEL: {current_level}
GOALS: {', '.join(goals) if goals else 'Not specified'}
PROBLEM AREAS: {', '.join(problem_areas) if problem_areas else 'Not specified'}

LESSON PLAN FOR THIS SESSION:
{json.dumps(lesson_data, indent=2) if lesson_data else 'No lesson linked to this session.'}

L1 INTERFERENCE PATTERNS (Polish):
{json.dumps(l1_patterns, indent=2) if l1_patterns else 'No L1 interference patterns tracked yet.'}

LEARNING DNA (learning style/preferences):
{json.dumps(learning_dna, indent=2) if learning_dna else 'No learning DNA data yet.'}

Generate specific, targeted observation questions -- NOT generic "rate speaking 1-5" but questions about whether the student demonstrated particular skills. Return as JSON."""

    system_prompt = (
        "You are an AI that generates targeted post-session observation "
        "questions for an English teacher. Based on the lesson content and "
        "student's known patterns, generate specific observation questions "
        "-- NOT generic 'rate speaking 1-5' but specific questions about "
        "whether the student demonstrated particular skills.\n\n"
        "You MUST respond with valid JSON in this exact format:\n"
        "{\n"
        '  "observation_questions": [\n'
        "    {\n"
        '      "skill_area": "grammar|vocabulary|speaking|reading|writing",\n'
        '      "question": "Specific observation question",\n'
        '      "what_to_look_for": "What would indicate progress vs struggle",\n'
        '      "related_l1_pattern": "Related Polish interference pattern if applicable"\n'
        "    }\n"
        "  ],\n"
        '  "follow_up_suggestions": ["Suggested homework or practice based on likely session outcomes"],\n'
        '  "notes_prompts": ["Specific things to note for the student\'s record"]\n'
        "}"
    )

    # ── Call AI ──────────────────────────────────────────────────────
    try:
        result_text = await ai_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            use_case="cheap",
            temperature=0.4,
            json_mode=True,
        )
    except Exception as exc:
        logger.error(
            "AI call failed for post-session prompts (session %s): %s", session_id, exc
        )
        return {"error": "AI service unavailable"}

    try:
        prompts = json.loads(result_text)
    except json.JSONDecodeError:
        logger.error(
            "Failed to parse post-session prompts JSON for session %s", session_id
        )
        return {"error": "Failed to parse AI response", "raw": result_text}

    return prompts
