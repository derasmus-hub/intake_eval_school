"""
quiz_scorer.py - Quiz scoring and results service

Provides:
- score_quiz_attempt(quiz_id, student_id, answers) - Score submitted answers
- get_attempt_summary(attempt_id) - Get summary with weak areas for teacher
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

import aiosqlite

from app.db import learning_loop as ll

logger = logging.getLogger(__name__)

# Canonical skill taxonomy mapping — normalizes free-form AI tags to fixed tags
SKILL_ALIASES = {
    "grammar_articles": "articles_definite",
    "articles_a_an_usage": "articles_indefinite",
    "articles_the_usage": "articles_definite",
    "grammar_articles_indefinite": "articles_indefinite",
    "grammar_articles_definite": "articles_definite",
    "grammar_articles_sentence_structure": "word_order",
    "grammar_articles_basic": "articles_indefinite",
    "vocabulary_business": "business_basic",
    "grammar_ordering": "word_order",
    "grammar_sentence_order": "word_order",
    "grammar_sentence_structure": "word_order",
    "sentence_structure": "word_order",
    "translation_business": "business_basic",
    "vocabulary_articles": "articles_indefinite",
    "prepositions_time": "word_order",
    "prepositions_place": "word_order",
    "prepositions_days": "word_order",
    "vocabulary_prepositions": "everyday_actions",
    "translation_prepositions": "everyday_actions",
    "articles_basic": "articles_indefinite",
}


def normalize_skill_tag(tag: str) -> str:
    """Map free-form AI skill tags to canonical taxonomy tags."""
    return SKILL_ALIASES.get(tag, tag)


def normalize_answer(answer: str) -> str:
    """Normalize an answer for comparison."""
    if not answer:
        return ""
    return answer.strip().lower()


def _strip_articles(text: str) -> str:
    """Remove leading articles from a normalized string."""
    for article in ("the ", "a ", "an "):
        if text.startswith(article):
            text = text[len(article):]
    return text


def _normalize_punctuation(text: str) -> str:
    """Remove trailing punctuation and collapse whitespace."""
    import re
    text = re.sub(r'[.,!?;:]+$', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_contractions(text: str) -> str:
    """Expand common contractions for comparison."""
    replacements = {
        "i'm": "i am", "you're": "you are", "he's": "he is", "she's": "she is",
        "it's": "it is", "we're": "we are", "they're": "they are",
        "isn't": "is not", "aren't": "are not", "wasn't": "was not",
        "weren't": "were not", "don't": "do not", "doesn't": "does not",
        "didn't": "did not", "won't": "will not", "can't": "cannot",
        "couldn't": "could not", "shouldn't": "should not",
        "wouldn't": "would not", "haven't": "have not", "hasn't": "has not",
        "hadn't": "had not", "i've": "i have", "you've": "you have",
        "we've": "we have", "they've": "they have", "i'll": "i will",
        "you'll": "you will", "he'll": "he will", "she'll": "she will",
        "we'll": "we will", "they'll": "they will", "i'd": "i would",
        "you'd": "you would", "he'd": "he would", "she'd": "she would",
        "we'd": "we would", "they'd": "they would",
    }
    for contraction, expanded in replacements.items():
        text = text.replace(contraction, expanded)
    return text


def score_question(question: Dict[str, Any], student_answer: str) -> Dict[str, Any]:
    """
    Score a single question.

    Returns:
        dict with: is_correct, expected_answer, explanation, needs_ai_grading
    """
    q_type = question.get("type", "")
    correct_answer = question.get("correct_answer", "")
    student_norm = normalize_answer(student_answer)
    correct_norm = normalize_answer(correct_answer)

    is_correct = False
    needs_ai_grading = False

    if q_type == "multiple_choice":
        # Exact match on option
        is_correct = student_norm == correct_norm

    elif q_type == "true_false":
        # Normalize true/false variants
        true_variants = ["true", "t", "yes", "y", "1", "prawda", "tak"]
        false_variants = ["false", "f", "no", "n", "0", "falsz", "nie"]

        student_bool = student_norm in true_variants
        correct_bool = correct_norm in true_variants

        if student_norm in true_variants or student_norm in false_variants:
            is_correct = student_bool == correct_bool

    elif q_type == "fill_blank":
        # Exact match first
        is_correct = student_norm == correct_norm

        if not is_correct:
            # Try with punctuation removed
            student_clean = _normalize_punctuation(student_norm)
            correct_clean = _normalize_punctuation(correct_norm)
            is_correct = student_clean == correct_clean

        if not is_correct:
            # Strip articles for comparison (common Polish learner issue)
            student_stripped = _strip_articles(student_norm)
            correct_stripped = _strip_articles(correct_norm)
            if student_stripped == correct_stripped and len(correct_stripped) > 2:
                is_correct = True

    elif q_type in ("translate", "reorder"):
        # Try exact match first
        is_correct = student_norm == correct_norm

        if not is_correct:
            # Try with contractions expanded and punctuation normalized
            student_expanded = _normalize_contractions(_normalize_punctuation(student_norm))
            correct_expanded = _normalize_contractions(_normalize_punctuation(correct_norm))
            is_correct = student_expanded == correct_expanded

        if not is_correct:
            # Try article-stripped comparison
            student_stripped = _strip_articles(_normalize_contractions(_normalize_punctuation(student_norm)))
            correct_stripped = _strip_articles(_normalize_contractions(_normalize_punctuation(correct_norm)))
            is_correct = student_stripped == correct_stripped

        # Flag for AI re-evaluation if still incorrect
        if not is_correct:
            needs_ai_grading = True

    else:
        # Default: exact match
        is_correct = student_norm == correct_norm

    return {
        "is_correct": is_correct,
        "expected_answer": correct_answer,
        "needs_ai_grading": needs_ai_grading,
        "explanation": question.get("explanation", ""),
    }


async def ai_grade_open_answer(
    question_text: str,
    expected: str,
    student_answer: str,
    student_level: str,
) -> Dict[str, Any]:
    """Use AI to grade translation/reorder answers with partial credit."""
    from app.services.ai_client import ai_chat

    prompt = f"""Grade this English learner's answer. Student level: {student_level}

