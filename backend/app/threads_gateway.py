"""Meta calls for the Threads API: code exchange, long-lived token exchange, refresh,
token inspection (`debug_token`) and the profile of the authorized user
(specs/010-threads-oauth-connection/research.md §2, §6–§8, §10).

This is the only module that interprets Meta's error numbers; callers only see the
semantic exceptions below. Several documented endpoints carry the token, the app
secret or the inspected token in the query string, so HTTP client logs are redacted by
`threads_connections.RedactThreadsSecrets`. No exception ever carries a response body,
a URL or a token, and they are raised `from None` so httpx errors (which contain the
URL) are never chained.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2 as httpx

from app.db import utc_now
from app.threads_oauth import REQUIRED_SCOPES, ThreadsAppConfig, ThreadsIdentity

# The Threads API answers on graph.threads.net and graph.threads.com; one host is used
# consistently (research §2). Token endpoints are unversioned.
THREADS_GRAPH_HOST = "https://graph.threads.net"
THREADS_API_VERSION = "v1.0"
CODE_EXCHANGE_ENDPOINT = f"{THREADS_GRAPH_HOST}/oauth/access_token"
LONG_LIVED_ENDPOINT = f"{THREADS_GRAPH_HOST}/access_token"
REFRESH_ENDPOINT = f"{THREADS_GRAPH_HOST}/refresh_access_token"
DEBUG_TOKEN_ENDPOINT = f"{THREADS_GRAPH_HOST}/{THREADS_API_VERSION}/debug_token"
ME_ENDPOINT = f"{THREADS_GRAPH_HOST}/{THREADS_API_VERSION}/me"
ME_FIELDS = "id,username,name,threads_profile_picture_url"

# Graph error codes (research §10). Everything else in 4xx is a rejection.
_TRANSIENT_CODES = frozenset({1, 2, 4, 17, 32, 613})
_INVALID_TOKEN_CODE = 190


@dataclass(frozen=True)
class ShortLivedToken:
    access_token: str = field(repr=False)
    user_id: str


@dataclass(frozen=True)
class ThreadsToken:
    """Long-lived Threads token, stored as JSON only in the secure storage.

    `token_obtained_at` is when AutoPublisher received it (for Meta's 24 h refresh
    condition); `expires_at` comes from the official `expires_in` of that response.
    """

    access_token: str = field(repr=False)
    token_obtained_at: datetime
    expires_at: datetime
    scopes: frozenset[str]

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "token_obtained_at": self.token_obtained_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
                "scopes": sorted(self.scopes),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "ThreadsToken":
        """Parse a stored secret; raise ValueError if it is unusable."""
        try:
            data = json.loads(raw)
            access_token = data["access_token"]
            obtained_at = datetime.fromisoformat(data["token_obtained_at"])
            expires_at = datetime.fromisoformat(data["expires_at"])
            scopes = data["scopes"]
        except (TypeError, KeyError, ValueError):
            raise ValueError("Invalid stored credentials.") from None
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Invalid stored credentials.")
        if obtained_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("Invalid stored credentials.")
        if not isinstance(scopes, list) or not all(
            isinstance(item, str) for item in scopes
        ):
            raise ValueError("Invalid stored credentials.")
        return cls(access_token, obtained_at, expires_at, frozenset(scopes))


@dataclass(frozen=True)
class ThreadsTokenInfo:
    """Normalized result of `debug_token`."""

    is_valid: bool
    user_id: str
    scopes: frozenset[str]
    data_access_expires_at: datetime | None


class ThreadsError(Exception):
    message = "Meta returned an error."

    def __init__(self) -> None:
        super().__init__(self.message)


class ThreadsUnavailable(ThreadsError):
    message = "Threads could not be reached or is temporarily limiting requests."


class ThreadsTokenInvalid(ThreadsError):
    message = "Threads no longer accepts the access token."


class ThreadsPermissionDenied(ThreadsError):
    message = "Threads reports that a required permission is missing."

    def __init__(self, permission: str | None = None) -> None:
        super().__init__()
        # Only one of the two required scope names, never free text from Meta.
        self.permission = permission


class ThreadsRejected(ThreadsError):
    message = "Threads rejected the request."


class ThreadsUnexpectedResponse(ThreadsError):
    message = "Threads returned an unexpected response."


def _json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _safe_permission(error: dict[str, Any]) -> str | None:
    """The affected scope, only if Meta names exactly one of the required ones."""
    message = error.get("message")
    if not isinstance(message, str):
        return None
    named = [name for name in sorted(REQUIRED_SCOPES) if name in message]
    return named[0] if len(named) == 1 else None


def _error_for(response: httpx.Response) -> ThreadsError:
    """Classify a non-200 response (research §10)."""
    if response.status_code >= 500 or response.status_code == 429:
        return ThreadsUnavailable()
    payload = _json(response) or {}
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(error, dict) and isinstance(code, int) and not isinstance(code, bool):
        if code == _INVALID_TOKEN_CODE:
            return ThreadsTokenInvalid()
        if code == 10 or 200 <= code <= 299:
            return ThreadsPermissionDenied(_safe_permission(error))
        if code in _TRANSIENT_CODES:
            return ThreadsUnavailable()
    return ThreadsRejected()


def _id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


class ThreadsGateway:
    def __init__(
        self, client: httpx.Client, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.client = client
        self.clock = clock

    def _send(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.TransportError:
            raise ThreadsUnavailable() from None
        if response.status_code != 200:
            raise _error_for(response)
        payload = _json(response)
        if payload is None:
            raise ThreadsUnexpectedResponse()
        return payload

    def exchange_code(self, code: str, config: ThreadsAppConfig) -> ShortLivedToken:
        """Authorization code → short-lived token and the Threads user ID. The code is
        single-use: callers never retry this call."""
        payload = self._send(
            "POST",
            CODE_EXCHANGE_ENDPOINT,
            data={
                "client_id": config.app_id,
                "client_secret": config.app_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config.redirect_uri,
            },
        )
        access_token = payload.get("access_token")
        user_id = _id(payload.get("user_id"))
        if not isinstance(access_token, str) or not access_token or user_id is None:
            raise ThreadsUnexpectedResponse()
        return ShortLivedToken(access_token, user_id)

    def _long_lived(
        self, payload: dict[str, Any], scopes: frozenset[str]
    ) -> ThreadsToken:
        access_token = payload.get("access_token")
        expires_in = _positive_int(payload.get("expires_in"))
        if not isinstance(access_token, str) or not access_token or expires_in is None:
            raise ThreadsUnexpectedResponse()
        now = self.clock()
        return ThreadsToken(
            access_token, now, now + timedelta(seconds=expires_in), scopes
        )

    def exchange_long_lived(
        self, short_token: ShortLivedToken, config: ThreadsAppConfig
    ) -> ThreadsToken:
        """Short-lived token → long-lived (60 days) token. Scopes are confirmed later
        with `debug_token`."""
        payload = self._send(
            "GET",
            LONG_LIVED_ENDPOINT,
            params={
                "grant_type": "th_exchange_token",
                "client_secret": config.app_secret,
                "access_token": short_token.access_token,
            },
        )
        return self._long_lived(payload, frozenset())

    def refresh(self, token: ThreadsToken) -> ThreadsToken:
        """Renew a long-lived token (≥ 24 h old and still valid); no app secret."""
        payload = self._send(
            "GET",
            REFRESH_ENDPOINT,
            params={
                "grant_type": "th_refresh_token",
                "access_token": token.access_token,
            },
        )
        return self._long_lived(payload, token.scopes)

    def debug_token(self, access_token: str) -> ThreadsTokenInfo:
        """Inspect a token with itself as the caller: the documented caller is a user
        access token of a Threads tester of the same app (research §7)."""
        payload = self._send(
            "GET",
            DEBUG_TOKEN_ENDPOINT,
            params={"input_token": access_token, "access_token": access_token},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ThreadsUnexpectedResponse()
        is_valid = data.get("is_valid")
        user_id = _id(data.get("user_id"))
        scopes = data.get("scopes")
        if (
            not isinstance(is_valid, bool)
            or user_id is None
            or not isinstance(scopes, list)
            or not all(isinstance(item, str) for item in scopes)
        ):
            raise ThreadsUnexpectedResponse()
        data_access = _positive_int(data.get("data_access_expires_at"))
        return ThreadsTokenInfo(
            is_valid=is_valid,
            user_id=user_id,
            scopes=frozenset(scopes),
            data_access_expires_at=datetime.fromtimestamp(data_access, UTC)
            if data_access is not None
            else None,
        )

    def fetch_me(self, access_token: str) -> ThreadsIdentity:
        """Profile of the authorized user; `id` is the authoritative Threads user ID."""
        payload = self._send(
            "GET",
            ME_ENDPOINT,
            params={"fields": ME_FIELDS, "access_token": access_token},
        )
        user_id = _id(payload.get("id"))
        username = payload.get("username")
        if user_id is None or not isinstance(username, str) or not username:
            raise ThreadsUnexpectedResponse()
        name = payload.get("name")
        picture = payload.get("threads_profile_picture_url")
        return ThreadsIdentity(
            threads_user_id=user_id,
            username=username,
            display_name=name if isinstance(name, str) and name else None,
            profile_picture_url=picture
            if isinstance(picture, str) and picture
            else None,
        )
