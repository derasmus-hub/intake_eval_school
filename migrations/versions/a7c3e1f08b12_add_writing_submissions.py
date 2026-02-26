"""add_writing_submissions

Table for storing student writing submissions and AI evaluations.

Revision ID: a7c3e1f08b12
Revises: 2fa31870e98e
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7c3e1f08b12"
down_revision: Union[str, Sequence[str], None] = "2fa31870e98e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS writing_submissions (
            id {pk},
            student_id INTEGER NOT NULL REFERENCES users(id),
            prompt_topic TEXT,
            submitted_text TEXT NOT NULL,
            evaluation_json TEXT,
            cefr_level TEXT,
            overall_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_writing_submissions_student "
        "ON writing_submissions(student_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS writing_submissions"))
