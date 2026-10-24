"""TikTok account connection over Login Kit for Desktop (see
specs/012-tiktok-oauth-connection).

The accounts core knows nothing about TikTok: connections are looked up here by
`account_id`. The credential (tokens, expiries, scopes) lives only in the secure
credential store (service `autopublisher.tiktok`) and that secret is the source of
truth; SQLite keeps a non-secret `credential_ref`, the public identity, the status and
an informational mirror of the expiries.

TikTok redirects the browser to the backend's loopback callback, which validates the
query strictly, uses the attempt once, exchanges the code and always answers with a
`303 See Other` to a clean result page, so `code` and `state` never stay in the
address bar. The frontend learns the result by polling the attempt.
"""

import html
import logging
import re
import threading
from collections.abc import Callable, Collection
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, NoReturn
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.accounts import (
    AccountGone,
    ConnectionHealth,
    ConnectionIdentity,
    account_gone_now,
    adopt_connected_identity,
    authorization_gone,
    expiring_connection_health,
    reread_account,
)
from app.cleanup import (
    CredentialTarget,
    PendingCredential,
    bounded,
    enqueue_credentials,
    queue_credential,
    run_credential_cleanup,
)
from app.config import TIKTOK_CALLBACK_PATH, get_tiktok_app_file
from app.credential_store import CredentialStore, CredentialStoreUnavailable
from app.db import get_session, get_session_factory, write_transaction
from app.errors import AppError, ConflictError, NotFoundError
from app.loopback import is_loopback_request, require_host_action
from app.models import (
    Account,
    Platform,
    Project,
    TikTokConnection,
    TikTokConnectionStatus,
)
from app.publications import account_reference
from app.schemas import (
    TikTokAuthorizeRead,
    TikTokCapabilitiesRead,
    TikTokConnectionRead,
    TikTokDisconnectRead,
    TikTokIdentityRead,
    TikTokOAuthAttemptRead,
    TikTokPermissionsRead,
)
from app.tiktok_gateway import (
    TikTokClientError,
    TikTokCredential,
    TikTokError,
    TikTokGateway,
    TikTokGrantInvalid,
    TikTokScopeMissing,
    TikTokTokenInvalid,
    TikTokUnavailable,
    TikTokUnexpectedResponse,
)
from app.tiktok_oauth import (
    REQUESTED_SCOPES,
    AttemptNotConfirmable,
    AttemptNotFound,
    CallbackInvalid,
    TikTokAppConfig,
    TikTokAttemptRegistry,
    TikTokAttemptStatus,
    TikTokIdentity,
    TikTokOAuthAttempt,
    TikTokOAuthNotConfigured,
    build_authorization_url,
    extract_state,
    generate_state,
    generate_tiktok_pkce_pair,
    load_tiktok_app_config,
    parse_callback,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tiktok"])

SessionDep = Annotated[Session, Depends(get_session)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]

RESULT_PATH = "/api/tiktok/oauth/result"

# Renewal policy (research §10): renew when the access token has at most
# REFRESH_MARGIN left; below EXPIRY_MARGIN it is no longer considered usable.
REFRESH_MARGIN = timedelta(hours=1)
EXPIRY_MARGIN = timedelta(minutes=5)

DOCS_HINT = "See docs/tiktok-accounts.md."
STORE_UNAVAILABLE_MESSAGE = (
    f"The system's secure credential storage is not available. {DOCS_HINT}"
)
NOT_CONFIGURED_MESSAGE = f"TikTok integration is not configured. {DOCS_HINT}"
PORT_MISMATCH_MESSAGE = (
    "The backend is not running on the port of the TikTok redirect URI. Start it on "
    f"that port or change the redirect URI. {DOCS_HINT}"
)
AUTHORIZATION_UNAVAILABLE_MESSAGE = (
    "Could not reach TikTok to finish the authorization. Check your connection and "
    "start the connection again."
)
UNEXPECTED_MESSAGE = "TikTok returned an unexpected response. Try again later."
INTERNAL_MESSAGE = "An unexpected error occurred. Please try again."
EXCHANGE_FAILED_MESSAGE = (
    "TikTok did not complete the authorization. Start the connection again."
)
CALLBACK_INVALID_MESSAGE = (
    "The response from TikTok was not valid. Start the connection again."
)
DENIED_MESSAGE = "The connection was cancelled in TikTok."
PROVIDER_ERROR_MESSAGE = (
    "TikTok could not complete the authorization. Make sure this TikTok account can "
    f"use your app (for example as a Sandbox target user) and try again. {DOCS_HINT}"
)
ALREADY_CONNECTED_MESSAGE = (
    "This TikTok account is already connected to another account in this project. "
    "Disconnect it there first."
)
CONNECTION_CHANGED_MESSAGE = (
    "The connection changed in the meantime. Start the connection again."
)
ATTEMPT_EXPIRED_MESSAGE = "This authorization has expired. Start the connection again."
NOT_CONNECTED_MESSAGE = "This TikTok account is not connected."
RECONNECT_REQUIRED_MESSAGE = (
    "The TikTok connection must be authorized again. Reconnect the account."
)
CREDENTIAL_LOST_MESSAGE = (
    "The stored TikTok credentials are missing. Reconnect the account."
)
REFRESH_EXPIRED_MESSAGE = (
    "The TikTok authorization has expired and cannot be renewed. Reconnect the account."
)
TOKEN_REJECTED_MESSAGE = (
    "TikTok no longer accepts this authorization. Reconnect the account."
)
IDENTITY_MISMATCH_MESSAGE = (
    "TikTok reports a different account than the linked one. Reconnect the account."
)
UNAVAILABLE_MESSAGE = "Could not reach TikTok. Check your connection and try again."
CLIENT_REJECTED_MESSAGE = (
    f"TikTok rejected AutoPublisher's app configuration. {DOCS_HINT}"
)
MANAGE_PERMISSIONS_HINT = (
    "You can remove its access in the TikTok app: Settings and privacy > Security and "
    "permissions > Manage app permissions."
)
REVOKE_FAILED_MESSAGE = (
    "TikTok did not confirm the revocation, so the connection was kept. Try again, or "
    "remove it locally without revoking."
)
CREDENTIAL_MISSING_MESSAGE = (
    "The stored TikTok credentials are missing, so AutoPublisher cannot revoke the "
    "access in TikTok. TikTok may still have AutoPublisher authorized: remove the "
    f"connection locally. {MANAGE_PERMISSIONS_HINT}"
)


def get_tiktok_credential_store(request: Request) -> CredentialStore:
    store: CredentialStore = request.app.state.tiktok_credential_store
    return store


def get_tiktok_gateway(request: Request) -> TikTokGateway:
    gateway: TikTokGateway = request.app.state.tiktok_gateway
    return gateway


def get_tiktok_registry(request: Request) -> TikTokAttemptRegistry:
    registry: TikTokAttemptRegistry = request.app.state.tiktok_attempts
    return registry


StoreDep = Annotated[CredentialStore, Depends(get_tiktok_credential_store)]
GatewayDep = Annotated[TikTokGateway, Depends(get_tiktok_gateway)]
RegistryDep = Annotated[TikTokAttemptRegistry, Depends(get_tiktok_registry)]


class TikTokCallbackOutcome(StrEnum):
    """Closed set of results of the clean result page (research §6.1)."""

    CONNECTED = "connected"
    CONFIRM_REQUIRED = "confirm_required"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INVALID = "invalid"


class AttemptFailure(Exception):
    """An expected failure while completing an authorization."""

    def __init__(
        self,
        code: str,
        message: str,
        outcome: TikTokCallbackOutcome = TikTokCallbackOutcome.FAILED,
        log_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.outcome = outcome
        self.log_id = log_id


def _commit(session: Session) -> None:
    """Single commit point of this module (tests inject persistence failures here)."""
    session.commit()


def _store_unavailable() -> AppError:
    return AppError(503, "credential_store_unavailable", STORE_UNAVAILABLE_MESSAGE)


def _not_configured(message: str = NOT_CONFIGURED_MESSAGE) -> AppError:
    return AppError(503, "tiktok_oauth_not_configured", message)


# --- Lookups and read models -------------------------------------------------------


def get_tiktok_account_or_error(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError("Account not found.")
    if account.platform != Platform.TIKTOK:
        raise ConflictError(
            "platform_not_supported", "Only TikTok accounts can be connected."
        )
    return account


def get_connection(session: Session, account_id: int) -> TikTokConnection | None:
    return session.scalars(
        select(TikTokConnection).where(TikTokConnection.account_id == account_id)
    ).first()


def oauth_configured() -> bool:
    """Whether the local TikTok app file is usable; read on every call."""
    try:
        load_tiktok_app_config(get_tiktok_app_file())
    except TikTokOAuthNotConfigured:
        return False
    return True


def load_config() -> TikTokAppConfig:
    try:
        return load_tiktok_app_config(get_tiktok_app_file())
    except TikTokOAuthNotConfigured:
        raise _not_configured() from None


def identity_of(connection: TikTokConnection) -> TikTokIdentity:
    return TikTokIdentity(
        open_id=connection.open_id,
        display_name=connection.display_name,
        avatar_url=connection.avatar_url,
    )


def _read_credential(store: CredentialStore, ref: str) -> TikTokCredential | None:
    """The stored credential, or None when missing or unreadable (raises
    CredentialStoreUnavailable if the store cannot be used)."""
    raw = store.get(ref)
    if raw is None:
        return None
    try:
        return TikTokCredential.from_json(raw)
    except ValueError:
        return None


def can_upload_to_inbox(store: CredentialStore, connection: TikTokConnection) -> bool:
    """Whether TikTok's last token response granted `video.upload`, read from the
    stored secret without any network; False when it cannot be read."""
    try:
        credential = _read_credential(store, connection.credential_ref)
    except CredentialStoreUnavailable:
        return False
    return credential is not None and credential.can_upload_to_inbox()


def _permissions(credential: TikTokCredential) -> TikTokPermissionsRead:
    """Scopes according to TikTok's last token response stored in the secret."""
    return TikTokPermissionsRead(
        granted=[name for name in REQUESTED_SCOPES if name in credential.scopes],
        source=credential.scopes_source,  # type: ignore[arg-type]
        confirmed_at=credential.obtained_at,
        capabilities=TikTokCapabilitiesRead(
            direct_post=credential.has_required_scopes(),
            inbox_upload=credential.can_upload_to_inbox(),
        ),
    )


def _sync_metadata(
    session: Session, connection: TikTokConnection, credential: TikTokCredential
) -> None:
    """Repair the SQLite mirror of the secret's expiries; idempotent and best-effort."""
    if (
        connection.access_expires_at == credential.access_expires_at
        and connection.refresh_expires_at == credential.refresh_expires_at
    ):
        return
    connection.access_expires_at = credential.access_expires_at
    connection.refresh_expires_at = credential.refresh_expires_at
    try:
        _commit(session)
    except Exception as error:
        session.rollback()
        logger.warning(
            "Could not repair the TikTok connection metadata of account %s (%s)",
            connection.account_id,
            type(error).__name__,
        )


def connection_to_read(
    session: Session,
    store: CredentialStore,
    connection: TikTokConnection | None,
    now: datetime,
    include_permissions: bool = False,
) -> TikTokConnectionRead:
    """Public view; never calls TikTok.

    The secret is read only for the single-connection views (`permissions`) or when
    the SQLite mirror says the renewable authorization expired: a later expiry in the
    secret repairs the mirror, a confirmed expiry or a missing secret marks
    `reconnect_required`, and an unavailable store changes nothing (data-model,
    "Lectura pública").
    """
    configured = oauth_configured()
    if connection is None:
        return TikTokConnectionRead(
            status="not_connected",
            identity=None,
            connected_at=None,
            last_verified_at=None,
            access_expires_at=None,
            refresh_expires_at=None,
            permissions=None,
            oauth_configured=configured,
        )
    stale = (
        connection.status == TikTokConnectionStatus.CONNECTED
        and connection.refresh_expires_at <= now
    )
    credential: TikTokCredential | None = None
    readable = False
    if include_permissions or stale:
        try:
            credential = _read_credential(store, connection.credential_ref)
            readable = True
        except CredentialStoreUnavailable:
            pass
    if stale and readable:
        if credential is not None and credential.refresh_expires_at > now:
            _sync_metadata(session, connection, credential)
        else:
            mark_reconnect_required(session, connection, now)
    return TikTokConnectionRead(
        status="connected"
        if connection.status == TikTokConnectionStatus.CONNECTED
        else "reconnect_required",
        identity=TikTokIdentityRead.model_validate(identity_of(connection).to_read()),
        connected_at=connection.connected_at,
        last_verified_at=connection.last_verified_at,
        access_expires_at=connection.access_expires_at,
        refresh_expires_at=connection.refresh_expires_at,
        permissions=_permissions(credential)
        if include_permissions and credential is not None
        else None,
        oauth_configured=configured,
    )


def attempt_to_read(attempt: TikTokOAuthAttempt) -> TikTokOAuthAttemptRead:
    return TikTokOAuthAttemptRead.model_validate(attempt.to_read())


# --- Rules -------------------------------------------------------------------------


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


def _already_connected(holder: Account | None) -> AppError:
    message = (
        f"This TikTok account is already connected to {account_reference(holder)} "
        "in this project. Disconnect it there first."
        if holder is not None
        else ALREADY_CONNECTED_MESSAGE
    )
    return AppError(409, "tiktok_account_already_connected", message)


def _identity_holder(
    session: Session, project_id: int, open_id: str, account_id: int
) -> Account | None:
    """Another account of the project linked to `open_id`, if any (active or
    not)."""
    return session.scalars(
        select(Account)
        .join(TikTokConnection, TikTokConnection.account_id == Account.id)
        .where(
            TikTokConnection.project_id == project_id,
            TikTokConnection.open_id == open_id,
            TikTokConnection.account_id != account_id,
        )
    ).first()


def ensure_identity_available(
    session: Session, project_id: int, open_id: str, account_id: int
) -> None:
    """A TikTok account can be linked to only one account per project (active or
    not). Checked before anything is stored; the unique key covers races."""
    holder = _identity_holder(session, project_id, open_id, account_id)
    if holder is not None:
        raise _already_connected(holder)


def mark_reconnect_required(
    session: Session, connection: TikTokConnection, now: datetime
) -> None:
    if connection.status != TikTokConnectionStatus.RECONNECT_REQUIRED:
        connection.status = TikTokConnectionStatus.RECONNECT_REQUIRED
        connection.updated_at = now
        _commit(session)


def discard_credential(
    gateway: TikTokGateway, credential: TikTokCredential, account_id: int
) -> None:
    """Best-effort revocation of a credential that will never be stored (research
    §13). Never raises and never changes the caller's outcome; only the account, the
    result and TikTok's `log_id` are logged."""
    try:
        config = load_tiktok_app_config(get_tiktok_app_file())
        gateway.revoke(credential.access_token, config)
    except Exception as error:
        log_id = error.log_id if isinstance(error, TikTokError) else None
        logger.info(
            "Discarded TikTok credential of account %s (failed%s)",
            account_id,
            f", log_id {log_id}" if log_id else "",
        )
        return
    logger.info("Discarded TikTok credential of account %s (revoked)", account_id)


def _pending(credential_ref: str, account_id: int) -> PendingCredential:
    return PendingCredential(Platform.TIKTOK, credential_ref, account_id)


def cleanup_pending_credentials(
    session_factory: sessionmaker[Session],
    store: CredentialStore,
    refs: Collection[str] | None = None,
) -> None:
    """Delete TikTok secrets queued for cleanup (all, or only `refs`).

    The generic queue (Feature 021); other platforms' rows wait for their own
    run. Idempotent and best-effort (research §12): a missing secret is not an
    error, a reference used by a connection is never deleted, and rows stay queued
    while the store is unavailable. Never raises.
    """
    run_credential_cleanup(
        session_factory,
        {Platform.TIKTOK: CredentialTarget(store, credential_lock)},
        refs,
    )


def _delete_new_secret(
    session_factory: sessionmaker[Session],
    store: CredentialStore,
    ref: str,
    account_id: int,
) -> None:
    """Undo a stored secret nothing points to; if that fails, queue it."""
    try:
        store.delete(ref)
    except CredentialStoreUnavailable:
        queue_credential(session_factory, _pending(ref, account_id))


def _is_identity_conflict(error: IntegrityError) -> bool:
    return "open_id" in str(error.orig)


def complete_connection(
    session_factory: sessionmaker[Session],
    store: CredentialStore,
    account_id: int,
    identity: TikTokIdentity,
    credential: TikTokCredential,
    now: datetime,
) -> TikTokConnection:
    """Link the identity with a new credential, in the safe order of FR-033/FR-034.

    The secret goes under a new reference; the row (and, when replacing, the previous
    reference queued for cleanup) is committed in one `write_transaction` that reads
    the account again; only then is the previous secret deleted. If that fails, or
    the account was deleted meanwhile (Feature 021), the new secret is deleted and
    any previous connection (row, reference and secret) stays untouched.
    """
    new_ref = uuid4().hex
    try:
        store.set(new_ref, credential.to_json())
    except CredentialStoreUnavailable:
        raise _store_unavailable() from None

    old_ref: str | None = None
    project_id: int | None = None
    try:
        with write_transaction(session_factory) as session:
            account = reread_account(session, account_id, Platform.TIKTOK)
            project_id = account.project_id
            ensure_account_connectable(session, account)
            existing = get_connection(session, account_id)
            old_ref = existing.credential_ref if existing is not None else None
            connection = existing or TikTokConnection(
                account_id=account.id, project_id=account.project_id
            )
            connection.open_id = identity.open_id
            connection.display_name = identity.display_name
            connection.avatar_url = identity.avatar_url
            connection.status = TikTokConnectionStatus.CONNECTED
            connection.credential_ref = new_ref
            connection.access_expires_at = credential.access_expires_at
            connection.refresh_expires_at = credential.refresh_expires_at
            connection.connected_at = now
            connection.last_verified_at = now
            connection.updated_at = now
            adopt_connected_identity(session, account, identity.display_name)
            if existing is None:
                session.add(connection)
            if old_ref is not None:
                enqueue_credentials(session, [_pending(old_ref, account_id)], now)
    except Exception as error:
        _delete_new_secret(session_factory, store, new_ref, account_id)
        if isinstance(error, AccountGone) or account_gone_now(
            session_factory, account_id
        ):
            raise authorization_gone() from None
        if isinstance(error, IntegrityError) and _is_identity_conflict(error):
            assert project_id is not None
            try:
                with session_factory() as session:
                    holder = _identity_holder(
                        session, project_id, identity.open_id, account_id
                    )
            except Exception:
                holder = None
            raise _already_connected(holder) from None
        raise
    if old_ref is not None:
        cleanup_pending_credentials(session_factory, store, [old_ref])
    return connection


# --- Credential lifecycle (research §10–§11) ----------------------------------------

_account_locks: dict[int, threading.RLock] = {}
_account_locks_guard = threading.Lock()


def _account_lock(account_id: int) -> threading.RLock:
    """In-memory lock shared by renewal, Verify, Disconnect and credential changes of
    one account. It only protects within this single backend process (one worker)."""
    with _account_locks_guard:
        return _account_locks.setdefault(account_id, threading.RLock())


def credential_lock(account_id: int) -> AbstractContextManager[None]:
    """`_account_lock` with a bounded wait (deferred credential cleanup, Feature
    021)."""
    return bounded(_account_lock(account_id))


def _connected_or_error(session: Session, account_id: int) -> TikTokConnection:
    connection = get_connection(session, account_id)
    if connection is None:
        raise AppError(409, "tiktok_not_connected", NOT_CONNECTED_MESSAGE)
    if connection.status == TikTokConnectionStatus.RECONNECT_REQUIRED:
        raise AppError(409, "tiktok_reconnect_required", RECONNECT_REQUIRED_MESSAGE)
    return connection


def _current_connection(session: Session, account_id: int) -> TikTokConnection:
    """The connection as committed now (another request may have changed it while
    this one waited for the account lock)."""
    session.expire_all()
    return _connected_or_error(session, account_id)


def _reconnect_required(
    session: Session, connection: TikTokConnection, now: datetime, message: str
) -> NoReturn:
    mark_reconnect_required(session, connection, now)
    raise AppError(409, "tiktok_reconnect_required", message)


def _identity_mismatch(
    session: Session, connection: TikTokConnection, now: datetime
) -> NoReturn:
    mark_reconnect_required(session, connection, now)
    raise AppError(409, "tiktok_identity_mismatch", IDENTITY_MISMATCH_MESSAGE)


def _unavailable() -> AppError:
    return AppError(503, "tiktok_unavailable", UNAVAILABLE_MESSAGE)


def _unexpected() -> AppError:
    return AppError(502, "tiktok_unexpected_response", UNEXPECTED_MESSAGE)


def _missing_scopes_message(missing: list[str]) -> str:
    return (
        "TikTok no longer grants every required permission (missing: "
        f"{', '.join(missing)}). Reconnect the account and grant every requested "
        "permission."
    )


def _store_credential(
    store: CredentialStore, ref: str, credential: TikTokCredential
) -> None:
    """Write the whole secret, retrying once (research §11)."""
    try:
        store.set(ref, credential.to_json())
    except CredentialStoreUnavailable:
        store.set(ref, credential.to_json())


def _renew(
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    connection: TikTokConnection,
    credential: TikTokCredential,
    now: datetime,
    usable: bool,
) -> TikTokCredential:
    """Renew with the refresh token and validate the answer before storing it.

    Temporary failures fall back to the current token while it is `usable`; only an
    official definitive signal marks the connection `reconnect_required`; app
    configuration problems change nothing.
    """
    try:
        config = load_tiktok_app_config(get_tiktok_app_file())
    except TikTokOAuthNotConfigured:
        raise _not_configured() from None
    try:
        refreshed = gateway.refresh(credential, config)
    except (TikTokUnavailable, TikTokUnexpectedResponse) as error:
        logger.warning(
            "Could not renew the TikTok token of account %s (temporary%s)",
            connection.account_id,
            f", log_id {error.log_id}" if error.log_id else "",
        )
        if usable:
            return credential
        if isinstance(error, TikTokUnavailable):
            raise _unavailable() from None
        raise _unexpected() from None
    except TikTokGrantInvalid:
        _reconnect_required(session, connection, now, TOKEN_REJECTED_MESSAGE)
    except TikTokClientError:
        raise _not_configured(CLIENT_REJECTED_MESSAGE) from None
    except TikTokError:
        raise _unexpected() from None

    if refreshed.open_id != connection.open_id:
        # Never stored: the secret keeps the linked identity's credential.
        _identity_mismatch(session, connection, now)
    if not refreshed.has_required_scopes():
        # The secret records what TikTok granted; the connection needs a new consent.
        try:
            _store_credential(store, connection.credential_ref, refreshed)
        except CredentialStoreUnavailable:
            pass
        _reconnect_required(
            session,
            connection,
            now,
            _missing_scopes_message(refreshed.missing_scopes()),
        )
    try:
        _store_credential(store, connection.credential_ref, refreshed)
    except CredentialStoreUnavailable:
        # The previous secret is untouched; if TikTok rotated the refresh token it
        # may no longer work (accepted risk, research §11).
        raise _store_unavailable() from None
    connection.access_expires_at = refreshed.access_expires_at
    connection.refresh_expires_at = refreshed.refresh_expires_at
    connection.updated_at = now
    try:
        _commit(session)
    except Exception as error:
        # The secret is authoritative: never restore the old token; the mirror is
        # repaired on the next access.
        session.rollback()
        logger.warning(
            "Could not save the renewed TikTok token metadata of account %s (%s)",
            connection.account_id,
            type(error).__name__,
        )
    return refreshed


def _usable_credential_locked(
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    connection: TikTokConnection,
    rejected_access_token: str | None = None,
) -> TikTokCredential:
    """The renewal policy; the caller holds the account lock.

    With `rejected_access_token`, TikTok has just refused that access token: it is
    renewed unless another request already replaced it.
    """
    now = gateway.clock()
    try:
        credential = _read_credential(store, connection.credential_ref)
    except CredentialStoreUnavailable:
        raise _store_unavailable() from None
    if credential is None:
        _reconnect_required(session, connection, now, CREDENTIAL_LOST_MESSAGE)
    _sync_metadata(session, connection, credential)
    if credential.refresh_expires_at <= now:
        _reconnect_required(session, connection, now, REFRESH_EXPIRED_MESSAGE)
    forced = (
        rejected_access_token is not None
        and credential.access_token == rejected_access_token
    )
    remaining = credential.access_expires_at - now
    if not forced and remaining > REFRESH_MARGIN:
        return credential
    usable = not forced and remaining > EXPIRY_MARGIN
    return _renew(session, store, gateway, connection, credential, now, usable)


def get_valid_credentials(
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    account_id: int,
) -> TikTokCredential:
    """Return a usable credential, renewing it on demand (research §10).

    Under the account lock: the secret is read first and the SQLite mirror repaired;
    an access token with more than REFRESH_MARGIN left is used as is, otherwise it is
    renewed and the answer's `open_id` and scopes are validated. Transient failures
    never change the status.
    """
    _connected_or_error(session, account_id)
    with _account_lock(account_id):
        connection = _current_connection(session, account_id)
        return _usable_credential_locked(session, store, gateway, connection)


def call_with_token[T](
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    account_id: int,
    call: Callable[[str], T],
) -> T:
    """Run `call(access_token)`; if TikTok rejects a supposedly valid access token,
    renew once and retry once. A second rejection requires reconnecting."""
    credential = get_valid_credentials(session, store, gateway, account_id)
    try:
        return call(credential.access_token)
    except TikTokTokenInvalid:
        pass
    with _account_lock(account_id):
        connection = _current_connection(session, account_id)
        renewed = _usable_credential_locked(
            session, store, gateway, connection, credential.access_token
        )
    try:
        return call(renewed.access_token)
    except TikTokTokenInvalid:
        _reconnect_required(
            session,
            _current_connection(session, account_id),
            gateway.clock(),
            TOKEN_REJECTED_MESSAGE,
        )


def get_linked_identity(session: Session, account_id: int) -> TikTokIdentity:
    """Public identity (including `open_id`) of a connected TikTok account."""
    return identity_of(_connected_or_error(session, account_id))


def mark_scope_not_authorized(
    session: Session, account_id: int, scope: str | None, now: datetime
) -> None:
    """React to TikTok's `scope_not_authorized` (e.g. `video.publish` while
    publishing): the account must be reconnected."""
    connection = get_connection(session, account_id)
    if connection is None:
        return
    logger.info(
        "TikTok reports a missing permission for account %s (%s)",
        account_id,
        scope or "unknown",
    )
    mark_reconnect_required(session, connection, now)


def verify_identity(
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    account_id: int,
) -> TikTokConnection:
    """Check the linked TikTok account with live signals, read-only towards TikTok.

    A usable access token (renewed if due), a correct `user/info` and the same
    `open_id` are live signals; `video.publish` is only known from TikTok's last
    token response and is never rewritten without a renewal (research §9). Error
    precedence (contracts/api.md): account, platform, inactive entities, not
    connected / reconnect required; only then are the store and TikTok used.
    """
    account = get_tiktok_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    _connected_or_error(session, account_id)
    try:
        identity = call_with_token(
            session, store, gateway, account_id, gateway.fetch_user_info
        )
    except TikTokScopeMissing:
        _reconnect_required(
            session,
            _current_connection(session, account_id),
            gateway.clock(),
            _missing_scopes_message(["user.info.basic"]),
        )
    except TikTokUnavailable:
        raise _unavailable() from None
    except TikTokError:
        raise _unexpected() from None
    with _account_lock(account_id):
        connection = _current_connection(session, account_id)
        now = gateway.clock()
        if identity.open_id != connection.open_id:
            _identity_mismatch(session, connection, now)
        connection.display_name = identity.display_name
        connection.avatar_url = identity.avatar_url
        connection.last_verified_at = now
        connection.updated_at = now
        _commit(session)
    return connection


# --- Logging -----------------------------------------------------------------------

# Loggers of the HTTP client stack (the same ones protected for the other platforms).
# httpx2 logs every request URL at INFO and httpcore2 logs headers at DEBUG.
HTTP_LOGGERS = (
    "httpx2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "httpcore2.proxy",
    "httpcore2.socks",
)

_SECRET_PARAMS = re.compile(
    r"\b(access_token|refresh_token|client_secret|code_verifier|code_challenge|code"
    r"|state|token)=[^&\s'\"<>]+",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[^\s'\",)]+", re.IGNORECASE)
_AUTHORIZE_QUERY = re.compile(r"(www\.tiktok\.com/v2/auth/authorize/?)\?[^\s'\"<>]*")
# The callback URL itself (code, state, error text) is never logged either.
_CALLBACK_QUERY = re.compile(re.escape(TIKTOK_CALLBACK_PATH) + r"/?\?[^\s'\"<>]*")
# Direct Post upload URLs (Feature 013) are ephemeral secrets: any URL of a TikTok
# API host whose path or query mentions an upload is replaced whole, as is any TikTok
# URL carrying an upload token or signature.
_UPLOAD_URL = re.compile(
    r"https?://[^\s'\"<>/]*tiktokapis\.[a-z]+/[^\s'\"<>]*upload[^\s'\"<>]*"
    r"|https?://[^\s'\"<>/]*tiktok[^\s'\"<>/]*/[^\s'\"<>]*"
    r"[?&](?:upload_token|upload_id|signature)=[^\s'\"<>]*",
    re.IGNORECASE,
)
_UPLOAD_PARAMS = re.compile(
    r"\b(upload_token|upload_id|signature)=[^&\s'\"<>]+", re.IGNORECASE
)


class RedactTikTokCallbackQuery(logging.Filter):
    """Drop the query string (authorization code, state) of callback access logs.

    Uvicorn's access log records `(client, method, path, http_version, status)`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith(TIKTOK_CALLBACK_PATH) and path[
                len(TIKTOK_CALLBACK_PATH) : len(TIKTOK_CALLBACK_PATH) + 1
            ] in ("?", "/"):
                record.args = (
                    *args[:2],
                    TIKTOK_CALLBACK_PATH + "?[redacted]",
                    *args[3:],
                )
        return True


class RedactTikTokSecrets(logging.Filter):
    """Remove tokens, the client secret, codes, verifiers, challenges, states and
    `Bearer` values from HTTP client logs, the query of authorization and callback
    URLs, and whole Direct Post upload URLs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # A broken record is left for logging to report.
            return True
        if "=" in message or "bearer" in message.lower() or "tiktok" in message:
            redacted = _UPLOAD_URL.sub("[redacted TikTok upload URL]", message)
            redacted = _UPLOAD_PARAMS.sub(r"\1=[redacted]", redacted)
            redacted = _AUTHORIZE_QUERY.sub(r"\1?[redacted]", redacted)
            redacted = _CALLBACK_QUERY.sub(
                TIKTOK_CALLBACK_PATH + "?[redacted]", redacted
            )
            redacted = _SECRET_PARAMS.sub(r"\1=[redacted]", redacted)
            redacted = _BEARER.sub(r"\1[redacted]", redacted)
            if redacted != message:
                record.msg = redacted
                record.args = ()
        return True


def install_log_redaction() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTikTokCallbackQuery) for f in access_logger.filters):
        access_logger.addFilter(RedactTikTokCallbackQuery())
    for name in HTTP_LOGGERS:
        http_logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTikTokSecrets) for f in http_logger.filters):
            http_logger.addFilter(RedactTikTokSecrets())


# --- Result page -------------------------------------------------------------------

_SAFE_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}
_RESULT_PAGES: dict[TikTokCallbackOutcome, tuple[str, str]] = {
    TikTokCallbackOutcome.CONNECTED: (
        "TikTok account connected",
        "The TikTok account is now connected to AutoPublisher.",
    ),
    TikTokCallbackOutcome.CONFIRM_REQUIRED: (
        "Confirm the TikTok account",
        "This account is already linked to another TikTok account. Return to "
        "AutoPublisher to confirm or cancel the change.",
    ),
    TikTokCallbackOutcome.CANCELLED: (
        "Connection cancelled",
        "The connection was cancelled in TikTok.",
    ),
    TikTokCallbackOutcome.FAILED: (
        "Connection failed",
        "The TikTok account could not be connected. Return to AutoPublisher to see "
        "what happened.",
    ),
    TikTokCallbackOutcome.INVALID: (
        "Authorization not valid",
        "This authorization is invalid or has expired. Start the connection again "
        "from AutoPublisher.",
    ),
}