Question: {question_text}
Expected answer: {expected}
Student's answer: {student_answer}

Respond with JSON:
{{"is_correct": true/false, "partial_credit": 0.0-1.0, "feedback": "brief explanation"}}

Rules:
- Accept grammatically correct alternatives (contractions, synonyms)
- For A1 students, accept answers missing articles if the core meaning is correct
- partial_credit: 1.0 = perfect, 0.5 = meaning correct but grammar errors, 0.0 = wrong"""

    try:
        result = await ai_chat(
            messages=[
                {"role": "system", "content": "You are a fair English teacher grading A1-C2 students."},
                {"role": "user", "content": prompt},
            ],
            use_case="cheap",
            temperature=0.1,
            json_mode=True,
        )
        return json.loads(result)
    except Exception as e:
        logger.error(f"AI grading failed: {e}")
        return {"is_correct": False, "partial_credit": 0.0, "feedback": "Could not grade"}


async def score_quiz_attempt(
    db: aiosqlite.Connection,
    quiz_id: int,
    student_id: int,
    answers: Dict[str, str],
    session_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Score a quiz attempt and store results.

    Args:
        db: The database connection
        quiz_id: The quiz ID
        student_id: The student ID
        answers: Dict mapping question_id to student's answer
        session_id: Optional session ID

    Returns:
        dict with: attempt_id, score, total_questions, correct_count, items, weak_areas
    """
    try:
        # Get the quiz
        quiz = await ll.get_quiz(db, quiz_id)
        if not quiz:
            return {"success": False, "error": "Quiz not found"}

        # Verify student owns this quiz
        if quiz["student_id"] != student_id:
            return {"success": False, "error": "Not authorized to take this quiz"}

        quiz_json = quiz.get("quiz_json", {})
        if isinstance(quiz_json, str):
            quiz_json = json.loads(quiz_json)

        questions = quiz_json.get("questions", [])
        if not questions:
            return {"success": False, "error": "Quiz has no questions"}

        # Create the attempt
        attempt_id = await ll.create_quiz_attempt(
            db, quiz_id, student_id, session_id
        )

        # Score each question
        items = []
        correct_count = 0
        skill_results = {}  # skill_tag -> {correct: int, total: int}

        for q in questions:
            q_id = q.get("id", "")
            student_answer = answers.get(q_id, "")

            result = score_question(q, student_answer)

            skill_tag = normalize_skill_tag(q.get("skill_tag", "general"))

            # Track skill performance
            if skill_tag not in skill_results:
                skill_results[skill_tag] = {"correct": 0, "total": 0}
            skill_results[skill_tag]["total"] += 1

            if result["is_correct"]:
                correct_count += 1
                skill_results[skill_tag]["correct"] += 1

            # Store item result
            await ll.create_quiz_attempt_item(
                db,
                attempt_id=attempt_id,
                question_id=q_id,
                is_correct=result["is_correct"],
                student_answer=student_answer,
                expected_answer=result["expected_answer"],
                skill_tag=skill_tag,
                time_spent=None  # Could be added if frontend tracks time
            )

            items.append({
                "question_id": q_id,
                "question_text": q.get("text", ""),
                "question_type": q.get("type", ""),
                "student_answer": student_answer,
                "is_correct": result["is_correct"],
                "expected_answer": result["expected_answer"],
                "explanation": result["explanation"],
                "skill_tag": skill_tag,
            })

        # Calculate score
        total_questions = len(questions)
        score = correct_count / total_questions if total_questions > 0 else 0

        # Identify weak areas (skills with < 50% accuracy)
        weak_areas = []
        for skill, stats in skill_results.items():
            if stats["total"] > 0:
                accuracy = stats["correct"] / stats["total"]
                if accuracy < 0.5:
                    weak_areas.append({
                        "skill": skill,
                        "accuracy": round(accuracy * 100),
                        "correct": stats["correct"],
                        "total": stats["total"],
                    })

        # Build results JSON
        results_json = {
            "score": round(score * 100),
            "correct_count": correct_count,
            "total_questions": total_questions,
            "weak_areas": weak_areas,
            "skill_breakdown": {
                skill: {
                    "accuracy": round((stats["correct"] / stats["total"]) * 100) if stats["total"] > 0 else 0,
                    "correct": stats["correct"],
                    "total": stats["total"],
                }
                for skill, stats in skill_results.items()
            },
        }

        # Submit the attempt with score
        await ll.submit_quiz_attempt(db, attempt_id, score, results_json)

        logger.info(f"Quiz {quiz_id} scored for student {student_id}: {score*100:.0f}%")

        return {
            "success": True,
            "attempt_id": attempt_id,
            "score": round(score * 100),
            "correct_count": correct_count,
            "total_questions": total_questions,
            "items": items,
            "weak_areas": weak_areas,
            "skill_breakdown": results_json["skill_breakdown"],
        }

    except Exception as e:
        logger.error(f"Error scoring quiz {quiz_id}: {e}")
        return {"success": False, "error": "Service temporarily unavailable"}


