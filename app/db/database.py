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
