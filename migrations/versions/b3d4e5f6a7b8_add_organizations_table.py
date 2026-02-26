"""add_organizations_table

Multi-tenancy: organizations table with name, slug, plan, owner, settings.

Revision ID: b3d4e5f6a7b8
Revises: a7c3e1f08b12
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a7c3e1f08b12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    pk = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS organizations (
            id {pk},
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            plan TEXT NOT NULL DEFAULT 'free',
            owner_id INTEGER REFERENCES users(id),
            settings TEXT DEFAULT '{{}}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug "
        "ON organizations(slug)"
    ))

    # Org invites for pending user invitations
    op.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS org_invites (
            id {pk},
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            email TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            token TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_org_invites_email "
        "ON org_invites(email)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS org_invites"))
    op.execute(sa.text("DROP TABLE IF EXISTS organizations"))
