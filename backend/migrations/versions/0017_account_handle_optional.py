"""Make the account handle optional (provisional accounts).

A NULL handle means only "identity not known yet": the account was created with a
platform and its identity is adopted when the connection completes. The unique key
(project, platform, handle_key) stays: SQLite treats NULLs as distinct.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HANDLE_PAIR = "(handle IS NULL) = (handle_key IS NULL)"


def upgrade() -> None:
    with op.batch_alter_table("accounts", recreate="always") as batch:
        batch.alter_column("handle", existing_type=sa.String(length=100), nullable=True)
        batch.alter_column("handle_key", existing_type=sa.String(), nullable=True)
        batch.create_check_constraint(op.f("ck_accounts_handle_pair"), HANDLE_PAIR)


def downgrade() -> None:
    provisional = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM accounts WHERE handle IS NULL"))
        .scalar_one()
    )
    if provisional:
        raise RuntimeError(
            f"Cannot downgrade: {provisional} account(s) have no handle yet; "
            "connect or discard them first."
        )
    with op.batch_alter_table("accounts", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_accounts_handle_pair"), type_="check")
        batch.alter_column(
            "handle", existing_type=sa.String(length=100), nullable=False
        )
        batch.alter_column("handle_key", existing_type=sa.String(), nullable=False)
