"""Threads account connection over the official Threads API (see
specs/010-threads-oauth-connection).

The accounts core knows nothing about Threads: connections are looked up here by
`account_id`. The long-lived token lives only in the secure credential store (service
`autopublisher.threads`) and that secret is the source of truth for the token, when it
was obtained, its expiry and its confirmed scopes; SQLite keeps a non-secret
`credential_ref`, the public identity and a repairable mirror of the dates. There is no
callback route: the user pastes the redirect URL and `complete` answers synchronously.
Disconnecting never contacts Meta.
"""

import logging
import re
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Annotated, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_threads_app_file
from app.credential_store import CredentialStore, CredentialStoreUnavailable
from app.db import get_session
from app.errors import AppError, ConflictError, NotFoundError
from app.models import (
    Account,
    Platform,
    Project,
    ThreadsConnection,
    ThreadsConnectionStatus,
)
from app.schemas import (
    ThreadsAuthorizeRead,
    ThreadsCompleteWrite,
    ThreadsConnectionRead,
    ThreadsIdentityRead,
    ThreadsOAuthAttemptRead,
)
from app.threads_gateway import (
    ThreadsError,
    ThreadsGateway,
    ThreadsPermissionDenied,
    ThreadsToken,
    ThreadsTokenInfo,
    ThreadsTokenInvalid,
    ThreadsUnavailable,
    ThreadsUnexpectedResponse,
)
from app.threads_oauth import (
    REQUIRED_SCOPES,
    AttemptExpired,
    AttemptNotConfirmable,
    AttemptNotFound,
    AttemptStateInvalid,
    InvalidRedirectUrl,
    RedirectResult,
    ThreadsAppConfig,
    ThreadsAttemptRegistry,
    ThreadsAttemptStatus,
    ThreadsIdentity,
    ThreadsOAuthAttempt,
    ThreadsOAuthNotConfigured,
    build_authorization_url,
    generate_state,
    load_threads_app_config,
    parse_redirect_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["threads"])

SessionDep = Annotated[Session, Depends(get_session)]

# Product decision of AutoPublisher, not a Meta rule: a token is only renewed when its
# expiry is this close (research §6).
RENEWAL_WINDOW = timedelta(days=7)
# Meta's technical condition: a long-lived token can only be refreshed once it is at
# least this old.
REFRESH_MIN_AGE = timedelta(hours=24)
# AutoPublisher's safety margin: a token this close to its expiry is not handed out.
EXPIRY_MARGIN = timedelta(minutes=5)

DOCS_HINT = "See docs/threads-accounts.md."
STORE_UNAVAILABLE_MESSAGE = (
    f"The system's secure credential storage is not available. {DOCS_HINT}"
)
NOT_CONFIGURED_MESSAGE = f"Threads integration is not configured. {DOCS_HINT}"
UNAVAILABLE_MESSAGE = "Could not reach Threads. Check your connection and try again."
AUTHORIZATION_UNAVAILABLE_MESSAGE = (
    "Could not reach Threads to finish the authorization. Check your connection and "
    "start the connection again."
)
UNEXPECTED_MESSAGE = "Threads returned an unexpected response. Try again later."
INTERNAL_MESSAGE = "An unexpected error occurred. Please try again."
EXCHANGE_FAILED_MESSAGE = (
    "Threads did not complete the authorization. Start the connection again."
)
REDIRECT_INVALID_MESSAGE = (
    "The pasted address is not the address Threads redirected to. Copy the full "
    "address of the page Threads opened and paste it again."
)
STATE_INVALID_MESSAGE = (
    "The pasted address does not belong to this connection attempt, or it was "
    "already used. Paste the address from this attempt or start the connection again."
)
ATTEMPT_EXPIRED_MESSAGE = "This authorization has expired. Start the connection again."
DENIED_MESSAGE = "The connection was cancelled in Threads."
PROVIDER_ERROR_MESSAGE = (
    "Threads could not complete the authorization. Make sure this Threads account can "
    f"use your app (for example as a Threads tester) and try again. {DOCS_HINT}"
)
NOT_CONNECTED_MESSAGE = "This Threads account is not connected."
TOKEN_REJECTED_MESSAGE = (
    "Threads no longer accepts the stored credentials. Reconnect the account."
)
RECONNECT_REQUIRED_MESSAGE = (
    "The Threads connection needs to be renewed. Reconnect the account."
)
IDENTITY_MISMATCH_MESSAGE = (
    "The authorized Threads account no longer matches the linked account. "
    "Reconnect the account to change it."
)


