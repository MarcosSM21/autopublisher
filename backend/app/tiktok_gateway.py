"""TikTok calls for Login Kit for Desktop: code exchange, refresh, revocation and the
profile of the authorized user (specs/012-tiktok-oauth-connection/research.md §2,
§7–§8, §13–§14); and for Direct Post with FILE_UPLOAD: Creator Info, init, chunk
upload and post status (specs/013-tiktok-direct-post/research.md §2–§3, §10, §16).

Token and revocation requests carry every secret (client secret, code, verifier,
tokens) only in a form-encoded body, never in the request URL. This is the only
module that interprets TikTok's error codes; callers only see the semantic exceptions
below. No exception ever carries a response body, a URL or a token, and they are
raised `from None` so httpx errors (which contain the URL) are never chained. TikTok's
`log_id` is kept when present: it is not secret and helps support. The upload URL is
an ephemeral secret: it only lives inside `UploadUrl` and is never logged nor raised.
"""

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx2 as httpx

from app.db import utc_now
from app.tiktok_oauth import (
    KNOWN_SCOPES,
    REQUESTED_SCOPES,
    REQUIRED_SCOPES,
    UPLOAD_SCOPE,
    TikTokAppConfig,
    TikTokIdentity,
    parse_scopes,
)

logger = logging.getLogger(__name__)

TIKTOK_API_HOST = "https://open.tiktokapis.com"
TOKEN_ENDPOINT = f"{TIKTOK_API_HOST}/v2/oauth/token/"
REVOKE_ENDPOINT = f"{TIKTOK_API_HOST}/v2/oauth/revoke/"
USER_INFO_ENDPOINT = f"{TIKTOK_API_HOST}/v2/user/info/"
USER_INFO_FIELDS = "open_id,display_name,avatar_url"
CREATOR_INFO_ENDPOINT = f"{TIKTOK_API_HOST}/v2/post/publish/creator_info/query/"
VIDEO_INIT_ENDPOINT = f"{TIKTOK_API_HOST}/v2/post/publish/video/init/"
INBOX_VIDEO_INIT_ENDPOINT = f"{TIKTOK_API_HOST}/v2/post/publish/inbox/video/init/"
STATUS_ENDPOINT = f"{TIKTOK_API_HOST}/v2/post/publish/status/fetch/"
TIKTOK_TIMEOUT_SECONDS = 10
INIT_TIMEOUT_SECONDS = 30
# A chunk is at most 64 MiB: writing it may take long on a slow connection.
UPLOAD_TIMEOUT = httpx.Timeout(connect=10, write=300, read=120, pool=10)
JSON_CONTENT_TYPE = "application/json; charset=UTF-8"

SCOPES_FROM_EXCHANGE = "token_exchange"
SCOPES_FROM_REFRESH = "token_refresh"
CREDENTIAL_VERSION = 1

# OAuth error codes (research §14).
_OAUTH_TRANSIENT = frozenset({"server_error", "temporarily_unavailable"})
_OAUTH_CLIENT = frozenset(
    {"invalid_client", "unauthorized_client", "invalid_request", "invalid_scope"}
)
# API error codes (`error.code` of the v2 API).
_API_TRANSIENT = frozenset({"rate_limit_exceeded", "internal_error"})
_API_SCOPE = frozenset({"scope_not_authorized", "scope_permission_missed"})
# Documented business rejections of Content Posting; any other code is unexpected.
POST_REJECTION_CODES = frozenset(
    {
        "invalid_param",
        "privacy_level_option_mismatch",
        "spam_risk_too_many_posts",
        "spam_risk_too_many_pending_share",
        "spam_risk_user_banned_from_posting",
        "reached_active_user_cap",
        "unaudited_client_can_only_post_to_private_accounts",
        "url_ownership_unverified",
        "invalid_publish_id",
        "token_not_authorized_for_specified_publish_id",
    }
)
_SAFE_LOG_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_FAIL_REASON = re.compile(r"^[a-z_]{1,64}$")
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")
PUBLISH_ID_MAX_LENGTH = 64
UPLOAD_URL_MAX_LENGTH = 2048


