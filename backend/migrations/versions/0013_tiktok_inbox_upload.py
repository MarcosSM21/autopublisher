"""TikTok Upload to Inbox: the generic `awaiting_user_action` status, the TikTok mode
of a publication and Upload to Inbox progress in TikTok publish runs.

Every TikTok publication created before this revision becomes Direct Post (the only
mode that existed): existing options rows get `mode = 'DIRECT_POST'` and publications
without options get a row with the initial values and that mode. New rows have no
default mode. Downgrading is only possible while no publication is awaiting user
action; it aborts before touching anything otherwise (statuses are never remapped).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-15
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_WHERE = "status NOT IN ('cancelled', 'published')"

OLD_STATUS_VALID = (
    "status IN ('unscheduled', 'scheduled', 'cancelled', 'publishing', "
    "'published', 'failed')"
)
OLD_STATUS_MATCHES_SCHEDULE = (
    "status IN ('cancelled', 'publishing', 'published', 'failed')"
    " OR (status = 'scheduled' AND scheduled_at IS NOT NULL)"
    " OR (status = 'unscheduled' AND scheduled_at IS NULL)"
)
STATUS_VALID = (
    "status IN ('unscheduled', 'scheduled', 'cancelled', 'publishing', "
    "'published', 'failed', 'awaiting_user_action')"
)
STATUS_MATCHES_SCHEDULE = (
    "status IN ('cancelled', 'publishing', 'published', 'failed', "
    "'awaiting_user_action')"
    " OR (status = 'scheduled' AND scheduled_at IS NOT NULL)"
    " OR (status = 'unscheduled' AND scheduled_at IS NULL)"
)

OPTIONS_MODE_VALID = "mode IS NULL OR mode IN ('DIRECT_POST', 'INBOX_UPLOAD')"

OLD_PHASE_VALID = (
    "phase IN ('preparing', 'initializing', 'uploading', 'final_chunk', "
    "'processing', 'succeeded', 'failed')"
)
PHASE_VALID = (
    "phase IN ('preparing', 'initializing', 'uploading', 'final_chunk', "
    "'processing', 'delivered', 'succeeded', 'failed')"
)
RUN_CHECKS = {
    "mode_valid": "mode IN ('DIRECT_POST', 'INBOX_UPLOAD')",
    "delivered_only_inbox": (
        "(phase <> 'delivered' AND delivered_to_inbox_at IS NULL) "
        "OR mode = 'INBOX_UPLOAD'"
    ),
    "user_published_only_inbox": "user_published_at IS NULL OR mode = 'INBOX_UPLOAD'",
    "public_post_count_valid": "public_post_count IS NULL OR public_post_count >= 0",
}


def _publication_checks(status_valid: str, matches_schedule: str) -> None:
    # Batch rebuilds keep the CHECKs but not the WHERE clause of partial indexes.
    with op.batch_alter_table("publications", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_publications_status_valid"), type_="check")
        batch.drop_constraint(
            op.f("ck_publications_status_matches_schedule"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_publications_status_valid"), status_valid
        )
        batch.create_check_constraint(
            op.f("ck_publications_status_matches_schedule"), matches_schedule
        )
    op.drop_index("uq_publications_active_content_account", table_name="publications")
    op.create_index(
        "uq_publications_active_content_account",
        "publications",
        ["content_id", "account_id"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_WHERE),
    )


def upgrade() -> None:
    _publication_checks(STATUS_VALID, STATUS_MATCHES_SCHEDULE)

    # --- TikTok options: the mode, never defaulted --------------------------------
    with op.batch_alter_table("tiktok_publication_options", recreate="always") as batch:
        batch.add_column(sa.Column("mode", sa.String(length=16), nullable=True))
        batch.create_check_constraint(
            op.f("ck_tiktok_publication_options_mode_valid"), OPTIONS_MODE_VALID
        )
    op.execute("UPDATE tiktok_publication_options SET mode = 'DIRECT_POST'")
    # Stored as naive UTC like every other timestamp.
    now = datetime.now(UTC).replace(tzinfo=None)
    op.get_bind().execute(
        sa.text(
            "INSERT INTO tiktok_publication_options (publication_id, mode, "
            "privacy_level, allow_comment, allow_duet, allow_stitch, "
            "commercial_disclosure_enabled, brand_organic_toggle, "
            "brand_content_toggle, is_aigc, updated_at) "
            "SELECT p.id, 'DIRECT_POST', NULL, 0, 0, 0, 0, 0, 0, NULL, :now "
            "FROM publications p JOIN accounts a ON a.id = p.account_id "
            "WHERE a.platform = 'tiktok' AND NOT EXISTS (SELECT 1 FROM "
            "tiktok_publication_options o WHERE o.publication_id = p.id)"
        ),
        {"now": now},
    )

    # --- TikTok publish runs: frozen mode and Upload to Inbox progress -------------
    with op.batch_alter_table("tiktok_publish_runs", recreate="always") as batch:
        batch.add_column(sa.Column("mode", sa.String(length=16), nullable=True))
        batch.add_column(
            sa.Column("delivered_to_inbox_at", sa.DateTime(), nullable=True)
        )
        batch.add_column(sa.Column("user_published_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("public_post_count", sa.Integer(), nullable=True))
    op.execute("UPDATE tiktok_publish_runs SET mode = 'DIRECT_POST'")
    with op.batch_alter_table("tiktok_publish_runs", recreate="always") as batch:
        batch.alter_column("mode", existing_type=sa.String(length=16), nullable=False)
        batch.drop_constraint(op.f("ck_tiktok_publish_runs_phase_valid"), type_="check")
        batch.create_check_constraint(
            op.f("ck_tiktok_publish_runs_phase_valid"), PHASE_VALID
        )
        for name, condition in RUN_CHECKS.items():
            batch.create_check_constraint(
                op.f(f"ck_tiktok_publish_runs_{name}"), condition
            )


def downgrade() -> None:
    awaiting = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM publications "
                "WHERE status = 'awaiting_user_action'"
            )
        )
        .scalar_one()
    )
    if awaiting:
        raise RuntimeError(
            f"Cannot downgrade: {awaiting} publication(s) are awaiting user action "
            "in TikTok; resolve them first."
        )

    with op.batch_alter_table("tiktok_publish_runs", recreate="always") as batch:
        for name in RUN_CHECKS:
            batch.drop_constraint(op.f(f"ck_tiktok_publish_runs_{name}"), type_="check")
        batch.drop_constraint(op.f("ck_tiktok_publish_runs_phase_valid"), type_="check")
        batch.create_check_constraint(
            op.f("ck_tiktok_publish_runs_phase_valid"), OLD_PHASE_VALID
        )
        batch.drop_column("public_post_count")
        batch.drop_column("user_published_at")
        batch.drop_column("delivered_to_inbox_at")
        batch.drop_column("mode")

    with op.batch_alter_table("tiktok_publication_options", recreate="always") as batch:
        batch.drop_constraint(
            op.f("ck_tiktok_publication_options_mode_valid"), type_="check"
        )
        batch.drop_column("mode")

    _publication_checks(OLD_STATUS_VALID, OLD_STATUS_MATCHES_SCHEDULE)
