"""Publication execution: new statuses, attempts and YouTube options.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUS_VALID = "status IN ('unscheduled', 'scheduled', 'cancelled')"
OLD_STATUS_MATCHES_SCHEDULE = (
    "status = 'cancelled'"
    " OR (status = 'scheduled' AND scheduled_at IS NOT NULL)"
    " OR (status = 'unscheduled' AND scheduled_at IS NULL)"
)
STATUS_VALID = (
    "status IN ('unscheduled', 'scheduled', 'cancelled', 'publishing', "
    "'published', 'failed')"
)
STATUS_MATCHES_SCHEDULE = (
    "status IN ('cancelled', 'publishing', 'published', 'failed')"
    " OR (status = 'scheduled' AND scheduled_at IS NOT NULL)"
    " OR (status = 'unscheduled' AND scheduled_at IS NULL)"
)
PUBLISHED_AT_MATCHES_STATUS = "(status = 'published') = (published_at IS NOT NULL)"


def _replace_active_index(where: str) -> None:
    op.drop_index("uq_publications_active_content_account", table_name="publications")
    op.create_index(
        "uq_publications_active_content_account",
        "publications",
        ["content_id", "account_id"],
        unique=True,
        sqlite_where=sa.text(where),
    )


def upgrade() -> None:
    # SQLite cannot alter constraints in place: batch mode rebuilds the table.
    with op.batch_alter_table("publications", recreate="always") as batch:
        batch.add_column(sa.Column("published_at", sa.DateTime(), nullable=True))
        batch.drop_constraint(op.f("ck_publications_status_valid"), type_="check")
        batch.drop_constraint(
            op.f("ck_publications_status_matches_schedule"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_publications_status_valid"), STATUS_VALID
        )
        batch.create_check_constraint(
            op.f("ck_publications_status_matches_schedule"), STATUS_MATCHES_SCHEDULE
        )
        batch.create_check_constraint(
            op.f("ck_publications_published_at_matches_status"),
            PUBLISHED_AT_MATCHES_STATUS,
        )
    _replace_active_index("status NOT IN ('cancelled', 'published')")

    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("progress_updated_at", sa.DateTime(), nullable=True),
        sa.Column("bytes_sent", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("outcome_determined", sa.Boolean(), nullable=True),
        sa.Column("external_id", sa.String(length=100), nullable=True),
        sa.Column("external_url", sa.String(length=500), nullable=True),
        sa.Column("submitted", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_publication_attempts_status_valid"),
        ),
        sa.CheckConstraint(
            "stage IN ('preparing', 'uploading', 'final_chunk', 'done')",
            name=op.f("ck_publication_attempts_stage_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_publication_attempts_finished_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name=op.f("ck_publication_attempts_error_matches_status"),
        ),
        sa.CheckConstraint(
            "bytes_sent >= 0 AND total_bytes >= 0 AND bytes_sent <= total_bytes",
            name=op.f("ck_publication_attempts_bytes_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_publication_attempts_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_attempts")),
    )
    op.create_index(
        "uq_publication_attempts_running",
        "publication_attempts",
        ["publication_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_publication_attempts_publication_id_started_at",
        "publication_attempts",
        ["publication_id", "started_at"],
    )

    op.create_table(
        "youtube_publication_options",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("privacy_status", sa.String(length=10), nullable=False),
        sa.Column("made_for_kids", sa.Boolean(), nullable=True),
        sa.Column("contains_synthetic_media", sa.Boolean(), nullable=True),
        sa.Column("notify_subscribers", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "privacy_status IN ('private', 'unlisted', 'public')",
            name=op.f("ck_youtube_publication_options_privacy_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_youtube_publication_options_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "publication_id", name=op.f("pk_youtube_publication_options")
        ),
    )


def downgrade() -> None:
    # Only valid while no publication uses the new statuses.
    op.drop_table("youtube_publication_options")
    op.drop_index(
        "ix_publication_attempts_publication_id_started_at",
        table_name="publication_attempts",
    )
    op.drop_index("uq_publication_attempts_running", table_name="publication_attempts")
    op.drop_table("publication_attempts")
    with op.batch_alter_table("publications", recreate="always") as batch:
        batch.drop_constraint(
            op.f("ck_publications_published_at_matches_status"), type_="check"
        )
        batch.drop_constraint(op.f("ck_publications_status_valid"), type_="check")
        batch.drop_constraint(
            op.f("ck_publications_status_matches_schedule"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_publications_status_valid"), OLD_STATUS_VALID
        )
        batch.create_check_constraint(
            op.f("ck_publications_status_matches_schedule"), OLD_STATUS_MATCHES_SCHEDULE
        )
        batch.drop_column("published_at")
    _replace_active_index("status != 'cancelled'")
