"""Periodic CEFR reassessment triggered after every 10 completed lessons.

Pulls skill tags from the last 10 lessons, asks AI to evaluate the student's
current CEFR level across sub-skills, and stores the result in cefr_history.
"""

import json
import logging
from app.services.ai_client import ai_chat

logger = logging.getLogger(__name__)

_REASSESSMENT_SYSTEM = """You are an expert English language assessor specializing in CEFR level evaluation for Polish-speaking learners.

You are performing a periodic reassessment based on a student's recent lesson performance data.

Analyze the student's recent lesson topics, skill tags, quiz scores, and progress to determine their current CEFR level across all sub-skills.

Consider:
1. The range of grammar topics covered — are they handling B1/B2 grammar or still working on A2?
2. Vocabulary breadth — topics and CEFR tags on recent lessons
3. Reading comprehension performance from quiz scores
4. Writing indicators from lesson content
5. Overall trajectory — is the student improving, stable, or struggling?

You MUST respond with valid JSON in this exact format:
{
  "determined_level": "A1|A2|B1|B2|C1|C2",
  "confidence_score": 0.0-1.0,
  "sub_skill_breakdown": {
    "grammar": "A1|A2|B1|B2|C1|C2",
    "vocabulary": "A1|A2|B1|B2|C1|C2",
    "reading": "A1|A2|B1|B2|C1|C2",
    "speaking": "A1|A2|B1|B2|C1|C2",
    "writing": "A1|A2|B1|B2|C1|C2"
  },
  "justification": "Brief explanation of the level determination based on recent performance",
  "trajectory": "improving|stable|declining",
  "recommendations": ["recommendation1", "recommendation2"]
}"""


async def trigger_reassessment(student_id: int, db) -> dict | None:
    """Generate a mini-CEFR reassessment from the last 10 completed lessons.

    Returns the reassessment result dict, or None if there's insufficient data.
    """
    # Get the last 10 completed lessons for this student
    cursor = await db.execute(
        """SELECT l.id, l.objective, l.difficulty, l.session_number
           FROM lessons l
           JOIN progress p ON p.lesson_id = l.id AND p.student_id = l.student_id
           WHERE l.student_id = ?
           ORDER BY p.completed_at DESC
           LIMIT 10""",
        (student_id,),
    )
    recent_lessons = await cursor.fetchall()

    if len(recent_lessons) < 10:
        logger.info(
            "Reassessment skipped for student %d: only %d completed lessons",
            student_id, len(recent_lessons),
        )
        return None

    lesson_ids = [row["id"] for row in recent_lessons]

    # Get skill tags for these lessons
    placeholders = ",".join("?" for _ in lesson_ids)
    cursor = await db.execute(
        f"""SELECT lesson_id, tag_type, tag_value, cefr_level
            FROM lesson_skill_tags
            WHERE lesson_id IN ({placeholders})
            ORDER BY lesson_id""",
        lesson_ids,
    )
    skill_tags = [dict(row) for row in await cursor.fetchall()]

    # Get quiz scores for these lessons
    cursor = await db.execute(
        f"""SELECT nq.session_id, qa.score, qa.results_json
            FROM quiz_attempts qa
            JOIN next_quizzes nq ON nq.id = qa.quiz_id
            WHERE qa.student_id = ?
            ORDER BY qa.submitted_at DESC
            LIMIT 10""",
        (student_id,),
    )
    quiz_scores = [dict(row) for row in await cursor.fetchall()]

    # Get current student level
    cursor = await db.execute(
        "SELECT name, current_level FROM users WHERE id = ?",
        (student_id,),
    )
    student = await cursor.fetchone()
    if not student:
        return None

    current_level = student["current_level"] or "A1"
    name = student["name"]

    # Get previous CEFR history
    cursor = await db.execute(
        """SELECT level, grammar_level, vocabulary_level, reading_level,
                  speaking_level, writing_level, recorded_at, source
           FROM cefr_history
           WHERE student_id = ?
           ORDER BY recorded_at DESC LIMIT 3""",
        (student_id,),
    )
    cefr_history = [dict(row) for row in await cursor.fetchall()]

    # Build the user message
    lessons_summary = []
    for row in recent_lessons:
        lessons_summary.append(
            f"- Session {row['session_number']}: {row['objective'] or 'N/A'} "
            f"(difficulty: {row['difficulty'] or 'N/A'})"
        )

    tags_summary = []
    for tag in skill_tags:
        tags_summary.append(
            f"- [{tag['tag_type']}] {tag['tag_value']} (CEFR: {tag.get('cefr_level', 'N/A')})"
        )

    scores_summary = []
    for qs in quiz_scores:
        scores_summary.append(f"- Score: {qs.get('score', 'N/A')}%")

    history_summary = []
    for h in cefr_history:
        history_summary.append(
            f"- {h.get('recorded_at', 'N/A')}: Overall {h['level']} "
            f"(grammar={h.get('grammar_level', '?')}, vocab={h.get('vocabulary_level', '?')}, "
            f"reading={h.get('reading_level', '?')}, speaking={h.get('speaking_level', '?')}, "
            f"writing={h.get('writing_level', '?')}) via {h.get('source', '?')}"
        )

    user_message = f"""Perform a periodic CEFR reassessment for this student:

STUDENT: {name} (ID: {student_id})
CURRENT LEVEL: {current_level}

LAST 10 COMPLETED LESSONS:
{chr(10).join(lessons_summary) if lessons_summary else 'No data'}

SKILL TAGS FROM THESE LESSONS:
{chr(10).join(tags_summary) if tags_summary else 'No skill tags available'}

RECENT QUIZ SCORES:
{chr(10).join(scores_summary) if scores_summary else 'No quiz data'}

CEFR HISTORY:
{chr(10).join(history_summary) if history_summary else 'No previous assessments'}

Based on this data, determine the student's current CEFR level as JSON."""

    result_text = await ai_chat(
        messages=[
            {"role": "system", "content": _REASSESSMENT_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        use_case="assessment",
        temperature=0.3,
        json_mode=True,
    )

    result = json.loads(result_text)

    determined_level = result.get("determined_level")
    if not determined_level:
        logger.warning("Reassessment for student %d returned no level", student_id)
        return result

    sub_skills = result.get("sub_skill_breakdown", {})

    # Store in cefr_history
    await db.execute(
        """INSERT INTO cefr_history
           (student_id, level, grammar_level, vocabulary_level,
            reading_level, speaking_level, writing_level,
            confidence, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'periodic_reassessment')""",
        (
            student_id,
            determined_level,
            sub_skills.get("grammar"),
            sub_skills.get("vocabulary"),
            sub_skills.get("reading"),
            sub_skills.get("speaking"),
            sub_skills.get("writing"),
            result.get("confidence_score"),
        ),
    )

    # Update current_level if the reassessment is confident enough
    # Threshold lowered from 0.7 to 0.6 so strong-performing students
    # are not stuck at a level when the AI is "moderately confident"
    confidence = result.get("confidence_score", 0)
    if confidence >= 0.6 and determined_level != current_level:
        await db.execute(
            "UPDATE users SET current_level = ? WHERE id = ?",
            (determined_level, student_id),
        )
        logger.info(
            "Student %d level updated from %s to %s (confidence: %.2f) via periodic reassessment",
            student_id, current_level, determined_level, confidence,
        )

    await db.commit()

    return result
