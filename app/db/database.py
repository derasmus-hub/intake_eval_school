import aiosqlite
from pathlib import Path
from app.config import settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    # Ensure parent directory exists (for Docker volume mounts)
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await get_db()
    try:
        schema = SCHEMA_PATH.read_text()
        await db.executescript(schema)
        await db.commit()

        # Run migrations for existing databases
        await _run_migrations(db)
    finally:
        await db.close()


async def _run_migrations(db):
    """Add columns to existing tables if they don't exist yet."""

    # Create new tables for availability feature (if not exist)
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS teacher_weekly_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            day_of_week TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES students(id)
        );

        CREATE TABLE IF NOT EXISTS teacher_availability_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            is_available INTEGER NOT NULL DEFAULT 1,
            custom_windows TEXT,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES students(id),
            UNIQUE(teacher_id, date)
        );

        CREATE INDEX IF NOT EXISTS idx_weekly_windows_teacher
            ON teacher_weekly_windows(teacher_id);
        CREATE INDEX IF NOT EXISTS idx_overrides_teacher_date
            ON teacher_availability_overrides(teacher_id, date);
    """)
    await db.commit()

    # Create Learning Loop tables (if not exist)
    await db.executescript("""
        -- Versioned learning plans for each student
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

        -- Lesson artifacts generated during sessions
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

        -- Quizzes generated from lesson artifacts
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

        -- Quiz attempts by students
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

        -- Individual question responses within a quiz attempt
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

        -- Indexes for Learning Loop tables
        CREATE INDEX IF NOT EXISTS idx_learning_plans_student
            ON learning_plans(student_id);
        CREATE INDEX IF NOT EXISTS idx_lesson_artifacts_student
            ON lesson_artifacts(student_id);
        CREATE INDEX IF NOT EXISTS idx_lesson_artifacts_session
            ON lesson_artifacts(session_id);
        CREATE INDEX IF NOT EXISTS idx_next_quizzes_student
            ON next_quizzes(student_id);
        CREATE INDEX IF NOT EXISTS idx_quiz_attempts_quiz
            ON quiz_attempts(quiz_id);
        CREATE INDEX IF NOT EXISTS idx_quiz_attempts_student
            ON quiz_attempts(student_id);
        CREATE INDEX IF NOT EXISTS idx_quiz_attempt_items_attempt
            ON quiz_attempt_items(attempt_id);
    """)
    await db.commit()

    migrations = [
        ("students", "role", "ALTER TABLE students ADD COLUMN role TEXT NOT NULL DEFAULT 'student'"),
        ("students", "email", "ALTER TABLE students ADD COLUMN email TEXT UNIQUE"),
        ("students", "password_hash", "ALTER TABLE students ADD COLUMN password_hash TEXT"),
        ("students", "total_xp", "ALTER TABLE students ADD COLUMN total_xp INTEGER DEFAULT 0"),
        ("students", "xp_level", "ALTER TABLE students ADD COLUMN xp_level INTEGER DEFAULT 1"),
        ("students", "streak", "ALTER TABLE students ADD COLUMN streak INTEGER DEFAULT 0"),
        ("students", "freeze_tokens", "ALTER TABLE students ADD COLUMN freeze_tokens INTEGER DEFAULT 0"),
        ("students", "last_activity_date", "ALTER TABLE students ADD COLUMN last_activity_date TEXT"),
        ("students", "avatar_id", "ALTER TABLE students ADD COLUMN avatar_id TEXT DEFAULT 'default'"),
        ("students", "theme_preference", "ALTER TABLE students ADD COLUMN theme_preference TEXT DEFAULT 'light'"),
        ("students", "display_title", "ALTER TABLE students ADD COLUMN display_title TEXT"),
        ("achievements", "category", "ALTER TABLE achievements ADD COLUMN category TEXT DEFAULT 'progress'"),
        ("achievements", "xp_reward", "ALTER TABLE achievements ADD COLUMN xp_reward INTEGER DEFAULT 0"),
        ("achievements", "icon", "ALTER TABLE achievements ADD COLUMN icon TEXT"),
        # Session notes columns
        ("sessions", "teacher_notes", "ALTER TABLE sessions ADD COLUMN teacher_notes TEXT"),
        ("sessions", "homework", "ALTER TABLE sessions ADD COLUMN homework TEXT"),
        ("sessions", "session_summary", "ALTER TABLE sessions ADD COLUMN session_summary TEXT"),
        ("sessions", "updated_at", "ALTER TABLE sessions ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]

    for table, column, sql in migrations:
        cursor = await db.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in await cursor.fetchall()]
        if column not in columns:
            await db.execute(sql)
            await db.commit()