async def get_attempt_summary(db: aiosqlite.Connection, attempt_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a summary of a quiz attempt for teacher review.

    Returns:
        dict with: score, weak_areas, mistakes, suggested_focus
    """
    attempt = await ll.get_quiz_attempt(db, attempt_id)
    if not attempt:
        return None

    items = await ll.get_quiz_attempt_items(db, attempt_id)

    # Get quiz details
    quiz = await ll.get_quiz(db, attempt["quiz_id"])
    quiz_json = quiz.get("quiz_json", {}) if quiz else {}
    if isinstance(quiz_json, str):
        quiz_json = json.loads(quiz_json)

    # Build question lookup
    questions = {q["id"]: q for q in quiz_json.get("questions", [])}

    # Find mistakes
    mistakes = []
    for item in items:
        if not item["is_correct"]:
            q = questions.get(item["question_id"], {})
            mistakes.append({
                "question": q.get("text", item["question_id"]),
                "student_answer": item["student_answer"],
                "correct_answer": item["expected_answer"],
                "skill_tag": item["skill_tag"],
            })

    # Get results
    results = attempt.get("results_json", {})
    if isinstance(results, str):
        results = json.loads(results)

    weak_areas = results.get("weak_areas", [])

    # Generate suggested focus points
    suggested_focus = []
    for weak in weak_areas:
        skill = weak.get("skill", "")
        accuracy = weak.get("accuracy", 0)
        suggested_focus.append(
            f"{skill.replace('_', ' ').title()}: {accuracy}% accuracy - needs review"
        )

    # If no weak areas but mistakes, suggest from mistakes
    if not suggested_focus and mistakes:
        skill_mistakes = {}
        for m in mistakes:
            skill = m.get("skill_tag", "general")
            if skill not in skill_mistakes:
                skill_mistakes[skill] = 0
            skill_mistakes[skill] += 1

        for skill, count in sorted(skill_mistakes.items(), key=lambda x: -x[1]):
            suggested_focus.append(
                f"{skill.replace('_', ' ').title()}: {count} mistake(s)"
            )

    return {
        "attempt_id": attempt_id,
        "quiz_id": attempt["quiz_id"],
        "student_id": attempt["student_id"],
        "score": attempt.get("score"),
        "score_percent": round((attempt.get("score") or 0) * 100),
        "submitted_at": attempt.get("submitted_at"),
        "total_questions": results.get("total_questions", len(items)),
        "correct_count": results.get("correct_count", sum(1 for i in items if i["is_correct"])),
        "weak_areas": weak_areas,
        "mistakes": mistakes,
        "suggested_focus": suggested_focus,
        "skill_breakdown": results.get("skill_breakdown", {}),
    }


async def get_student_quiz_for_session(db: aiosqlite.Connection, student_id: int, session_id: int) -> Optional[Dict[str, Any]]:
    """
    Get the quiz that a student should take for an upcoming session.
    This is typically the quiz from their PREVIOUS confirmed session.

    Returns the quiz if found and not yet completed.
    """
    # Find the most recent quiz for this student that hasn't been attempted
    cursor = await db.execute(
        """SELECT nq.*, s.scheduled_at
           FROM next_quizzes nq
           JOIN sessions s ON s.id = nq.session_id
           WHERE nq.student_id = ?
             AND NOT EXISTS (
                 SELECT 1 FROM quiz_attempts qa
                 WHERE qa.quiz_id = nq.id AND qa.student_id = ?
             )
           ORDER BY nq.created_at DESC
           LIMIT 1""",
        (student_id, student_id)
    )
    row = await cursor.fetchone()

    if not row:
        return None

    result = dict(row)

    # Parse quiz JSON
    if result.get("quiz_json"):
        if isinstance(result["quiz_json"], str):
            result["quiz_json"] = json.loads(result["quiz_json"])

    return result


async def get_pending_quizzes_for_student(db: aiosqlite.Connection, student_id: int) -> List[Dict[str, Any]]:
    """
    Get all pending (not yet attempted) quizzes for a student.
    """
    cursor = await db.execute(
        """SELECT nq.id, nq.session_id, nq.quiz_json, nq.created_at,
                  s.scheduled_at as session_date
           FROM next_quizzes nq
           LEFT JOIN sessions s ON s.id = nq.session_id
           WHERE nq.student_id = ?
             AND NOT EXISTS (
                 SELECT 1 FROM quiz_attempts qa
                 WHERE qa.quiz_id = nq.id AND qa.student_id = ?
             )
           ORDER BY nq.created_at DESC""",
        (student_id, student_id)
    )
    rows = await cursor.fetchall()

    quizzes = []
    for row in rows:
        quiz = dict(row)
        if quiz.get("quiz_json"):
            if isinstance(quiz["quiz_json"], str):
                quiz["quiz_json"] = json.loads(quiz["quiz_json"])
        quizzes.append({
            "id": quiz["id"],
            "session_id": quiz["session_id"],
            "title": quiz["quiz_json"].get("title", "Pre-Class Quiz"),
            "title_pl": quiz["quiz_json"].get("title_pl", "Quiz przed lekcją"),
            "question_count": len(quiz["quiz_json"].get("questions", [])),
            "estimated_time": quiz["quiz_json"].get("estimated_time_minutes", 5),
            "session_date": quiz.get("session_date"),
            "created_at": quiz["created_at"],
        })

    return quizzes