@dataclass(frozen=True)
class TikTokCredential:
    """A TikTok credential, stored as one JSON secret only in the secure storage.

    Expiries come from `expires_in` / `refresh_expires_in` of the response that
    produced it, counted from `obtained_at`. `scopes` and `scopes_source` record the
    official scope list of that response.
    """

    open_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: datetime
    refresh_expires_at: datetime
    scopes: frozenset[str]
    scopes_source: str
    obtained_at: datetime

    def has_required_scopes(self) -> bool:
        """The base scopes: the connection is usable (renewals check this)."""
        return REQUIRED_SCOPES <= self.scopes

    def has_requested_scopes(self) -> bool:
        """Every scope Connect / Reconnect asks for (the callback checks this)."""
        return frozenset(REQUESTED_SCOPES) <= self.scopes

    def can_upload_to_inbox(self) -> bool:
        return UPLOAD_SCOPE in self.scopes

    def missing_scopes(self, scopes: Iterable[str] = REQUIRED_SCOPES) -> list[str]:
        """The names of `scopes` not granted, in the order they are requested."""
        wanted = frozenset(scopes)
        return [
            name
            for name in REQUESTED_SCOPES
            if name in wanted and name not in self.scopes
        ]

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": CREDENTIAL_VERSION,
                "open_id": self.open_id,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "access_expires_at": self.access_expires_at.isoformat(),
                "refresh_expires_at": self.refresh_expires_at.isoformat(),
                "scopes": sorted(self.scopes),
                "scopes_source": self.scopes_source,
                "obtained_at": self.obtained_at.isoformat(),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "TikTokCredential":
        """Parse a stored secret; raise ValueError if it is unusable."""
        try:
            data = json.loads(raw)
            version = data["version"]
            open_id = data["open_id"]
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            access_expires_at = datetime.fromisoformat(data["access_expires_at"])
            refresh_expires_at = datetime.fromisoformat(data["refresh_expires_at"])
            scopes = data["scopes"]
            scopes_source = data["scopes_source"]
            obtained_at = datetime.fromisoformat(data["obtained_at"])
        except (TypeError, KeyError, ValueError):
            raise ValueError("Invalid stored credentials.") from None
        if version != CREDENTIAL_VERSION:
            raise ValueError("Invalid stored credentials.")
        for value in (open_id, access_token, refresh_token):
            if not isinstance(value, str) or not value:
                raise ValueError("Invalid stored credentials.")
        for moment in (access_expires_at, refresh_expires_at, obtained_at):
            if moment.tzinfo is None:
                raise ValueError("Invalid stored credentials.")
        if not isinstance(scopes, list) or not all(
            isinstance(item, str) for item in scopes
        ):
            raise ValueError("Invalid stored credentials.")
        if scopes_source not in (SCOPES_FROM_EXCHANGE, SCOPES_FROM_REFRESH):
            raise ValueError("Invalid stored credentials.")
        return cls(
            open_id=open_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            scopes=frozenset(scopes),
            scopes_source=scopes_source,
            obtained_at=obtained_at,
        )


class TikTokError(Exception):
    message = "TikTok returned an error."
    # HTTP status of an upload answer, kept only for diagnosis.
    http_status: int | None = None

    def __init__(self, log_id: str | None = None) -> None:
        super().__init__(self.message)
        # TikTok's request id, only when it has a safe shape.
        self.log_id = log_id


class TikTokUnavailable(TikTokError):
    message = "TikTok could not be reached or is temporarily limiting requests."

    def __init__(
        self, log_id: str | None = None, *, rate_limited: bool = False
    ) -> None:
        super().__init__(log_id)
        # 429 / `rate_limit_exceeded`, only to choose the message and the wait.
        self.rate_limited = rate_limited


class TikTokGrantInvalid(TikTokError):
    message = "TikTok rejected the authorization code or the refresh token."


class TikTokRejected(TikTokError):
    message = "TikTok denied the request."


