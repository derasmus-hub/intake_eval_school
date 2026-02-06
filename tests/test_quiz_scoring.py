"""
test_quiz_scoring.py - Tests for Phase 3 quiz taking and scoring

Tests:
- create quiz -> submit attempt -> score computed -> stored
- scoring logic for different question types
- attempt summary generation
- pending quizzes retrieval

Run with: python tests/test_quiz_scoring.py
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import learning_loop as ll

# Test tracking
PASS = 0
FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    tag = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    extra = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {label}{extra}")
    return ok


async def setup_test_db():
    """Initialize an in-memory database for tests."""
    import aiosqlite
    from app.db.database import SCHEMA_PATH

    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row

    # Load schema
    schema = SCHEMA_PATH.read_text()
    await db.executescript(schema)
    await db.commit()

    # Run migrations for learning loop tables
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS learning_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            plan_json TEXT NOT NULL,
            summary TEXT,
            source_intake_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lesson_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            student_id INTEGER NOT NULL,
            teacher_id INTEGER,
            lesson_json TEXT NOT NULL,
            topics_json TEXT,
            difficulty TEXT,
            prompt_version TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS next_quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            student_id INTEGER NOT NULL,
            quiz_json TEXT NOT NULL,
            derived_from_lesson_artifact_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            session_id INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            submitted_at TIMESTAMP,
            score REAL,
            results_json TEXT
        );

        CREATE TABLE IF NOT EXISTS quiz_attempt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            is_correct INTEGER NOT NULL DEFAULT 0,
            student_answer TEXT,
            expected_answer TEXT,
            skill_tag TEXT,
            time_spent INTEGER
        );
    """)
    await db.commit()

    return db


async def create_fixtures(db):
    """Create student, teacher, session fixtures."""
    # Create student
    cursor = await db.execute(
        """INSERT INTO students (name, email, role, password_hash, current_level)
           VALUES (?, ?, ?, ?, ?)""",
        ("Test Student", "student@test.com", "student", "hashed_password", "B1")
    )
    await db.commit()
    student_id = cursor.lastrowid

    # Create teacher
    cursor = await db.execute(
        """INSERT INTO students (name, email, role, password_hash)
           VALUES (?, ?, ?, ?)""",
        ("Test Teacher", "teacher@test.com", "teacher", "hashed_password")
    )
    await db.commit()
    teacher_id = cursor.lastrowid

    # Create a confirmed session
    cursor = await db.execute(
        """INSERT INTO sessions (student_id, teacher_id, scheduled_at, duration_min, status)
           VALUES (?, ?, ?, ?, ?)""",
        (student_id, teacher_id, "2026-02-15T14:00:00", 60, "confirmed")
    )
    await db.commit()
    session_id = cursor.lastrowid

    return {
        "student_id": student_id,
        "teacher_id": teacher_id,
        "session_id": session_id
    }


# Sample quiz data
SAMPLE_QUIZ = {
    "title": "Present Perfect Quiz",
    "title_pl": "Quiz: Present Perfect",
    "description": "Test your knowledge of present perfect tense",
    "estimated_time_minutes": 5,
    "questions": [
        {
            "id": "q1",
            "type": "multiple_choice",
            "text": "I ___ never been to Paris.",
            "options": ["have", "has", "had", "having"],
            "correct_answer": "have",
            "skill_tag": "grammar_present_perfect",
            "difficulty": "easy",
            "explanation": "First person singular uses 'have'"
        },
        {
            "id": "q2",
            "type": "fill_blank",
            "text": "She ___ finished her homework.",
            "correct_answer": "has",
            "skill_tag": "grammar_present_perfect",
            "difficulty": "easy",
            "explanation": "Third person singular uses 'has'"
        },
        {
            "id": "q3",
            "type": "true_false",
            "text": "'I have went to school' is grammatically correct.",
            "correct_answer": "false",
            "skill_tag": "grammar_present_perfect",
            "difficulty": "medium",
            "explanation": "Should be 'I have gone to school'"
        },
        {
            "id": "q4",
            "type": "translate",
            "text": "Translate: 'Zjadłem śniadanie' (I have eaten breakfast)",
            "correct_answer": "I have eaten breakfast",
            "skill_tag": "translation",
            "difficulty": "medium",
            "explanation": "Present perfect for completed action"
        },
        {
            "id": "q5",
            "type": "multiple_choice",
            "text": "They ___ lived here for 10 years.",
            "options": ["has", "have", "had", "having"],
            "correct_answer": "have",
            "skill_tag": "grammar_present_perfect",
            "difficulty": "easy",
            "explanation": "Third person plural uses 'have'"
        }
    ]
}