def result_redirect(outcome: TikTokCallbackOutcome) -> RedirectResponse:
    """`303 See Other` to the clean result page: the callback URL with `code` and
    `state` leaves the address bar and is replaced in the history."""
    return RedirectResponse(
        f"{RESULT_PATH}?outcome={outcome.value}",
        status_code=status.HTTP_303_SEE_OTHER,
        headers=_SAFE_PAGE_HEADERS,
    )


def render_result_page(outcome: str | None) -> HTMLResponse:
    """Minimal page from a fixed dictionary; the query is never reflected."""
    try:
        known = TikTokCallbackOutcome(outcome or "")
    except ValueError:
        known = TikTokCallbackOutcome.INVALID
    title, message = _RESULT_PAGES[known]
    body = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>AutoPublisher</title></head>
<body style="font-family: sans-serif; max-width: 36rem; margin: 3rem auto;">
<h1>{html.escape(title)}</h1>
<p>{html.escape(message)}</p>
<p>You can close this tab and return to AutoPublisher.</p>
</body>
</html>
"""
    return HTMLResponse(
        body,
        status_code=200,
        headers={
            **_SAFE_PAGE_HEADERS,
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


# --- Completing an authorization ----------------------------------------------------


def _account_deleted(error: Exception) -> bool:
    """Whether a completion failed because its account no longer exists."""
    code = getattr(error, "code", None)
    return isinstance(error, NotFoundError) or code == authorization_gone().code


def _failure_from(error: Exception) -> AttemptFailure:
    if isinstance(error, (ConflictError, AppError)):
        return AttemptFailure(error.code, error.message)
    if isinstance(error, NotFoundError):
        return AttemptFailure("not_found", error.message)
    raise error


def _gateway_failure(error: TikTokError) -> AttemptFailure:
    if isinstance(error, TikTokUnavailable):
        return AttemptFailure(
            "tiktok_unavailable", AUTHORIZATION_UNAVAILABLE_MESSAGE, log_id=error.log_id
        )
    if isinstance(error, TikTokUnexpectedResponse):
        return AttemptFailure(
            "tiktok_unexpected_response", UNEXPECTED_MESSAGE, log_id=error.log_id
        )
    return AttemptFailure(
        "tiktok_token_exchange_failed", EXCHANGE_FAILED_MESSAGE, log_id=error.log_id
    )


def _permission_missing(missing: list[str]) -> AttemptFailure:
    return AttemptFailure(
        "tiktok_permission_missing",
        "TikTok did not grant every requested permission (missing: "
        f"{', '.join(missing)}). Connect again and grant every requested permission.",
    )


def _complete_with_credential(
    session: Session,
    session_factory: sessionmaker[Session],
    store: CredentialStore,
    gateway: TikTokGateway,
    registry: TikTokAttemptRegistry,
    attempt: TikTokOAuthAttempt,
    account: Account,
    credential: TikTokCredential,
) -> TikTokCallbackOutcome:
    # Only the official token response decides which scopes were granted (FR-008).
    # Connect / Reconnect require every requested scope: a partial grant fails before
    # anything is stored, so a previous connection stays untouched (014 research §2).
    if not credential.has_requested_scopes():
        raise _permission_missing(credential.missing_scopes(REQUESTED_SCOPES))
    try:
        identity = gateway.fetch_user_info(credential.access_token)
    except TikTokScopeMissing as error:
        raise _permission_missing([error.scope or "user.info.basic"]) from None
    except TikTokUnavailable as error:
        raise _gateway_failure(error) from None
    except TikTokError as error:
        raise AttemptFailure(
            "tiktok_unexpected_response", UNEXPECTED_MESSAGE, log_id=error.log_id
        ) from None
    if identity.open_id != credential.open_id:
        raise AttemptFailure("tiktok_unexpected_response", UNEXPECTED_MESSAGE)

    cleanup_pending_credentials(session_factory, store)
    now = gateway.clock()
    try:
        ensure_identity_available(
            session, account.project_id, identity.open_id, account.id
        )
        with _account_lock(account.id):
            session.expire_all()
            existing = get_connection(session, account.id)
            if existing is not None and existing.open_id != identity.open_id:
                # Never switch accounts silently: the credential waits in memory
                # for an explicit confirmation (FR-031).
                registry.await_confirmation(
                    attempt,
                    identity,
                    credential,
                    current_identity=identity_of(existing),
                )
                return TikTokCallbackOutcome.CONFIRM_REQUIRED
            connection = complete_connection(
                session_factory, store, account.id, identity, credential, now
            )
    except (ConflictError, AppError) as failure:
        raise _failure_from(failure) from None
    registry.finish(
        attempt,
        TikTokAttemptStatus.COMPLETED,
        connection=connection_to_read(
            session, store, connection, now, include_permissions=True
        ).model_dump(mode="json"),
    )
    return TikTokCallbackOutcome.CONNECTED


def _process_callback(
    session: Session,
    session_factory: sessionmaker[Session],
    store: CredentialStore,
    gateway: TikTokGateway,
    registry: TikTokAttemptRegistry,
    attempt: TikTokOAuthAttempt,
    verifier: str,
    items: list[tuple[str, str]],
) -> TikTokCallbackOutcome:
    try:
        callback = parse_callback(items)
    except CallbackInvalid:
        raise AttemptFailure(
            "tiktok_oauth_callback_invalid", CALLBACK_INVALID_MESSAGE
        ) from None
    if callback.error is not None:
        # `error_description` is never shown nor logged.
        if callback.error == "access_denied":
            raise AttemptFailure(
                "tiktok_oauth_denied",
                DENIED_MESSAGE,
                outcome=TikTokCallbackOutcome.CANCELLED,
            )
        raise AttemptFailure("tiktok_oauth_provider_error", PROVIDER_ERROR_MESSAGE)
    code = callback.code
    assert code is not None

    try:
        account = get_tiktok_account_or_error(session, attempt.account_id)
        # Checked before any request to TikTok (it may have been deactivated).
        ensure_account_connectable(session, account)
        config = load_config()
    except (ConflictError, AppError, NotFoundError) as failure:
        raise _failure_from(failure) from None

    # The code is single-use: it is exchanged exactly once, never retried.
    try:
        credential = gateway.exchange_code(code, verifier, config)
    except TikTokError as error:
        raise _gateway_failure(error) from None

    try:
        return _complete_with_credential(
            session,
            session_factory,
            store,
            gateway,
            registry,
            attempt,
            account,
            credential,
        )
    except Exception as error:
        # Never stored: revoke it best-effort, keeping the original outcome. A
        # deleted account is never revoked: deleting never contacts TikTok.
        if not _account_deleted(error):
            discard_credential(gateway, credential, account.id)
        raise


def handle_callback(
    request: Request,
    session: Session,
    session_factory: sessionmaker[Session],
    store: CredentialStore,
    gateway: TikTokGateway,
    registry: TikTokAttemptRegistry,
) -> TikTokCallbackOutcome:
    """Validate and process a callback; the attempt keeps the detailed result."""
    if not is_loopback_request(request.scope):
        return TikTokCallbackOutcome.INVALID
    items = request.query_params.multi_items()
    state = extract_state(items)
    consumed = registry.consume_state(state) if state is not None else None
    if consumed is None:
        return TikTokCallbackOutcome.INVALID
    attempt, verifier = consumed
    try:
        return _process_callback(
            session, session_factory, store, gateway, registry, attempt, verifier, items
        )
    except AttemptFailure as failure:
        logger.info(
            "TikTok authorization failed for account %s (%s%s)",
            attempt.account_id,
            failure.code,
            f", log_id {failure.log_id}" if failure.log_id else "",
        )
        registry.finish(
            attempt,
            TikTokAttemptStatus.FAILED,
            error={"code": failure.code, "message": failure.message},
        )
        return failure.outcome
    except Exception as unexpected:
        logger.error(
            "Unexpected error while completing a TikTok authorization for account %s "
            "(%s)",
            attempt.account_id,
            type(unexpected).__name__,
        )
        registry.finish(
            attempt,
            TikTokAttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        return TikTokCallbackOutcome.FAILED


# --- Routes ------------------------------------------------------------------------


@router.get(
    "/accounts/{account_id}/tiktok-connection", response_model=TikTokConnectionRead
)
def get_tiktok_connection(
    account_id: int, session: SessionDep, store: StoreDep, gateway: GatewayDep
) -> TikTokConnectionRead:
    get_tiktok_account_or_error(session, account_id)
    return connection_to_read(
        session,
        store,
        get_connection(session, account_id),
        gateway.clock(),
        include_permissions=True,
    )


@router.post(
    "/accounts/{account_id}/tiktok-connection/authorize",
    response_model=TikTokAuthorizeRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_tiktok(
    account_id: int, request: Request, session: SessionDep, registry: RegistryDep
) -> TikTokAuthorizeRead:
    require_host_action(request)
    account = get_tiktok_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    config = load_config()
    # The browser comes back to this backend: its real socket port (never the Host
    # header, which comes from the Vite proxy) must be the redirect URI's port.
    server = request.scope.get("server")
    if server is None or server[1] != urlsplit(config.redirect_uri).port:
        raise _not_configured(PORT_MISMATCH_MESSAGE)
    state = generate_state()
    verifier, challenge = generate_tiktok_pkce_pair()
    existing = get_connection(session, account.id)
    attempt = registry.create(
        account.id,
        state,
        verifier,
        current_identity=identity_of(existing) if existing is not None else None,
    )
    return TikTokAuthorizeRead(
        attempt_id=attempt.attempt_id,
        authorization_url=build_authorization_url(config, state, challenge),
        expires_at=attempt.expires_at,
    )


@router.get(
    TIKTOK_CALLBACK_PATH.removeprefix("/api"),
    response_class=RedirectResponse,
    include_in_schema=False,
)
def tiktok_oauth_callback(
    request: Request,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> RedirectResponse:
    """Destination of TikTok's redirect; never serves content at its own URL."""
    return result_redirect(
        handle_callback(request, session, session_factory, store, gateway, registry)
    )