def get_threads_credential_store(request: Request) -> CredentialStore:
    store: CredentialStore = request.app.state.threads_credential_store
    return store


def get_threads_gateway(request: Request) -> ThreadsGateway:
    gateway: ThreadsGateway = request.app.state.threads_gateway
    return gateway


def get_threads_registry(request: Request) -> ThreadsAttemptRegistry:
    registry: ThreadsAttemptRegistry = request.app.state.threads_attempts
    return registry


StoreDep = Annotated[CredentialStore, Depends(get_threads_credential_store)]
GatewayDep = Annotated[ThreadsGateway, Depends(get_threads_gateway)]
RegistryDep = Annotated[ThreadsAttemptRegistry, Depends(get_threads_registry)]


class AttemptFailure(Exception):
    """An expected failure while completing an authorization."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class GrantRejected(Exception):
    """`debug_token` says the token is not valid or lacks a required scope."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__("The Threads grant is not usable.")
        self.missing = missing


class GrantIdentityMismatch(Exception):
    """`debug_token` reports a user other than the expected one."""


def _commit(session: Session) -> None:
    """Single commit point of this module (tests inject persistence failures here)."""
    session.commit()


def _store_unavailable() -> AppError:
    return AppError(503, "credential_store_unavailable", STORE_UNAVAILABLE_MESSAGE)


def _unavailable() -> AppError:
    return AppError(503, "threads_unavailable", UNAVAILABLE_MESSAGE)


def _unexpected() -> AppError:
    return AppError(502, "threads_unexpected_response", UNEXPECTED_MESSAGE)


def _permission_message(missing: list[str]) -> str:
    if not missing:
        return (
            "A required Threads permission is missing or was withdrawn. "
            "Reconnect the account and grant all requested permissions."
        )
    return (
        "A required Threads permission is missing or was withdrawn "
        f"({', '.join(missing)}). Reconnect the account and grant all requested "
        "permissions."
    )


# --- Lookups and read models -------------------------------------------------------


