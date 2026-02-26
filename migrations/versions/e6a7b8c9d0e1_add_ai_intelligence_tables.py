"""add_ai_intelligence_tables

Tables for the AI Intelligence Core:
- learning_dna: living student profile recalculated after every interaction
- l1_interference_tracking: per-student Polish→English interference pattern tracking
- pre_class_warmups: auto-generated warm-up packages before sessions

Revision ID: e6a7b8c9d0e1
Revises: d5f6a7b8c9d0
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "d5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    # Living Learning DNA profile
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS learning_dna (
            id {pk},
            student_id INTEGER NOT NULL REFERENCES users(id),
            dna_json TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            trigger_event TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_learning_dna_student "
        "ON learning_dna(student_id)"
    ))

    # Per-student L1 interference tracking
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS l1_interference_tracking (
            id {pk},
            student_id INTEGER NOT NULL REFERENCES users(id),
            pattern_category TEXT NOT NULL,
            pattern_detail TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'exhibited',
            occurrences INTEGER DEFAULT 1,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            overcome_at TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_l1_tracking_student "
        "ON l1_interference_tracking(student_id)"
    ))
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_l1_tracking_unique "
        "ON l1_interference_tracking(student_id, pattern_category, pattern_detail)"
    ))

    # Pre-class warm-up packages
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS pre_class_warmups (
            id {pk},
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            student_id INTEGER NOT NULL REFERENCES users(id),
            warmup_json TEXT NOT NULL,
            results_json TEXT,
            confidence_rating INTEGER,
            status TEXT NOT NULL DEFAULT 'generated',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_warmups_session "
        "ON pre_class_warmups(session_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_warmups_student "
        "ON pre_class_warmups(student_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS pre_class_warmups"))
    op.execute(sa.text("DROP TABLE IF EXISTS l1_interference_tracking"))
    op.execute(sa.text("DROP TABLE IF EXISTS learning_dna"))
