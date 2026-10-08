"""Instagram account connection over Instagram Login (see
specs/008-instagram-oauth-connection).

The accounts core knows nothing about Instagram: connections are looked up here by
`account_id`. The long-lived token lives only in the secure credential store (service
`autopublisher.instagram`); SQLite keeps a non-secret `credential_ref`. There is no
callback route: the user pastes the redirect URL and `complete` answers synchronously.
Disconnecting never contacts Meta.
"""

import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Annotated, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_instagram_app_file
from app.credential_store import CredentialStore, CredentialStoreUnavailable
from app.db import get_session
from app.errors import AppError, ConflictError, NotFoundError
from app.instagram_gateway import (
    PROFESSIONAL_ACCOUNT_TYPES,
    InstagramGateway,
    InstagramToken,
    MetaError,
    MetaPermissionDenied,
    MetaTokenInvalid,
    MetaUnavailable,
    MetaUnexpectedResponse,
)
from app.instagram_oauth import (
    REQUIRED_PERMISSIONS,
    AttemptExpired,
    AttemptNotConfirmable,
    AttemptNotFound,
    AttemptStateInvalid,
    InstagramAttemptRegistry,
    InstagramAttemptStatus,
    InstagramIdentity,
    InstagramOAuthAttempt,
    InstagramOAuthNotConfigured,
    InvalidRedirectUrl,
    MetaAppConfig,
    RedirectResult,
    build_authorization_url,
    generate_state,
    load_meta_app_config,
    parse_redirect_url,
)
from app.models import (
    Account,
    InstagramConnection,
    InstagramConnectionStatus,
    Platform,
    Project,
)
from app.schemas import (
    InstagramAuthorizeRead,
    InstagramCompleteWrite,
    InstagramConnectionRead,
    InstagramIdentityRead,
    InstagramOAuthAttemptRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["instagram"])

SessionDep = Annotated[Session, Depends(get_session)]

# Official minimum age of a long-lived token before it can be refreshed (research §5).
REFRESH_MIN_AGE = timedelta(hours=24)
# Tokens closer than this to expiry must be refreshed before use.
EXPIRY_MARGIN = timedelta(minutes=5)

DOCS_HINT = "See docs/instagram-accounts.md."
STORE_UNAVAILABLE_MESSAGE = (
    f"The system's secure credential storage is not available. {DOCS_HINT}"
)
NOT_CONFIGURED_MESSAGE = f"Instagram integration is not configured. {DOCS_HINT}"
UNAVAILABLE_MESSAGE = "Could not reach Instagram. Check your connection and try again."
UNEXPECTED_MESSAGE = "Instagram returned an unexpected response. Try again later."
INTERNAL_MESSAGE = "An unexpected error occurred. Please try again."
NOT_PROFESSIONAL_MESSAGE = (
    "Only Instagram Professional accounts (Business or Creator) can be connected. "
    "Convert this account to a Professional account in Instagram and try again."
)
EXCHANGE_FAILED_MESSAGE = (
    "Instagram did not complete the authorization. Start the connection again."
)
REDIRECT_INVALID_MESSAGE = (
    "The pasted address is not the address Instagram redirected to. Copy the full "
    "address of the page Instagram opened and paste it again."
)
STATE_INVALID_MESSAGE = (
    "The pasted address does not belong to this connection attempt, or it was "
    "already used. Paste the address from this attempt or start the connection again."
)
ATTEMPT_EXPIRED_MESSAGE = "This authorization has expired. Start the connection again."
DENIED_MESSAGE = "The connection was cancelled in Instagram."
PROVIDER_ERROR_MESSAGE = (
    "Instagram could not complete the authorization. Make sure this Instagram account "
    f"can use your Meta App (for example as an Instagram tester) and try again. "
    f"{DOCS_HINT}"
)
NOT_CONNECTED_MESSAGE = "This Instagram account is not connected."
TOKEN_REJECTED_MESSAGE = (
    "Instagram no longer accepts the stored credentials. Reconnect the account."
)
RECONNECT_REQUIRED_MESSAGE = (
    "The Instagram connection needs to be renewed. Reconnect the account."
)


