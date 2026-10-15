"""Create Telegram connections.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Non-secret reference to the session in the secure credential storage.
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=True),
        sa.Column("channel_access_hash", sa.String(length=32), nullable=True),
        sa.Column("channel_title", sa.String(length=255), nullable=True),
        sa.Column("channel_username", sa.String(length=100), nullable=True),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("flood_wait_until", sa.DateTime(), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('connected', 'reconnect_required')",
            name=op.f("ck_telegram_connections_status"),
        ),
        sa.CheckConstraint(
            "(channel_id IS NULL AND channel_access_hash IS NULL "
            "AND channel_title IS NULL) OR (channel_id IS NOT NULL "
            "AND channel_access_hash IS NOT NULL AND channel_title IS NOT NULL)",
            name=op.f("ck_telegram_connections_channel_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_telegram_connections_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_telegram_connections_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_connections")),
        sa.UniqueConstraint(
            "account_id", name=op.f("uq_telegram_connections_account_id")
        ),
        sa.UniqueConstraint(
            "credential_ref", name=op.f("uq_telegram_connections_credential_ref")
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_connections")
