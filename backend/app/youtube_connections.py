"""YouTube account connection over OAuth 2.0 (see specs/005-youtube-oauth-connection).

The accounts core knows nothing about YouTube: connections are looked up here by
`account_id`. Tokens live only in the secure credential store; SQLite keeps a
non-secret `credential_ref`. Disconnecting never contacts Google.
"""

import html
import logging
import re
import threading
from datetime import timedelta
from typing import Annotated, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_google_oauth_client_file, get_oauth_redirect_uri
from app.credential_store import CredentialStore, CredentialStoreUnavailable
from app.db import get_session, utc_now
from app.errors import AppError, ConflictError, NotFoundError
from app.models import (
    Account,
    Platform,
    Project,
    Publication,
    PublicationStatus,
    YouTubeConnection,
    YouTubeConnectionStatus,
)
from app.schemas import (
    AuthorizeRead,
    OAuthAttemptRead,
    YouTubeChannelRead,
    YouTubeConnectionRead,
)
from app.youtube_gateway import (
    GoogleForbidden,
    GoogleGateway,
    GoogleRejected,
    GoogleUnauthorized,
    GoogleUnavailable,
    InvalidGrant,
    TokenSet,
)
from app.youtube_oauth import (
    REQUIRED_SCOPES,
    AttemptNotConfirmable,
    AttemptNotFound,
    AttemptStatus,
    ChannelInfo,
    OAuthAttempt,
    OAuthAttemptRegistry,
    OAuthClientConfig,
    OAuthNotConfigured,
    build_authorization_url,
    generate_pkce_pair,
    generate_state,
    load_client_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["youtube"])

SessionDep = Annotated[Session, Depends(get_session)]

# Access tokens closer than this to expiry are refreshed before use.
REFRESH_MARGIN = timedelta(seconds=60)

STORE_UNAVAILABLE_MESSAGE = (
    "The system's secure credential storage is not available. "
    "See the README section 'Connecting YouTube'."
)
NOT_CONFIGURED_MESSAGE = (
    "YouTube integration is not configured. "
    "See the README section 'Connecting YouTube'."
)
UNAVAILABLE_MESSAGE = "Could not reach YouTube. Check your connection and try again."
INTERNAL_MESSAGE = "An unexpected error occurred. Please try again."


def get_credential_store(request: Request) -> CredentialStore:
    store: CredentialStore = request.app.state.credential_store
    return store


def get_gateway(request: Request) -> GoogleGateway:
    gateway: GoogleGateway = request.app.state.google_gateway
    return gateway


def get_registry(request: Request) -> OAuthAttemptRegistry:
    registry: OAuthAttemptRegistry = request.app.state.oauth_attempts
    return registry


StoreDep = Annotated[CredentialStore, Depends(get_credential_store)]
GatewayDep = Annotated[GoogleGateway, Depends(get_gateway)]
RegistryDep = Annotated[OAuthAttemptRegistry, Depends(get_registry)]


