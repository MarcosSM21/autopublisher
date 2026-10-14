"""TikTok publishing: TikTok options (with the consent) and TikTok publish runs.

Neither table can hold the upload URL, tokens or raw TikTok answers.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tiktok_publication_options",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("privacy_level", sa.String(length=32), nullable=True),
        sa.Column(
            "allow_comment", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "allow_duet", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "allow_stitch", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "commercial_disclosure_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "brand_organic_toggle",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "brand_content_toggle",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("is_aigc", sa.Boolean(), nullable=True),
        sa.Column("consent_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("consent_declaration_version", sa.String(length=40), nullable=True),
        sa.Column("consented_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "privacy_level IS NULL OR privacy_level IN ('PUBLIC_TO_EVERYONE', "
            "'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY')",
            name=op.f("ck_tiktok_publication_options_privacy_valid"),
        ),
        sa.CheckConstraint(
            "commercial_disclosure_enabled = 1 OR "
            "(brand_organic_toggle = 0 AND brand_content_toggle = 0)",
            name=op.f("ck_tiktok_publication_options_brand_toggles_need_disclosure"),
        ),
        sa.CheckConstraint(
            "NOT (brand_content_toggle = 1 AND privacy_level = 'SELF_ONLY')",
            name=op.f("ck_tiktok_publication_options_branded_not_private"),
        ),
        sa.CheckConstraint(
            "(consent_fingerprint IS NULL) = (consent_declaration_version IS NULL) "
            "AND (consent_fingerprint IS NULL) = (consented_at IS NULL)",
            name=op.f("ck_tiktok_publication_options_consent_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_tiktok_publication_options_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "publication_id", name=op.f("pk_tiktok_publication_options")
        ),
    )

    op.create_table(
        "tiktok_publish_runs",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("publish_id", sa.String(length=64), nullable=True),
        sa.Column("video_size", sa.Integer(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("total_chunk_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_bytes", sa.Integer(), nullable=False),
        sa.Column("remote_uploaded_bytes", sa.Integer(), nullable=True),
        sa.Column("initialized_at", sa.DateTime(), nullable=True),
        sa.Column("final_chunk_started_at", sa.DateTime(), nullable=True),
        sa.Column("final_chunk_http_status", sa.Integer(), nullable=True),
        sa.Column("last_remote_status", sa.String(length=32), nullable=True),
        sa.Column("fail_reason", sa.String(length=64), nullable=True),
        sa.Column("last_log_id", sa.String(length=64), nullable=True),
        sa.Column("last_status_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "phase IN ('preparing', 'initializing', 'uploading', 'final_chunk', "
            "'processing', 'succeeded', 'failed')",
            name=op.f("ck_tiktok_publish_runs_phase_valid"),
        ),
        sa.CheckConstraint(
            "confirmed_bytes BETWEEN 0 AND video_size",
            name=op.f("ck_tiktok_publish_runs_confirmed_bytes_range"),
        ),
        sa.CheckConstraint(
            "total_chunk_count BETWEEN 1 AND 1000",
            name=op.f("ck_tiktok_publish_runs_total_chunk_count_range"),
        ),
        sa.CheckConstraint(
            "final_chunk_started_at IS NULL OR publish_id IS NOT NULL",
            name=op.f("ck_tiktok_publish_runs_write_ahead_needs_publish_id"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["publication_attempts.id"],
            name=op.f("fk_tiktok_publish_runs_attempt_id_publication_attempts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            name=op.f("fk_tiktok_publish_runs_publication_id_publications"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_tiktok_publish_runs")),
        sa.UniqueConstraint(
            "publish_id", name=op.f("uq_tiktok_publish_runs_publish_id")
        ),
    )
    op.create_index(
        "ix_tiktok_publish_runs_publication_id",
        "tiktok_publish_runs",
        ["publication_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tiktok_publish_runs_publication_id", table_name="tiktok_publish_runs"
    )
    op.drop_table("tiktok_publish_runs")
    op.drop_table("tiktok_publication_options")
