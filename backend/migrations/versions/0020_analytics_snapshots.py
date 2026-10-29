"""Analytics snapshots, values and refresh state (Feature 027).

Additive only: three new tables, no existing row or table changes.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTOINCREMENT = {"sqlite_autoincrement": True}


def upgrade() -> None:
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("remote_id", sa.String(length=100), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "trigger IN ('automatic', 'manual')",
            name=op.f("ck_metric_snapshots_trigger_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_metric_snapshots_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_snapshots")),
        **AUTOINCREMENT,
    )
    op.create_index(
        "ix_metric_snapshots_publication_id_captured_at",
        "metric_snapshots",
        ["publication_id", "captured_at"],
    )
    op.create_table(
        "metric_values",
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "value >= 0", name=op.f("ck_metric_values_value_non_negative")
        ),
        sa.CheckConstraint(
            "origin IN ('public_counter', 'insight')",
            name=op.f("ck_metric_values_origin_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["metric_snapshots.id"],
            name=op.f("fk_metric_values_snapshot_id_metric_snapshots"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "snapshot_id", "metric_name", name=op.f("pk_metric_values")
        ),
    )
    op.create_table(
        "publication_metric_states",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("manual_requested_at", sa.DateTime(), nullable=True),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'ok', 'stale', 'rate_limited', "
            "'reconnect_required', 'permission_required', 'remote_not_found', "
            "'remote_deleted')",
            name=op.f("ck_publication_metric_states_status_valid"),
        ),
        sa.CheckConstraint(
            "failure_count >= 0",
            name=op.f("ck_publication_metric_states_failure_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_publication_metric_states_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "publication_id", name=op.f("pk_publication_metric_states")
        ),
    )


def downgrade() -> None:
    op.drop_table("publication_metric_states")
    op.drop_table("metric_values")
    op.drop_index(
        "ix_metric_snapshots_publication_id_captured_at",
        table_name="metric_snapshots",
    )
    op.drop_table("metric_snapshots")
