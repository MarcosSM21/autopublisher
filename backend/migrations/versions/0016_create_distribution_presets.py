"""Create distribution presets.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "distribution_presets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_distribution_presets_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_distribution_presets")),
        sa.UniqueConstraint(
            "project_id",
            "name_key",
            name=op.f("uq_distribution_presets_project_id_name_key"),
        ),
    )
    op.create_table(
        "distribution_preset_accounts",
        sa.Column("preset_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["preset_id"],
            ["distribution_presets.id"],
            name=op.f("fk_distribution_preset_accounts_preset_id_distribution_presets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name=op.f("fk_distribution_preset_accounts_account_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "preset_id", "account_id", name=op.f("pk_distribution_preset_accounts")
        ),
    )
    op.create_index(
        op.f("ix_distribution_preset_accounts_account_id"),
        "distribution_preset_accounts",
        ["account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_distribution_preset_accounts_account_id"),
        table_name="distribution_preset_accounts",
    )
    op.drop_table("distribution_preset_accounts")
    op.drop_table("distribution_presets")
