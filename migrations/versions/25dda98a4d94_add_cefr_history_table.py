"""add_cefr_history_table

Track CEFR level changes over time with per-skill sub-levels.

Revision ID: 25dda98a4d94
Revises: 57bc43084dc5
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "25dda98a4d94"
down_revision: Union[str, Sequence[str], None] = "57bc43084dc5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS cefr_history (
            id              {pk},
            student_id      INTEGER NOT NULL REFERENCES users(id),
            level           TEXT NOT NULL,
            grammar_level   TEXT,
            vocabulary_level TEXT,
            reading_level   TEXT,
            speaking_level  TEXT,
            writing_level   TEXT,
            confidence      REAL,
            source          TEXT DEFAULT 'assessment',
            assessment_id   INTEGER REFERENCES assessments(id),
            recorded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_cefr_history_student "
        "ON cefr_history(student_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS cefr_history"))