def get_threads_account_or_error(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError("Account not found.")
    if account.platform != Platform.THREADS:
        raise ConflictError(
            "platform_not_supported", "Only Threads accounts can be connected."
        )
    return account


def get_connection(session: Session, account_id: int) -> ThreadsConnection | None:
    return session.scalars(
        select(ThreadsConnection).where(ThreadsConnection.account_id == account_id)
    ).first()


def oauth_configured() -> bool:
    """Whether the local Threads app file is usable; read on every call."""
    try:
        load_threads_app_config(get_threads_app_file())
    except ThreadsOAuthNotConfigured:
        return False
    return True


def load_config() -> ThreadsAppConfig:
    try:
        return load_threads_app_config(get_threads_app_file())
    except ThreadsOAuthNotConfigured:
        raise AppError(
            503, "threads_oauth_not_configured", NOT_CONFIGURED_MESSAGE
        ) from None


def identity_of(connection: ThreadsConnection) -> ThreadsIdentity:
    return ThreadsIdentity(
        threads_user_id=connection.threads_user_id,
        username=connection.username,
        display_name=connection.display_name,
        profile_picture_url=connection.profile_picture_url,
    )


def mark_reconnect_required(
    session: Session, connection: ThreadsConnection, now: datetime
) -> None:
    if connection.status != ThreadsConnectionStatus.RECONNECT_REQUIRED:
        connection.status = ThreadsConnectionStatus.RECONNECT_REQUIRED
        connection.updated_at = now
        _commit(session)


def _read_token(store: CredentialStore, ref: str) -> ThreadsToken | None:
    """The stored token, or None when missing or unreadable (raises if unavailable)."""
    raw = store.get(ref)
    if raw is None:
        return None
    try:
        return ThreadsToken.from_json(raw)
    except ValueError:
        return None


def _sync_metadata(
    session: Session, connection: ThreadsConnection, token: ThreadsToken
) -> None:
    """Repair the SQLite mirror of the secret's dates; idempotent and best-effort."""
    if (
        connection.token_obtained_at == token.token_obtained_at
        and connection.credential_expires_at == token.expires_at
    ):
        return
    connection.token_obtained_at = token.token_obtained_at
    connection.credential_expires_at = token.expires_at
    try:
        _commit(session)
    except Exception as error:
        session.rollback()
        logger.warning(
            "Could not repair the Threads connection metadata of account %s (%s)",
            connection.account_id,
            type(error).__name__,
        )


def connection_to_read(
    session: Session,
    store: CredentialStore,
    connection: ThreadsConnection | None,
    now: datetime,
) -> ThreadsConnectionRead:
    """Public view; never calls Meta.

    `data_access_expires_at` is shown as is and never changes the status. When the
    SQLite mirror says the token expired, the secret (source of truth) is read first:
    a later valid expiry repairs the mirror, a confirmed expiry or a missing secret
    marks `reconnect_required`, and an unavailable store changes nothing.
    """
    configured = oauth_configured()
    if connection is None:
        return ThreadsConnectionRead(
            status="not_connected",
            identity=None,
            connected_at=None,
            last_verified_at=None,
            token_obtained_at=None,
            access_expires_at=None,
            data_access_expires_at=None,
            oauth_configured=configured,
        )
    if (
        connection.status == ThreadsConnectionStatus.CONNECTED
        and connection.credential_expires_at <= now
    ):
        try:
            token = _read_token(store, connection.credential_ref)
        except CredentialStoreUnavailable:
            pass
        else:
            if token is not None and token.expires_at > now:
                _sync_metadata(session, connection, token)
            else:
                mark_reconnect_required(session, connection, now)
    return ThreadsConnectionRead(
        status="connected"
        if connection.status == ThreadsConnectionStatus.CONNECTED
        else "reconnect_required",
        identity=ThreadsIdentityRead.model_validate(identity_of(connection).to_read()),
        connected_at=connection.connected_at,
        last_verified_at=connection.last_verified_at,
        token_obtained_at=connection.token_obtained_at,
        access_expires_at=connection.credential_expires_at,
        data_access_expires_at=connection.data_access_expires_at,
        oauth_configured=configured,
    )


def attempt_to_read(attempt: ThreadsOAuthAttempt) -> ThreadsOAuthAttemptRead:
    return ThreadsOAuthAttemptRead.model_validate(attempt.to_read())


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


def ensure_identity_available(
    session: Session, project_id: int, threads_user_id: str, account_id: int
) -> None:
    """A Threads account can be linked to only one account per project (active or
    not)."""
    holder = session.execute(
        select(Account.handle)
        .join(ThreadsConnection, ThreadsConnection.account_id == Account.id)
        .where(
            ThreadsConnection.project_id == project_id,
            ThreadsConnection.threads_user_id == threads_user_id,
            ThreadsConnection.account_id != account_id,
        )
    ).first()
    if holder is not None:
        raise AppError(
            409,
            "threads_account_already_connected",
            f"This Threads account is already connected to @{holder.handle} in this "
            "project. Disconnect it there first.",
        )


def _discard_secret(store: CredentialStore, ref: str, account_id: int) -> None:
    """Best-effort delete; if it fails the entry stays orphaned (documented)."""
    try:
        store.delete(ref)
    except CredentialStoreUnavailable:
        logger.warning(
            "Could not delete stored Threads credentials for account %s", account_id
        )


def complete_connection(
    session: Session,
    store: CredentialStore,
    account: Account,
    identity: ThreadsIdentity,
    token: ThreadsToken,
    token_info: ThreadsTokenInfo,
    now: datetime,
) -> ThreadsConnection:
    """Link the identity with a new credential, in a safe order (data-model).

    The secret goes under a new reference; the row is committed; only then is the
    previous secret deleted. If the commit fails, the new secret is deleted and any
    previous connection (row, reference and secret) stays untouched.
    """
    existing = get_connection(session, account.id)
    old_ref = existing.credential_ref if existing is not None else None
    new_ref = uuid4().hex
    try:
        store.set(new_ref, token.to_json())
    except CredentialStoreUnavailable:
        raise _store_unavailable() from None

    try:
        connection = existing or ThreadsConnection(
            account_id=account.id, project_id=account.project_id
        )
        connection.threads_user_id = identity.threads_user_id
        connection.username = identity.username
        connection.display_name = identity.display_name
        connection.profile_picture_url = identity.profile_picture_url
        connection.status = ThreadsConnectionStatus.CONNECTED
        connection.credential_ref = new_ref
        connection.token_obtained_at = token.token_obtained_at
        connection.credential_expires_at = token.expires_at
        connection.data_access_expires_at = token_info.data_access_expires_at
        connection.connected_at = now
        connection.last_verified_at = now
        connection.updated_at = now
        if existing is None:
            session.add(connection)
        _commit(session)
    except Exception as error:
        session.rollback()
        _discard_secret(store, new_ref, account.id)
        if isinstance(error, IntegrityError):
            raise AppError(
                409,
                "threads_account_already_connected",
                "This Threads account is already connected to another account in "
                "this project. Disconnect it there first.",
            ) from None
        raise
    if old_ref is not None:
        _discard_secret(store, old_ref, account.id)
    return connection


def _confirm_grant(
    gateway: ThreadsGateway, access_token: str, expected_user_id: str
) -> ThreadsTokenInfo:
    """Confirm with `debug_token` that the token is valid, belongs to the expected user
    and holds both required scopes (spec FR-008). Gateway errors propagate."""
    info = gateway.debug_token(access_token)
    if not info.is_valid:
        raise GrantRejected([])
    if info.user_id != expected_user_id:
        raise GrantIdentityMismatch()
    missing = sorted(REQUIRED_SCOPES - info.scopes)
    if missing:
        raise GrantRejected(missing)
    return info


def _reconnect_required(
    session: Session, connection: ThreadsConnection, now: datetime, message: str
) -> NoReturn:
    mark_reconnect_required(session, connection, now)
    raise AppError(409, "threads_reconnect_required", message)


def _identity_mismatch(
    session: Session, connection: ThreadsConnection, now: datetime
) -> NoReturn:
    mark_reconnect_required(session, connection, now)
    raise AppError(409, "threads_identity_mismatch", IDENTITY_MISMATCH_MESSAGE)


def _grant_rejected(
    session: Session, connection: ThreadsConnection, now: datetime, missing: list[str]
) -> NoReturn:
    if missing:
        _reconnect_required(session, connection, now, _permission_message(missing))
    _reconnect_required(session, connection, now, TOKEN_REJECTED_MESSAGE)


_refresh_locks: dict[int, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _account_lock(account_id: int) -> threading.Lock:
    with _refresh_locks_guard:
        return _refresh_locks.setdefault(account_id, threading.Lock())


def _connected_or_error(session: Session, account_id: int) -> ThreadsConnection:
    connection = get_connection(session, account_id)
    if connection is None:
        raise AppError(409, "threads_not_connected", NOT_CONNECTED_MESSAGE)
    if connection.status == ThreadsConnectionStatus.RECONNECT_REQUIRED:
        raise AppError(409, "threads_reconnect_required", RECONNECT_REQUIRED_MESSAGE)
    return connection


def _inspect_after_refresh(
    session: Session,
    store: CredentialStore,
    gateway: ThreadsGateway,
    connection: ThreadsConnection,
    token: ThreadsToken,
) -> ThreadsToken:
    """Inspect a freshly renewed token (data-model, step 8c).

    The refresh is already complete: transient failures and failed writes keep the new
    token and the last known metadata; only an official definitive signal marks the
    connection `reconnect_required`. `data_access_expires_at` is never computed.
    """
    now = gateway.clock()
    try:
        info = _confirm_grant(gateway, token.access_token, connection.threads_user_id)
    except GrantIdentityMismatch:
        _identity_mismatch(session, connection, now)
    except GrantRejected as rejected:
        _grant_rejected(session, connection, now, rejected.missing)
    except ThreadsTokenInvalid:
        _reconnect_required(session, connection, now, TOKEN_REJECTED_MESSAGE)
    except ThreadsPermissionDenied as error:
        _reconnect_required(
            session,
            connection,
            now,
            _permission_message([error.permission] if error.permission else []),
        )
    except ThreadsError:
        logger.warning(
            "Could not inspect the renewed Threads token of account %s (temporary)",
            connection.account_id,
        )
        return token
    if info.scopes != token.scopes:
        updated = replace(token, scopes=info.scopes)
        try:
            store.set(connection.credential_ref, updated.to_json())
        except CredentialStoreUnavailable:
            logger.warning(
                "Could not store the confirmed Threads scopes of account %s",
                connection.account_id,
            )
        else:
            token = updated
    connection.data_access_expires_at = info.data_access_expires_at
    connection.updated_at = now
    try:
        _commit(session)
    except Exception as error:
        session.rollback()
        logger.warning(
            "Could not save the Threads data access expiry of account %s (%s)",
            connection.account_id,
            type(error).__name__,
        )
    return token


def get_valid_credentials(
    session: Session,
    store: CredentialStore,
    gateway: ThreadsGateway,
    account_id: int,
) -> ThreadsToken:
    """Return a usable long-lived token, renewing it under AutoPublisher's policy.

    Policy of data-model.md: the secret is read first and the SQLite mirror repaired;
    a token with more than RENEWAL_WINDOW left is used as is; inside the window it is
    renewed once Meta allows it (≥ REFRESH_MIN_AGE). Transient failures never change
    the status; an expired token, a missing secret or a definitive rejection mark the
    connection `reconnect_required`. `data_access_expires_at` plays no part here.
    """
    connection = _connected_or_error(session, account_id)
    with _account_lock(account_id):
        now = gateway.clock()
        try:
            token = _read_token(store, connection.credential_ref)
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
        if token is None:
            _reconnect_required(
                session,
                connection,
                now,
                "The stored Threads credentials are missing. Reconnect the account.",
            )
        _sync_metadata(session, connection, token)
        remaining = token.expires_at - now
        if remaining <= timedelta(0):
            _reconnect_required(
                session,
                connection,
                now,
                "The Threads access has expired and cannot be renewed. "
                "Reconnect the account.",
            )
        if remaining > RENEWAL_WINDOW:
            return token
        usable = remaining > EXPIRY_MARGIN
        if now - token.token_obtained_at < REFRESH_MIN_AGE:
            if usable:
                return token
            # About to expire and not yet renewable: AutoPublisher's safety margin
            # combined with Meta's 24 h condition.
            _reconnect_required(
                session,
                connection,
                now,
                "The Threads access is about to expire and cannot be renewed yet. "
                "Reconnect the account.",
            )

        try:
            refreshed = gateway.refresh(token)
        except (ThreadsUnavailable, ThreadsUnexpectedResponse) as error:
            if not usable:
                if isinstance(error, ThreadsUnavailable):
                    raise _unavailable() from None
                raise _unexpected() from None
            logger.warning(
                "Could not renew the Threads token of account %s (temporary)",
                account_id,
            )
            return token
        except ThreadsPermissionDenied as error:
            _reconnect_required(
                session,
                connection,
                now,
                _permission_message([error.permission] if error.permission else []),
            )
        except ThreadsError:
            # Token rejected (190) or any other definitive rejection of the renewal.
            _reconnect_required(session, connection, now, TOKEN_REJECTED_MESSAGE)
        try:
            store.set(connection.credential_ref, refreshed.to_json())
        except CredentialStoreUnavailable:
            # The previous secret is untouched and still valid.
            raise _store_unavailable() from None
        connection.token_obtained_at = refreshed.token_obtained_at
        connection.credential_expires_at = refreshed.expires_at
        connection.updated_at = now
        try:
            _commit(session)
        except Exception as error:
            # The secret is authoritative: never restore the old token; the mirror is
            # repaired on the next access.
            session.rollback()
            logger.warning(
                "Could not save the renewed Threads token metadata of account %s (%s)",
                account_id,
                type(error).__name__,
            )
        return _inspect_after_refresh(session, store, gateway, connection, refreshed)


def get_linked_identity(session: Session, account_id: int) -> ThreadsIdentity:
    """Public identity of a connected Threads account (for Feature 011)."""
    return identity_of(_connected_or_error(session, account_id))


def verify_identity(
    session: Session,
    store: CredentialStore,
    gateway: ThreadsGateway,
    account_id: int,
) -> ThreadsConnection:
    """Check the linked Threads account against Meta, read-only towards Threads.

    Error precedence (contracts/api.md): missing account, platform, inactive project
    or account, not connected, reconnect required; only then are the secure storage
    and Meta used.
    """
    account = get_threads_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    connection = _connected_or_error(session, account_id)
    token = get_valid_credentials(session, store, gateway, account_id)
    now = gateway.clock()
    try:
        info = _confirm_grant(gateway, token.access_token, connection.threads_user_id)
        identity = gateway.fetch_me(token.access_token)
    except GrantIdentityMismatch:
        _identity_mismatch(session, connection, now)
    except GrantRejected as rejected:
        _grant_rejected(session, connection, now, rejected.missing)
    except ThreadsUnavailable:
        raise _unavailable() from None
    except ThreadsTokenInvalid:
        _reconnect_required(session, connection, now, TOKEN_REJECTED_MESSAGE)
    except ThreadsPermissionDenied as error:
        _reconnect_required(
            session,
            connection,
            now,
            _permission_message([error.permission] if error.permission else []),
        )
    except ThreadsError:
        raise _unexpected() from None
    if identity.threads_user_id != connection.threads_user_id:
        _identity_mismatch(session, connection, now)
    if info.scopes != token.scopes:
        # Only rewrite the secret when the confirmed scopes changed, keeping the token
        # and its dates exactly as they are.
        try:
            store.set(
                connection.credential_ref, replace(token, scopes=info.scopes).to_json()
            )
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
    connection.username = identity.username
    connection.display_name = identity.display_name
    connection.profile_picture_url = identity.profile_picture_url
    connection.data_access_expires_at = info.data_access_expires_at
    connection.last_verified_at = now
    connection.updated_at = now
    _commit(session)
    return connection


# --- Logging -----------------------------------------------------------------------

# Loggers of the HTTP client stack (the same ones protected for YouTube and
# Instagram). httpx2 logs every request URL at INFO and httpcore2 logs headers at DEBUG.
HTTP_LOGGERS = (
    "httpx2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "httpcore2.proxy",
    "httpcore2.socks",
)

_SECRET_PARAMS = re.compile(
    r"\b(access_token|input_token|client_secret|code|state)=[^&\s'\"<>]+",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[^\s'\",)]+", re.IGNORECASE)
# App access tokens have the form TH|<app id>|<token or secret>.
_APP_TOKEN = re.compile(r"TH(\||%7C)[^\s&'\"<>]+", re.IGNORECASE)
# Graph object ids in request paths (user, container and post ids, Feature 011).
_GRAPH_OBJECT_ID = re.compile(r"(graph\.threads\.(?:net|com)/v\d+\.\d+/)\d+")


class RedactThreadsSecrets(logging.Filter):
    """Remove tokens, the app secret, codes and states from HTTP client logs.

    Threads' token and debug endpoints carry `access_token`, `input_token` and
    `client_secret` in the query string (research §16). Object ids in request paths
    (containers, posts) are never logged either.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # A broken record is left for logging to report.
            return True
        lowered = message.lower()
        if (
            "=" in message
            or "bearer" in lowered
            or "th|" in lowered
            or "graph.threads" in lowered
        ):
            redacted = _SECRET_PARAMS.sub(r"\1=[redacted]", message)
            redacted = _BEARER.sub(r"\1[redacted]", redacted)
            redacted = _APP_TOKEN.sub("TH|[redacted]", redacted)
            redacted = _GRAPH_OBJECT_ID.sub(r"\1[id]", redacted)
            if redacted != message:
                record.msg = redacted
                record.args = ()
        return True


def install_log_redaction() -> None:
    for name in HTTP_LOGGERS:
        http_logger = logging.getLogger(name)
        if not any(isinstance(f, RedactThreadsSecrets) for f in http_logger.filters):
            http_logger.addFilter(RedactThreadsSecrets())


# --- Completing an authorization ----------------------------------------------------


def _failure_from(error: Exception) -> AttemptFailure:
    if isinstance(error, ConflictError):
        return AttemptFailure(409, error.code, error.message)
    if isinstance(error, AppError):
        return AttemptFailure(error.status_code, error.code, error.message)
    if isinstance(error, NotFoundError):
        return AttemptFailure(404, "not_found", error.message)
    raise error


def _exchange_failure(error: ThreadsError) -> AttemptFailure:
    if isinstance(error, ThreadsUnavailable):
        return AttemptFailure(
            503, "threads_unavailable", AUTHORIZATION_UNAVAILABLE_MESSAGE
        )
    if isinstance(error, ThreadsUnexpectedResponse):
        return AttemptFailure(502, "threads_unexpected_response", UNEXPECTED_MESSAGE)
    return AttemptFailure(502, "threads_token_exchange_failed", EXCHANGE_FAILED_MESSAGE)


def _permission_missing(missing: list[str]) -> AttemptFailure:
    if missing:
        message = (
            "Grant all requested permissions to connect the account. Missing: "
            f"{', '.join(missing)}."
        )
    else:
        message = (
            "Threads did not confirm the requested permissions. Grant all requested "
            "permissions and start the connection again."
        )
    return AttemptFailure(422, "threads_permission_missing", message)


def _process_redirect(
    session: Session,
    store: CredentialStore,
    gateway: ThreadsGateway,
    registry: ThreadsAttemptRegistry,
    attempt: ThreadsOAuthAttempt,
    redirect: RedirectResult,
    config: ThreadsAppConfig,
) -> None:
    if redirect.error is not None:
        if redirect.error == "access_denied":
            raise AttemptFailure(400, "threads_oauth_denied", DENIED_MESSAGE)
        raise AttemptFailure(
            400, "threads_oauth_provider_error", PROVIDER_ERROR_MESSAGE
        )
    code = redirect.code
    assert code is not None

    try:
        account = get_threads_account_or_error(session, attempt.account_id)
        # Checked before any request to Meta (it may have been deactivated).
        ensure_account_connectable(session, account)
    except (ConflictError, AppError, NotFoundError) as failure:
        raise _failure_from(failure) from None

    # The code is single-use: it is exchanged exactly once, never retried.
    try:
        short_token = gateway.exchange_code(code, config)
    except ThreadsError as error:
        raise _exchange_failure(error) from None
    try:
        token = gateway.exchange_long_lived(short_token, config)
    except ThreadsError as error:
        raise _exchange_failure(error) from None
    try:
        info = _confirm_grant(gateway, token.access_token, short_token.user_id)
    except GrantRejected as rejected:
        raise _permission_missing(rejected.missing) from None
    except GrantIdentityMismatch:
        raise AttemptFailure(
            502, "threads_unexpected_response", UNEXPECTED_MESSAGE
        ) from None
    except ThreadsPermissionDenied as error:
        raise _permission_missing(
            [error.permission] if error.permission else []
        ) from None
    except (ThreadsUnavailable, ThreadsUnexpectedResponse) as error:
        raise _exchange_failure(error) from None
    except ThreadsError:
        # The grant cannot be confirmed: never connect without confirmation.
        raise _permission_missing([]) from None
    token = replace(token, scopes=info.scopes)
    try:
        identity = gateway.fetch_me(token.access_token)
    except ThreadsPermissionDenied as error:
        raise _permission_missing(
            [error.permission] if error.permission else []
        ) from None
    except ThreadsError as error:
        raise _exchange_failure(error) from None
    if identity.threads_user_id != short_token.user_id:
        raise AttemptFailure(502, "threads_unexpected_response", UNEXPECTED_MESSAGE)

    now = gateway.clock()
    try:
        ensure_identity_available(
            session, account.project_id, identity.threads_user_id, account.id
        )
        existing = get_connection(session, account.id)
        if (
            existing is not None
            and existing.threads_user_id != identity.threads_user_id
        ):
            # Never replace a linked account silently: wait for a confirmation.
            registry.await_confirmation(
                attempt, identity, (token, info), identity_of(existing)
            )
            return
        connection = complete_connection(
            session, store, account, identity, token, info, now
        )
    except (ConflictError, AppError) as failure:
        raise _failure_from(failure) from None
    registry.finish(
        attempt,
        ThreadsAttemptStatus.COMPLETED,
        connection=connection_to_read(session, store, connection, now).model_dump(
            mode="json"
        ),
    )


# --- Routes ------------------------------------------------------------------------


@router.get(
    "/accounts/{account_id}/threads-connection",
    response_model=ThreadsConnectionRead,
)
def get_threads_connection(
    account_id: int, session: SessionDep, store: StoreDep, gateway: GatewayDep
) -> ThreadsConnectionRead:
    get_threads_account_or_error(session, account_id)
    return connection_to_read(
        session, store, get_connection(session, account_id), gateway.clock()
    )


@router.post(
    "/accounts/{account_id}/threads-connection/authorize",
    response_model=ThreadsAuthorizeRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_threads(
    account_id: int, session: SessionDep, registry: RegistryDep
) -> ThreadsAuthorizeRead:
    account = get_threads_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    config = load_config()
    state = generate_state()
    existing = get_connection(session, account.id)
    attempt = registry.create(
        account.id,
        state,
        current_identity=identity_of(existing) if existing is not None else None,
    )
    return ThreadsAuthorizeRead(
        attempt_id=attempt.attempt_id,
        authorization_url=build_authorization_url(config, state),
        expires_at=attempt.expires_at,
    )


def _attempt_expired() -> AppError:
    return AppError(410, "threads_oauth_attempt_expired", ATTEMPT_EXPIRED_MESSAGE)


@router.post(
    "/threads/oauth/attempts/{attempt_id}/complete",
    response_model=ThreadsOAuthAttemptRead,
)
def complete_threads_attempt(
    attempt_id: str,
    body: ThreadsCompleteWrite,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> ThreadsOAuthAttemptRead:
    """Finish an authorization with the redirect URL the user pasted.

    Problems with the pasted URL itself (wrong address, wrong state) keep the attempt
    pending so a correct paste still works; once the state is used, every outcome
    finishes the attempt.
    """
    found = registry.get(attempt_id)
    if found is None or found.status == ThreadsAttemptStatus.EXPIRED:
        raise _attempt_expired()
    config = load_config()
    try:
        redirect = parse_redirect_url(body.redirect_url, config)
    except InvalidRedirectUrl:
        raise AppError(
            400, "threads_oauth_redirect_url_invalid", REDIRECT_INVALID_MESSAGE
        ) from None
    try:
        attempt = registry.consume_state(attempt_id, redirect.state)
    except (AttemptNotFound, AttemptExpired):
        raise _attempt_expired() from None
    except AttemptStateInvalid:
        raise AppError(
            400, "threads_oauth_state_invalid", STATE_INVALID_MESSAGE
        ) from None

    try:
        _process_redirect(session, store, gateway, registry, attempt, redirect, config)
    except AttemptFailure as failure:
        logger.info(
            "Threads authorization failed for account %s (%s)",
            attempt.account_id,
            failure.code,
        )
        registry.finish(
            attempt,
            ThreadsAttemptStatus.FAILED,
            error={"code": failure.code, "message": failure.message},
        )
        raise AppError(failure.status_code, failure.code, failure.message) from None
    except Exception as unexpected:
        logger.error(
            "Unexpected error while completing a Threads authorization for account %s "
            "(%s)",
            attempt.account_id,
            type(unexpected).__name__,
        )
        registry.finish(
            attempt,
            ThreadsAttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        raise AppError(500, "internal_error", INTERNAL_MESSAGE) from None
    return attempt_to_read(attempt)


def _not_confirmable() -> AppError:
    return AppError(
        409,
        "threads_oauth_attempt_not_confirmable",
        "This authorization is no longer waiting for a confirmation.",
    )


def _attempt_not_found() -> AppError:
    return AppError(
        404, "threads_oauth_attempt_not_found", "This authorization was not found."
    )


@router.post(
    "/threads/oauth/attempts/{attempt_id}/confirm",
    response_model=ThreadsOAuthAttemptRead,
)
def confirm_threads_attempt(
    attempt_id: str,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> ThreadsOAuthAttemptRead:
    try:
        attempt, credentials = registry.claim_confirmation(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    token, token_info = credentials
    now = gateway.clock()
    try:
        account = get_threads_account_or_error(session, attempt.account_id)
        ensure_account_connectable(session, account)
        existing = get_connection(session, account.id)
        if (
            existing is None
            or attempt.current_identity is None
            or existing.threads_user_id != attempt.current_identity.threads_user_id
        ):
            raise AppError(
                409,
                "threads_connection_changed",
                "The connection changed in the meantime. Start the connection again.",
            )
        new_identity = attempt.new_identity
        assert new_identity is not None
        ensure_identity_available(
            session, account.project_id, new_identity.threads_user_id, account.id
        )
        connection = complete_connection(
            session, store, account, new_identity, token, token_info, now
        )
    except (ConflictError, AppError, NotFoundError) as failure:
        reported = _failure_from(failure)
        registry.finish(
            attempt,
            ThreadsAttemptStatus.FAILED,
            error={"code": reported.code, "message": reported.message},
        )
        raise
    except Exception as unexpected:
        logger.error(
            "Unexpected error while confirming a Threads account change for account "
            "%s (%s)",
            attempt.account_id,
            type(unexpected).__name__,
        )
        registry.finish(
            attempt,
            ThreadsAttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        raise AppError(500, "internal_error", INTERNAL_MESSAGE) from None
    registry.finish(
        attempt,
        ThreadsAttemptStatus.COMPLETED,
        connection=connection_to_read(session, store, connection, now).model_dump(
            mode="json"
        ),
    )
    return attempt_to_read(attempt)


@router.post(
    "/threads/oauth/attempts/{attempt_id}/cancel",
    response_model=ThreadsOAuthAttemptRead,
)
def cancel_threads_attempt(
    attempt_id: str, registry: RegistryDep
) -> ThreadsOAuthAttemptRead:
    try:
        attempt = registry.cancel(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    return attempt_to_read(attempt)


@router.post(
    "/accounts/{account_id}/threads-connection/verify",
    response_model=ThreadsConnectionRead,
)
def verify_threads_connection(
    account_id: int, session: SessionDep, store: StoreDep, gateway: GatewayDep
) -> ThreadsConnectionRead:
    connection = verify_identity(session, store, gateway, account_id)
    return connection_to_read(session, store, connection, gateway.clock())


@router.post(
    "/accounts/{account_id}/threads-connection/disconnect",
    response_model=ThreadsConnectionRead,
)
def disconnect_threads(
    account_id: int,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> ThreadsConnectionRead:
    """Delete the stored token, then the reference. Meta is never contacted."""
    get_threads_account_or_error(session, account_id)
    connection = get_connection(session, account_id)
    if connection is not None:
        try:
            store.delete(connection.credential_ref)
        except CredentialStoreUnavailable:
            # Keep the connection and its reference so the user can retry.
            raise _store_unavailable() from None
        session.delete(connection)
        _commit(session)
    registry.expire_for_account(account_id)
    return connection_to_read(session, store, None, gateway.clock())
