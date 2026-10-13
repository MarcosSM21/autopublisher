"""Create Threads connections.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "threads_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("threads_user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("profile_picture_url", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Non-secret reference to the token in the system's secure credential storage.
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("token_obtained_at", sa.DateTime(), nullable=False),
        sa.Column("credential_expires_at", sa.DateTime(), nullable=False),
        sa.Column("data_access_expires_at", sa.DateTime(), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('connected', 'reconnect_required')",
            name=op.f("ck_threads_connections_status"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_threads_connections_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_threads_connections_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threads_connections")),
        sa.UniqueConstraint(
            "account_id", name=op.f("uq_threads_connections_account_id")
        ),
        sa.UniqueConstraint(
            "project_id",
            "threads_user_id",
            name=op.f("uq_threads_connections_project_id_threads_user_id"),
        ),
        sa.UniqueConstraint(
            "credential_ref", name=op.f("uq_threads_connections_credential_ref")
        ),
    )


def downgrade() -> None:
    op.drop_table("threads_connections")
