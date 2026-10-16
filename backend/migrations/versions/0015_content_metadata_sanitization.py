"""Content metadata state and clean copy (Remove metadata).

Every existing content becomes `unknown`: its original keeps being published as is.
Downgrade drops the columns; clean copies (`*.clean.*` files) are left on disk because
a downgrade never deletes media files, and earlier revisions have no sweep for them.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COPY_COLUMNS = (
    "sanitized_storage_path",
    "sanitized_checksum",
    "sanitized_size_bytes",
    "sanitized_at",
)


def upgrade() -> None:
    with op.batch_alter_table("contents", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "metadata_status",
                sa.String(length=10),
                nullable=False,
                server_default="unknown",
            )
        )
        batch.add_column(
            sa.Column("sanitized_storage_path", sa.String(length=255), nullable=True)
        )
        batch.add_column(
            sa.Column("sanitized_checksum", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("sanitized_size_bytes", sa.Integer(), nullable=True)
        )
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        batch.add_column(sa.Column("sanitized_at", sa.DateTime(), nullable=True))
        batch.create_unique_constraint(
            op.f("uq_contents_sanitized_storage_path"), ["sanitized_storage_path"]
        )
        batch.create_check_constraint(
            op.f("ck_contents_metadata_status_valid"),
            "metadata_status IN ('unknown', 'clean', 'sanitized')",
        )
        batch.create_check_constraint(
            op.f("ck_contents_sanitized_copy_complete"),
            "metadata_status != 'sanitized' OR ("
            + " AND ".join(f"{c} IS NOT NULL" for c in COPY_COLUMNS)
            + ")",
        )
        batch.create_check_constraint(
            op.f("ck_contents_sanitized_copy_only_sanitized"),
            "metadata_status = 'sanitized' OR ("
            + " AND ".join(f"{c} IS NULL" for c in COPY_COLUMNS)
            + ")",
        )


def downgrade() -> None:
    with op.batch_alter_table("contents", recreate="always") as batch:
        batch.drop_constraint(
            op.f("ck_contents_sanitized_copy_only_sanitized"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_contents_sanitized_copy_complete"), type_="check"
        )
        batch.drop_constraint(op.f("ck_contents_metadata_status_valid"), type_="check")
        batch.drop_constraint(
            op.f("uq_contents_sanitized_storage_path"), type_="unique"
        )
        for column in reversed(COPY_COLUMNS):
            batch.drop_column(column)
        batch.drop_column("metadata_status")
