"""Threads publishing: publications without content, Threads options and runs.

`publications.content_id` becomes nullable for text-only posts. Downgrading is only
possible while no publication lacks a content; it aborts before touching the schema
otherwise (publications are never deleted and contents never invented).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_WHERE = "status NOT IN ('cancelled', 'published')"


def _set_content_nullable(nullable: bool) -> None:
    # Batch rebuilds keep the CHECKs but not the WHERE clause of partial indexes.
    with op.batch_alter_table("publications", recreate="always") as batch:
        batch.alter_column("content_id", existing_type=sa.Integer(), nullable=nullable)
    op.drop_index("uq_publications_active_content_account", table_name="publications")
    op.create_index(
        "uq_publications_active_content_account",
        "publications",
        ["content_id", "account_id"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_WHERE),
    )


def upgrade() -> None:
    _set_content_nullable(True)

    op.create_table(
        "threads_publication_options",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("alt_text", sa.String(length=1000), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "alt_text IS NULL OR length(alt_text) <= 1000",
            name=op.f("ck_threads_publication_options_alt_text_length"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_threads_publication_options_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "publication_id", name=op.f("pk_threads_publication_options")
        ),
    )

    op.create_table(
        "threads_publish_runs",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("media_kind", sa.String(length=10), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("container_id", sa.String(length=64), nullable=True),
        sa.Column("container_created_at", sa.DateTime(), nullable=True),
        sa.Column("container_status", sa.String(length=20), nullable=True),
        sa.Column("container_error", sa.String(length=40), nullable=True),
        sa.Column("publish_started_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "phase IN ('preparing', 'delivering_media', 'creating_container', "
            "'processing_container', 'publishing', 'verifying_result', 'succeeded', "
            "'failed')",
            name=op.f("ck_threads_publish_runs_phase_valid"),
        ),
        sa.CheckConstraint(
            "media_kind IN ('text', 'image', 'video')",
            name=op.f("ck_threads_publish_runs_media_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["publication_attempts.id"],
            name=op.f("fk_threads_publish_runs_attempt_id_publication_attempts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_threads_publish_runs_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_threads_publish_runs")),
    )
    op.create_index(
        "ix_threads_publish_runs_publication_id_container_created_at",
        "threads_publish_runs",
        ["publication_id", "container_created_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    without_content = connection.execute(
        sa.text("SELECT COUNT(*) FROM publications WHERE content_id IS NULL")
    ).scalar_one()
    if without_content:
        raise RuntimeError(
            f"Cannot downgrade: {without_content} publications have no content "
            "(text posts introduced by 0010)."
        )
    op.drop_index(
        "ix_threads_publish_runs_publication_id_container_created_at",
        table_name="threads_publish_runs",
    )
    op.drop_table("threads_publish_runs")
    op.drop_table("threads_publication_options")
    _set_content_nullable(False)
