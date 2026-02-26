"""add_session_skill_observations

Structured per-skill teacher observations after each class session.

Revision ID: f351a15d99fd
Revises: 25dda98a4d94
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f351a15d99fd"
down_revision: Union[str, Sequence[str], None] = "25dda98a4d94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS session_skill_observations (
            id           {pk},
            session_id   INTEGER NOT NULL REFERENCES sessions(id),
            student_id   INTEGER NOT NULL REFERENCES users(id),
            teacher_id   INTEGER NOT NULL REFERENCES users(id),
            skill        TEXT NOT NULL,
            score        REAL,
            cefr_level   TEXT,
            notes        TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_skill_obs_session "
        "ON session_skill_observations(session_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_skill_obs_student "
        "ON session_skill_observations(student_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS session_skill_observations"))
