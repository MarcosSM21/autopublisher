"""Create publications.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("title_override", sa.String(length=200), nullable=True),
        sa.Column("description_override", sa.String(length=5000), nullable=True),
        sa.Column("hashtags_override", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('unscheduled', 'scheduled', 'cancelled')",
            name=op.f("ck_publications_status_valid"),
        ),
        sa.CheckConstraint(
            "status = 'cancelled'"
            " OR (status = 'scheduled' AND scheduled_at IS NOT NULL)"
            " OR (status = 'unscheduled' AND scheduled_at IS NULL)",
            name=op.f("ck_publications_status_matches_schedule"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_publications_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["contents.id"],
            name=op.f("fk_publications_content_id_contents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_publications_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publications")),
    )
    op.create_index(
        "uq_publications_active_content_account",
        "publications",
        ["content_id", "account_id"],
        unique=True,
        sqlite_where=sa.text("status != 'cancelled'"),
    )
    op.create_index(
        "ix_publications_project_id_status_scheduled_at",
        "publications",
        ["project_id", "status", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publications_project_id_status_scheduled_at", table_name="publications"
    )
    op.drop_index("uq_publications_active_content_account", table_name="publications")
    op.drop_table("publications")
