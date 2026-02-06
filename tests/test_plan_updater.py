"""
test_plan_updater.py - Tests for the Learning Plan Update Service

Tests:
- submit quiz -> new plan version created
- plan versions increment, older preserved
- gather_quiz_analysis aggregates skill data correctly
- gather_teacher_notes retrieves recent notes
- on_quiz_submitted hook triggers plan update

Run with: python tests/test_plan_updater.py
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import learning_loop as ll
from app.config import settings

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

    # Use in-memory database
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (source_intake_id) REFERENCES assessments(id)
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (teacher_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS next_quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            student_id INTEGER NOT NULL,
            quiz_json TEXT NOT NULL,
            derived_from_lesson_artifact_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (derived_from_lesson_artifact_id) REFERENCES lesson_artifacts(id)
        );

        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            session_id INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            submitted_at TIMESTAMP,
            score REAL,
            results_json TEXT,
            FOREIGN KEY (quiz_id) REFERENCES next_quizzes(id),
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS quiz_attempt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id INTEGER NOT NULL,
            question_id TEXT NOT NULL,
            is_correct INTEGER NOT NULL DEFAULT 0,
            student_answer TEXT,
            expected_answer TEXT,
            skill_tag TEXT,
            time_spent INTEGER,
            FOREIGN KEY (attempt_id) REFERENCES quiz_attempts(id)
        );
    """)
    await db.commit()

    return db


async def create_fixtures(db):
    """Create student, teacher, session, and quiz fixtures."""
    # Create student
    cursor = await db.execute(
        """INSERT INTO students (name, email, role, password_hash, current_level, goals)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("Test Student", "student@test.com", "student", "hashed_password", "B1",
         json.dumps(["Improve speaking", "Business English"]))
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

    # Create session with teacher notes
    cursor = await db.execute(
        """INSERT INTO sessions (student_id, teacher_id, scheduled_at, duration_min, status,
                                 teacher_notes, session_summary, homework)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (student_id, teacher_id, "2026-02-05T14:00:00", 60, "completed",
         "Student struggles with article usage. Good progress on vocabulary.",
         "Covered present perfect tense. Needs more practice with irregular verbs.",
         "Complete exercises on page 42")
    )
    await db.commit()
    session_id = cursor.lastrowid

    # Create quiz
    quiz_data = {
        "title": "Grammar Quiz",
        "questions": [
            {"id": "q1", "type": "fill_blank", "text": "I ___ to the store.", "correct_answer": "went", "skill_tag": "grammar_past_simple"},
            {"id": "q2", "type": "multiple_choice", "text": "Which is correct?", "correct_answer": "A", "skill_tag": "grammar_articles"},
            {"id": "q3", "type": "fill_blank", "text": "She ___ been here.", "correct_answer": "has", "skill_tag": "grammar_present_perfect"},
        ]
    }
    cursor = await db.execute(
        """INSERT INTO next_quizzes (student_id, session_id, quiz_json)
           VALUES (?, ?, ?)""",
        (student_id, session_id, json.dumps(quiz_data))
    )
    await db.commit()
    quiz_id = cursor.lastrowid

    return {
        "student_id": student_id,
        "teacher_id": teacher_id,
        "session_id": session_id,
        "quiz_id": quiz_id
    }