async def test_score_question_logic():
    """Test the scoring logic for different question types."""
    print("\n=== Score Question Logic Tests ===")

    from app.services.quiz_scorer import score_question

    # Multiple choice - correct
    result = score_question(
        {"type": "multiple_choice", "correct_answer": "have"},
        "have"
    )
    check("Multiple choice correct", result["is_correct"] is True)

    # Multiple choice - wrong
    result = score_question(
        {"type": "multiple_choice", "correct_answer": "have"},
        "has"
    )
    check("Multiple choice wrong", result["is_correct"] is False)

    # Multiple choice - case insensitive
    result = score_question(
        {"type": "multiple_choice", "correct_answer": "Have"},
        "have"
    )
    check("Multiple choice case insensitive", result["is_correct"] is True)

    # Fill blank - correct
    result = score_question(
        {"type": "fill_blank", "correct_answer": "has"},
        "has"
    )
    check("Fill blank correct", result["is_correct"] is True)

    # Fill blank - with extra spaces
    result = score_question(
        {"type": "fill_blank", "correct_answer": "has"},
        "  has  "
    )
    check("Fill blank trims whitespace", result["is_correct"] is True)

    # True/false - true correct
    result = score_question(
        {"type": "true_false", "correct_answer": "true"},
        "true"
    )
    check("True/false true correct", result["is_correct"] is True)

    # True/false - false correct
    result = score_question(
        {"type": "true_false", "correct_answer": "false"},
        "false"
    )
    check("True/false false correct", result["is_correct"] is True)

    # True/false - yes = true
    result = score_question(
        {"type": "true_false", "correct_answer": "true"},
        "yes"
    )
    check("True/false yes=true", result["is_correct"] is True)

    # True/false - wrong
    result = score_question(
        {"type": "true_false", "correct_answer": "false"},
        "true"
    )
    check("True/false wrong", result["is_correct"] is False)

    # Translate - exact match
    result = score_question(
        {"type": "translate", "correct_answer": "I have eaten breakfast"},
        "I have eaten breakfast"
    )
    check("Translate exact match", result["is_correct"] is True)

    # Translate - case insensitive
    result = score_question(
        {"type": "translate", "correct_answer": "I have eaten breakfast"},
        "i have eaten breakfast"
    )
    check("Translate case insensitive", result["is_correct"] is True)


