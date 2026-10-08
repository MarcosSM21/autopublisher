"""Create Instagram connections.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instagram_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("instagram_user_id", sa.String(length=64), nullable=False),
        sa.Column("app_scoped_id", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("account_type", sa.String(length=20), nullable=False),
        sa.Column("profile_picture_url", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Non-secret reference to the token in the system's secure credential storage.
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("credential_expires_at", sa.DateTime(), nullable=False),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('connected', 'reconnect_required')",
            name=op.f("ck_instagram_connections_status"),
        ),
        sa.CheckConstraint(
            "account_type IN ('BUSINESS', 'MEDIA_CREATOR')",
            name=op.f("ck_instagram_connections_account_type"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_instagram_connections_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_instagram_connections_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instagram_connections")),
        sa.UniqueConstraint(
            "account_id", name=op.f("uq_instagram_connections_account_id")
        ),
        sa.UniqueConstraint(
            "project_id",
            "instagram_user_id",
            name=op.f("uq_instagram_connections_project_id_instagram_user_id"),
        ),
        sa.UniqueConstraint(
            "credential_ref", name=op.f("uq_instagram_connections_credential_ref")
        ),
    )


def downgrade() -> None:
    op.drop_table("instagram_connections")
