"""add_org_id_to_users

Add nullable org_id FK to users table. Create a default organization
and assign all existing users to it.

Revision ID: c4e5f6a7b8c9
Revises: b3d4e5f6a7b8
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "b3d4e5f6a7b8"
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
    dialect = bind.dialect.name

    # Add org_id column to users (nullable for backward compat)
    if not _column_exists(bind, "users", "org_id"):
        op.execute(sa.text(
            "ALTER TABLE users ADD COLUMN org_id INTEGER REFERENCES organizations(id)"
        ))

    # Create default organization
    if dialect == "postgresql":
        op.execute(sa.text(
            "INSERT INTO organizations (name, slug, plan, settings) "
            "VALUES ('Default School', 'default', 'free', '{}') "
            "ON CONFLICT (slug) DO NOTHING"
        ))
        # Assign all existing users to the default org
        op.execute(sa.text(
            "UPDATE users SET org_id = (SELECT id FROM organizations WHERE slug = 'default') "
            "WHERE org_id IS NULL"
        ))
    else:
        op.execute(sa.text(
            "INSERT OR IGNORE INTO organizations (name, slug, plan, settings) "
            "VALUES ('Default School', 'default', 'free', '{}')"
        ))
        op.execute(sa.text(
            "UPDATE users SET org_id = (SELECT id FROM organizations WHERE slug = 'default') "
            "WHERE org_id IS NULL"
        ))

    # Index for org_id lookups
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_users_org_id"))
    # SQLite >= 3.35 and PostgreSQL both support DROP COLUMN
    op.execute(sa.text("ALTER TABLE users DROP COLUMN org_id"))
