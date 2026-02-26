"""add_session_lesson_link_and_attendance

Add lesson_id FK and attended flag to sessions table.
- lesson_id links a session to the lesson plan used
- attended: 0 = unknown, 1 = attended, -1 = no-show

Revision ID: 82011f75ce7a
Revises: f351a15d99fd
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "82011f75ce7a"
down_revision: Union[str, Sequence[str], None] = "f351a15d99fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table: str, column: str) -> bool:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        result = bind.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ), {"t": table, "c": column})
        return result.fetchone() is not None
    else:
        result = bind.execute(sa.text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in result.fetchall())


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "sessions", "lesson_id"):
        op.execute(sa.text(
            "ALTER TABLE sessions ADD COLUMN lesson_id INTEGER REFERENCES lessons(id)"
        ))
    if not _column_exists(bind, "sessions", "attended"):
        op.execute(sa.text(
            "ALTER TABLE sessions ADD COLUMN attended INTEGER DEFAULT 0"
        ))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE sessions DROP COLUMN lesson_id"))
    op.execute(sa.text("ALTER TABLE sessions DROP COLUMN attended"))
