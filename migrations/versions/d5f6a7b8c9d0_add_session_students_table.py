"""add_session_students_table

Junction table for group classes: many students can attend one session.

Revision ID: d5f6a7b8c9d0
Revises: c4e5f6a7b8c9
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "c4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS session_students (
            id {pk},
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            student_id INTEGER NOT NULL REFERENCES users(id),
            attended INTEGER DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_session_students_unique "
        "ON session_students(session_id, student_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_session_students_student "
        "ON session_students(student_id)"
    ))

    # Add is_group flag and max_students to sessions (if not already present)
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        result = bind.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'sessions' AND column_name = 'is_group'"
        ))
        if not result.fetchone():
            op.execute(sa.text(
                "ALTER TABLE sessions ADD COLUMN is_group INTEGER DEFAULT 0"
            ))
        result = bind.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'sessions' AND column_name = 'max_students'"
        ))
        if not result.fetchone():
            op.execute(sa.text(
                "ALTER TABLE sessions ADD COLUMN max_students INTEGER DEFAULT 1"
            ))
    else:
        # SQLite: check via PRAGMA
        result = bind.execute(sa.text("PRAGMA table_info(sessions)"))
        cols = {row[1] for row in result.fetchall()}
        if "is_group" not in cols:
            op.execute(sa.text(
                "ALTER TABLE sessions ADD COLUMN is_group INTEGER DEFAULT 0"
            ))
        if "max_students" not in cols:
            op.execute(sa.text(
                "ALTER TABLE sessions ADD COLUMN max_students INTEGER DEFAULT 1"
            ))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE sessions DROP COLUMN max_students"))
    op.execute(sa.text("ALTER TABLE sessions DROP COLUMN is_group"))
    op.execute(sa.text("DROP TABLE IF EXISTS session_students"))
