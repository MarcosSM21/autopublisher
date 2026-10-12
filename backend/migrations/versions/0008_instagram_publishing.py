"""Instagram publishing: new attempt stages, Instagram options and runs, temporary
media.

Downgrading is only possible while no attempt uses the stages introduced here; it
aborts before touching the schema otherwise (stages are never mapped to other values).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STAGE_VALID = "stage IN ('preparing', 'uploading', 'final_chunk', 'done')"
STAGE_VALID = (
    "stage IN ('preparing', 'uploading', 'processing', 'finalizing', "
    "'final_chunk', 'done')"
)


def _replace_stage_check(check: str) -> None:
    with op.batch_alter_table("publication_attempts", recreate="always") as batch:
        batch.drop_constraint(
            op.f("ck_publication_attempts_stage_valid"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_publication_attempts_stage_valid"), check
        )
    # Batch rebuilds do not keep the WHERE clause of SQLite partial indexes.
    op.drop_index("uq_publication_attempts_running", table_name="publication_attempts")
    op.create_index(
        "uq_publication_attempts_running",
        "publication_attempts",
        ["publication_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )


def upgrade() -> None:
    _replace_stage_check(STAGE_VALID)

    op.create_table(
        "instagram_publication_options",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=True),
        sa.Column(
            "share_to_feed", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("alt_text", sa.String(length=1000), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "alt_text IS NULL OR length(alt_text) <= 1000",
            name=op.f("ck_instagram_publication_options_alt_text_length"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_instagram_publication_options_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "publication_id", name=op.f("pk_instagram_publication_options")
        ),
    )

    op.create_table(
        "temporary_media_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        # Random, non-secret key: it gives no access without a signature.
        sa.Column("object_key", sa.String(length=255), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "cleanup_failures",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_cleanup_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "size_bytes >= 0 AND cleanup_failures >= 0",
            name=op.f("ck_temporary_media_objects_counters_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["publication_attempts.id"],
            name=op.f("fk_temporary_media_objects_attempt_id_publication_attempts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_temporary_media_objects")),
        sa.UniqueConstraint(
            "object_key", name=op.f("uq_temporary_media_objects_object_key")
        ),
    )
    op.create_index(
        "ix_temporary_media_objects_pending", "temporary_media_objects", ["deleted_at"]
    )

    op.create_table(
        "instagram_publish_runs",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("media_kind", sa.String(length=10), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("container_id", sa.String(length=64), nullable=True),
        sa.Column("container_created_at", sa.DateTime(), nullable=True),
        sa.Column("container_status", sa.String(length=20), nullable=True),
        sa.Column("reused_from_attempt_id", sa.Integer(), nullable=True),
        sa.Column("publish_started_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "phase IN ('preparing', 'delivering_media', 'creating_container', "
            "'processing_container', 'publishing', 'verifying_result', 'succeeded', "
            "'failed')",
            name=op.f("ck_instagram_publish_runs_phase_valid"),
        ),
        sa.CheckConstraint(
            "media_kind IN ('image', 'reel')",
            name=op.f("ck_instagram_publish_runs_media_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["publication_attempts.id"],
            name=op.f("fk_instagram_publish_runs_attempt_id_publication_attempts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_instagram_publish_runs_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_instagram_publish_runs")),
    )
    op.create_index(
        "ix_instagram_publish_runs_publication_id_container_created_at",
        "instagram_publish_runs",
        ["publication_id", "container_created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    in_use = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM publication_attempts "
            "WHERE stage IN ('processing', 'finalizing')"
        )
    ).scalar_one()
    if in_use:
        raise RuntimeError(
            f"Cannot downgrade: {in_use} publication attempts use the stages "
            "'processing'/'finalizing' introduced by 0008."
        )
    op.drop_index(
        "ix_instagram_publish_runs_publication_id_container_created_at",
        table_name="instagram_publish_runs",
    )
    op.drop_table("instagram_publish_runs")
    op.drop_index(
        "ix_temporary_media_objects_pending", table_name="temporary_media_objects"
    )
    op.drop_table("temporary_media_objects")
    op.drop_table("instagram_publication_options")
    _replace_stage_check(OLD_STAGE_VALID)