@router.get(
    RESULT_PATH.removeprefix("/api"),
    response_class=HTMLResponse,
    include_in_schema=False,
)
def tiktok_oauth_result(request: Request) -> HTMLResponse:
    outcomes = request.query_params.getlist("outcome")
    return render_result_page(outcomes[0] if len(outcomes) == 1 else None)


def _attempt_not_found() -> AppError:
    return AppError(
        404, "tiktok_oauth_attempt_not_found", "This authorization was not found."
    )


def _not_confirmable() -> AppError:
    return AppError(
        409,
        "tiktok_oauth_attempt_not_confirmable",
        "This authorization can no longer be changed.",
    )


@router.get(
    "/tiktok/oauth/attempts/{attempt_id}", response_model=TikTokOAuthAttemptRead
)
def get_tiktok_attempt(
    attempt_id: str, registry: RegistryDep
) -> TikTokOAuthAttemptRead:
    attempt = registry.get(attempt_id)
    if attempt is None:
        raise _attempt_not_found()
    return attempt_to_read(attempt)


@router.post(
    "/tiktok/oauth/attempts/{attempt_id}/cancel",
    response_model=TikTokOAuthAttemptRead,
)
def cancel_tiktok_attempt(
    attempt_id: str, registry: RegistryDep
) -> TikTokOAuthAttemptRead:
    """Allowed with inactive entities; a pending credential is discarded."""
    try:
        attempt = registry.cancel(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    return attempt_to_read(attempt)


@router.post(
    "/tiktok/oauth/attempts/{attempt_id}/confirm",
    response_model=TikTokOAuthAttemptRead,
)
def confirm_tiktok_attempt(
    attempt_id: str,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TikTokOAuthAttemptRead:
    """Replace the linked TikTok account with the one awaiting confirmation.

    Active entities and uniqueness are checked again; the replacement uses the safe
    order of `complete_connection`. On any failure the pending credential is
    discarded (revoked best-effort) and the previous connection stays untouched.
    """
    current = registry.get(attempt_id)
    if current is not None and current.status == TikTokAttemptStatus.EXPIRED:
        raise AppError(410, "tiktok_oauth_attempt_expired", ATTEMPT_EXPIRED_MESSAGE)
    try:
        attempt, credential = registry.claim_confirmation(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    now = gateway.clock()
    try:
        account = get_tiktok_account_or_error(session, attempt.account_id)
        ensure_account_connectable(session, account)
        cleanup_pending_credentials(session_factory, store)
        new_identity = attempt.new_identity
        assert new_identity is not None
        with _account_lock(account.id):
            session.expire_all()
            existing = get_connection(session, account.id)
            if (
                existing is None
                or attempt.current_identity is None
                or existing.open_id != attempt.current_identity.open_id
            ):
                raise AppError(
                    409, "tiktok_connection_changed", CONNECTION_CHANGED_MESSAGE
                )
            ensure_identity_available(
                session, account.project_id, new_identity.open_id, account.id
            )
            connection = complete_connection(
                session_factory, store, account.id, new_identity, credential, now
            )
    except (ConflictError, AppError, NotFoundError) as failure:
        if not _account_deleted(failure):
            discard_credential(gateway, credential, attempt.account_id)
        reported = _failure_from(failure)
        registry.finish(
            attempt,
            TikTokAttemptStatus.FAILED,
            error={"code": reported.code, "message": reported.message},
        )
        raise
    except Exception as unexpected:
        logger.error(
            "Unexpected error while confirming a TikTok account change for account "
            "%s (%s)",
            attempt.account_id,
            type(unexpected).__name__,
        )
        discard_credential(gateway, credential, attempt.account_id)
        registry.finish(
            attempt,
            TikTokAttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        raise AppError(500, "internal_error", INTERNAL_MESSAGE) from None
    registry.finish(
        attempt,
        TikTokAttemptStatus.COMPLETED,
        connection=connection_to_read(
            session, store, connection, now, include_permissions=True
        ).model_dump(mode="json"),
    )
    return attempt_to_read(attempt)


@router.post(
    "/accounts/{account_id}/tiktok-connection/verify",
    response_model=TikTokConnectionRead,
)
def verify_tiktok_connection(
    account_id: int, session: SessionDep, store: StoreDep, gateway: GatewayDep
) -> TikTokConnectionRead:
    connection = verify_identity(session, store, gateway, account_id)
    return connection_to_read(
        session, store, connection, gateway.clock(), include_permissions=True
    )


# --- Disconnect (research §13) ------------------------------------------------------


def _revoke_failed() -> AppError:
    return AppError(503, "tiktok_revoke_failed", REVOKE_FAILED_MESSAGE)


def _revoke_credential(
    store: CredentialStore,
    gateway: TikTokGateway,
    connection: TikTokConnection,
    credential: TikTokCredential,
    config: TikTokAppConfig,
    now: datetime,
) -> str:
    """Revoke in TikTok; return `revoked` or `already_invalid` (only what TikTok
    confirmed), or raise `tiktok_revoke_failed` when the answer is not definitive.

    Renewing first (an access token inside EXPIRY_MARGIN) is allowed even for
    inactive entities: it is only used to revoke.
    """
    if credential.refresh_expires_at <= now:
        return "already_invalid"
    if credential.access_expires_at - now <= EXPIRY_MARGIN:
        try:
            refreshed = gateway.refresh(credential, config)
        except TikTokGrantInvalid:
            return "already_invalid"
        except TikTokError:
            raise _revoke_failed() from None
        try:
            _store_credential(store, connection.credential_ref, refreshed)
        except CredentialStoreUnavailable:
            # Revoking with the new token still works; deleting will report it.
            logger.warning(
                "Could not store the renewed TikTok token of account %s before "
                "revoking",
                connection.account_id,
            )
        credential = refreshed
    try:
        gateway.revoke(credential.access_token, config)
    except (TikTokGrantInvalid, TikTokTokenInvalid):
        return "already_invalid"
    except TikTokError as error:
        logger.info(
            "TikTok did not confirm the revocation for account %s (%s%s)",
            connection.account_id,
            type(error).__name__,
            f", log_id {error.log_id}" if error.log_id else "",
        )
        raise _revoke_failed() from None
    return "revoked"


def _delete_connection(
    session: Session, store: CredentialStore, connection: TikTokConnection
) -> None:
    """Delete the secret, then the row; nothing is deleted if the store fails."""
    try:
        store.delete(connection.credential_ref)
    except CredentialStoreUnavailable:
        raise _store_unavailable() from None
    session.delete(connection)
    _commit(session)


def _disconnected(
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    registry: TikTokAttemptRegistry,
    account_id: int,
    revocation: str,
) -> TikTokDisconnectRead:
    registry.expire_for_account(account_id)
    return TikTokDisconnectRead(
        connection=connection_to_read(session, store, None, gateway.clock()),
        revocation=revocation,  # type: ignore[arg-type]
    )


@router.post(
    "/accounts/{account_id}/tiktok-connection/disconnect",
    response_model=TikTokDisconnectRead,
)
def disconnect_tiktok(
    account_id: int,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TikTokDisconnectRead:
    """Revoke in TikTok, then delete the secret and the connection.

    Allowed with inactive entities and idempotent. Only a confirmed revocation is
    reported as `revoked`; a credential TikTok declares invalid is `already_invalid`;
    anything ambiguous keeps everything (`tiktok_revoke_failed`).
    """
    get_tiktok_account_or_error(session, account_id)
    cleanup_pending_credentials(session_factory, store)
    with _account_lock(account_id):
        session.expire_all()
        connection = get_connection(session, account_id)
        if connection is None:
            return _disconnected(
                session, store, gateway, registry, account_id, "not_connected"
            )
        try:
            credential = _read_credential(store, connection.credential_ref)
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
        if credential is None:
            raise AppError(409, "tiktok_credential_missing", CREDENTIAL_MISSING_MESSAGE)
        try:
            config = load_tiktok_app_config(get_tiktok_app_file())
        except TikTokOAuthNotConfigured:
            raise _revoke_failed() from None
        revocation = _revoke_credential(
            store, gateway, connection, credential, config, gateway.clock()
        )
        _delete_connection(session, store, connection)
    logger.info("Disconnected TikTok account %s (%s)", account_id, revocation)
    return _disconnected(session, store, gateway, registry, account_id, revocation)


@router.post(
    "/accounts/{account_id}/tiktok-connection/remove-local",
    response_model=TikTokDisconnectRead,
)
def remove_tiktok_locally(
    account_id: int,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> TikTokDisconnectRead:
    """Explicit removal without revoking: TikTok is never contacted, so it may still
    have AutoPublisher authorized. The account and its publications stay."""
    get_tiktok_account_or_error(session, account_id)
    cleanup_pending_credentials(session_factory, store)
    with _account_lock(account_id):
        session.expire_all()
        connection = get_connection(session, account_id)
        if connection is None:
            return _disconnected(
                session, store, gateway, registry, account_id, "not_connected"
            )
        _delete_connection(session, store, connection)
    logger.info("Removed TikTok account %s locally without revoking", account_id)
    return _disconnected(session, store, gateway, registry, account_id, "not_revoked")


def health_of(connection: TikTokConnection, now: datetime) -> ConnectionHealth:
    """Health from the row only: the access token renews itself, so only the
    refresh token's expiry matters. Never the keyring, never `connection_to_read`
    (it may repair the row)."""
    identity = ConnectionIdentity(
        connection.display_name or "TikTok account", None, connection.avatar_url
    )
    return expiring_connection_health(
        "TikTok",
        connection.status,
        identity,
        connection.refresh_expires_at,
        now,
    )
