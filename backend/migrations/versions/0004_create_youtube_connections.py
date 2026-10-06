"""Create YouTube connections.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "youtube_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("channel_title", sa.String(length=200), nullable=False),
        sa.Column("channel_handle", sa.String(length=100), nullable=True),
        sa.Column("channel_thumbnail_url", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Non-secret reference to the tokens in the system's secure credential storage.
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('connected', 'reconnect_required')",
            name=op.f("ck_youtube_connections_status"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_youtube_connections_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_youtube_connections_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_youtube_connections")),
        sa.UniqueConstraint(
            "account_id", name=op.f("uq_youtube_connections_account_id")
        ),
        sa.UniqueConstraint(
            "project_id",
            "channel_id",
            name=op.f("uq_youtube_connections_project_id_channel_id"),
        ),
        sa.UniqueConstraint(
            "credential_ref", name=op.f("uq_youtube_connections_credential_ref")
        ),
    )


def downgrade() -> None:
    op.drop_table("youtube_connections")