async def create_quiz_attempt_with_items(db, quiz_id, student_id, session_id, items_data, score):
    """Helper to create a quiz attempt with items."""
    cursor = await db.execute(
        """INSERT INTO quiz_attempts (quiz_id, student_id, session_id, submitted_at, score, results_json)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)""",
        (quiz_id, student_id, session_id, score,
         json.dumps({"skill_breakdown": {}, "correct_count": sum(1 for i in items_data if i["is_correct"]), "total_questions": len(items_data)}))
    )
    await db.commit()
    attempt_id = cursor.lastrowid

    for item in items_data:
        await db.execute(
            """INSERT INTO quiz_attempt_items (attempt_id, question_id, is_correct, student_answer, expected_answer, skill_tag)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (attempt_id, item["question_id"], 1 if item["is_correct"] else 0,
             item.get("student_answer", ""), item.get("expected_answer", ""), item.get("skill_tag", ""))
        )
    await db.commit()

    return attempt_id


async def test_gather_quiz_analysis(db, fixtures):
    """Test gather_quiz_analysis aggregates quiz data correctly."""
    print("\n=== gather_quiz_analysis Tests ===")

    from app.services.plan_updater import gather_quiz_analysis

    student_id = fixtures["student_id"]
    quiz_id = fixtures["quiz_id"]
    session_id = fixtures["session_id"]

    # Create quiz attempt with mixed results
    items = [
        {"question_id": "q1", "is_correct": True, "student_answer": "went", "expected_answer": "went", "skill_tag": "grammar_past_simple"},
        {"question_id": "q2", "is_correct": False, "student_answer": "B", "expected_answer": "A", "skill_tag": "grammar_articles"},
        {"question_id": "q3", "is_correct": True, "student_answer": "has", "expected_answer": "has", "skill_tag": "grammar_present_perfect"},
    ]

    # Store results_json with skill_breakdown for proper aggregation
    results_json = {
        "skill_breakdown": {
            "grammar_past_simple": {"correct": 1, "total": 1},
            "grammar_articles": {"correct": 0, "total": 1},
            "grammar_present_perfect": {"correct": 1, "total": 1},
        },
        "correct_count": 2,
        "total_questions": 3
    }

    cursor = await db.execute(
        """INSERT INTO quiz_attempts (quiz_id, student_id, session_id, submitted_at, score, results_json)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)""",
        (quiz_id, student_id, session_id, 0.67, json.dumps(results_json))
    )
    await db.commit()
    attempt_id = cursor.lastrowid

    for item in items:
        await db.execute(
            """INSERT INTO quiz_attempt_items (attempt_id, question_id, is_correct, student_answer, expected_answer, skill_tag)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (attempt_id, item["question_id"], 1 if item["is_correct"] else 0,
             item.get("student_answer", ""), item.get("expected_answer", ""), item.get("skill_tag", ""))
        )
    await db.commit()

    # Test analysis
    analysis = await gather_quiz_analysis(db, student_id)

    check("Analysis has quiz count", analysis["quiz_count"] == 1)
    check("Analysis has average score", analysis["average_score"] == 67)
    check("Skill breakdown has grammar_articles", "grammar_articles" in analysis["skill_breakdown"])
    check("Articles marked as weak (0%)", analysis["skill_breakdown"]["grammar_articles"]["accuracy"] == 0)
    check("Past simple marked as strong (100%)", analysis["skill_breakdown"]["grammar_past_simple"]["accuracy"] == 100)
    check("Recent mistakes captured", len(analysis["recent_mistakes"]) == 1)  # One wrong answer


async def test_gather_teacher_notes(db, fixtures):
    """Test gather_teacher_notes retrieves session notes."""
    print("\n=== gather_teacher_notes Tests ===")

    from app.services.plan_updater import gather_teacher_notes

    student_id = fixtures["student_id"]

    notes = await gather_teacher_notes(db, student_id)

    check("Notes retrieved", len(notes) >= 1)
    check("Notes contain teacher notes", notes[0].get("notes") is not None)
    check("Notes contain session summary", notes[0].get("summary") is not None)
    check("Notes contain homework", notes[0].get("homework") is not None)


async def test_plan_version_increment(db, fixtures):
    """Test that plan versions increment correctly."""
    print("\n=== Plan Version Increment Tests ===")

    student_id = fixtures["student_id"]

    # Create first plan
    plan1_id = await ll.create_learning_plan(
        db, student_id,
        plan_json={"summary": "Initial plan", "goals_next_2_weeks": ["Learn basics"]},
        summary="Initial learning plan"
    )
    plan1 = await ll.get_learning_plan(db, plan1_id)
    check("First plan has version 1", plan1["version"] == 1)

    # Create second plan
    plan2_id = await ll.create_learning_plan(
        db, student_id,
        plan_json={"summary": "Updated plan", "goals_next_2_weeks": ["Advanced topics"]},
        summary="Updated after quiz"
    )
    plan2 = await ll.get_learning_plan(db, plan2_id)
    check("Second plan has version 2", plan2["version"] == 2)

    # Create third plan
    plan3_id = await ll.create_learning_plan(
        db, student_id,
        plan_json={"summary": "Third plan"},
        summary="Third update"
    )
    plan3 = await ll.get_learning_plan(db, plan3_id)
    check("Third plan has version 3", plan3["version"] == 3)

    # Verify all versions preserved
    all_plans = await ll.get_learning_plans_by_student(db, student_id)
    check("All 3 versions preserved", len(all_plans) == 3)

    # Verify latest plan is version 3
    latest = await ll.get_latest_learning_plan(db, student_id)
    check("Latest plan is version 3", latest["version"] == 3)

    # Verify oldest plan still accessible
    oldest = await ll.get_learning_plan(db, plan1_id)
    check("Version 1 still accessible", oldest is not None and oldest["version"] == 1)


