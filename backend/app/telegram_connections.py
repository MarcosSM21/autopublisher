"""Telegram user account connection over MTProto (see
specs/015-telegram-user-publishing, contracts/api.md).

The accounts core knows nothing about Telegram: connections are looked up here by
`account_id`. The authorized session lives only in the secure credential store (service
`autopublisher.telegram`); SQLite keeps a non-secret `credential_ref`, the public
identity and the destination channel. A login waiting for its code or 2FA password is
kept in memory only and is lost on restart.

At most one Telegram client uses the session of an account at a time
(`account_session`, research §2): publications wait for it, interactive routes answer
`409 telegram_busy`. Different accounts never block each other.
"""

import json
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import TELEGRAM_LOGIN_TTL, get_telegram_app_file
from app.credential_store import CredentialStore, CredentialStoreUnavailable
from app.db import get_session, utc_now
from app.errors import AppError, ConflictError, NotFoundError
from app.models import (
    Account,
    Platform,
    Project,
    Publication,
    PublicationStatus,
    TelegramConnection,
    TelegramConnectionStatus,
)
from app.schemas import (
    TelegramChannelRead,
    TelegramChannelsRead,
    TelegramChannelWrite,
    TelegramConnectionRead,
    TelegramIdentityRead,
    TelegramLoginCodeWrite,
    TelegramLoginPasswordWrite,
    TelegramLoginRead,
    TelegramLoginStartWrite,
)
from app.telegram_gateway import (
    PasswordRequired,
    PendingLogin,
    SignedIn,
    TelegramAppConfig,
    TelegramChannel,
    TelegramError,
    TelegramGateway,
    TelegramIdentity,
    TelegramLoginInvalid,
    TelegramRateLimited,
    TelegramUnauthorized,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["telegram"])

SessionDep = Annotated[Session, Depends(get_session)]

# Statuses that freeze the destination channel of an account (FR-014a).
PENDING_STATUSES = (PublicationStatus.SCHEDULED, PublicationStatus.PUBLISHING)
# How often a waiting publication checks whether the application is stopping.
LOCK_POLL_SECONDS = 1.0

NOT_CONFIGURED_MESSAGE = (
    "Telegram is not configured. Add your api_id and api_hash to the local Telegram "
    "app file (see docs/telegram.md)."
)
BUSY_MESSAGE = (
    "Telegram is busy with another operation of this account. Try again in a moment."
)
STORE_UNAVAILABLE_MESSAGE = (
    "The system's secure credential storage is not available. Unlock it and try again."
)
UNAVAILABLE_MESSAGE = "Telegram could not be reached. Try again in a moment."
RATE_LIMITED_MESSAGE = "Telegram asks to wait {seconds} seconds before trying again."
NOT_CONNECTED_MESSAGE = "This Telegram account is not connected."
ALREADY_CONNECTED_MESSAGE = (
    "This Telegram account is already connected. Disconnect it first to connect "
    "another Telegram account."
)
RECONNECT_MESSAGE = (
    "The Telegram session is no longer valid. Connect the account again."
)
LOGIN_NOT_PENDING_MESSAGE = (
    "There is no Telegram login waiting for this step. Start the connection again."
)
IDENTITY_MISMATCH_MESSAGE = (
    "You signed in with a different Telegram account. Disconnect this account first "
    "to connect another one."
)
CHANNEL_BLOCKED_MESSAGE = (
    "Finish or cancel the pending Telegram publications of this account before "
    "changing its channel."
)
CHANNEL_NOT_ELIGIBLE_MESSAGE = (
    "This channel is not one of the broadcast channels where you can post."
)


# --- App configuration ----------------------------------------------------------------


class TelegramNotConfigured(Exception):
    pass


def load_telegram_app_config(path: Path) -> TelegramAppConfig:
    """Read the local Telegram app JSON; raise TelegramNotConfigured if unusable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise TelegramNotConfigured() from None
    if not isinstance(data, dict):
        raise TelegramNotConfigured()
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    if isinstance(api_id, str) and api_id.isdigit():
        api_id = int(api_id)
    if not isinstance(api_id, int) or isinstance(api_id, bool) or api_id <= 0:
        raise TelegramNotConfigured()
    if not isinstance(api_hash, str) or not api_hash.strip():
        raise TelegramNotConfigured()
    return TelegramAppConfig(api_id, api_hash.strip())


def configured() -> bool:
    try:
        load_telegram_app_config(get_telegram_app_file())
    except TelegramNotConfigured:
        return False
    return True


def load_config() -> TelegramAppConfig:
    try:
        return load_telegram_app_config(get_telegram_app_file())
    except TelegramNotConfigured:
        raise AppError(503, "telegram_not_configured", NOT_CONFIGURED_MESSAGE) from None


# --- One client per account at a time -------------------------------------------------


class SessionWaitStopped(Exception):
    """The application stopped while waiting for the account's session."""


