"""rename_students_to_users_drop_filler

Rename the 'students' table to 'users' and drop the unused 'filler' column.
Uses raw SQL for maximum SQLite compatibility.

Revision ID: 57bc43084dc5
Revises: 4e5ae2d2764e
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "57bc43084dc5"
down_revision: Union[str, Sequence[str], None] = "4e5ae2d2764e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Check if 'students' table exists (it won't on fresh DBs where schema.sql
    # already creates 'users' directly).
    if dialect == "postgresql":
        result = bind.execute(sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'students')"
        ))
        students_exists = result.scalar()
    else:
        result = bind.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='students'"
        ))
        students_exists = result.fetchone() is not None

    if students_exists:
        # Step 1: Rename students -> users
        op.execute(sa.text("ALTER TABLE students RENAME TO users"))

        # Step 2: Drop the 'filler' column if it exists
        if dialect == "postgresql":
            op.execute(sa.text(
                "ALTER TABLE users DROP COLUMN IF EXISTS filler"
            ))
        else:
            # SQLite >= 3.35.0 supports DROP COLUMN
            try:
                op.execute(sa.text("ALTER TABLE users DROP COLUMN filler"))
            except Exception:
                pass  # Column may not exist


def downgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE users ADD COLUMN filler TEXT DEFAULT 'student'")
    )
    op.execute(sa.text("ALTER TABLE users RENAME TO students"))
