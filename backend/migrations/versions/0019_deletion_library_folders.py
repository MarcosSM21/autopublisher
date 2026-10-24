"""Deletion and Library folders (Feature 021).

Non-destructive: every row keeps its id and every existing media item stays in
Unsorted (`folder_id` NULL). Ids that appear in URLs stop being reused
(AUTOINCREMENT; `sqlite_sequence` starts at the current maximum). TikTok's
credential orphans become the generic `pending_credential_deletions` queue.
Foreign keys are off during migrations (Alembic's engine has no pragma).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTOINCREMENT = {"sqlite_autoincrement": True}
ACTIVE_WHERE = "status NOT IN ('cancelled', 'published')"
CREDENTIAL_PLATFORMS = "'youtube', 'instagram', 'threads', 'tiktok', 'telegram'"


def _recreate_partial_index(
    name: str, table: str, columns: list[str], where: str
) -> None:
    # Batch rebuilds do not keep the WHERE clause of SQLite partial indexes.
    op.drop_index(name, table_name=table)
    op.create_index(name, table, columns, unique=True, sqlite_where=sa.text(where))


def upgrade() -> None:
    op.create_table(
        "library_folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        # Stored as naive UTC; app.db.UTCDateTime restores the time zone on read.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "depth BETWEEN 1 AND 5", name=op.f("ck_library_folders_depth_range")
        ),
        sa.CheckConstraint(
            "(parent_id IS NULL) = (depth = 1)",
            name=op.f("ck_library_folders_root_depth"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id", "project_id"],
            ["library_folders.id", "library_folders.project_id"],
            name=op.f("fk_library_folders_parent_id_library_folders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_library_folders_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_folders")),
        sa.UniqueConstraint(
            "id", "project_id", name=op.f("uq_library_folders_id_project_id")
        ),
        **AUTOINCREMENT,
    )
    op.create_index(
        "uq_library_folders_root_name",
        "library_folders",
        ["project_id", "name_key"],
        unique=True,
        sqlite_where=sa.text("parent_id IS NULL"),
    )
    op.create_index(
        "uq_library_folders_child_name",
        "library_folders",
        ["parent_id", "name_key"],
        unique=True,
        sqlite_where=sa.text("parent_id IS NOT NULL"),
    )

    # Copying the rows with their ids sets `sqlite_sequence` to the current maximum.
    for table in ("projects", "accounts", "distribution_presets"):
        with op.batch_alter_table(table, recreate="always", table_kwargs=AUTOINCREMENT):
            pass

    with op.batch_alter_table(
        "contents", recreate="always", table_kwargs=AUTOINCREMENT
    ) as batch:
        batch.add_column(sa.Column("folder_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_contents_folder_id_library_folders"),
            "library_folders",
            ["folder_id", "project_id"],
            ["id", "project_id"],
            ondelete="RESTRICT",
        )
        batch.create_index(op.f("ix_contents_folder_id"), ["folder_id"])

    with op.batch_alter_table(
        "publications", recreate="always", table_kwargs=AUTOINCREMENT
    ):
        pass
    _recreate_partial_index(
        "uq_publications_active_content_account",
        "publications",
        ["content_id", "account_id"],
        ACTIVE_WHERE,
    )

    with op.batch_alter_table("temporary_media_objects") as batch:
        batch.alter_column("attempt_id", existing_type=sa.Integer(), nullable=True)

    op.create_table(
        "pending_file_deletions",
        sa.Column("storage_path", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("storage_path", name=op.f("pk_pending_file_deletions")),
    )
    op.create_table(
        "pending_credential_deletions",
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            f"platform IN ({CREDENTIAL_PLATFORMS})",
            name=op.f("ck_pending_credential_deletions_platform_valid"),
        ),
        sa.PrimaryKeyConstraint(
            "credential_ref", name=op.f("pk_pending_credential_deletions")
        ),
    )
    op.execute(
        "INSERT INTO pending_credential_deletions "
        "(credential_ref, platform, account_id, created_at) "
        "SELECT credential_ref, 'tiktok', account_id, created_at "
        "FROM tiktok_credential_orphans"
    )
    op.drop_table("tiktok_credential_orphans")


def downgrade() -> None:
    connection = op.get_bind()
    detached = connection.execute(
        sa.text("SELECT COUNT(*) FROM temporary_media_objects WHERE attempt_id IS NULL")
    ).scalar_one()
    if detached:
        raise RuntimeError(
            f"Cannot downgrade below 0019: {detached} temporary media object(s) "
            "belong to deleted posts. Let them be cleaned up first."
        )

    op.create_table(
        "tiktok_credential_orphans",
        sa.Column("credential_ref", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "credential_ref", name=op.f("pk_tiktok_credential_orphans")
        ),
    )
    op.execute(
        "INSERT INTO tiktok_credential_orphans (credential_ref, account_id, "
        "created_at) SELECT credential_ref, account_id, created_at "
        "FROM pending_credential_deletions WHERE platform = 'tiktok'"
    )
    op.drop_table("pending_credential_deletions")
    op.drop_table("pending_file_deletions")

    with op.batch_alter_table("temporary_media_objects") as batch:
        batch.alter_column("attempt_id", existing_type=sa.Integer(), nullable=False)

    # AUTOINCREMENT stays (harmless): ids are simply never reused.
    with op.batch_alter_table(
        "contents", recreate="always", table_kwargs=AUTOINCREMENT
    ) as batch:
        batch.drop_index(op.f("ix_contents_folder_id"))
        batch.drop_constraint(
            op.f("fk_contents_folder_id_library_folders"), type_="foreignkey"
        )
        batch.drop_column("folder_id")

    op.drop_index("uq_library_folders_child_name", table_name="library_folders")
    op.drop_index("uq_library_folders_root_name", table_name="library_folders")
    op.drop_table("library_folders")