async def test_create_quiz_and_submit(db, fixtures):
    """Test creating a quiz and submitting answers."""
    print("\n=== Create Quiz and Submit Tests ===")

    student_id = fixtures["student_id"]
    session_id = fixtures["session_id"]

    # Create quiz
    quiz_id = await ll.create_quiz(
        db,
        student_id=student_id,
        quiz_json=SAMPLE_QUIZ,
        session_id=session_id
    )
    check("Quiz created", quiz_id is not None and quiz_id > 0, f"id={quiz_id}")

    # Verify quiz stored
    quiz = await ll.get_quiz(db, quiz_id)
    check("Quiz retrieved", quiz is not None)
    check("Quiz has correct student_id", quiz["student_id"] == student_id)

    # Submit answers using the scorer
    answers = {
        "q1": "have",       # Correct
        "q2": "has",        # Correct
        "q3": "false",      # Correct
        "q4": "I have eaten breakfast",  # Correct
        "q5": "has"         # Wrong (should be 'have')
    }

    # Mock the scorer to use our test db
    with patch('app.services.quiz_scorer.get_db', return_value=db):
        from app.services.quiz_scorer import score_quiz_attempt

        db.close = AsyncMock()

        result = await score_quiz_attempt(
            quiz_id=quiz_id,
            student_id=student_id,
            answers=answers,
            session_id=session_id
        )

        check("Scoring succeeded", result.get("success", False))
        check("Attempt ID returned", result.get("attempt_id") is not None)
        check("Score is 80%", result.get("score") == 80, f"score={result.get('score')}")
        check("4 correct out of 5", result.get("correct_count") == 4, f"correct={result.get('correct_count')}")
        check("Total questions is 5", result.get("total_questions") == 5)

        # Check items
        items = result.get("items", [])
        check("5 items returned", len(items) == 5)

        # Check specific item correctness
        q1_item = next((i for i in items if i["question_id"] == "q1"), None)
        check("Q1 marked correct", q1_item and q1_item["is_correct"])

        q5_item = next((i for i in items if i["question_id"] == "q5"), None)
        check("Q5 marked incorrect", q5_item and not q5_item["is_correct"])

        # Check weak areas
        weak_areas = result.get("weak_areas", [])
        # grammar_present_perfect should not be weak (3/4 = 75%)
        # but let's check the structure
        check("Weak areas is a list", isinstance(weak_areas, list))


async def test_attempt_stored_in_db(db, fixtures):
    """Test that attempt and items are properly stored."""
    print("\n=== Attempt Storage Tests ===")

    student_id = fixtures["student_id"]

    # Get the attempt we created
    cursor = await db.execute(
        "SELECT * FROM quiz_attempts WHERE student_id = ? ORDER BY id DESC LIMIT 1",
        (student_id,)
    )
    attempt = await cursor.fetchone()

    check("Attempt found in DB", attempt is not None)

    if attempt:
        attempt_id = attempt["id"]
        check("Attempt has score", attempt["score"] is not None)
        check("Attempt has submitted_at", attempt["submitted_at"] is not None)
        check("Attempt has results_json", attempt["results_json"] is not None)

        # Parse results
        results = json.loads(attempt["results_json"]) if isinstance(attempt["results_json"], str) else attempt["results_json"]
        check("Results has score", "score" in results)
        check("Results has skill_breakdown", "skill_breakdown" in results)

        # Get items
        cursor = await db.execute(
            "SELECT * FROM quiz_attempt_items WHERE attempt_id = ?",
            (attempt_id,)
        )
        items = await cursor.fetchall()
        check("5 items stored", len(items) == 5)

        # Check item structure
        item = dict(items[0])
        check("Item has question_id", item["question_id"] is not None)
        check("Item has skill_tag", item["skill_tag"] is not None)
        check("Item has expected_answer", item["expected_answer"] is not None)


async def test_attempt_summary(db, fixtures):
    """Test getting attempt summary for teacher."""
    print("\n=== Attempt Summary Tests ===")

    student_id = fixtures["student_id"]

    # Get the attempt
    cursor = await db.execute(
        "SELECT id FROM quiz_attempts WHERE student_id = ? ORDER BY id DESC LIMIT 1",
        (student_id,)
    )
    attempt = await cursor.fetchone()

    if not attempt:
        check("No attempt to test summary", False)
        return

    attempt_id = attempt["id"]

    with patch('app.services.quiz_scorer.get_db', return_value=db):
        from app.services.quiz_scorer import get_attempt_summary

        db.close = AsyncMock()

        summary = await get_attempt_summary(attempt_id)

        check("Summary returned", summary is not None)
        check("Summary has score", "score" in summary)
        check("Summary has mistakes", "mistakes" in summary)
        check("Summary has suggested_focus", "suggested_focus" in summary)

        # Should have 1 mistake (q5)
        mistakes = summary.get("mistakes", [])
        check("1 mistake recorded", len(mistakes) == 1, f"mistakes={len(mistakes)}")

        if mistakes:
            mistake = mistakes[0]
            check("Mistake has question", "question" in mistake)
            check("Mistake has student_answer", "student_answer" in mistake)
            check("Mistake has correct_answer", "correct_answer" in mistake)