class AttemptFailure(Exception):
    """An expected failure while completing an authorization."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _store_unavailable() -> AppError:
    return AppError(503, "credential_store_unavailable", STORE_UNAVAILABLE_MESSAGE)


# --- Lookups and read models -------------------------------------------------------


def get_youtube_account_or_error(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError("Account not found.")
    if account.platform != Platform.YOUTUBE:
        raise ConflictError(
            "platform_not_supported", "Only YouTube accounts can be connected."
        )
    return account


def ensure_not_publishing(session: Session, account_id: int) -> None:
    """The connection cannot change while one of its uploads is running (FR-048)."""
    running = session.scalars(
        select(Publication.id).where(
            Publication.account_id == account_id,
            Publication.status == PublicationStatus.PUBLISHING,
        )
    ).first()
    if running is not None:
        raise ConflictError(
            "publication_in_progress",
            "A publication of this account is being uploaded. Wait until it "
            "finishes before changing the connection.",
        )


def get_connection(session: Session, account_id: int) -> YouTubeConnection | None:
    return session.scalars(
        select(YouTubeConnection).where(YouTubeConnection.account_id == account_id)
    ).first()


def oauth_configured() -> bool:
    """Whether the local OAuth client file is usable; read on every call."""
    try:
        load_client_config(get_google_oauth_client_file())
    except OAuthNotConfigured:
        return False
    return True


def channel_of(connection: YouTubeConnection) -> ChannelInfo:
    return ChannelInfo(
        connection.channel_id,
        connection.channel_title,
        connection.channel_handle,
        connection.channel_thumbnail_url,
    )


def connection_to_read(connection: YouTubeConnection | None) -> YouTubeConnectionRead:
    configured = oauth_configured()
    if connection is None:
        return YouTubeConnectionRead(
            status="not_connected",
            channel=None,
            connected_at=None,
            last_verified_at=None,
            oauth_configured=configured,
        )
    return YouTubeConnectionRead(
        status="connected"
        if connection.status == YouTubeConnectionStatus.CONNECTED
        else "reconnect_required",
        channel=YouTubeChannelRead(
            id=connection.channel_id,
            title=connection.channel_title,
            handle=connection.channel_handle,
            thumbnail_url=connection.channel_thumbnail_url,
        ),
        connected_at=connection.connected_at,
        last_verified_at=connection.last_verified_at,
        oauth_configured=configured,
    )


def attempt_to_read(attempt: OAuthAttempt) -> OAuthAttemptRead:
    return OAuthAttemptRead.model_validate(attempt.to_read())


# --- Rules -------------------------------------------------------------------------


def ensure_account_connectable(session: Session, account: Account) -> None:
    """New authorizations need an active project and an active account."""
    project = session.get(Project, account.project_id)
    if project is None or not project.is_active:
        raise ConflictError(
            "project_inactive", "Reactivate the project before connecting accounts."
        )
    if not account.is_active:
        raise ConflictError(
            "account_inactive", "Reactivate the account before connecting it."
        )


def ensure_channel_available(
    session: Session, project_id: int, channel_id: str, account_id: int
) -> None:
    """A channel can be linked to only one account per project (active or not)."""
    holder = session.execute(
        select(Account.handle)
        .join(YouTubeConnection, YouTubeConnection.account_id == Account.id)
        .where(
            YouTubeConnection.project_id == project_id,
            YouTubeConnection.channel_id == channel_id,
            YouTubeConnection.account_id != account_id,
        )
    ).first()
    if holder is not None:
        raise ConflictError(
            "channel_already_connected",
            f"This YouTube channel is already connected to @{holder.handle} in this "
            "project. Disconnect it there first.",
        )


def load_client() -> OAuthClientConfig:
    try:
        return load_client_config(get_google_oauth_client_file())
    except OAuthNotConfigured:
        raise AppError(503, "oauth_not_configured", NOT_CONFIGURED_MESSAGE) from None


def redirect_uri() -> str:
    try:
        return get_oauth_redirect_uri()
    except ValueError as error:
        raise AppError(503, "oauth_not_configured", str(error)) from None


def _discard_secret(store: CredentialStore, ref: str, account_id: int) -> None:
    """Best-effort delete; if it fails the entry stays orphaned (spec FR-025)."""
    try:
        store.delete(ref)
    except CredentialStoreUnavailable:
        logger.warning(
            "Could not delete stored YouTube credentials for account %s", account_id
        )


def complete_connection(
    session: Session,
    store: CredentialStore,
    account: Account,
    channel: ChannelInfo,
    tokens: TokenSet,
) -> YouTubeConnection:
    """Store the credentials, then link the channel; never a row without a secret."""
    existing = get_connection(session, account.id)
    old_ref = existing.credential_ref if existing is not None else None
    new_ref = uuid4().hex
    try:
        store.set(new_ref, tokens.to_json())
    except CredentialStoreUnavailable:
        raise _store_unavailable() from None

    now = utc_now()
    try:
        connection = existing or YouTubeConnection(
            account_id=account.id, project_id=account.project_id
        )
        connection.channel_id = channel.id
        connection.channel_title = channel.title
        connection.channel_handle = channel.handle
        connection.channel_thumbnail_url = channel.thumbnail_url
        connection.status = YouTubeConnectionStatus.CONNECTED
        connection.credential_ref = new_ref
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
            raise ConflictError(
                "channel_already_connected",
                "This YouTube channel is already connected to another account in "
                "this project. Disconnect it there first.",
            ) from None
        raise
    if old_ref is not None:
        _discard_secret(store, old_ref, account.id)
    return connection


def mark_reconnect_required(session: Session, connection: YouTubeConnection) -> None:
    if connection.status != YouTubeConnectionStatus.RECONNECT_REQUIRED:
        connection.status = YouTubeConnectionStatus.RECONNECT_REQUIRED
        connection.updated_at = utc_now()
        session.commit()


def _reconnect_required(
    session: Session, connection: YouTubeConnection, message: str
) -> NoReturn:
    mark_reconnect_required(session, connection)
    raise ConflictError("reconnect_required", message)


_refresh_locks: dict[int, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _account_lock(account_id: int) -> threading.Lock:
    with _refresh_locks_guard:
        return _refresh_locks.setdefault(account_id, threading.Lock())


def get_valid_credentials(
    session: Session,
    store: CredentialStore,
    gateway: GoogleGateway,
    account_id: int,
    *,
    force_refresh: bool = False,
) -> TokenSet:
    """Return usable credentials, refreshing them without user interaction if needed.

    A definitive rejection (or missing secret) marks the connection as
    `reconnect_required`; transient failures never change its status.
    """
    connection = get_connection(session, account_id)
    if connection is None:
        raise ConflictError("not_connected", "This YouTube account is not connected.")
    with _account_lock(account_id):
        try:
            raw = store.get(connection.credential_ref)
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
        try:
            tokens = TokenSet.from_json(raw) if raw is not None else None
        except ValueError:
            tokens = None
        if tokens is None:
            _reconnect_required(
                session,
                connection,
                "The stored credentials are missing. Reconnect the channel.",
            )
        if not force_refresh and tokens.expires_at - utc_now() > REFRESH_MARGIN:
            return tokens

        client = load_client()
        try:
            refreshed = gateway.refresh(tokens, client)
        except InvalidGrant:
            _reconnect_required(
                session,
                connection,
                "Google no longer accepts the stored credentials. "
                "Reconnect the channel.",
            )
        except GoogleUnavailable:
            raise AppError(503, "youtube_unavailable", UNAVAILABLE_MESSAGE) from None
        except GoogleRejected:
            raise AppError(
                503,
                "oauth_not_configured",
                "Google rejected AutoPublisher's OAuth client. "
                "Check the OAuth configuration.",
            ) from None
        try:
            store.set(connection.credential_ref, refreshed.to_json())
        except CredentialStoreUnavailable:
            raise _store_unavailable() from None
        return refreshed


# --- Logging -----------------------------------------------------------------------

CALLBACK_PATH = "/api/youtube/oauth/callback"


class RedactOAuthCallbackQuery(logging.Filter):
    """Drop the query string (authorization code, state) of callback access logs.

    Uvicorn's access log records `(client, method, path, http_version, status)`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith(CALLBACK_PATH + "?"):
                record.args = (*args[:2], CALLBACK_PATH + "?[redacted]", *args[3:])
        return True