class TikTokClientError(TikTokError):
    message = "TikTok rejected AutoPublisher's app configuration or request."


class TikTokTokenInvalid(TikTokError):
    message = "TikTok no longer accepts the access token."


class TikTokScopeMissing(TikTokError):
    message = "TikTok reports that a required permission is missing."

    def __init__(self, scope: str | None = None, log_id: str | None = None) -> None:
        super().__init__(log_id)
        # Only one of the known scope names, never free text from TikTok.
        self.scope = scope if scope in KNOWN_SCOPES else None


class TikTokUnexpectedResponse(TikTokError):
    message = "TikTok returned an unexpected response."


class TikTokPostRejected(TikTokError):
    message = "TikTok rejected the post request."

    def __init__(self, code: str, log_id: str | None = None) -> None:
        super().__init__(log_id)
        # Always one of POST_REJECTION_CODES, never free text from TikTok.
        self.code = code


class TikTokUploadRejected(TikTokError):
    message = "TikTok rejected an uploaded chunk."

    def __init__(self, status: int) -> None:
        super().__init__()
        # 400, 403 (upload URL expired) or 404.
        self.status = status


@dataclass(frozen=True)
class UploadProgress:
    """TikTok's answer `Content-Range: bytes 0-{accepted_bytes}/{total}`. Unlike the
    request header (inclusive last byte), the second number is the count of bytes
    TikTok accepted, i.e. the next offset (V2 real: a chunk ending at byte 33554431
    is answered with `bytes 0-33554432/…`)."""

    accepted_bytes: int
    # None when TikTok answers `*`.
    total: int | None


class TikTokUploadRangeMismatch(TikTokError):
    message = "TikTok reports that the uploaded bytes do not match the chunk sent."

    def __init__(self, progress: UploadProgress | None) -> None:
        super().__init__()
        # TikTok's `Content-Range` progress, when present and readable.
        self.progress = progress


