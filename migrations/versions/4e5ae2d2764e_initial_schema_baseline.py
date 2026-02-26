"""initial_schema_baseline

Baseline migration representing the existing schema.
For existing databases, stamp this revision instead of running it:
    alembic stamp 4e5ae2d2764e

Revision ID: 4e5ae2d2764e
Revises:
Create Date: 2026-02-25 08:56:12.736184

"""
from typing import Sequence, Union
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision: str = "4e5ae2d2764e"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _adapt_sql(sql: str, dialect_name: str) -> str:
    """Adapt DDL for the target database dialect."""
    if dialect_name == "postgresql":
        # AUTOINCREMENT → SERIAL for PostgreSQL
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        # IF NOT EXISTS on indexes is fine for both
    return sql


def upgrade() -> None:
    """Create the full initial schema.

    This executes schema.sql which uses CREATE TABLE IF NOT EXISTS,
    so it is safe to run against an existing database.
    """
    dialect_name = op.get_bind().dialect.name

    schema_path = Path(__file__).resolve().parents[2] / "app" / "db" / "schema.sql"
    schema_sql = schema_path.read_text()
    # Execute each statement individually (op.execute doesn't support executescript)
    for statement in schema_sql.split(";"):
        # Strip comment lines before checking if there's real SQL
        lines = [
            line for line in statement.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            adapted = _adapt_sql(cleaned, dialect_name)
            op.execute(sa.text(adapted))


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    tables = [
        "quiz_attempt_items",
        "quiz_attempts",
        "next_quizzes",
        "lesson_artifacts",
        "learning_plans",
        "teacher_invites",
        "teacher_availability_overrides",
        "teacher_weekly_windows",
        "teacher_availability",
        "sessions",
        "game_scores",
        "xp_log",
        "daily_challenges",
        "recall_sessions",
        "learning_points",
        "vocabulary_cards",
        "achievements",
        "learning_paths",
        "assessments",
        "progress",
        "lessons",
        "learner_profiles",
        "students",
    ]
    for table in tables:
        op.drop_table(table)
