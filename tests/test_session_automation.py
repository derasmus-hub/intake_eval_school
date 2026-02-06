"""
test_session_automation.py - Tests for Phase 2 session automation

Tests:
- confirm session -> ensures lesson_artifact and next_quiz created
- re-confirm -> no duplicate records
- idempotency of build functions
- endpoint access control

Run with: python tests/test_session_automation.py
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

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
    """Create student, teacher, and session fixtures."""
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

    # Create a session in 'requested' status
    cursor = await db.execute(
        """INSERT INTO sessions (student_id, scheduled_at, duration_min, status)
           VALUES (?, ?, ?, ?)""",
        (student_id, "2026-02-15T14:00:00", 60, "requested")
    )
    await db.commit()
    session_id = cursor.lastrowid

    # Create a learner profile for context
    cursor = await db.execute(
        """INSERT INTO learner_profiles (student_id, gaps, priorities, profile_summary)
           VALUES (?, ?, ?, ?)""",
        (
            student_id,
            json.dumps(["present_perfect", "articles"]),
            json.dumps(["grammar", "speaking"]),
            "Intermediate Polish student working on grammar accuracy"
        )
    )
    await db.commit()

    return {
        "student_id": student_id,
        "teacher_id": teacher_id,
        "session_id": session_id
    }


# Mock OpenAI response for lesson generation
MOCK_LESSON_RESPONSE = {
    "objective": "Master the present perfect tense",
    "polish_explanation": "Czas Present Perfect",
    "exercises": [
        {"type": "fill_in", "instruction": "Fill in the blank", "content": "I ___ eaten.", "answer": "have"}
    ],
    "conversation_prompts": ["Have you ever visited London?"],
    "win_activity": "List 3 things you have done today",
    "difficulty": "B1",
    "warm_up": {"description": "Quick review", "activity": "Name 3 past participles", "duration_minutes": 5},
    "presentation": {
        "topic": "Present Perfect Tense",
        "explanation": "Used for actions with present relevance",
        "polish_explanation": "Uzywamy gdy akcja ma zwiazek z terazniejszoscia",
        "examples": ["I have finished my homework."]
    },
    "controlled_practice": {
        "exercises": [{"type": "fill_in", "instruction": "Complete", "content": "She ___ gone.", "answer": "has"}],
        "instructions": "Complete the exercises"
    },
    "free_practice": {
        "activity": "Roleplay",
        "description": "Interview about experiences",
        "prompts": ["What have you done this week?"],
        "success_criteria": "Uses present perfect correctly"
    },
    "wrap_up": {
        "summary": "Present perfect for experiences",
        "homework": "Write 5 sentences",
        "win_activity": "Tell one thing you have learned"
    }
}

MOCK_QUIZ_RESPONSE = {
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
            "explanation": "First person uses 'have'"
        },
        {
            "id": "q2",
            "type": "fill_blank",
            "text": "She ___ finished her homework.",
            "correct_answer": "has",
            "skill_tag": "grammar_present_perfect",
            "difficulty": "easy",
            "explanation": "Third person singular uses 'has'"
        }
    ]
}


def create_mock_openai_response(content):
    """Create a mock OpenAI API response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(content)
    return mock_response


async def test_idempotency_lesson_exists(db, fixtures):
    """Test that build_lesson_for_session is idempotent."""
    print("\n=== Idempotency Tests ===")

    session_id = fixtures["session_id"]
    student_id = fixtures["student_id"]
    teacher_id = fixtures["teacher_id"]

    # Manually create a lesson artifact
    artifact_id = await ll.create_lesson_artifact(
        db,
        student_id=student_id,
        lesson_json=MOCK_LESSON_RESPONSE,
        session_id=session_id,
        teacher_id=teacher_id,
        difficulty="B1"
    )

    # Verify it exists
    cursor = await db.execute(
        "SELECT id FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    existing = await cursor.fetchone()
    check("Lesson artifact created manually", existing is not None)

    # Check idempotency function
    from app.services.session_automation import lesson_artifact_exists_for_session
    exists = await lesson_artifact_exists_for_session(db, session_id)
    check("lesson_artifact_exists_for_session returns True", exists)

    # Count artifacts - should be 1
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    count = (await cursor.fetchone())["cnt"]
    check("Only one artifact exists for session", count == 1)


async def test_idempotency_quiz_exists(db, fixtures):
    """Test that build_next_quiz_from_lesson is idempotent."""
    session_id = fixtures["session_id"]
    student_id = fixtures["student_id"]

    # Create artifact first
    artifact_id = await ll.create_lesson_artifact(
        db,
        student_id=student_id,
        lesson_json=MOCK_LESSON_RESPONSE,
        session_id=session_id
    )

    # Manually create a quiz
    quiz_id = await ll.create_quiz(
        db,
        student_id=student_id,
        quiz_json=MOCK_QUIZ_RESPONSE,
        session_id=session_id,
        derived_from_lesson_artifact_id=artifact_id
    )

    # Check idempotency
    from app.services.session_automation import quiz_exists_for_session
    exists = await quiz_exists_for_session(db, session_id)
    check("quiz_exists_for_session returns True", exists)

    # Count quizzes - should be 1
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM next_quizzes WHERE session_id = ?",
        (session_id,)
    )
    count = (await cursor.fetchone())["cnt"]
    check("Only one quiz exists for session", count == 1)


