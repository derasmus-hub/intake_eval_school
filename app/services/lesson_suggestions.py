"""Pre-class lesson suggestions.

Gathers recent student context and asks AI to propose 3 lesson topics
the teacher can choose from before confirming the next session.
"""

import json
import logging
from app.services.ai_client import ai_chat

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an expert English curriculum planner for Polish-speaking students.

Given a student's recent progress data, learning profile, CEFR history, and goals,
suggest exactly 3 lesson topic options for their next session.

The 3 suggestions MUST be distinct approaches:

1. REVIEW-FOCUSED — Targets the student's weakest area based on recent quiz scores,
   recall weak areas, teacher observations, or skill tags where performance was low.
   This helps reinforce struggling concepts before moving on.

2. PROGRESSION-FOCUSED — Introduces the next natural grammar/vocabulary topic in
   the CEFR curriculum for this student's level. Look at what topics have been
   covered and suggest the logical next step. Avoid repeating recently covered topics.

3. INTEREST-BASED — Based on the student's stated goals, interests, or needs
   (e.g. "travel", "business English", "exam prep"). Frame a grammar/vocabulary
   topic through the lens of what motivates this student.

For each suggestion provide:
- title: A clear, concise lesson title
- type: "review" | "progression" | "interest"
- rationale: 2-3 sentences explaining WHY this topic now, referencing specific
  student data (recent scores, gaps, goals)
- difficulty: The CEFR level this lesson targets (A1-C2)
- grammar_focus: The specific grammar point (if applicable)
- vocabulary_preview: 4-6 key vocabulary words the lesson would introduce or review
- estimated_duration_minutes: Suggested session length (usually 45 or 60)