def get_instagram_credential_store(request: Request) -> CredentialStore:
    store: CredentialStore = request.app.state.instagram_credential_store
    return store


def get_instagram_gateway(request: Request) -> InstagramGateway:
    gateway: InstagramGateway = request.app.state.instagram_gateway
    return gateway


def get_instagram_registry(request: Request) -> InstagramAttemptRegistry:
    registry: InstagramAttemptRegistry = request.app.state.instagram_attempts
    return registry


StoreDep = Annotated[CredentialStore, Depends(get_instagram_credential_store)]
GatewayDep = Annotated[InstagramGateway, Depends(get_instagram_gateway)]
RegistryDep = Annotated[InstagramAttemptRegistry, Depends(get_instagram_registry)]


class AttemptFailure(Exception):
    """An expected failure while completing an authorization."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _store_unavailable() -> AppError:
    return AppError(503, "credential_store_unavailable", STORE_UNAVAILABLE_MESSAGE)


def _unavailable() -> AppError:
    return AppError(503, "instagram_unavailable", UNAVAILABLE_MESSAGE)


def _unexpected() -> AppError:
    return AppError(502, "instagram_unexpected_response", UNEXPECTED_MESSAGE)


def _permission_message(missing: list[str]) -> str:
    if not missing:
        return (
            "A required Instagram permission is missing or was withdrawn. "
            "Reconnect the account and grant all requested permissions."
        )
    names = ", ".join(missing)
    return (
        f"A required Instagram permission is missing or was withdrawn ({names}). "
        "Reconnect the account and grant all requested permissions."
    )


# --- Lookups and read models -------------------------------------------------------


def get_instagram_account_or_error(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError("Account not found.")
    if account.platform != Platform.INSTAGRAM:
        raise ConflictError(
            "platform_not_supported", "Only Instagram accounts can be connected."
        )
    return account


def get_connection(session: Session, account_id: int) -> InstagramConnection | None:
    return session.scalars(
        select(InstagramConnection).where(InstagramConnection.account_id == account_id)
    ).first()


def oauth_configured() -> bool:
    """Whether the local Meta App file is usable; read on every call."""
    try:
        load_meta_app_config(get_instagram_app_file())
    except InstagramOAuthNotConfigured:
        return False
    return True


def load_config() -> MetaAppConfig:
    try:
        return load_meta_app_config(get_instagram_app_file())
    except InstagramOAuthNotConfigured:
        raise AppError(
            503, "instagram_oauth_not_configured", NOT_CONFIGURED_MESSAGE
        ) from None


def identity_of(connection: InstagramConnection) -> InstagramIdentity:
    return InstagramIdentity(
        instagram_user_id=connection.instagram_user_id,
        username=connection.username,
        account_type=connection.account_type,
        profile_picture_url=connection.profile_picture_url,
        app_scoped_id=connection.app_scoped_id,
    )


def mark_reconnect_required(
    session: Session, connection: InstagramConnection, now: datetime
) -> None:
    if connection.status != InstagramConnectionStatus.RECONNECT_REQUIRED:
        connection.status = InstagramConnectionStatus.RECONNECT_REQUIRED
        connection.updated_at = now
        session.commit()


def connection_to_read(
    session: Session, connection: InstagramConnection | None, now: datetime
) -> InstagramConnectionRead:
    """Public view; an expired token can no longer be renewed, so a connection whose
    token has expired is marked `reconnect_required` here, without any network call."""
    configured = oauth_configured()
    if connection is None:
        return InstagramConnectionRead(
            status="not_connected",
            identity=None,
            connected_at=None,
            last_verified_at=None,
            access_expires_at=None,
            oauth_configured=configured,
        )
    if (
        connection.status == InstagramConnectionStatus.CONNECTED
        and connection.credential_expires_at <= now
    ):
        mark_reconnect_required(session, connection, now)
    return InstagramConnectionRead(
        status="connected"
        if connection.status == InstagramConnectionStatus.CONNECTED
        else "reconnect_required",
        identity=InstagramIdentityRead.model_validate(
            identity_of(connection).to_read()
        ),
        connected_at=connection.connected_at,
        last_verified_at=connection.last_verified_at,
        access_expires_at=connection.credential_expires_at,
        oauth_configured=configured,
    )


def attempt_to_read(attempt: InstagramOAuthAttempt) -> InstagramOAuthAttemptRead:
    return InstagramOAuthAttemptRead.model_validate(attempt.to_read())


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
    session: Session, project_id: int, instagram_user_id: str, account_id: int
) -> None:
    """An Instagram account can be linked to only one account per project (active
    or not)."""
    holder = session.execute(
        select(Account.handle)
        .join(InstagramConnection, InstagramConnection.account_id == Account.id)
        .where(
            InstagramConnection.project_id == project_id,
            InstagramConnection.instagram_user_id == instagram_user_id,
            InstagramConnection.account_id != account_id,
        )
    ).first()
    if holder is not None:
        raise AppError(
            409,
            "instagram_account_already_connected",
            f"This Instagram account is already connected to @{holder.handle} in "
            "this project. Disconnect it there first.",
        )


def _discard_secret(store: CredentialStore, ref: str, account_id: int) -> None:
    """Best-effort delete; if it fails the entry stays orphaned (documented)."""
    try:
        store.delete(ref)
    except CredentialStoreUnavailable:
        logger.warning(
            "Could not delete stored Instagram credentials for account %s", account_id
        )


def complete_connection(
    session: Session,
    store: CredentialStore,
    account: Account,
    identity: InstagramIdentity,
    token: InstagramToken,
    now: datetime,
) -> InstagramConnection:
    """Store the token, then link the identity; never a row without a secret."""
    existing = get_connection(session, account.id)
    old_ref = existing.credential_ref if existing is not None else None
    new_ref = uuid4().hex
    try:
        store.set(new_ref, token.to_json())
    except CredentialStoreUnavailable:
        raise _store_unavailable() from None

    try:
        connection = existing or InstagramConnection(
            account_id=account.id, project_id=account.project_id
        )
        connection.instagram_user_id = identity.instagram_user_id
        connection.app_scoped_id = identity.app_scoped_id
        connection.username = identity.username
        assert identity.account_type is not None
        connection.account_type = identity.account_type
        connection.profile_picture_url = identity.profile_picture_url
        connection.status = InstagramConnectionStatus.CONNECTED
        connection.credential_ref = new_ref
        connection.credential_expires_at = token.expires_at
        connection.connected_at = now
        connection.last_verified_at = now
        connection.updated_at = now
        if existing is None:
            session.add(connection)
        session.commit()
    except Exception as error:
        session.rollback()
        _discard_secret(store, new_ref, account.id)
        if isinstance(error, IntegrityError):
            raise AppError(
                409,
                "instagram_account_already_connected",
                "This Instagram account is already connected to another account in "
                "this project. Disconnect it there first.",
            ) from None
        raise
    if old_ref is not None:
        _discard_secret(store, old_ref, account.id)
    return connection


def _reconnect_required(
    session: Session, connection: InstagramConnection, now: datetime, message: str
) -> NoReturn:
    mark_reconnect_required(session, connection, now)
    raise AppError(409, "instagram_reconnect_required", message)


_refresh_locks: dict[int, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _account_lock(account_id: int) -> threading.Lock:
    with _refresh_locks_guard:
        return _refresh_locks.setdefault(account_id, threading.Lock())


def _connected_or_error(session: Session, account_id: int) -> InstagramConnection:
    connection = get_connection(session, account_id)
    if connection is None:
        raise AppError(409, "instagram_not_connected", NOT_CONNECTED_MESSAGE)
    if connection.status == InstagramConnectionStatus.RECONNECT_REQUIRED:
        raise AppError(409, "instagram_reconnect_required", RECONNECT_REQUIRED_MESSAGE)
    return connection


def get_valid_credentials(
    session: Session,
    store: CredentialStore,
    gateway: InstagramGateway,
    account_id: int,
) -> InstagramToken:
    """Return a usable long-lived token, renewing it when the official flow allows.

    Policy of data-model.md: a definitive rejection, a withdrawn permission, an
    expired token or a missing secret mark the connection `reconnect_required`;
    transient failures never change its status.
    """
    connection = _connected_or_error(session, account_id)
    with _account_lock(account_id):
        try:
            raw = store.get(connection.credential_ref)
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
        try:
            token = InstagramToken.from_json(raw) if raw is not None else None
        except ValueError:
            token = None
        now = gateway.clock()
        if token is None:
            _reconnect_required(
                session,
                connection,
                now,
                "The stored Instagram credentials are missing. Reconnect the account.",
            )
        expiring = token.expires_at - now <= EXPIRY_MARGIN
        renewable = now - token.issued_at >= REFRESH_MIN_AGE
        if expiring and (token.expires_at <= now or not renewable):
            _reconnect_required(
                session,
                connection,
                now,
                "The Instagram access has expired and cannot be renewed. "
                "Reconnect the account.",
            )
        if not renewable:
            return token

        try:
            refreshed = gateway.refresh(token)
        except MetaUnavailable:
            if expiring:
                raise _unavailable() from None
            logger.warning(
                "Could not renew the Instagram token of account %s (temporary)",
                account_id,
            )
            return token
        except MetaPermissionDenied as error:
            _reconnect_required(
                session,
                connection,
                now,
                _permission_message([error.permission] if error.permission else []),
            )
        except MetaUnexpectedResponse:
            if expiring:
                raise _unexpected() from None
            logger.warning(
                "Unexpected response renewing the Instagram token of account %s",
                account_id,
            )
            return token
        except MetaError:
            # Token rejected (190) or any other definitive rejection of the renewal.
            _reconnect_required(
                session,
                connection,
                now,
                TOKEN_REJECTED_MESSAGE,
            )
        try:
            store.set(connection.credential_ref, refreshed.to_json())
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
        connection.credential_expires_at = refreshed.expires_at
        connection.updated_at = now
        session.commit()
        return refreshed


def fetch_identity(gateway: InstagramGateway, access_token: str) -> InstagramIdentity:
    """Identity of the account the token belongs to (raises the gateway's errors)."""
    return gateway.fetch_me(access_token)


def verify_identity(
    session: Session,
    store: CredentialStore,
    gateway: InstagramGateway,
    account_id: int,
) -> InstagramConnection:
    """Check the linked Instagram account against Meta and refresh its public data.

    Error precedence (contracts/api.md): missing account, platform, inactive project
    or account, not connected, reconnect required; only then are the secure storage
    and Meta used.
    """
    account = get_instagram_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    connection = _connected_or_error(session, account_id)
    token = get_valid_credentials(session, store, gateway, account_id)
    now = gateway.clock()
    missing = sorted(REQUIRED_PERMISSIONS - token.permissions)
    if missing:
        _reconnect_required(session, connection, now, _permission_message(missing))
    try:
        identity = fetch_identity(gateway, token.access_token)
    except MetaUnavailable:
        raise _unavailable() from None
    except MetaTokenInvalid:
        _reconnect_required(
            session,
            connection,
            now,
            TOKEN_REJECTED_MESSAGE,
        )
    except MetaPermissionDenied as error:
        _reconnect_required(
            session,
            connection,
            now,
            _permission_message([error.permission] if error.permission else []),
        )
    except MetaError:
        raise _unexpected() from None
    if identity.instagram_user_id != connection.instagram_user_id:
        mark_reconnect_required(session, connection, now)
        raise AppError(
            409,
            "instagram_identity_mismatch",
            "The authorized Instagram account no longer matches the linked account. "
            "Reconnect the account to change it.",
        )
    if identity.account_type not in PROFESSIONAL_ACCOUNT_TYPES:
        mark_reconnect_required(session, connection, now)
        raise AppError(
            409, "instagram_account_not_professional", NOT_PROFESSIONAL_MESSAGE
        )
    assert identity.account_type is not None
    connection.username = identity.username
    connection.account_type = identity.account_type
    connection.profile_picture_url = identity.profile_picture_url
    if identity.app_scoped_id is not None:
        connection.app_scoped_id = identity.app_scoped_id
    connection.last_verified_at = now
    connection.updated_at = now
    session.commit()
    return connection


# --- Logging -----------------------------------------------------------------------

# Loggers of the HTTP client stack (the same ones protected for YouTube). httpx2 logs
# every request URL at INFO and httpcore2 logs headers at DEBUG.
HTTP_LOGGERS = (
    "httpx2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "httpcore2.proxy",
    "httpcore2.socks",
)

_SECRET_PARAMS = re.compile(
    r"\b(access_token|client_secret|code|state)=[^&\s'\"<>]+", re.IGNORECASE
)
_BEARER = re.compile(r"(Bearer\s+)[^\s'\",)]+", re.IGNORECASE)


class RedactInstagramSecrets(logging.Filter):
    """Remove tokens, the app secret, codes and states from HTTP client logs.

    Instagram's token endpoints carry `access_token` and `client_secret` in the query
    string (research §13).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # A broken record is left for logging to report.
            return True
        lowered = message.lower()
        if "=" in message or "bearer" in lowered:
            redacted = _SECRET_PARAMS.sub(r"\1=[redacted]", message)
            redacted = _BEARER.sub(r"\1[redacted]", redacted)
            if redacted != message:
                record.msg = redacted
                record.args = ()
        return True


def install_log_redaction() -> None:
    for name in HTTP_LOGGERS:
        http_logger = logging.getLogger(name)
        if not any(isinstance(f, RedactInstagramSecrets) for f in http_logger.filters):
            http_logger.addFilter(RedactInstagramSecrets())


# --- Completing an authorization ----------------------------------------------------


def _failure_from(error: Exception) -> AttemptFailure:
    if isinstance(error, ConflictError):
        return AttemptFailure(409, error.code, error.message)
    if isinstance(error, AppError):
        return AttemptFailure(error.status_code, error.code, error.message)
    if isinstance(error, NotFoundError):
        return AttemptFailure(404, "not_found", error.message)
    raise error


def _exchange_failure(error: MetaError) -> AttemptFailure:
    if isinstance(error, MetaUnavailable):
        return AttemptFailure(503, "instagram_unavailable", UNAVAILABLE_MESSAGE)
    if isinstance(error, MetaUnexpectedResponse):
        return AttemptFailure(502, "instagram_unexpected_response", UNEXPECTED_MESSAGE)
    return AttemptFailure(
        502, "instagram_token_exchange_failed", EXCHANGE_FAILED_MESSAGE
    )


def _process_redirect(
    session: Session,
    store: CredentialStore,
    gateway: InstagramGateway,
    registry: InstagramAttemptRegistry,
    attempt: InstagramOAuthAttempt,
    redirect: RedirectResult,
    config: MetaAppConfig,
) -> None:
    if redirect.error is not None:
        if redirect.error == "access_denied":
            raise AttemptFailure(400, "instagram_oauth_denied", DENIED_MESSAGE)
        raise AttemptFailure(
            400, "instagram_oauth_provider_error", PROVIDER_ERROR_MESSAGE
        )
    code = redirect.code
    assert code is not None

    try:
        account = get_instagram_account_or_error(session, attempt.account_id)
        # Checked before any request to Meta (it may have been deactivated).
        ensure_account_connectable(session, account)
    except (ConflictError, AppError, NotFoundError) as failure:
        raise _failure_from(failure) from None

    try:
        short_token = gateway.exchange_code(code, config)
    except MetaError as error:
        raise _exchange_failure(error) from None
    missing = sorted(REQUIRED_PERMISSIONS - short_token.permissions)
    if missing:
        raise AttemptFailure(
            422,
            "instagram_permission_missing",
            f"Grant all requested permissions to connect the account. Missing: "
            f"{', '.join(missing)}.",
        )
    try:
        token = gateway.exchange_long_lived(short_token, config)
    except MetaError as error:
        raise _exchange_failure(error) from None
    try:
        identity = fetch_identity(gateway, token.access_token)
    except MetaPermissionDenied as error:
        missing = [error.permission] if error.permission else []
        raise AttemptFailure(
            422, "instagram_permission_missing", _permission_message(missing)
        ) from None
    except MetaError as error:
        raise _exchange_failure(error) from None
    if identity.account_type not in PROFESSIONAL_ACCOUNT_TYPES:
        raise AttemptFailure(
            422, "instagram_account_not_professional", NOT_PROFESSIONAL_MESSAGE
        )

    now = gateway.clock()
    try:
        ensure_identity_available(
            session, account.project_id, identity.instagram_user_id, account.id
        )
        existing = get_connection(session, account.id)
        if (
            existing is not None
            and existing.instagram_user_id != identity.instagram_user_id
        ):
            # Never replace a linked account silently: wait for a confirmation.
            registry.await_confirmation(attempt, identity, token, identity_of(existing))
            return
        connection = complete_connection(session, store, account, identity, token, now)
    except (ConflictError, AppError) as failure:
        raise _failure_from(failure) from None
    registry.finish(
        attempt,
        InstagramAttemptStatus.COMPLETED,
        connection=connection_to_read(session, connection, now).model_dump(mode="json"),
    )


# --- Routes ------------------------------------------------------------------------


@router.get(
    "/accounts/{account_id}/instagram-connection",
    response_model=InstagramConnectionRead,
)
def get_instagram_connection(
    account_id: int, session: SessionDep, gateway: GatewayDep
) -> InstagramConnectionRead:
    get_instagram_account_or_error(session, account_id)
    return connection_to_read(
        session, get_connection(session, account_id), gateway.clock()
    )


@router.post(
    "/accounts/{account_id}/instagram-connection/authorize",
    response_model=InstagramAuthorizeRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_instagram(
    account_id: int, session: SessionDep, registry: RegistryDep
) -> InstagramAuthorizeRead:
    account = get_instagram_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    config = load_config()
    state = generate_state()
    existing = get_connection(session, account.id)
    attempt = registry.create(
        account.id,
        state,
        current_identity=identity_of(existing) if existing is not None else None,
    )
    return InstagramAuthorizeRead(
        attempt_id=attempt.attempt_id,
        authorization_url=build_authorization_url(config, state),
        expires_at=attempt.expires_at,
    )


def _attempt_expired() -> AppError:
    return AppError(410, "instagram_oauth_attempt_expired", ATTEMPT_EXPIRED_MESSAGE)


@router.post(
    "/instagram/oauth/attempts/{attempt_id}/complete",
    response_model=InstagramOAuthAttemptRead,
)
def complete_instagram_attempt(
    attempt_id: str,
    body: InstagramCompleteWrite,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> InstagramOAuthAttemptRead:
    """Finish an authorization with the redirect URL the user pasted.

    Problems with the pasted URL itself (wrong address, wrong state) keep the attempt
    pending so a correct paste still works; once the state is used, every outcome
    finishes the attempt.
    """
    found = registry.get(attempt_id)
    if found is None or found.status == InstagramAttemptStatus.EXPIRED:
        raise _attempt_expired()
    config = load_config()
    try:
        redirect = parse_redirect_url(body.redirect_url, config)
    except InvalidRedirectUrl:
        raise AppError(
            400, "instagram_oauth_redirect_url_invalid", REDIRECT_INVALID_MESSAGE
        ) from None
    try:
        attempt = registry.consume_state(attempt_id, redirect.state)
    except (AttemptNotFound, AttemptExpired):
        raise _attempt_expired() from None
    except AttemptStateInvalid:
        raise AppError(
            400, "instagram_oauth_state_invalid", STATE_INVALID_MESSAGE
        ) from None

    try:
        _process_redirect(session, store, gateway, registry, attempt, redirect, config)
    except AttemptFailure as failure:
        logger.info(
            "Instagram authorization failed for account %s (%s)",
            attempt.account_id,
            failure.code,
        )
        registry.finish(
            attempt,
            InstagramAttemptStatus.FAILED,
            error={"code": failure.code, "message": failure.message},
        )
        raise AppError(failure.status_code, failure.code, failure.message) from None
    except Exception as unexpected:
        logger.error(
            "Unexpected error while completing an Instagram authorization for "
            "account %s (%s)",
            attempt.account_id,
            type(unexpected).__name__,
        )
        registry.finish(
            attempt,
            InstagramAttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        raise AppError(500, "internal_error", INTERNAL_MESSAGE) from None
    return attempt_to_read(attempt)


def _not_confirmable() -> AppError:
    return AppError(
        409,
        "instagram_oauth_attempt_not_confirmable",
        "This authorization is no longer waiting for a confirmation.",
    )


def _attempt_not_found() -> AppError:
    return AppError(
        404, "instagram_oauth_attempt_not_found", "This authorization was not found."
    )


@router.post(
    "/instagram/oauth/attempts/{attempt_id}/confirm",
    response_model=InstagramOAuthAttemptRead,
)
def confirm_instagram_attempt(
    attempt_id: str,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> InstagramOAuthAttemptRead:
    try:
        attempt, token = registry.claim_confirmation(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    now = gateway.clock()
    try:
        account = get_instagram_account_or_error(session, attempt.account_id)
        ensure_account_connectable(session, account)
        existing = get_connection(session, account.id)
        if (
            existing is None
            or attempt.current_identity is None
            or existing.instagram_user_id != attempt.current_identity.instagram_user_id
        ):
            raise AppError(
                409,
                "instagram_connection_changed",
                "The connection changed in the meantime. Start the connection again.",
            )
        new_identity = attempt.new_identity
        assert new_identity is not None
        ensure_identity_available(
            session, account.project_id, new_identity.instagram_user_id, account.id
        )
        connection = complete_connection(
            session, store, account, new_identity, token, now
        )
    except (ConflictError, AppError, NotFoundError) as failure:
        reported = _failure_from(failure)
        registry.finish(
            attempt,
            InstagramAttemptStatus.FAILED,
            error={"code": reported.code, "message": reported.message},
        )
        raise
    except Exception:
        registry.finish(
            attempt,
            InstagramAttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        raise
    registry.finish(
        attempt,
        InstagramAttemptStatus.COMPLETED,
        connection=connection_to_read(session, connection, now).model_dump(mode="json"),
    )
    return attempt_to_read(attempt)


@router.post(
    "/instagram/oauth/attempts/{attempt_id}/cancel",
    response_model=InstagramOAuthAttemptRead,
)
def cancel_instagram_attempt(
    attempt_id: str, registry: RegistryDep
) -> InstagramOAuthAttemptRead:
    try:
        attempt = registry.cancel(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    return attempt_to_read(attempt)


@router.post(
    "/accounts/{account_id}/instagram-connection/verify",
    response_model=InstagramConnectionRead,
)
def verify_instagram_connection(
    account_id: int, session: SessionDep, store: StoreDep, gateway: GatewayDep
) -> InstagramConnectionRead:
    connection = verify_identity(session, store, gateway, account_id)
    return connection_to_read(session, connection, gateway.clock())


@router.post(
    "/accounts/{account_id}/instagram-connection/disconnect",
    response_model=InstagramConnectionRead,
)
def disconnect_instagram(
    account_id: int,
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
) -> InstagramConnectionRead:
    """Delete the stored token, then the reference. Meta is never contacted."""
    get_instagram_account_or_error(session, account_id)
    connection = get_connection(session, account_id)
    if connection is not None:
        try:
            store.delete(connection.credential_ref)
        except CredentialStoreUnavailable:
            # Keep the connection and its reference so the user can retry.
            raise _store_unavailable() from None
        session.delete(connection)
        session.commit()
    registry.expire_for_account(account_id)
    return connection_to_read(session, None, gateway.clock())
