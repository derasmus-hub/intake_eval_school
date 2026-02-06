"""
test_learning_loop.py - Tests for the Learning Loop database layer

Tests:
- Create student/teacher/session fixtures
- Insert learning plan, lesson artifact, quiz, attempt
- Read back and validate referential integrity

Run with: python tests/test_learning_loop.py
"""

import asyncio
import json
import sys
from pathlib import Path

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
    """Create student, teacher, session, and assessment fixtures."""
    # Create student
    cursor = await db.execute(
        """INSERT INTO students (name, email, role, password_hash)
           VALUES (?, ?, ?, ?)""",
        ("Test Student", "student@test.com", "student", "hashed_password")
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

    # Create session
    cursor = await db.execute(
        """INSERT INTO sessions (student_id, teacher_id, scheduled_at, duration_min, status)
           VALUES (?, ?, ?, ?, ?)""",
        (student_id, teacher_id, "2026-02-10T14:00:00", 60, "confirmed")
    )
    await db.commit()
    session_id = cursor.lastrowid

    # Create assessment (intake)
    cursor = await db.execute(
        """INSERT INTO assessments (student_id, stage, status, responses)
           VALUES (?, ?, ?, ?)""",
        (student_id, "placement", "completed", json.dumps({"q1": "answer1"}))
    )
    await db.commit()
    assessment_id = cursor.lastrowid

    return {
        "student_id": student_id,
        "teacher_id": teacher_id,
        "session_id": session_id,
        "assessment_id": assessment_id
    }


async def test_learning_plans(db, fixtures):
    """Test learning plan CRUD operations."""
    print("\n=== Learning Plans Tests ===")

    student_id = fixtures["student_id"]
    assessment_id = fixtures["assessment_id"]

    # Test create learning plan
    plan_data = {"goals": ["Improve speaking fluency"], "weeks": 4}
    plan_id = await ll.create_learning_plan(
        db, student_id, plan_data,
        summary="Focus on conversation skills",
        source_intake_id=assessment_id
    )
    check("Create learning plan", plan_id is not None and plan_id > 0, f"id={plan_id}")

    # Test get learning plan
    plan = await ll.get_learning_plan(db, plan_id)
    check("Get learning plan by ID", plan is not None)
    check("Plan has correct student_id", plan["student_id"] == student_id)
    check("Plan has correct source_intake_id", plan["source_intake_id"] == assessment_id)
    check("Plan JSON parsed correctly", plan["plan_json"] == plan_data)
    check("Plan version is 1", plan["version"] == 1)

    # Test auto-versioning
    plan2_id = await ll.create_learning_plan(db, student_id, {"v": 2})
    plan3_id = await ll.create_learning_plan(db, student_id, {"v": 3})
    plan2 = await ll.get_learning_plan(db, plan2_id)
    plan3 = await ll.get_learning_plan(db, plan3_id)
    check("Plan 2 has version 2", plan2["version"] == 2)
    check("Plan 3 has version 3", plan3["version"] == 3)

    # Test get latest
    latest = await ll.get_latest_learning_plan(db, student_id)
    check("Latest plan is version 3", latest["version"] == 3)

    # Test get all plans for student
    plans = await ll.get_learning_plans_by_student(db, student_id)
    check("Get all plans returns 3 plans", len(plans) == 3)
    check("Plans ordered by version desc", plans[0]["version"] == 3)


async def test_lesson_artifacts(db, fixtures):
    """Test lesson artifact CRUD operations."""
    print("\n=== Lesson Artifacts Tests ===")

    student_id = fixtures["student_id"]
    teacher_id = fixtures["teacher_id"]
    session_id = fixtures["session_id"]

    # Test create lesson artifact
    lesson_data = {"title": "Present Perfect Tense", "objectives": ["Usage", "Practice"]}
    topics_data = {"grammar": ["present_perfect"], "vocabulary": ["time_expressions"]}

    artifact_id = await ll.create_lesson_artifact(
        db, student_id, lesson_data,
        session_id=session_id,
        teacher_id=teacher_id,
        topics_json=topics_data,
        difficulty="B1",
        prompt_version="v1.0"
    )
    check("Create lesson artifact", artifact_id is not None and artifact_id > 0, f"id={artifact_id}")

    # Test get lesson artifact
    artifact = await ll.get_lesson_artifact(db, artifact_id)
    check("Get artifact by ID", artifact is not None)
    check("Artifact has correct student_id", artifact["student_id"] == student_id)
    check("Artifact has correct session_id", artifact["session_id"] == session_id)
    check("Artifact has correct teacher_id", artifact["teacher_id"] == teacher_id)
    check("Lesson JSON parsed correctly", artifact["lesson_json"] == lesson_data)
    check("Topics JSON parsed correctly", artifact["topics_json"] == topics_data)
    check("Artifact difficulty is B1", artifact["difficulty"] == "B1")

    # Test get by session
    await ll.create_lesson_artifact(db, student_id, {"n": 2}, session_id=session_id)
    artifacts = await ll.get_lesson_artifacts_by_session(db, session_id)
    check("Get artifacts by session returns 2", len(artifacts) == 2)

    # Test get by student
    artifacts = await ll.get_lesson_artifacts_by_student(db, student_id)
    check("Get artifacts by student returns 2", len(artifacts) == 2)


async def test_quizzes(db, fixtures):
    """Test quiz CRUD operations."""
    print("\n=== Quizzes Tests ===")

    student_id = fixtures["student_id"]
    session_id = fixtures["session_id"]

    # Create a lesson artifact first
    artifact_id = await ll.create_lesson_artifact(db, student_id, {"title": "Test"})

    # Test create quiz
    quiz_data = {
        "questions": [
            {"id": "q1", "type": "multiple_choice", "text": "What is...?"},
            {"id": "q2", "type": "fill_blank", "text": "Complete: I ___ gone..."}
        ],
        "time_limit": 300
    }

    quiz_id = await ll.create_quiz(
        db, student_id, quiz_data,
        session_id=session_id,
        derived_from_lesson_artifact_id=artifact_id
    )
    check("Create quiz", quiz_id is not None and quiz_id > 0, f"id={quiz_id}")

    # Test get quiz
    quiz = await ll.get_quiz(db, quiz_id)
    check("Get quiz by ID", quiz is not None)
    check("Quiz has correct student_id", quiz["student_id"] == student_id)
    check("Quiz has correct artifact reference", quiz["derived_from_lesson_artifact_id"] == artifact_id)
    check("Quiz JSON parsed correctly", quiz["quiz_json"] == quiz_data)

    # Test get quizzes from artifact
    await ll.create_quiz(db, student_id, {"n": 2}, derived_from_lesson_artifact_id=artifact_id)
    quizzes = await ll.get_quizzes_from_lesson_artifact(db, artifact_id)
    check("Get quizzes from artifact returns 2", len(quizzes) == 2)


async def test_quiz_attempts(db, fixtures):
    """Test quiz attempt CRUD operations."""
    print("\n=== Quiz Attempts Tests ===")

    student_id = fixtures["student_id"]
    session_id = fixtures["session_id"]

    # Create a quiz first
    quiz_id = await ll.create_quiz(db, student_id, {"questions": []})

    # Test create attempt
    attempt_id = await ll.create_quiz_attempt(db, quiz_id, student_id, session_id)
    check("Create quiz attempt", attempt_id is not None and attempt_id > 0, f"id={attempt_id}")

    # Test get attempt
    attempt = await ll.get_quiz_attempt(db, attempt_id)
    check("Get attempt by ID", attempt is not None)
    check("Attempt has correct quiz_id", attempt["quiz_id"] == quiz_id)
    check("Attempt has correct student_id", attempt["student_id"] == student_id)
    check("Attempt started_at is set", attempt["started_at"] is not None)
    check("Attempt submitted_at is None initially", attempt["submitted_at"] is None)

    # Test submit attempt
    results_data = {"correct": 8, "total": 10, "feedback": "Good job!"}
    await ll.submit_quiz_attempt(db, attempt_id, score=0.8, results_json=results_data)
    attempt = await ll.get_quiz_attempt(db, attempt_id)
    check("Submitted attempt has score", attempt["score"] == 0.8)
    check("Submitted attempt has submitted_at", attempt["submitted_at"] is not None)
    check("Submitted attempt has results_json", attempt["results_json"] == results_data)

    # Test get attempts by quiz
    await ll.create_quiz_attempt(db, quiz_id, student_id)
    attempts = await ll.get_quiz_attempts_by_quiz(db, quiz_id)
    check("Get attempts by quiz returns 2", len(attempts) == 2)


async def test_quiz_attempt_items(db, fixtures):
    """Test quiz attempt item CRUD operations."""
    print("\n=== Quiz Attempt Items Tests ===")

    student_id = fixtures["student_id"]

    # Create quiz and attempt
    quiz_id = await ll.create_quiz(db, student_id, {"questions": []})
    attempt_id = await ll.create_quiz_attempt(db, quiz_id, student_id)

    # Test create single item
    item_id = await ll.create_quiz_attempt_item(
        db, attempt_id, "q1",
        is_correct=True,
        student_answer="answer A",
        expected_answer="answer A",
        skill_tag="grammar_present_perfect",
        time_spent=45
    )
    check("Create quiz attempt item", item_id is not None and item_id > 0, f"id={item_id}")

    # Test get items
    items = await ll.get_quiz_attempt_items(db, attempt_id)
    check("Get items returns 1 item", len(items) == 1)
    check("Item has correct attempt_id", items[0]["attempt_id"] == attempt_id)
    check("Item has correct question_id", items[0]["question_id"] == "q1")
    check("Item is_correct is True (1)", items[0]["is_correct"] == 1)

    # Test batch create
    batch_items = [
        {"question_id": "q2", "is_correct": True, "skill_tag": "grammar"},
        {"question_id": "q3", "is_correct": False, "skill_tag": "vocabulary"},
        {"question_id": "q4", "is_correct": True, "skill_tag": "grammar"},
    ]
    item_ids = await ll.create_quiz_attempt_items_batch(db, attempt_id, batch_items)
    check("Batch create returns 3 IDs", len(item_ids) == 3)

    items = await ll.get_quiz_attempt_items(db, attempt_id)
    check("Get items now returns 4 items", len(items) == 4)

    # Test get by skill tag
    grammar_items = await ll.get_items_by_skill_tag(db, student_id, "grammar")
    check("Get grammar items returns 2", len(grammar_items) == 2)


async def test_full_learning_loop_flow(db, fixtures):
    """Test the complete learning loop flow with referential integrity."""
    print("\n=== Full Learning Loop Flow Test ===")

    student_id = fixtures["student_id"]
    teacher_id = fixtures["teacher_id"]
    session_id = fixtures["session_id"]
    assessment_id = fixtures["assessment_id"]

    # 1. Create learning plan from intake assessment
    plan_data = {"goals": ["Improve grammar"], "weeks": 4}
    plan_id = await ll.create_learning_plan(
        db, student_id, plan_data,
        summary="Focus on grammar improvement",
        source_intake_id=assessment_id
    )
    check("Flow: Created learning plan", plan_id > 0)

    # 2. Create lesson artifact during session
    lesson_data = {"title": "Present Perfect Tense"}
    artifact_id = await ll.create_lesson_artifact(
        db, student_id, lesson_data,
        session_id=session_id,
        teacher_id=teacher_id,
        topics_json={"grammar": ["present_perfect"]},
        difficulty="B1"
    )
    check("Flow: Created lesson artifact", artifact_id > 0)

    # 3. Create quiz derived from lesson
    quiz_data = {"questions": [{"id": "q1"}, {"id": "q2"}]}
    quiz_id = await ll.create_quiz(
        db, student_id, quiz_data,
        session_id=session_id,
        derived_from_lesson_artifact_id=artifact_id
    )
    check("Flow: Created quiz", quiz_id > 0)

    # 4. Student takes quiz
    attempt_id = await ll.create_quiz_attempt(db, quiz_id, student_id, session_id)
    check("Flow: Created quiz attempt", attempt_id > 0)

    # 5. Record individual question responses
    items = [
        {"question_id": "q1", "is_correct": True, "skill_tag": "grammar_pp", "time_spent": 30},
        {"question_id": "q2", "is_correct": False, "skill_tag": "grammar_pp", "time_spent": 45}
    ]
    await ll.create_quiz_attempt_items_batch(db, attempt_id, items)
    check("Flow: Created attempt items", True)

    # 6. Submit quiz with score
    await ll.submit_quiz_attempt(db, attempt_id, score=0.5, results_json={"weak": ["agreement"]})
    check("Flow: Submitted quiz attempt", True)

    # Validate referential integrity by reading back all entities
    print("\n=== Referential Integrity Validation ===")

    plan = await ll.get_learning_plan(db, plan_id)
    check("Integrity: Plan references assessment", plan["source_intake_id"] == assessment_id)

    artifact = await ll.get_lesson_artifact(db, artifact_id)
    check("Integrity: Artifact references session", artifact["session_id"] == session_id)
    check("Integrity: Artifact references student", artifact["student_id"] == student_id)
    check("Integrity: Artifact references teacher", artifact["teacher_id"] == teacher_id)

    quiz = await ll.get_quiz(db, quiz_id)
    check("Integrity: Quiz references artifact", quiz["derived_from_lesson_artifact_id"] == artifact_id)
    check("Integrity: Quiz references student", quiz["student_id"] == student_id)

    attempt = await ll.get_quiz_attempt(db, attempt_id)
    check("Integrity: Attempt references quiz", attempt["quiz_id"] == quiz_id)
    check("Integrity: Attempt references student", attempt["student_id"] == student_id)
    check("Integrity: Attempt has score 0.5", attempt["score"] == 0.5)

    attempt_items = await ll.get_quiz_attempt_items(db, attempt_id)
    check("Integrity: All items reference attempt", all(i["attempt_id"] == attempt_id for i in attempt_items))
    check("Integrity: 2 items recorded", len(attempt_items) == 2)


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Learning Loop Database Layer Tests")
    print("=" * 60)

    db = await setup_test_db()
    fixtures = await create_fixtures(db)

    try:
        await test_learning_plans(db, fixtures)
        await test_lesson_artifacts(db, fixtures)
        await test_quizzes(db, fixtures)
        await test_quiz_attempts(db, fixtures)
        await test_quiz_attempt_items(db, fixtures)
        await test_full_learning_loop_flow(db, fixtures)
    finally:
        await db.close()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60 + "\n")

    return FAIL == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