class UploadUrl:
    """The upload URL returned by `video/init/`: an ephemeral secret (valid one hour)
    kept only in memory. It is revealed only to send a chunk."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "UploadUrl([redacted])"

    __str__ = __repr__


@dataclass(frozen=True)
class CreatorInfo:
    nickname: str
    username: str | None
    # Signed TikTok URL valid for 2 hours: only displayed, never stored.
    avatar_url: str | None
    privacy_level_options: tuple[str, ...]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_video_post_duration_sec: int


@dataclass(frozen=True)
class InitResult:
    publish_id: str
    upload_url: UploadUrl


@dataclass(frozen=True)
class ChunkResult:
    # 206 (more chunks expected) or 201 (every chunk received).
    status: int
    # Diagnosis only on 206/201.
    progress: UploadProgress | None


@dataclass(frozen=True)
class PublishStatus:
    status: str
    # Only `^[a-z_]{1,64}$`, otherwise "unknown".
    fail_reason: str | None
    # `publicaly_available_post_id` (TikTok's spelling): public posts only.
    post_ids: tuple[int, ...]
    uploaded_bytes: int | None


def _json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _log_id(payload: dict[str, Any]) -> str | None:
    candidates = [payload.get("log_id")]
    error = payload.get("error")
    if isinstance(error, dict):
        candidates.append(error.get("log_id"))
    for value in candidates:
        if isinstance(value, str) and _SAFE_LOG_ID.match(value):
            return value
    return None


def _error_code(payload: dict[str, Any]) -> str | None:
    """The error code of an OAuth (`error`: str) or API (`error.code`) answer, or None
    when the payload reports no error."""
    error = payload.get("error")
    if isinstance(error, str):
        return error or None
    if isinstance(error, dict):
        code = error.get("code")
        if isinstance(code, str) and code and code != "ok":
            return code
        if code == "ok" or code is None:
            return None
        return "unknown"
    return None if error is None else "unknown"


def _classify(code: str, log_id: str | None) -> TikTokError:
    """Map a TikTok error code to a semantic exception (research §14)."""
    if code == "invalid_grant":
        return TikTokGrantInvalid(log_id)
    if code == "access_denied":
        return TikTokRejected(log_id)
    if code in _OAUTH_CLIENT or code.startswith("unsupported_"):
        return TikTokClientError(log_id)
    if code == "rate_limit_exceeded":
        return TikTokUnavailable(log_id, rate_limited=True)
    if code in _OAUTH_TRANSIENT or code in _API_TRANSIENT:
        return TikTokUnavailable(log_id)
    if code == "access_token_invalid":
        return TikTokTokenInvalid(log_id)
    if code in _API_SCOPE:
        return TikTokScopeMissing(log_id=log_id)
    if code in POST_REJECTION_CODES:
        return TikTokPostRejected(code, log_id)
    return TikTokUnexpectedResponse(log_id)


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _strict_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("not a boolean")
    return value


def _upload_progress(response: httpx.Response) -> UploadProgress | None:
    """TikTok's progress from `Content-Range: bytes 0-{accepted_bytes}/{total}`; None
    when absent or unreadable (including a start other than 0)."""
    match = _CONTENT_RANGE.match(response.headers.get("content-range", "").strip())
    if not match or int(match.group(1)) != 0:
        return None
    total = match.group(3)
    return UploadProgress(
        accepted_bytes=int(match.group(2)),
        total=None if total == "*" else int(total),
    )


def _ok_data(payload: dict[str, Any] | None) -> dict[str, Any]:
    """The `data` object of a v2 answer whose error code is `ok`."""
    if payload is None:
        raise TikTokUnexpectedResponse()
    status = payload.get("error")
    data = payload.get("data")
    if not isinstance(status, dict) or status.get("code") != "ok":
        raise TikTokUnexpectedResponse(_log_id(payload))
    if not isinstance(data, dict):
        raise TikTokUnexpectedResponse(_log_id(payload))
    return data


class TikTokGateway:
    def __init__(
        self, client: httpx.Client, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.client = client
        self.clock = clock

    def _send(self, method: str, url: str, **kwargs: Any) -> dict[str, Any] | None:
        """Send a request; return the JSON object (None for an empty 200 body) or
        raise the semantic exception. An error body with HTTP 200 is an error."""
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.TransportError:
            raise TikTokUnavailable() from None
        if response.status_code >= 500 or response.status_code == 429:
            raise TikTokUnavailable(
                _log_id(_json(response) or {}),
                rate_limited=response.status_code == 429,
            )
        if response.status_code == 200 and not response.content.strip():
            return None
        payload = _json(response)
        if payload is None:
            raise TikTokUnexpectedResponse()
        code = _error_code(payload)
        if code is not None:
            raise _classify(code, _log_id(payload))
        if response.status_code != 200:
            raise TikTokUnexpectedResponse(_log_id(payload))
        return payload

    def _post_form(self, url: str, form: dict[str, str]) -> dict[str, Any] | None:
        return self._send(
            "POST",
            url,
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Cache-Control": "no-cache",
            },
        )

    def _credential(
        self, payload: dict[str, Any] | None, scopes_source: str
    ) -> TikTokCredential:
        if payload is None:
            raise TikTokUnexpectedResponse()
        access_token = _text(payload.get("access_token"))
        refresh_token = _text(payload.get("refresh_token"))
        open_id = _text(payload.get("open_id"))
        expires_in = _positive_int(payload.get("expires_in"))
        refresh_expires_in = _positive_int(payload.get("refresh_expires_in"))
        scope = payload.get("scope")
        token_type = payload.get("token_type")
        if (
            access_token is None
            or refresh_token is None
            or open_id is None
            or expires_in is None
            or refresh_expires_in is None
            or not isinstance(scope, str)
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
        ):
            raise TikTokUnexpectedResponse(_log_id(payload))
        now = self.clock()
        return TikTokCredential(
            open_id=open_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=now + timedelta(seconds=expires_in),
            refresh_expires_at=now + timedelta(seconds=refresh_expires_in),
            scopes=parse_scopes(scope),
            scopes_source=scopes_source,
            obtained_at=now,
        )

    def exchange_code(
        self, code: str, code_verifier: str, config: TikTokAppConfig
    ) -> TikTokCredential:
        """Authorization code + PKCE verifier → credential. The code is single-use:
        callers never retry this call."""
        payload = self._post_form(
            TOKEN_ENDPOINT,
            {
                "client_key": config.client_key,
                "client_secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config.redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        return self._credential(payload, SCOPES_FROM_EXCHANGE)

    def refresh(
        self, credential: TikTokCredential, config: TikTokAppConfig
    ) -> TikTokCredential:
        """Renew the access token; the returned refresh token (rotated or not) is the
        one to keep."""
        payload = self._post_form(
            TOKEN_ENDPOINT,
            {
                "client_key": config.client_key,
                "client_secret": config.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": credential.refresh_token,
            },
        )
        return self._credential(payload, SCOPES_FROM_REFRESH)

    def revoke(self, access_token: str, config: TikTokAppConfig) -> None:
        """Revoke the authorization; success is an empty answer without error."""
        self._post_form(
            REVOKE_ENDPOINT,
            {
                "client_key": config.client_key,
                "client_secret": config.client_secret,
                "token": access_token,
            },
        )

    def fetch_user_info(self, access_token: str) -> TikTokIdentity:
        """Profile of the user who authorized the token (`user.info.basic`)."""
        try:
            payload = self._send(
                "GET",
                USER_INFO_ENDPOINT,
                params={"fields": USER_INFO_FIELDS},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except TikTokScopeMissing as error:
            raise TikTokScopeMissing("user.info.basic", error.log_id) from None
        if payload is None:
            raise TikTokUnexpectedResponse()
        status = payload.get("error")
        if not isinstance(status, dict) or status.get("code") != "ok":
            raise TikTokUnexpectedResponse(_log_id(payload))
        data = payload.get("data")
        user = data.get("user") if isinstance(data, dict) else None
        if not isinstance(user, dict):
            raise TikTokUnexpectedResponse(_log_id(payload))
        open_id = _text(user.get("open_id"))
        if open_id is None:
            raise TikTokUnexpectedResponse(_log_id(payload))
        return TikTokIdentity(
            open_id=open_id,
            display_name=_text(user.get("display_name")),
            avatar_url=_text(user.get("avatar_url")),
        )

    # --- Direct Post (Feature 013) ----------------------------------------------------

    def _post_json(
        self,
        url: str,
        access_token: str,
        body: dict[str, Any] | None,
        timeout: float = TIKTOK_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        content = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else b""
        )
        try:
            payload = self._send(
                "POST",
                url,
                content=content,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": JSON_CONTENT_TYPE,
                },
                timeout=timeout,
            )
        except TikTokScopeMissing as error:
            raise TikTokScopeMissing("video.publish", error.log_id) from None
        return _ok_data(payload)

    def query_creator_info(self, access_token: str) -> CreatorInfo:
        """Who receives the post and what TikTok allows now (strict: a missing or
        mistyped field is never replaced by a default)."""
        data = self._post_json(CREATOR_INFO_ENDPOINT, access_token, None)
        nickname = _text(data.get("creator_nickname"))
        options = data.get("privacy_level_options")
        max_duration = _positive_int(data.get("max_video_post_duration_sec"))
        username = data.get("creator_username")
        avatar = data.get("creator_avatar_url")
        try:
            flags = [
                _strict_bool(data.get(name))
                for name in ("comment_disabled", "duet_disabled", "stitch_disabled")
            ]
        except ValueError:
            raise TikTokUnexpectedResponse() from None
        if (
            nickname is None
            or max_duration is None
            or not isinstance(options, list)
            or not options
            or not all(isinstance(item, str) and item for item in options)
            or (username is not None and not isinstance(username, str))
            or (avatar is not None and not isinstance(avatar, str))
        ):
            raise TikTokUnexpectedResponse()
        return CreatorInfo(
            nickname=nickname,
            username=_text(username),
            avatar_url=_text(avatar),
            privacy_level_options=tuple(options),
            comment_disabled=flags[0],
            duet_disabled=flags[1],
            stitch_disabled=flags[2],
            max_video_post_duration_sec=max_duration,
        )

    def init_video_post(
        self,
        access_token: str,
        post_info: dict[str, Any],
        source_info: dict[str, Any],
    ) -> InitResult:
        """Initialize one Direct Post. Callers never repeat this call."""
        return self._init(
            VIDEO_INIT_ENDPOINT,
            access_token,
            {"post_info": post_info, "source_info": source_info},
        )

    def init_inbox_video(
        self, access_token: str, source_info: dict[str, Any]
    ) -> InitResult:
        """Initialize one Upload to Inbox: `source_info` only, never `post_info`
        (the user finishes the post in TikTok). Callers never repeat this call."""
        return self._init(
            INBOX_VIDEO_INIT_ENDPOINT, access_token, {"source_info": source_info}
        )

    def _init(
        self, endpoint: str, access_token: str, body: dict[str, Any]
    ) -> InitResult:
        data = self._post_json(
            endpoint, access_token, body, timeout=INIT_TIMEOUT_SECONDS
        )
        publish_id = _text(data.get("publish_id"))
        upload_url = _text(data.get("upload_url"))
        if (
            publish_id is None
            or len(publish_id) > PUBLISH_ID_MAX_LENGTH
            or upload_url is None
            or len(upload_url) > UPLOAD_URL_MAX_LENGTH
            or not upload_url.startswith("https://")
        ):
            raise TikTokUnexpectedResponse()
        return InitResult(publish_id=publish_id, upload_url=UploadUrl(upload_url))

    def upload_chunk(
        self,
        upload_url: UploadUrl,
        data: bytes,
        first: int,
        last: int,
        total: int,
        content_type: str,
    ) -> ChunkResult:
        """`PUT` one chunk to the upload URL, without `Authorization`."""
        try:
            response = self.client.request(
                "PUT",
                upload_url.reveal(),
                content=data,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {first}-{last}/{total}",
                },
                timeout=UPLOAD_TIMEOUT,
            )
        except httpx.TransportError:
            raise TikTokUnavailable() from None
        status = response.status_code
        if status in (201, 206):
            return ChunkResult(status=status, progress=_upload_progress(response))
        error: TikTokError
        if status in (400, 403, 404):
            error = TikTokUploadRejected(status)
        elif status == 416:
            error = TikTokUploadRangeMismatch(_upload_progress(response))
        elif status >= 500 or status == 429:
            error = TikTokUnavailable(rate_limited=status == 429)
        else:
            error = TikTokUnexpectedResponse()
        error.http_status = status
        raise error

    def fetch_publish_status(self, access_token: str, publish_id: str) -> PublishStatus:
        """Status of one `publish_id` (the only source of truth after the last
        chunk; posts are never listed)."""
        data = self._post_json(
            STATUS_ENDPOINT, access_token, {"publish_id": publish_id}
        )
        status = _text(data.get("status"))
        if status is None:
            raise TikTokUnexpectedResponse()
        reason = data.get("fail_reason")
        fail_reason = None
        if reason is not None:
            safe = isinstance(reason, str) and _SAFE_FAIL_REASON.match(reason)
            fail_reason = reason if safe else "unknown"
        raw_ids = data.get("publicaly_available_post_id")
        post_ids: tuple[int, ...] = ()
        if isinstance(raw_ids, list):
            post_ids = tuple(
                item
                for item in raw_ids
                if isinstance(item, int) and not isinstance(item, bool)
            )
            if len(post_ids) != len(raw_ids):
                logger.warning("TikTok returned post ids that are not integers.")
        uploaded = data.get("uploaded_bytes")
        uploaded_bytes = (
            uploaded
            if isinstance(uploaded, int)
            and not isinstance(uploaded, bool)
            and uploaded >= 0
            else None
        )
        return PublishStatus(
            status=status,
            fail_reason=fail_reason,
            post_ids=post_ids,
            uploaded_bytes=uploaded_bytes,
        )
