from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session, utc_now
from app.errors import AppError, ConflictError, NotFoundError
from app.models import Account
from app.normalization import normalize_key
from app.projects import get_project_or_404
from app.schemas import AccountCreate, AccountRead, AccountUpdate, Handle

router = APIRouter(prefix="/api", tags=["accounts"])

SessionDep = Annotated[Session, Depends(get_session)]
_HANDLE: TypeAdapter[str] = TypeAdapter(Handle)


# --- Connection health (Feature 018, research.md §8) -----------------------------


@dataclass(frozen=True)
class ConnectionIdentity:
    """Who the connection belongs to, as shown to the user: never platform ids,
    tokens or credential references."""

    name: str
    username: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True)
class AccountIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ConnectionHealth:
    """Health of an existing connection row, read from SQLite columns only.

    Each connection module builds it with `health_of(connection, now)`; the account
    states that need no connection (`inactive`, `not_connected`) and the `expiring`
    flag are added by `overview.account_health`, the only place that combines them.
    """

    state: Literal["ready", "reconnect_needed", "setup_required"]
    identity: ConnectionIdentity
    expires_at: datetime | None = None
    issue: AccountIssue | None = None


def reconnect_issue(platform: str) -> AccountIssue:
    return AccountIssue(
        "reconnect_required",
        f"{platform} no longer accepts the saved login. Reconnect to keep publishing.",
    )


def expired_issue(platform: str) -> AccountIssue:
    return AccountIssue(
        "credential_expired",
        f"The {platform} login has expired. Reconnect to keep publishing.",
    )


def expiring_connection_health(
    platform: str,
    status: str,
    identity: ConnectionIdentity,
    expires_at: datetime,
    now: datetime,
) -> ConnectionHealth:
    """Shared by connections whose credential has a local expiry."""
    if status == "reconnect_required":
        return ConnectionHealth(
            "reconnect_needed", identity, expires_at, reconnect_issue(platform)
        )
    if expires_at <= now:
        return ConnectionHealth(
            "reconnect_needed", identity, expires_at, expired_issue(platform)
        )
    return ConnectionHealth("ready", identity, expires_at)


AUTHORIZATION_GONE_MESSAGE = (
    "This authorization is no longer valid: the account was removed. "
    "Start the connection again from AutoPublisher."
)


def account_gone_now(session_factory: sessionmaker[Session], account_id: int) -> bool:
    """After a failed completion: whether the account was deleted meanwhile (read in
    a fresh session, the failed `write_transaction` is already closed)."""
    with session_factory() as session:
        return session.get(Account, account_id) is None


class AccountGone(Exception):
    """The account was deleted before a connection result could be saved."""


def reread_account(session: Session, account_id: int, platform: str) -> Account:
    """The account as committed now, read inside the `write_transaction` that saves
    a connection result (Feature 021, research §9b). A late result for a deleted
    account raises `AccountGone`: nothing is ever recreated for it."""
    account = session.get(Account, account_id)
    if account is None or account.platform != platform:
        raise AccountGone()
    return account


def authorization_gone() -> AppError:
    return AppError(409, "oauth_state_invalid", AUTHORIZATION_GONE_MESSAGE)


def adopt_connected_identity(
    session: Session, account: Account, candidate: str | None
) -> None:
    """Give a provisional account the identity of its first connection (no commit).

    Only when the handle is still NULL; never overwrites one. The candidate goes
    through the same rules as any handle (`Handle`); if it is empty, invalid or
    already used on the platform in the project, the handle stays NULL and the
    connection is not affected (its identity stays visible through health).
    """
    if account.handle is not None or candidate is None:
        return
    try:
        handle = _HANDLE.validate_python(candidate)
    except ValidationError:
        return
    handle_key = normalize_key(handle)
    taken = session.scalars(
        select(Account.id).where(
            Account.project_id == account.project_id,
            Account.platform == account.platform,
            Account.handle_key == handle_key,
            Account.id != account.id,
        )
    ).first()
    if taken is None:
        account.handle = handle
        account.handle_key = handle_key


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
    # Without a handle the account is provisional: NULL, never a made-up value.
    handle_key = None
    if body.handle is not None:
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
