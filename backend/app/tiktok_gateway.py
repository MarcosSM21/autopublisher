"""TikTok calls for Login Kit for Desktop: code exchange, refresh, revocation and the
profile of the authorized user (specs/012-tiktok-oauth-connection/research.md §2,
§7–§8, §13–§14).

Token and revocation requests carry every secret (client secret, code, verifier,
tokens) only in a form-encoded body, never in the request URL. This is the only
module that interprets TikTok's error codes; callers only see the semantic exceptions
below. No exception ever carries a response body, a URL or a token, and they are
raised `from None` so httpx errors (which contain the URL) are never chained. TikTok's
`log_id` is kept when present: it is not secret and helps support.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx2 as httpx

from app.db import utc_now
from app.tiktok_oauth import (
    REQUIRED_SCOPES,
    SCOPES,
    TikTokAppConfig,
    TikTokIdentity,
    parse_scopes,
)

TIKTOK_API_HOST = "https://open.tiktokapis.com"
TOKEN_ENDPOINT = f"{TIKTOK_API_HOST}/v2/oauth/token/"
REVOKE_ENDPOINT = f"{TIKTOK_API_HOST}/v2/oauth/revoke/"
USER_INFO_ENDPOINT = f"{TIKTOK_API_HOST}/v2/user/info/"
USER_INFO_FIELDS = "open_id,display_name,avatar_url"
TIKTOK_TIMEOUT_SECONDS = 10

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
_SAFE_LOG_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
        return REQUIRED_SCOPES <= self.scopes

    def missing_scopes(self) -> list[str]:
        return [name for name in SCOPES if name not in self.scopes]

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

    def __init__(self, log_id: str | None = None) -> None:
        super().__init__(self.message)
        # TikTok's request id, only when it has a safe shape.
        self.log_id = log_id


class TikTokUnavailable(TikTokError):
    message = "TikTok could not be reached or is temporarily limiting requests."


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
        # Only one of the required scope names, never free text from TikTok.
        self.scope = scope if scope in REQUIRED_SCOPES else None


class TikTokUnexpectedResponse(TikTokError):
    message = "TikTok returned an unexpected response."


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
    if code in _OAUTH_TRANSIENT or code in _API_TRANSIENT:
        return TikTokUnavailable(log_id)
    if code == "access_token_invalid":
        return TikTokTokenInvalid(log_id)
    if code in _API_SCOPE:
        return TikTokScopeMissing(log_id=log_id)
    return TikTokUnexpectedResponse(log_id)


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


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
            raise TikTokUnavailable(_log_id(_json(response) or {}))
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
