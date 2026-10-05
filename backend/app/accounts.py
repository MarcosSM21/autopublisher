from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session, utc_now
from app.errors import ConflictError, NotFoundError
from app.models import Account
from app.normalization import normalize_key
from app.projects import get_project_or_404
from app.schemas import AccountCreate, AccountRead, AccountUpdate

router = APIRouter(prefix="/api", tags=["accounts"])

SessionDep = Annotated[Session, Depends(get_session)]


def ensure_handle_available(
    session: Session,
    project_id: int,
    platform: str,
    handle_key: str,
    exclude_id: int | None = None,
) -> None:
    """Reject a handle already used on the platform in the project, even if inactive."""
    query = select(Account.id).where(
        Account.project_id == project_id,
        Account.platform == platform,
        Account.handle_key == handle_key,
    )
    if exclude_id is not None:
        query = query.where(Account.id != exclude_id)
    if session.scalars(query).first() is not None:
        raise ConflictError(
            "duplicate",
            "This project already has an account with this handle on this platform.",
            field="handle",
        )


@router.get("/projects/{project_id}/accounts", response_model=list[AccountRead])
def list_accounts(project_id: int, session: SessionDep) -> list[Account]:
    get_project_or_404(session, project_id)
    query = (
        select(Account)
        .where(Account.project_id == project_id)
        .order_by(Account.platform, Account.handle_key)
    )
    return list(session.scalars(query))


@router.post(
    "/projects/{project_id}/accounts",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    project_id: int, body: AccountCreate, session: SessionDep
) -> Account:
    project = get_project_or_404(session, project_id)
    if not project.is_active:
        raise ConflictError(
            "project_inactive", "Reactivate the project before adding accounts."
        )
    handle_key = normalize_key(body.handle)
    ensure_handle_available(session, project_id, body.platform, handle_key)
    now = utc_now()
    account = Account(
        project_id=project_id,
        platform=body.platform.value,
        handle=body.handle,
        handle_key=handle_key,
        display_name=body.display_name,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(account)
    session.commit()
    return account


@router.patch("/accounts/{account_id}", response_model=AccountRead)
def update_account(
    account_id: int, body: AccountUpdate, session: SessionDep
) -> Account:
    """Apply only effective changes; allowed whatever the project's state."""
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError("Account not found.")
    fields = body.model_fields_set
    changed = False

    if "handle" in fields and body.handle is not None and body.handle != account.handle:
        handle_key = normalize_key(body.handle)
        ensure_handle_available(
            session,
            account.project_id,
            account.platform,
            handle_key,
            exclude_id=account.id,
        )
        account.handle = body.handle
        account.handle_key = handle_key
        changed = True
    if "display_name" in fields and body.display_name != account.display_name:
        account.display_name = body.display_name
        changed = True
    if (
        "is_active" in fields
        and body.is_active is not None
        and body.is_active != account.is_active
    ):
        account.is_active = body.is_active
        changed = True

    if changed:
        account.updated_at = utc_now()
        session.commit()
    return account