_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(account_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(account_id, threading.Lock())


def busy_error() -> AppError:
    return AppError(409, "telegram_busy", BUSY_MESSAGE)


@contextmanager
def account_session(
    account_id: int,
    *,
    wait: bool,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[None]:
    """Hold the session of one account for the whole life of one Telegram client.

    `wait=False` raises `409 telegram_busy` when it is in use; `wait=True` waits,
    giving up with `SessionWaitStopped` if `should_stop()` becomes true.
    """
    lock = _lock_for(account_id)
    if wait:
        while not lock.acquire(timeout=LOCK_POLL_SECONDS):
            if should_stop is not None and should_stop():
                raise SessionWaitStopped()
    elif not lock.acquire(blocking=False):
        raise busy_error()
    try:
        yield
    finally:
        lock.release()


# --- Pending logins (memory only) -----------------------------------------------------


@dataclass(frozen=True)
class TelegramLogin:
    step: str  # "code" | "password"
    session: str = field(repr=False)
    phone: str = field(repr=False)
    phone_code_hash: str = field(repr=False)
    expires_at: datetime


class TelegramLoginRegistry:
    """Logins waiting for a code or a password, by account; latest one wins."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._logins: dict[int, TelegramLogin] = {}

    def put(self, account_id: int, login: TelegramLogin) -> None:
        with self._lock:
            self._logins[account_id] = login

    def get(self, account_id: int) -> TelegramLogin | None:
        with self._lock:
            login = self._logins.get(account_id)
            if login is not None and login.expires_at <= self.clock():
                del self._logins[account_id]
                return None
            return login

    def discard(self, account_id: int) -> None:
        with self._lock:
            self._logins.pop(account_id, None)


# --- Dependencies ---------------------------------------------------------------------


def get_telegram_credential_store(request: Request) -> CredentialStore:
    store: CredentialStore = request.app.state.telegram_credential_store
    return store


def get_telegram_gateway(request: Request) -> TelegramGateway:
    gateway: TelegramGateway = request.app.state.telegram_gateway
    return gateway


def get_telegram_registry(request: Request) -> TelegramLoginRegistry:
    registry: TelegramLoginRegistry = request.app.state.telegram_logins
    return registry


StoreDep = Annotated[CredentialStore, Depends(get_telegram_credential_store)]
GatewayDep = Annotated[TelegramGateway, Depends(get_telegram_gateway)]
RegistryDep = Annotated[TelegramLoginRegistry, Depends(get_telegram_registry)]


# --- Helpers --------------------------------------------------------------------------


def _commit(session: Session) -> None:
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise


def _store_unavailable() -> AppError:
    return AppError(503, "credential_store_unavailable", STORE_UNAVAILABLE_MESSAGE)


def gateway_error(error: TelegramError) -> AppError:
    """Safe API error for a Telegram failure (contracts/api.md)."""
    if isinstance(error, TelegramRateLimited):
        return AppError(
            429,
            "telegram_rate_limited",
            RATE_LIMITED_MESSAGE.format(seconds=error.seconds),
        )
    if isinstance(error, TelegramLoginInvalid):
        return AppError(422, "telegram_login_invalid", error.reason)
    if isinstance(error, TelegramUnauthorized):
        return AppError(409, "telegram_reconnect_required", RECONNECT_MESSAGE)
    return AppError(503, "telegram_unavailable", UNAVAILABLE_MESSAGE)


def get_telegram_account_or_error(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError("Account not found.")
    if account.platform != Platform.TELEGRAM:
        raise ConflictError(
            "platform_not_supported", "Only Telegram accounts can be connected."
        )
    return account


def ensure_account_connectable(session: Session, account: Account) -> None:
    """Active operations need an active project and an active account."""
    project = session.get(Project, account.project_id)
    if project is None or not project.is_active:
        raise ConflictError(
            "project_inactive", "Reactivate the project before connecting accounts."
        )
    if not account.is_active:
        raise ConflictError(
            "account_inactive", "Reactivate the account before connecting it."
        )


def get_connection(session: Session, account_id: int) -> TelegramConnection | None:
    return session.scalars(
        select(TelegramConnection).where(TelegramConnection.account_id == account_id)
    ).one_or_none()


def channel_change_blocked(session: Session, account_id: int) -> bool:
    """Whether a Telegram publication of the account is scheduled or publishing."""
    return (
        session.scalars(
            select(Publication.id)
            .where(
                Publication.account_id == account_id,
                Publication.status.in_(PENDING_STATUSES),
            )
            .limit(1)
        ).first()
        is not None
    )


def mark_reconnect_required(
    session: Session, connection: TelegramConnection, now: datetime
) -> None:
    if connection.status != TelegramConnectionStatus.RECONNECT_REQUIRED:
        connection.status = TelegramConnectionStatus.RECONNECT_REQUIRED
        connection.updated_at = now
        _commit(session)


def _secret(session_string: str, user_id: str) -> str:
    return json.dumps({"v": 1, "session": session_string, "user_id": user_id})


def load_session(store: CredentialStore, connection: TelegramConnection) -> str | None:
    """The stored session, or None when missing or unreadable (raises if the store
    is unavailable)."""
    raw = store.get(connection.credential_ref)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    value = data.get("session") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value:
        return None
    if data.get("user_id") != connection.telegram_user_id:
        return None
    return value


def _phone_hint(phone: str) -> str:
    return f"{phone[:3]}{'•' * max(len(phone) - 5, 1)}{phone[-2:]}"


def connection_to_read(
    session: Session,
    account_id: int,
    connection: TelegramConnection | None,
    login: TelegramLogin | None,
    now: datetime,
) -> TelegramConnectionRead:
    login_read = (
        TelegramLoginRead(
            step="password" if login.step == "password" else "code",
            phone_hint=_phone_hint(login.phone),
            expires_at=login.expires_at,
        )
        if login is not None
        else None
    )
    blocked = channel_change_blocked(session, account_id)
    if connection is None:
        return TelegramConnectionRead(
            account_id=account_id,
            configured=configured(),
            status="not_connected",
            identity=None,
            channel=None,
            channel_change_blocked=blocked,
            login=login_read,
            connected_at=None,
            last_verified_at=None,
            rate_limited_until=None,
        )
    channel = (
        TelegramChannelRead(
            channel_id=connection.channel_id,
            title=connection.channel_title or "",
            username=connection.channel_username,
        )
        if connection.channel_id is not None
        else None
    )
    flood_until = connection.flood_wait_until
    return TelegramConnectionRead(
        account_id=account_id,
        configured=configured(),
        status=(
            "connected"
            if connection.status == TelegramConnectionStatus.CONNECTED
            else "reconnect_required"
        ),
        identity=TelegramIdentityRead(
            telegram_user_id=connection.telegram_user_id,
            display_name=connection.display_name,
            username=connection.username,
        ),
        channel=channel,
        channel_change_blocked=blocked,
        login=login_read,
        connected_at=connection.connected_at,
        last_verified_at=connection.last_verified_at,
        rate_limited_until=(
            flood_until if flood_until is not None and flood_until > now else None
        ),
    )


def _read(
    session: Session, registry: TelegramLoginRegistry, account_id: int
) -> TelegramConnectionRead:
    return connection_to_read(
        session,
        account_id,
        get_connection(session, account_id),
        registry.get(account_id),
        registry.clock(),
    )


def _forget_session(
    gateway: TelegramGateway, config: TelegramAppConfig, session_string: str
) -> None:
    """Best effort: revoke a session AutoPublisher will not keep."""
    try:
        gateway.log_out(config, session_string)
    except Exception as error:  # Never hides the original failure.
        logger.warning(
            "An unused Telegram session could not be revoked (%s).",
            type(error).__name__,
        )


def _complete_login(
    session: Session,
    store: CredentialStore,
    gateway: TelegramGateway,
    registry: TelegramLoginRegistry,
    config: TelegramAppConfig,
    account: Account,
    signed_in: SignedIn,
) -> None:
    """Store the authorized session and create or renew the connection."""
    registry.discard(account.id)
    identity: TelegramIdentity = signed_in.identity
    now = registry.clock()
    connection = get_connection(session, account.id)
    if connection is not None and connection.telegram_user_id != identity.user_id:
        _forget_session(gateway, config, signed_in.session)
        raise AppError(409, "telegram_identity_mismatch", IDENTITY_MISMATCH_MESSAGE)
    ref = connection.credential_ref if connection is not None else uuid4().hex
    try:
        store.set(ref, _secret(signed_in.session, identity.user_id))
    except CredentialStoreUnavailable:
        _forget_session(gateway, config, signed_in.session)
        raise _store_unavailable() from None
    if connection is None:
        connection = TelegramConnection(
            account_id=account.id,
            project_id=account.project_id,
            credential_ref=ref,
            connected_at=now,
        )
        session.add(connection)
    connection.telegram_user_id = identity.user_id
    connection.display_name = identity.display_name
    connection.username = identity.username
    connection.status = TelegramConnectionStatus.CONNECTED
    connection.last_verified_at = now
    connection.updated_at = now
    try:
        _commit(session)
    except SQLAlchemyError:
        if connection.id is None:  # A new secret nothing would point to.
            try:
                store.delete(ref)
            except CredentialStoreUnavailable:
                pass
        raise


def _connected_or_error(session: Session, account_id: int) -> TelegramConnection:
    connection = get_connection(session, account_id)
    if connection is None:
        raise AppError(409, "telegram_not_connected", NOT_CONNECTED_MESSAGE)
    if connection.status != TelegramConnectionStatus.CONNECTED:
        raise AppError(409, "telegram_reconnect_required", RECONNECT_MESSAGE)
    return connection


def _session_or_reconnect(
    session: Session,
    store: CredentialStore,
    connection: TelegramConnection,
    now: datetime,
) -> str:
    try:
        session_string = load_session(store, connection)
    except CredentialStoreUnavailable:
        raise _store_unavailable() from None
    if session_string is None:
        mark_reconnect_required(session, connection, now)
        raise AppError(409, "telegram_reconnect_required", RECONNECT_MESSAGE)
    return session_string


def _raise_for(
    session: Session,
    connection: TelegramConnection,
    error: TelegramError,
    now: datetime,
) -> NoReturn:
    if isinstance(error, TelegramUnauthorized):
        mark_reconnect_required(session, connection, now)
    raise gateway_error(error) from None


# --- Routes ---------------------------------------------------------------------------

_BASE = "/accounts/{account_id}/telegram-connection"


@router.get(_BASE, response_model=TelegramConnectionRead)
def get_telegram_connection(
    account_id: int, session: SessionDep, registry: RegistryDep
) -> TelegramConnectionRead:
    get_telegram_account_or_error(session, account_id)
    return _read(session, registry, account_id)


@router.post(f"{_BASE}/login/start", response_model=TelegramConnectionRead)
def start_telegram_login(
    account_id: int,
    body: TelegramLoginStartWrite,
    session: SessionDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TelegramConnectionRead:
    account = get_telegram_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    connection = get_connection(session, account_id)
    if (
        connection is not None
        and connection.status == TelegramConnectionStatus.CONNECTED
    ):
        raise AppError(409, "telegram_already_connected", ALREADY_CONNECTED_MESSAGE)
    config = load_config()
    registry.discard(account_id)
    with account_session(account_id, wait=False):
        try:
            pending = gateway.send_code(config, body.phone)
        except TelegramError as error:
            raise gateway_error(error) from None
    registry.put(
        account_id,
        TelegramLogin(
            step="code",
            session=pending.session,
            phone=pending.phone,
            phone_code_hash=pending.phone_code_hash,
            expires_at=registry.clock() + TELEGRAM_LOGIN_TTL,
        ),
    )
    return _read(session, registry, account_id)


def _pending_login(
    registry: TelegramLoginRegistry, account_id: int, step: str
) -> TelegramLogin:
    login = registry.get(account_id)
    if login is None or login.step != step:
        raise AppError(409, "telegram_login_not_pending", LOGIN_NOT_PENDING_MESSAGE)
    return login


@router.post(f"{_BASE}/login/code", response_model=TelegramConnectionRead)
def submit_telegram_code(
    account_id: int,
    body: TelegramLoginCodeWrite,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TelegramConnectionRead:
    account = get_telegram_account_or_error(session, account_id)
    login = _pending_login(registry, account_id, "code")
    config = load_config()
    with account_session(account_id, wait=False):
        try:
            result = gateway.sign_in_code(
                config,
                PendingLogin(login.session, login.phone, login.phone_code_hash),
                body.code,
            )
        except TelegramError as error:
            raise gateway_error(error) from None
        if isinstance(result, PasswordRequired):
            registry.put(
                account_id, replace(login, step="password", session=result.session)
            )
        else:
            _complete_login(session, store, gateway, registry, config, account, result)
    return _read(session, registry, account_id)


@router.post(f"{_BASE}/login/password", response_model=TelegramConnectionRead)
def submit_telegram_password(
    account_id: int,
    body: TelegramLoginPasswordWrite,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TelegramConnectionRead:
    account = get_telegram_account_or_error(session, account_id)
    login = _pending_login(registry, account_id, "password")
    config = load_config()
    with account_session(account_id, wait=False):
        try:
            signed_in = gateway.sign_in_password(config, login.session, body.password)
        except TelegramError as error:
            raise gateway_error(error) from None
        _complete_login(session, store, gateway, registry, config, account, signed_in)
    return _read(session, registry, account_id)


@router.post(f"{_BASE}/login/cancel", response_model=TelegramConnectionRead)
def cancel_telegram_login(
    account_id: int, session: SessionDep, registry: RegistryDep
) -> TelegramConnectionRead:
    get_telegram_account_or_error(session, account_id)
    registry.discard(account_id)
    return _read(session, registry, account_id)


@router.post(f"{_BASE}/verify", response_model=TelegramConnectionRead)
def verify_telegram_connection(
    account_id: int,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TelegramConnectionRead:
    """A real check: the session must still be authorized for the same user."""
    get_telegram_account_or_error(session, account_id)
    connection = get_connection(session, account_id)
    if connection is None:
        raise AppError(409, "telegram_not_connected", NOT_CONNECTED_MESSAGE)
    config = load_config()
    now = registry.clock()
    with account_session(account_id, wait=False):
        try:
            session_string = load_session(store, connection)
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
        if session_string is None:
            mark_reconnect_required(session, connection, now)
            return _read(session, registry, account_id)
        try:
            identity = gateway.get_me(config, session_string)
        except TelegramUnauthorized:
            mark_reconnect_required(session, connection, now)
            return _read(session, registry, account_id)
        except TelegramError as error:
            raise gateway_error(error) from None
    if identity.user_id != connection.telegram_user_id:
        mark_reconnect_required(session, connection, now)
        return _read(session, registry, account_id)
    connection.display_name = identity.display_name
    connection.username = identity.username
    connection.status = TelegramConnectionStatus.CONNECTED
    connection.last_verified_at = now
    connection.updated_at = now
    _commit(session)
    return _read(session, registry, account_id)


def _eligible_channels(
    session: Session,
    store: CredentialStore,
    gateway: TelegramGateway,
    registry: TelegramLoginRegistry,
    connection: TelegramConnection,
) -> list[TelegramChannel]:
    config = load_config()
    now = registry.clock()
    with account_session(connection.account_id, wait=False):
        session_string = _session_or_reconnect(session, store, connection, now)
        try:
            return gateway.list_channels(config, session_string)
        except TelegramError as error:
            _raise_for(session, connection, error, now)


@router.get(f"{_BASE}/channels", response_model=TelegramChannelsRead)
def list_telegram_channels(
    account_id: int,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TelegramChannelsRead:
    get_telegram_account_or_error(session, account_id)
    connection = _connected_or_error(session, account_id)
    channels = _eligible_channels(session, store, gateway, registry, connection)
    return TelegramChannelsRead(
        channels=[
            TelegramChannelRead(
                channel_id=channel.channel_id,
                title=channel.title,
                username=channel.username,
            )
            for channel in channels
        ]
    )


@router.put(f"{_BASE}/channel", response_model=TelegramConnectionRead)
def set_telegram_channel(
    account_id: int,
    body: TelegramChannelWrite,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TelegramConnectionRead:
    """Select the destination channel among the eligible ones, re-listed here so the
    access hash never travels through the API."""
    get_telegram_account_or_error(session, account_id)
    connection = _connected_or_error(session, account_id)
    if channel_change_blocked(session, account_id):
        raise AppError(409, "telegram_channel_change_blocked", CHANNEL_BLOCKED_MESSAGE)
    channels = _eligible_channels(session, store, gateway, registry, connection)
    chosen = next(
        (item for item in channels if item.channel_id == body.channel_id), None
    )
    if chosen is None:
        raise AppError(
            422, "telegram_channel_not_eligible", CHANNEL_NOT_ELIGIBLE_MESSAGE
        )
    # Checked again: a publication may have been scheduled meanwhile.
    if channel_change_blocked(session, account_id):
        raise AppError(409, "telegram_channel_change_blocked", CHANNEL_BLOCKED_MESSAGE)
    connection.channel_id = chosen.channel_id
    connection.channel_access_hash = chosen.access_hash
    connection.channel_title = chosen.title
    connection.channel_username = chosen.username
    connection.updated_at = registry.clock()
    _commit(session)
    return _read(session, registry, account_id)