class NonClosingDBWrapper:
    """Wrapper that prevents close() from actually closing the DB."""
    def __init__(self, db):
        self._db = db

    async def execute(self, *args, **kwargs):
        return await self._db.execute(*args, **kwargs)

    async def executemany(self, *args, **kwargs):
        return await self._db.executemany(*args, **kwargs)

    async def commit(self):
        return await self._db.commit()

    async def close(self):
        # Don't actually close - let the test harness handle cleanup
        pass

    @property
    def row_factory(self):
        return self._db.row_factory


async def test_update_learning_plan_creates_version(db, fixtures):
    """Test that update_learning_plan creates a new version."""
    print("\n=== update_learning_plan Creates Version Tests ===")

    from app.services.plan_updater import update_learning_plan

    student_id = fixtures["student_id"]
    quiz_id = fixtures["quiz_id"]
    session_id = fixtures["session_id"]

    # Create initial plan
    await ll.create_learning_plan(
        db, student_id,
        plan_json={"summary": "Initial plan"},
        summary="Initial learning plan"
    )

    # Create a quiz attempt to give context
    items = [
        {"question_id": "q1", "is_correct": False, "skill_tag": "grammar_articles"},
        {"question_id": "q2", "is_correct": True, "skill_tag": "grammar_past_simple"},
    ]
    results_json = {
        "skill_breakdown": {
            "grammar_articles": {"correct": 0, "total": 1},
            "grammar_past_simple": {"correct": 1, "total": 1},
        }
    }
    cursor = await db.execute(
        """INSERT INTO quiz_attempts (quiz_id, student_id, session_id, submitted_at, score, results_json)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)""",
        (quiz_id, student_id, session_id, 0.5, json.dumps(results_json))
    )
    await db.commit()
    attempt_id = cursor.lastrowid

    for item in items:
        await db.execute(
            """INSERT INTO quiz_attempt_items (attempt_id, question_id, is_correct, student_answer, expected_answer, skill_tag)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (attempt_id, item["question_id"], 1 if item["is_correct"] else 0, "", "", item.get("skill_tag", ""))
        )
    await db.commit()

    # Mock OpenAI response
    mock_plan_response = {
        "goals_next_2_weeks": ["Improve article usage", "Practice past simple"],
        "top_weaknesses": [{"skill_area": "grammar_articles", "accuracy_observed": 0, "error_pattern": "Missing articles", "priority": "high"}],
        "recommended_drills": [{"type": "fill_blank", "target_skill": "grammar_articles", "description": "Article exercises", "frequency": "daily"}],
        "vocabulary_focus": {"domains": ["everyday"], "target_words": 20, "selection_rationale": "Build foundation"},
        "grammar_focus": {"primary_topic": "articles", "secondary_topics": ["past_simple"], "polish_interference_notes": "Polish lacks articles"},
        "difficulty_adjustment": {"current_level": "B1", "recommendation": "maintain", "rationale": "Steady progress"},
        "teacher_guidance": {"session_focus": "Articles", "avoid_topics": [], "encouragement_points": ["Good vocabulary"]},
        "summary": "Focus on article usage over next 2 weeks."
    }

    # Use non-closing wrapper to prevent update_learning_plan from closing the test db
    wrapped_db = NonClosingDBWrapper(db)

    # We need to mock the OpenAI client and get_db
    async def mock_get_db():
        return wrapped_db

    with patch('app.services.plan_updater.get_db', mock_get_db), \
         patch('app.services.plan_updater.AsyncOpenAI') as mock_openai:

        # Mock OpenAI response
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = json.dumps(mock_plan_response)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_openai.return_value = mock_client

        # Call update_learning_plan
        result = await update_learning_plan(student_id=student_id, trigger="quiz_submission")

        check("Update returns success", result.get("success") is True)
        check("Update returns plan_id", result.get("plan_id") is not None)
        check("Update returns summary", result.get("summary") is not None)

    # Verify new version was created
    all_plans = await ll.get_learning_plans_by_student(db, student_id)
    check("Two plan versions exist", len(all_plans) == 2)

    latest = await ll.get_latest_learning_plan(db, student_id)
    check("Latest plan is version 2", latest["version"] == 2)


async def test_on_quiz_submitted_triggers_update(db, fixtures):
    """Test that on_quiz_submitted hook triggers plan update."""
    print("\n=== on_quiz_submitted Hook Tests ===")

    from app.services.plan_updater import on_quiz_submitted

    student_id = fixtures["student_id"]
    quiz_id = fixtures["quiz_id"]

    # Create initial plan
    await ll.create_learning_plan(
        db, student_id,
        plan_json={"summary": "Initial plan"},
        summary="Initial learning plan"
    )

    # Create a quiz attempt
    cursor = await db.execute(
        """INSERT INTO quiz_attempts (quiz_id, student_id, submitted_at, score, results_json)
           VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)""",
        (quiz_id, student_id, 0.8, json.dumps({"skill_breakdown": {}}))
    )
    await db.commit()
    attempt_id = cursor.lastrowid

    # Mock the update
    mock_plan_response = {
        "goals_next_2_weeks": ["Continue progress"],
        "top_weaknesses": [],
        "recommended_drills": [],
        "vocabulary_focus": {"domains": [], "target_words": 20, "selection_rationale": "General vocabulary"},
        "grammar_focus": {"primary_topic": "review", "secondary_topics": [], "polish_interference_notes": ""},
        "difficulty_adjustment": {"current_level": "B1", "recommendation": "maintain", "rationale": "Good progress"},
        "teacher_guidance": {"session_focus": "Review", "avoid_topics": [], "encouragement_points": ["Doing well"]},
        "summary": "Good progress, continue current approach."
    }

    # Use non-closing wrapper
    wrapped_db = NonClosingDBWrapper(db)

    async def mock_get_db():
        return wrapped_db

    with patch('app.services.plan_updater.get_db', mock_get_db), \
         patch('app.services.plan_updater.AsyncOpenAI') as mock_openai:

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = json.dumps(mock_plan_response)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_openai.return_value = mock_client

        result = await on_quiz_submitted(
            student_id=student_id,
            quiz_id=quiz_id,
            attempt_id=attempt_id
        )

        check("Hook returns success", result.get("success") is True)
        check("Hook returns plan_id", result.get("plan_id") is not None)

    # Verify plan was updated
    all_plans = await ll.get_learning_plans_by_student(db, student_id)
    check("Two plan versions exist after hook", len(all_plans) == 2)


async def test_get_student_learning_plan(db, fixtures):
    """Test get_student_learning_plan returns latest plan with version info."""
    print("\n=== get_student_learning_plan Tests ===")

    from app.services.plan_updater import get_student_learning_plan

    student_id = fixtures["student_id"]

    # Use non-closing wrapper
    wrapped_db = NonClosingDBWrapper(db)

    async def mock_get_db():
        return wrapped_db

    # No plan initially
    with patch('app.services.plan_updater.get_db', mock_get_db):
        plan = await get_student_learning_plan(student_id)
        check("Returns None when no plan exists", plan is None)

    # Create plans
    await ll.create_learning_plan(db, student_id, {"goals": ["v1"]}, summary="Version 1")
    await ll.create_learning_plan(db, student_id, {"goals": ["v2"]}, summary="Version 2")

    with patch('app.services.plan_updater.get_db', mock_get_db):
        plan = await get_student_learning_plan(student_id)

        check("Plan exists", plan is not None)
        check("Plan is version 2", plan["version"] == 2)
        check("Total versions is 2", plan["total_versions"] == 2)
        check("Plan has summary", plan["summary"] == "Version 2")


async def test_get_plan_history(db, fixtures):
    """Test get_plan_history returns all versions."""
    print("\n=== get_plan_history Tests ===")

    from app.services.plan_updater import get_plan_history

    student_id = fixtures["student_id"]

    # Create multiple plans
    await ll.create_learning_plan(db, student_id, {"goals_next_2_weeks": ["goal1"]}, summary="Plan 1")
    await ll.create_learning_plan(db, student_id, {"goals_next_2_weeks": ["goal2"]}, summary="Plan 2")
    await ll.create_learning_plan(db, student_id, {"goals_next_2_weeks": ["goal3"]}, summary="Plan 3")

    # Use non-closing wrapper
    wrapped_db = NonClosingDBWrapper(db)

    async def mock_get_db():
        return wrapped_db

    with patch('app.services.plan_updater.get_db', mock_get_db):
        history = await get_plan_history(student_id, limit=10)

        check("History has 3 plans", len(history) == 3)
        check("First plan is version 3 (most recent)", history[0]["version"] == 3)
        check("Last plan is version 1 (oldest)", history[2]["version"] == 1)
        check("Plans have goals", len(history[0]["goals"]) > 0)


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Learning Plan Updater Tests")
    print("=" * 60)

    # Each test group gets a fresh database for isolation
    test_functions = [
        test_gather_quiz_analysis,
        test_gather_teacher_notes,
        test_plan_version_increment,
        test_update_learning_plan_creates_version,
        test_on_quiz_submitted_triggers_update,
        test_get_student_learning_plan,
        test_get_plan_history,
    ]

    for test_fn in test_functions:
        db = await setup_test_db()
        fixtures = await create_fixtures(db)
        try:
            await test_fn(db, fixtures)
        finally:
            await db.close()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60 + "\n")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