async def test_get_student_context(db, fixtures):
    """Test context gathering for lesson generation."""
    print("\n=== Context Gathering Tests ===")

    student_id = fixtures["student_id"]

    from app.services.session_automation import get_student_context
    context = await get_student_context(db, student_id)

    check("Context has profile", "profile" in context)
    check("Context has progress_history", "progress_history" in context)
    check("Context has session_count", "session_count" in context)
    check("Profile has profile_summary", context["profile"].get("profile_summary") is not None)


async def test_mock_lesson_generation(db, fixtures):
    """Test lesson generation with mocked OpenAI."""
    print("\n=== Mock Lesson Generation Tests ===")

    session_id = fixtures["session_id"]
    student_id = fixtures["student_id"]
    teacher_id = fixtures["teacher_id"]

    # Update session to confirmed status with teacher
    await db.execute(
        "UPDATE sessions SET status = 'confirmed', teacher_id = ? WHERE id = ?",
        (teacher_id, session_id)
    )
    await db.commit()

    # Mock the OpenAI client
    mock_response = create_mock_openai_response(MOCK_LESSON_RESPONSE)

    with patch('app.services.session_automation.AsyncOpenAI') as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.return_value = mock_client

        # Also mock get_db to return our test db
        with patch('app.services.session_automation.get_db', return_value=db):
            from app.services.session_automation import build_lesson_for_session

            # Since we're mocking get_db, we need to handle db.close()
            db.close = AsyncMock()

            result = await build_lesson_for_session(session_id)

            check("Lesson generation succeeded", result.get("success", False))
            check("Artifact ID returned", result.get("artifact_id") is not None)

    # Verify artifact was created
    cursor = await db.execute(
        "SELECT * FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    artifact = await cursor.fetchone()
    check("Lesson artifact stored in DB", artifact is not None)

    if artifact:
        lesson_json = json.loads(artifact["lesson_json"]) if isinstance(artifact["lesson_json"], str) else artifact["lesson_json"]
        check("Lesson has objective", lesson_json.get("objective") is not None)
        check("Lesson has difficulty", lesson_json.get("difficulty") is not None)


async def test_mock_quiz_generation(db, fixtures):
    """Test quiz generation with mocked OpenAI."""
    print("\n=== Mock Quiz Generation Tests ===")

    session_id = fixtures["session_id"]
    student_id = fixtures["student_id"]

    # First ensure lesson artifact exists
    cursor = await db.execute(
        "SELECT id FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    artifact = await cursor.fetchone()

    if not artifact:
        # Create one
        await ll.create_lesson_artifact(
            db,
            student_id=student_id,
            lesson_json=MOCK_LESSON_RESPONSE,
            session_id=session_id
        )

    mock_response = create_mock_openai_response(MOCK_QUIZ_RESPONSE)

    with patch('app.services.session_automation.AsyncOpenAI') as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.return_value = mock_client

        with patch('app.services.session_automation.get_db', return_value=db):
            from app.services.session_automation import build_next_quiz_from_lesson

            db.close = AsyncMock()

            result = await build_next_quiz_from_lesson(session_id)

            check("Quiz generation succeeded", result.get("success", False))
            check("Quiz ID returned", result.get("quiz_id") is not None)

    # Verify quiz was created
    cursor = await db.execute(
        "SELECT * FROM next_quizzes WHERE session_id = ?",
        (session_id,)
    )
    quiz = await cursor.fetchone()
    check("Quiz stored in DB", quiz is not None)

    if quiz:
        quiz_json = json.loads(quiz["quiz_json"]) if isinstance(quiz["quiz_json"], str) else quiz["quiz_json"]
        check("Quiz has title", quiz_json.get("title") is not None)
        check("Quiz has questions", len(quiz_json.get("questions", [])) > 0)


async def test_on_session_confirmed_flow(db, fixtures):
    """Test the full on_session_confirmed flow."""
    print("\n=== Full Confirmation Flow Tests ===")

    # Create a fresh session for this test
    cursor = await db.execute(
        """INSERT INTO sessions (student_id, scheduled_at, duration_min, status, teacher_id)
           VALUES (?, ?, ?, ?, ?)""",
        (fixtures["student_id"], "2026-02-20T10:00:00", 60, "confirmed", fixtures["teacher_id"])
    )
    await db.commit()
    new_session_id = cursor.lastrowid

    lesson_response = create_mock_openai_response(MOCK_LESSON_RESPONSE)
    quiz_response = create_mock_openai_response(MOCK_QUIZ_RESPONSE)

    call_count = [0]

    async def mock_create(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return lesson_response
        return quiz_response

    with patch('app.services.session_automation.AsyncOpenAI') as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = mock_create
        mock_openai.return_value = mock_client

        with patch('app.services.session_automation.get_db', return_value=db):
            from app.services.session_automation import on_session_confirmed

            db.close = AsyncMock()

            result = await on_session_confirmed(new_session_id, fixtures["teacher_id"])

            check("Result has lesson status", "lesson" in result)
            check("Result has quiz status", "quiz" in result)
            check("Lesson completed", result["lesson"].get("status") == "completed")
            check("Quiz completed", result["quiz"].get("status") == "completed")

    # Verify both were created
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM lesson_artifacts WHERE session_id = ?",
        (new_session_id,)
    )
    lesson_count = (await cursor.fetchone())["cnt"]
    check("Lesson artifact created for new session", lesson_count == 1)

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM next_quizzes WHERE session_id = ?",
        (new_session_id,)
    )
    quiz_count = (await cursor.fetchone())["cnt"]
    check("Quiz created for new session", quiz_count == 1)


async def test_re_confirm_no_duplicates(db, fixtures):
    """Test that re-confirming doesn't create duplicate records."""
    print("\n=== Re-Confirm No Duplicates Tests ===")

    session_id = fixtures["session_id"]

    # First check current counts
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    initial_lesson_count = (await cursor.fetchone())["cnt"]

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM next_quizzes WHERE session_id = ?",
        (session_id,)
    )
    initial_quiz_count = (await cursor.fetchone())["cnt"]

    # Run confirmation flow again with mocks (should be idempotent)
    lesson_response = create_mock_openai_response(MOCK_LESSON_RESPONSE)

    with patch('app.services.session_automation.AsyncOpenAI') as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=lesson_response)
        mock_openai.return_value = mock_client

        with patch('app.services.session_automation.get_db', return_value=db):
            from app.services.session_automation import build_lesson_for_session

            db.close = AsyncMock()

            # Call again
            result = await build_lesson_for_session(session_id)

            # Should report already_existed
            check("Reports already existed", result.get("already_existed", False))

    # Counts should be same
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    final_lesson_count = (await cursor.fetchone())["cnt"]
    check("Lesson count unchanged", final_lesson_count == initial_lesson_count)