# Loggers of the HTTP client stack. httpx2 logs every request URL at INFO and
# httpcore2 logs response headers (including `Location`) at DEBUG.
HTTP_LOGGERS = (
    "httpx2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "httpcore2.proxy",
    "httpcore2.socks",
)

_UPLOAD_ID = re.compile(r"upload_id=[^&\s'\"<>]+")
# videos.list?id=… carries a video ID, which gives access to unlisted videos.
_VIDEO_ID_PARAM = re.compile(r"([?&]id=)[^&\s'\"<>]+")
# YouTube repeats the session id in this response header, which httpcore2 logs at
# DEBUG either as a (b'name', b'value') tuple or as "name: value".
_UPLOAD_ID_HEADER = re.compile(
    r"(x-guploader-uploadid['\"]?\s*[,:]\s*b?['\"]?)[^'\"\s,)]+", re.IGNORECASE
)


class RedactYouTubeUrls(logging.Filter):
    """Remove upload session ids (in URLs and in the `X-GUploader-UploadID` header)
    and video ids from HTTP client logs.

    Whoever holds a session id can continue the upload, and a video id is part of
    the link to an unlisted video, so neither may reach any log (research.md §7, §15).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # A broken record is left for logging to report.
            return True
        lowered = message.lower()
        if "id=" in lowered or "x-guploader-uploadid" in lowered:
            redacted = _UPLOAD_ID.sub("upload_id=[redacted]", message)
            redacted = _VIDEO_ID_PARAM.sub(r"\1[redacted]", redacted)
            redacted = _UPLOAD_ID_HEADER.sub(r"\1[redacted]", redacted)
            if redacted != message:
                record.msg = redacted
                record.args = ()
        return True


def install_log_redaction() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactOAuthCallbackQuery) for f in access_logger.filters):
        access_logger.addFilter(RedactOAuthCallbackQuery())
    for name in HTTP_LOGGERS:
        http_logger = logging.getLogger(name)
        if not any(isinstance(f, RedactYouTubeUrls) for f in http_logger.filters):
            http_logger.addFilter(RedactYouTubeUrls())


# --- Callback page -----------------------------------------------------------------


def render_callback_page(title: str, message: str, status_code: int) -> HTMLResponse:
    """Minimal page shown in the browser tab Google redirects to."""
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
    return HTMLResponse(body, status_code=status_code)


def _failure_from(error: Exception) -> AttemptFailure:
    if isinstance(error, (ConflictError, AppError)):
        return AttemptFailure(error.code, error.message)
    if isinstance(error, NotFoundError):
        return AttemptFailure("not_found", error.message)
    raise error


def _identify_channel(gateway: GoogleGateway, access_token: str) -> ChannelInfo:
    try:
        channels = gateway.list_my_channels(access_token)
    except GoogleUnavailable:
        raise AttemptFailure("youtube_unavailable", UNAVAILABLE_MESSAGE) from None
    except (GoogleUnauthorized, GoogleForbidden, GoogleRejected):
        raise AttemptFailure(
            "oauth_exchange_failed",
            "Google did not complete the authorization. Try again.",
        ) from None
    if not channels:
        raise AttemptFailure(
            "youtube_no_channel", "This Google account has no YouTube channel."
        )
    # Never pick one channel among several: the effective channel must be unambiguous.
    if len(channels) != 1 or not channels[0].id:
        raise AttemptFailure(
            "youtube_channel_ambiguous",
            "Could not determine which YouTube channel to connect. Select the right "
            "channel in Google's account chooser and try again.",
        )
    return channels[0]


def _process_callback(
    session: Session,
    store: CredentialStore,
    gateway: GoogleGateway,
    registry: OAuthAttemptRegistry,
    attempt: OAuthAttempt,
    code: str | None,
    error: str | None,
) -> HTMLResponse:
    if error is not None:
        if error == "access_denied":
            raise AttemptFailure(
                "oauth_cancelled", "The connection was cancelled in Google."
            )
        raise AttemptFailure(
            "oauth_provider_error", "Google could not complete the authorization."
        )
    if not code:
        raise AttemptFailure(
            "oauth_callback_invalid", "The response from Google was not valid."
        )
    verifier = attempt.code_verifier
    if verifier is None:
        raise AttemptFailure(
            "oauth_state_invalid",
            "This authorization is invalid or has expired. "
            "Start the connection again from AutoPublisher.",
        )

    try:
        account = get_youtube_account_or_error(session, attempt.account_id)
        # Checked before any request to Google (the account may have been deactivated).
        ensure_account_connectable(session, account)
        client = load_client()
        callback_uri = redirect_uri()
    except (ConflictError, AppError, NotFoundError) as failure:
        raise _failure_from(failure) from None

    try:
        tokens = gateway.exchange_code(code, verifier, callback_uri, client)
    except GoogleUnavailable:
        raise AttemptFailure("youtube_unavailable", UNAVAILABLE_MESSAGE) from None
    except (GoogleRejected, InvalidGrant):
        raise AttemptFailure(
            "oauth_exchange_failed",
            "Google did not complete the authorization. Try again.",
        ) from None
    if not REQUIRED_SCOPES <= tokens.scopes:
        raise AttemptFailure(
            "oauth_scope_insufficient",
            "Grant all requested permissions to connect the channel.",
        )
    if tokens.refresh_token is None:
        raise AttemptFailure(
            "oauth_offline_access_missing",
            "Google did not grant lasting access. Connect again and allow all "
            "requested access.",
        )

    channel = _identify_channel(gateway, tokens.access_token)
    existing = get_connection(session, account.id)
    if existing is not None and existing.channel_id != channel.id:
        # Never replace a linked channel silently: wait for an explicit confirmation.
        registry.await_confirmation(attempt, channel, tokens, channel_of(existing))
        return render_callback_page(
            "Confirm the YouTube channel",
            "This account is already linked to another channel. Return to "
            "AutoPublisher to confirm or cancel the change.",
            200,
        )

    try:
        ensure_channel_available(session, account.project_id, channel.id, account.id)
        connection = complete_connection(session, store, account, channel, tokens)
    except (ConflictError, AppError) as failure:
        raise _failure_from(failure) from None
    registry.finish(
        attempt,
        AttemptStatus.COMPLETED,
        connection=connection_to_read(connection).model_dump(mode="json"),
    )
    return render_callback_page(
        "YouTube channel connected",
        f"{channel.title} ({channel.id}) is now connected to AutoPublisher.",
        200,
    )


# --- Routes ------------------------------------------------------------------------


@router.get(
    "/accounts/{account_id}/youtube-connection", response_model=YouTubeConnectionRead
)
def get_youtube_connection(
    account_id: int, session: SessionDep
) -> YouTubeConnectionRead:
    get_youtube_account_or_error(session, account_id)
    return connection_to_read(get_connection(session, account_id))


@router.post(
    "/accounts/{account_id}/youtube-connection/authorize",
    response_model=AuthorizeRead,
    status_code=status.HTTP_201_CREATED,
)
def authorize_youtube(
    account_id: int, session: SessionDep, registry: RegistryDep
) -> AuthorizeRead:
    account = get_youtube_account_or_error(session, account_id)
    ensure_account_connectable(session, account)
    ensure_not_publishing(session, account.id)
    client = load_client()
    callback_uri = redirect_uri()
    state = generate_state()
    verifier, challenge = generate_pkce_pair()
    existing = get_connection(session, account.id)
    attempt = registry.create(
        account.id,
        state,
        verifier,
        current_channel=channel_of(existing) if existing is not None else None,
    )
    return AuthorizeRead(
        attempt_id=attempt.attempt_id,
        authorization_url=build_authorization_url(
            client.client_id, callback_uri, state, challenge
        ),
        expires_at=attempt.expires_at,
    )


@router.get("/youtube/oauth/callback", response_class=HTMLResponse)
def youtube_oauth_callback(
    session: SessionDep,
    store: StoreDep,
    gateway: GatewayDep,
    registry: RegistryDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    attempt = registry.consume_state(state) if state else None
    if attempt is None:
        return render_callback_page(
            "Authorization not valid",
            "This authorization is invalid or has expired. "
            "Start the connection again from AutoPublisher.",
            400,
        )
    try:
        return _process_callback(
            session, store, gateway, registry, attempt, code, error
        )
    except AttemptFailure as failure:
        registry.finish(
            attempt,
            AttemptStatus.FAILED,
            error={"code": failure.code, "message": failure.message},
        )
        return render_callback_page("Connection failed", failure.message, 400)
    except Exception as unexpected:
        logger.error(
            "Unexpected error while completing a YouTube authorization for "
            "account %s (%s)",
            attempt.account_id,
            type(unexpected).__name__,
        )
        registry.finish(
            attempt,
            AttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        return render_callback_page("Connection failed", INTERNAL_MESSAGE, 500)


@router.get("/youtube/oauth/attempts/{attempt_id}", response_model=OAuthAttemptRead)
def get_oauth_attempt(attempt_id: str, registry: RegistryDep) -> OAuthAttemptRead:
    attempt = registry.get(attempt_id)
    if attempt is None:
        raise AppError(
            404, "oauth_attempt_not_found", "This authorization was not found."
        )
    return attempt_to_read(attempt)


def _not_confirmable() -> ConflictError:
    return ConflictError(
        "oauth_attempt_not_confirmable",
        "This authorization is no longer waiting for a confirmation.",
    )


def _attempt_not_found() -> AppError:
    return AppError(404, "oauth_attempt_not_found", "This authorization was not found.")


@router.post(
    "/youtube/oauth/attempts/{attempt_id}/confirm", response_model=OAuthAttemptRead
)
def confirm_oauth_attempt(
    attempt_id: str, session: SessionDep, store: StoreDep, registry: RegistryDep
) -> OAuthAttemptRead:
    try:
        attempt, tokens = registry.claim_confirmation(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    try:
        account = get_youtube_account_or_error(session, attempt.account_id)
        ensure_account_connectable(session, account)
        existing = get_connection(session, account.id)
        if (
            existing is None
            or attempt.current_channel is None
            or existing.channel_id != attempt.current_channel.id
        ):
            raise ConflictError(
                "connection_changed",
                "The connection changed in the meantime. Start the connection again.",
            )
        new_channel = attempt.new_channel
        assert new_channel is not None
        ensure_channel_available(
            session, account.project_id, new_channel.id, account.id
        )
        connection = complete_connection(session, store, account, new_channel, tokens)
    except (ConflictError, AppError, NotFoundError) as failure:
        reported = _failure_from(failure)
        registry.finish(
            attempt,
            AttemptStatus.FAILED,
            error={"code": reported.code, "message": reported.message},
        )
        raise
    except Exception:
        registry.finish(
            attempt,
            AttemptStatus.FAILED,
            error={"code": "internal_error", "message": INTERNAL_MESSAGE},
        )
        raise
    registry.finish(
        attempt,
        AttemptStatus.COMPLETED,
        connection=connection_to_read(connection).model_dump(mode="json"),
    )
    return attempt_to_read(attempt)


@router.post(
    "/youtube/oauth/attempts/{attempt_id}/cancel", response_model=OAuthAttemptRead
)
def cancel_oauth_attempt(attempt_id: str, registry: RegistryDep) -> OAuthAttemptRead:
    try:
        attempt = registry.cancel(attempt_id)
    except AttemptNotFound:
        raise _attempt_not_found() from None
    except AttemptNotConfirmable:
        raise _not_confirmable() from None
    return attempt_to_read(attempt)


def list_channels(
    session: Session,
    store: CredentialStore,
    gateway: GoogleGateway,
    connection: YouTubeConnection,
) -> list[ChannelInfo]:
    tokens = get_valid_credentials(session, store, gateway, connection.account_id)
    for attempt_number in range(2):
        try:
            return gateway.list_my_channels(tokens.access_token)
        except GoogleUnauthorized:
            if attempt_number == 0:
                tokens = get_valid_credentials(
                    session, store, gateway, connection.account_id, force_refresh=True
                )
                continue
            _reconnect_required(
                session,
                connection,
                "YouTube no longer accepts the stored credentials. "
                "Reconnect the channel.",
            )
        except GoogleForbidden:
            _reconnect_required(
                session,
                connection,
                "YouTube denied access to the channel. Reconnect the channel.",
            )
        except (GoogleUnavailable, GoogleRejected):
            raise AppError(503, "youtube_unavailable", UNAVAILABLE_MESSAGE) from None
    raise AssertionError("unreachable")


@router.post(
    "/accounts/{account_id}/youtube-connection/verify",
    response_model=YouTubeConnectionRead,
)
def verify_youtube_connection(
    account_id: int, session: SessionDep, store: StoreDep, gateway: GatewayDep
) -> YouTubeConnectionRead:
    get_youtube_account_or_error(session, account_id)
    connection = get_connection(session, account_id)
    if connection is None:
        raise ConflictError("not_connected", "This YouTube account is not connected.")
    channels = list_channels(session, store, gateway, connection)
    if len(channels) != 1 or channels[0].id != connection.channel_id:
        _reconnect_required(
            session,
            connection,
            "The authorized YouTube channel no longer matches the linked channel. "
            "Reconnect the channel.",
        )
    channel = channels[0]
    now = utc_now()
    connection.channel_title = channel.title
    connection.channel_handle = channel.handle
    connection.channel_thumbnail_url = channel.thumbnail_url
    connection.status = YouTubeConnectionStatus.CONNECTED
    connection.last_verified_at = now
    connection.updated_at = now
    session.commit()
    return connection_to_read(connection)


@router.post(
    "/accounts/{account_id}/youtube-connection/disconnect",
    response_model=YouTubeConnectionRead,
)
def disconnect_youtube(
    account_id: int, session: SessionDep, store: StoreDep, registry: RegistryDep
) -> YouTubeConnectionRead:
    """Delete the local credentials, then the reference. Google is never contacted."""
    get_youtube_account_or_error(session, account_id)
    ensure_not_publishing(session, account_id)
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
    return connection_to_read(None)
