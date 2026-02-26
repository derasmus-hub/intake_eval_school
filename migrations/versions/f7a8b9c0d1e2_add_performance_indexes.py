"""add_performance_indexes

Composite and single-column indexes on high-traffic query paths to
improve dashboard, scheduler, and spaced-repetition lookup performance.

Revision ID: f7a8b9c0d1e2
Revises: e6a7b8c9d0e1
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # learning_points indexes
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_learning_points_student "
        "ON learning_points(student_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_learning_points_review "
        "ON learning_points(student_id, next_review_date)"
    ))

    # vocabulary_cards index
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_vocabulary_student_review "
        "ON vocabulary_cards(student_id, next_review)"
    ))

    # sessions indexes
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_sessions_student "
        "ON sessions(student_id, status, scheduled_at)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_sessions_teacher "
        "ON sessions(teacher_id, status)"
    ))

    # progress indexes
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_progress_student "
        "ON progress(student_id, completed_at)"
    ))

    # assessments index
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_assessments_student "
        "ON assessments(student_id, status)"
    ))

    # recall_sessions index
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_recall_sessions_student "
        "ON recall_sessions(student_id, status, completed_at)"
    ))

    # xp_log index
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_xp_log_student "
        "ON xp_log(student_id, created_at)"
    ))

    # achievements index
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_achievements_student "
        "ON achievements(student_id)"
    ))

    # lessons index
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_lessons_student "
        "ON lessons(student_id, session_number)"
    ))

    # progress unique constraint index
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_progress_unique "
        "ON progress(lesson_id, student_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_progress_unique"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_lessons_student"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_achievements_student"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_xp_log_student"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_recall_sessions_student"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_assessments_student"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_progress_student"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sessions_teacher"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sessions_student"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_vocabulary_student_review"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_learning_points_review"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_learning_points_student"))