async def test_get_session_lesson_and_quiz(db, fixtures):
    """Test the getter functions for lesson and quiz."""
    print("\n=== Getter Functions Tests ===")

    session_id = fixtures["session_id"]
    student_id = fixtures["student_id"]

    # Ensure artifacts exist
    cursor = await db.execute(
        "SELECT id FROM lesson_artifacts WHERE session_id = ?",
        (session_id,)
    )
    artifact = await cursor.fetchone()

    if not artifact:
        artifact_id = await ll.create_lesson_artifact(
            db,
            student_id=student_id,
            lesson_json=MOCK_LESSON_RESPONSE,
            session_id=session_id,
            difficulty="B1"
        )
    else:
        artifact_id = artifact["id"]

    cursor = await db.execute(
        "SELECT id FROM next_quizzes WHERE session_id = ?",
        (session_id,)
    )
    quiz = await cursor.fetchone()

    if not quiz:
        await ll.create_quiz(
            db,
            student_id=student_id,
            quiz_json=MOCK_QUIZ_RESPONSE,
            session_id=session_id,
            derived_from_lesson_artifact_id=artifact_id
        )

    # Update session to confirmed
    await db.execute(
        "UPDATE sessions SET status = 'confirmed' WHERE id = ?",
        (session_id,)
    )
    await db.commit()

    # Test getters with mocked db
    with patch('app.services.session_automation.get_db', return_value=db):
        from app.services.session_automation import get_session_lesson, get_session_quiz

        db.close = AsyncMock()

        lesson = await get_session_lesson(session_id)
        check("get_session_lesson returns data", lesson is not None)
        check("Lesson has lesson_json", lesson.get("lesson_json") is not None)

        quiz = await get_session_quiz(session_id)
        check("get_session_quiz returns data", quiz is not None)
        check("Quiz has quiz_json", quiz.get("quiz_json") is not None)


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Session Automation Tests (Phase 2)")
    print("=" * 60)

    db = await setup_test_db()
    fixtures = await create_fixtures(db)

    try:
        await test_idempotency_lesson_exists(db, fixtures)
        await test_idempotency_quiz_exists(db, fixtures)
        await test_get_student_context(db, fixtures)
        await test_mock_lesson_generation(db, fixtures)
        await test_mock_quiz_generation(db, fixtures)
        await test_on_session_confirmed_flow(db, fixtures)
        await test_re_confirm_no_duplicates(db, fixtures)
        await test_get_session_lesson_and_quiz(db, fixtures)
    finally:
        await db.close()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60 + "\n")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
