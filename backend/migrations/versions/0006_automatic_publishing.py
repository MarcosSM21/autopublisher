"""Automatic publishing: consent, last automatic failure, attempt trigger, pause.

Every existing publication stays disarmed: scheduled dates created before this
revision never caused real publications, so none of them may start automatically.
This revision only touches SQLite.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_WHERE = "status NOT IN ('cancelled', 'published')"


def _recreate_partial_index(
    name: str, table: str, columns: list[str], where: str
) -> None:
    # Batch rebuilds do not keep the WHERE clause of SQLite partial indexes.
    op.drop_index(name, table_name=table)
    op.create_index(name, table, columns, unique=True, sqlite_where=sa.text(where))


def upgrade() -> None:
    with op.batch_alter_table("publications", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "auto_publish_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("auto_publish_error_code", sa.String(length=40), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "auto_publish_error_message", sa.String(length=500), nullable=True
            )
        )
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        batch.add_column(
            sa.Column("auto_publish_failed_at", sa.DateTime(), nullable=True)
        )
        batch.create_check_constraint(
            op.f("ck_publications_auto_publish_only_scheduled"),
            "auto_publish_enabled = 0 OR status = 'scheduled'",
        )
        batch.create_check_constraint(
            op.f("ck_publications_auto_publish_error_only_armed"),
            "auto_publish_enabled = 1 OR (auto_publish_error_code IS NULL"
            " AND auto_publish_error_message IS NULL"
            " AND auto_publish_failed_at IS NULL)",
        )
        batch.create_check_constraint(
            op.f("ck_publications_auto_publish_error_pair"),
            "(auto_publish_error_code IS NULL) = (auto_publish_error_message IS NULL)"
            " AND (auto_publish_error_code IS NULL) = (auto_publish_failed_at IS NULL)",
        )
        batch.create_index(
            "ix_publications_status_auto_publish_scheduled_at",
            ["status", "auto_publish_enabled", "scheduled_at"],
        )
    _recreate_partial_index(
        "uq_publications_active_content_account",
        "publications",
        ["content_id", "account_id"],
        ACTIVE_WHERE,
    )

    with op.batch_alter_table("publication_attempts", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "trigger",
                sa.String(length=20),
                nullable=False,
                server_default="manual",
            )
        )
        batch.create_check_constraint(
            op.f("ck_publication_attempts_trigger_valid"),
            "trigger IN ('manual', 'scheduled')",
        )
    _recreate_partial_index(
        "uq_publication_attempts_running",
        "publication_attempts",
        ["publication_id"],
        "status = 'running'",
    )

    settings = op.create_table(
        "automation_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "automation_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_automation_settings_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_settings")),
    )
    # Not paused: nothing is armed after this revision, so nothing can start until
    # the user explicitly enables auto-publish on a publication.
    op.bulk_insert(
        settings,
        [
            {
                "id": 1,
                "automation_paused": False,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("automation_settings")
    with op.batch_alter_table("publication_attempts", recreate="always") as batch:
        batch.drop_constraint(
            op.f("ck_publication_attempts_trigger_valid"), type_="check"
        )
        batch.drop_column("trigger")
    _recreate_partial_index(
        "uq_publication_attempts_running",
        "publication_attempts",
        ["publication_id"],
        "status = 'running'",
    )
    with op.batch_alter_table("publications", recreate="always") as batch:
        batch.drop_index("ix_publications_status_auto_publish_scheduled_at")
        batch.drop_constraint(
            op.f("ck_publications_auto_publish_error_pair"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_publications_auto_publish_error_only_armed"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_publications_auto_publish_only_scheduled"), type_="check"
        )
        batch.drop_column("auto_publish_failed_at")
        batch.drop_column("auto_publish_error_message")
        batch.drop_column("auto_publish_error_code")
        batch.drop_column("auto_publish_enabled")
    _recreate_partial_index(
        "uq_publications_active_content_account",
        "publications",
        ["content_id", "account_id"],
        ACTIVE_WHERE,
    )
