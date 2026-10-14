"""Create TikTok connections and pending credential cleanups.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tiktok_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("open_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Non-secret reference to the credential in the secure credential storage.
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("access_expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('connected', 'reconnect_required')",
            name=op.f("ck_tiktok_connections_status"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_tiktok_connections_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tiktok_connections_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tiktok_connections")),
        sa.UniqueConstraint(
            "account_id", name=op.f("uq_tiktok_connections_account_id")
        ),
        sa.UniqueConstraint(
            "project_id",
            "open_id",
            name=op.f("uq_tiktok_connections_project_id_open_id"),
        ),
        sa.UniqueConstraint(
            "credential_ref", name=op.f("uq_tiktok_connections_credential_ref")
        ),
    )
    op.create_table(
        "tiktok_credential_orphans",
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "credential_ref", name=op.f("pk_tiktok_credential_orphans")
        ),
    )


def downgrade() -> None:
    op.drop_table("tiktok_credential_orphans")
    op.drop_table("tiktok_connections")
