"""Create the installation password and browser sessions (Feature 020).

Existing data is untouched: a database from before this revision gets both tables
empty, which means "no password configured yet" (`set-password` sets it).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "installation_auth",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("password_changed_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_installation_auth_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installation_auth")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_auth_sessions")),
    )


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_table("installation_auth")