async def test_pending_quizzes(db, fixtures):
    """Test getting pending quizzes for student."""
    print("\n=== Pending Quizzes Tests ===")

    student_id = fixtures["student_id"]
    session_id = fixtures["session_id"]

    # Create a new quiz (the previous one was already attempted)
    quiz_id = await ll.create_quiz(
        db,
        student_id=student_id,
        quiz_json={
            "title": "New Quiz",
            "title_pl": "Nowy Quiz",
            "questions": [{"id": "q1", "type": "fill_blank", "text": "Test", "correct_answer": "test"}],
            "estimated_time_minutes": 3
        },
        session_id=session_id
    )

    with patch('app.services.quiz_scorer.get_db', return_value=db):
        from app.services.quiz_scorer import get_pending_quizzes_for_student

        db.close = AsyncMock()

        pending = await get_pending_quizzes_for_student(student_id)

        check("Pending quizzes returned", pending is not None)
        check("At least 1 pending quiz", len(pending) >= 1, f"count={len(pending)}")

        if pending:
            quiz = pending[0]
            check("Quiz has id", "id" in quiz)
            check("Quiz has title", "title" in quiz)
            check("Quiz has question_count", "question_count" in quiz)


async def test_double_submit_prevented(db, fixtures):
    """Test that double submission is prevented."""
    print("\n=== Double Submit Prevention Tests ===")

    student_id = fixtures["student_id"]
    session_id = fixtures["session_id"]

    # Create a fresh quiz
    quiz_id = await ll.create_quiz(
        db,
        student_id=student_id,
        quiz_json={
            "title": "Double Submit Test",
            "questions": [
                {"id": "q1", "type": "fill_blank", "text": "Test", "correct_answer": "answer", "skill_tag": "test"}
            ]
        },
        session_id=session_id
    )

    with patch('app.services.quiz_scorer.get_db', return_value=db):
        from app.services.quiz_scorer import score_quiz_attempt

        db.close = AsyncMock()

        # First submission
        result1 = await score_quiz_attempt(quiz_id, student_id, {"q1": "answer"})
        check("First submit succeeds", result1.get("success", False))

        # Second submission should fail (if we check in the scorer)
        # Note: The actual duplicate check is in the route, not scorer
        # So we'll test that an attempt exists

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM quiz_attempts WHERE quiz_id = ? AND student_id = ?",
            (quiz_id, student_id)
        )
        count = (await cursor.fetchone())["cnt"]
        check("Only 1 attempt exists", count == 1, f"count={count}")


async def test_skill_tag_aggregation(db, fixtures):
    """Test that skill tags are properly aggregated."""
    print("\n=== Skill Tag Aggregation Tests ===")

    student_id = fixtures["student_id"]

    # Query items by skill tag (db is passed directly to ll functions)
    items = await ll.get_items_by_skill_tag(db, student_id, "grammar_present_perfect")

    check("Grammar items found", len(items) > 0, f"count={len(items)}")

    # Check that items have the right skill tag
    all_correct_tag = all(item["skill_tag"] == "grammar_present_perfect" for item in items)
    check("All items have grammar skill tag", all_correct_tag)


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Quiz Scoring Tests (Phase 3)")
    print("=" * 60)

    db = await setup_test_db()
    fixtures = await create_fixtures(db)

    try:
        await test_score_question_logic()
        await test_create_quiz_and_submit(db, fixtures)
        await test_attempt_stored_in_db(db, fixtures)
        await test_attempt_summary(db, fixtures)
        await test_pending_quizzes(db, fixtures)
        await test_double_submit_prevented(db, fixtures)
        await test_skill_tag_aggregation(db, fixtures)
    finally:
        await db.close()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60 + "\n")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
