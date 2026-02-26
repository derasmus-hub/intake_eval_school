"""add_lesson_skill_tags

Structured skill tags for lessons, enabling queries like
"show all lessons covering present perfect" or
"what vocabulary has this student been exposed to".

Revision ID: 2fa31870e98e
Revises: 82011f75ce7a
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2fa31870e98e"
down_revision: Union[str, Sequence[str], None] = "82011f75ce7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS lesson_skill_tags (
            id         {pk},
            lesson_id  INTEGER NOT NULL REFERENCES lessons(id),
            tag_type   TEXT NOT NULL,
            tag_value  TEXT NOT NULL,
            cefr_level TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_lesson_skill_tags_lesson "
        "ON lesson_skill_tags(lesson_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_lesson_skill_tags_value "
        "ON lesson_skill_tags(tag_type, tag_value)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS lesson_skill_tags"))