You MUST respond with valid JSON in this exact format:
{
  "suggestions": [
    {
      "title": "string",
      "type": "review",
      "rationale": "string",
      "difficulty": "A1|A2|B1|B2|C1|C2",
      "grammar_focus": "string or null",
      "vocabulary_preview": ["word1", "word2", "word3", "word4"],
      "estimated_duration_minutes": 45
    },
    {
      "title": "string",
      "type": "progression",
      "rationale": "string",
      "difficulty": "A1|A2|B1|B2|C1|C2",
      "grammar_focus": "string or null",
      "vocabulary_preview": ["word1", "word2", "word3", "word4"],
      "estimated_duration_minutes": 45
    },
    {
      "title": "string",
      "type": "interest",
      "rationale": "string",
      "difficulty": "A1|A2|B1|B2|C1|C2",
      "grammar_focus": "string or null",
      "vocabulary_preview": ["word1", "word2", "word3", "word4"],
      "estimated_duration_minutes": 45
    }
  ]
}"""


async def get_lesson_suggestions(student_id: int, db) -> dict:
    """Generate 3 lesson topic suggestions for a student.

    Returns the parsed AI response with a 'suggestions' list.
    """

    # ── Gather student context ────────────────────────────────────

    # Basic info
    cursor = await db.execute(
        "SELECT name, current_level, goals, problem_areas FROM users WHERE id = ?",
        (student_id,),
    )
    student = await cursor.fetchone()
    if not student:
        return {"suggestions": [], "error": "Student not found"}

    current_level = student["current_level"] or "A1"
    goals = []
    if student["goals"]:
        try:
            goals = json.loads(student["goals"])
        except (json.JSONDecodeError, TypeError):
            goals = [student["goals"]] if student["goals"] else []

    problem_areas = []
    if student["problem_areas"]:
        try:
            problem_areas = json.loads(student["problem_areas"])
        except (json.JSONDecodeError, TypeError):
            problem_areas = [student["problem_areas"]] if student["problem_areas"] else []

    # Learner profile
    cursor = await db.execute(
        """SELECT gaps, priorities, profile_summary
           FROM learner_profiles
           WHERE student_id = ? ORDER BY created_at DESC LIMIT 1""",
        (student_id,),
    )
    profile_row = await cursor.fetchone()
    profile_summary = ""
    priorities = []
    gaps = []
    if profile_row:
        profile_summary = profile_row["profile_summary"] or ""
        if profile_row["priorities"]:
            try:
                priorities = json.loads(profile_row["priorities"])
            except (json.JSONDecodeError, TypeError):
                pass
        if profile_row["gaps"]:
            try:
                gaps = json.loads(profile_row["gaps"])
            except (json.JSONDecodeError, TypeError):
                pass

    # Recent progress (last 5 lessons)
    cursor = await db.execute(
        """SELECT p.score, p.areas_improved, p.areas_struggling, l.objective
           FROM progress p
           JOIN lessons l ON l.id = p.lesson_id
           WHERE p.student_id = ?
           ORDER BY p.completed_at DESC LIMIT 5""",
        (student_id,),
    )
    progress_rows = await cursor.fetchall()
    recent_progress = []
    for row in progress_rows:
        improved = []
        struggling = []
        try:
            improved = json.loads(row["areas_improved"]) if row["areas_improved"] else []
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            struggling = json.loads(row["areas_struggling"]) if row["areas_struggling"] else []
        except (json.JSONDecodeError, TypeError):
            pass
        recent_progress.append({
            "objective": row["objective"],
            "score": row["score"],
            "areas_improved": improved,
            "areas_struggling": struggling,
        })

    # Recent lesson topics (last 10)
    cursor = await db.execute(
        "SELECT objective FROM lessons WHERE student_id = ? ORDER BY session_number DESC LIMIT 10",
        (student_id,),
    )
    recent_topics = [r["objective"] for r in await cursor.fetchall() if r["objective"]]

    # Skill tags from recent lessons
    cursor = await db.execute(
        """SELECT lst.tag_type, lst.tag_value, lst.cefr_level
           FROM lesson_skill_tags lst
           JOIN lessons l ON l.id = lst.lesson_id
           WHERE l.student_id = ?
           ORDER BY l.session_number DESC
           LIMIT 20""",
        (student_id,),
    )
    skill_tags = [dict(r) for r in await cursor.fetchall()]

    # CEFR history (last 3)
    cursor = await db.execute(
        """SELECT level, grammar_level, vocabulary_level, reading_level,
                  speaking_level, writing_level, source, recorded_at
           FROM cefr_history
           WHERE student_id = ? ORDER BY recorded_at DESC LIMIT 3""",
        (student_id,),
    )
    cefr_history = [dict(r) for r in await cursor.fetchall()]

    # Teacher skill observations (last 10)
    cursor = await db.execute(
        """SELECT skill, score, cefr_level, notes
           FROM session_skill_observations
           WHERE student_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (student_id,),
    )
    teacher_obs = [dict(r) for r in await cursor.fetchall()]

    # Recall weak areas
    cursor = await db.execute(
        """SELECT weak_areas FROM recall_sessions
           WHERE student_id = ? AND status = 'completed'
           ORDER BY completed_at DESC LIMIT 1""",
        (student_id,),
    )
    recall_row = await cursor.fetchone()
    recall_weak = []
    if recall_row and recall_row["weak_areas"]:
        try:
            recall_weak = json.loads(recall_row["weak_areas"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Writing CEFR from recent submissions
    cursor = await db.execute(
        """SELECT cefr_level, overall_score
           FROM writing_submissions
           WHERE student_id = ?
           ORDER BY created_at DESC LIMIT 3""",
        (student_id,),
    )
    writing_data = [dict(r) for r in await cursor.fetchall()]

    # ── Build the prompt ──────────────────────────────────────────

    user_message = f"""Suggest 3 lesson topics for this student's next session:

STUDENT: {student["name"]} (ID: {student_id})
CURRENT LEVEL: {current_level}

GOALS: {', '.join(goals) if goals else 'Not specified'}
PROBLEM AREAS: {', '.join(problem_areas) if problem_areas else 'Not specified'}

LEARNER PROFILE SUMMARY:
{profile_summary or 'No profile available yet.'}

PRIORITY AREAS: {', '.join(priorities) if priorities else 'None identified'}

IDENTIFIED GAPS:
{json.dumps(gaps, indent=2) if gaps else 'None identified'}

RECENT LESSON TOPICS (most recent first — do NOT repeat these):
{chr(10).join('- ' + t for t in recent_topics) if recent_topics else 'No lessons yet.'}

RECENT PROGRESS (last 5 lessons):
{json.dumps(recent_progress, indent=2) if recent_progress else 'No progress data yet.'}

SKILL TAGS FROM RECENT LESSONS:
{json.dumps(skill_tags, indent=2) if skill_tags else 'No skill tags yet.'}

CEFR HISTORY:
{json.dumps(cefr_history, indent=2) if cefr_history else 'No CEFR history yet.'}

TEACHER OBSERVATIONS:
{json.dumps(teacher_obs, indent=2) if teacher_obs else 'No observations yet.'}

RECALL WEAK AREAS (from spaced repetition):
{', '.join(recall_weak) if recall_weak else 'None'}

RECENT WRITING PERFORMANCE:
{json.dumps(writing_data, indent=2) if writing_data else 'No writing data yet.'}

Based on all of this data, suggest 3 distinct lesson topics as JSON."""

    result_text = await ai_chat(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        use_case="cheap",
        temperature=0.7,
        json_mode=True,
    )

    return json.loads(result_text)
