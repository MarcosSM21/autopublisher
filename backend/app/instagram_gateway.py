"""Meta calls for Instagram Login: code exchange, long-lived token exchange, refresh and
`/me` (see research.md §5, §8, §9).

This is the only module that interprets Meta's error numbers; callers only see the
semantic exceptions below. The token endpoints are documented with the token (and the
app secret) in the query string, so HTTP client logs are redacted by
`instagram_connections.RedactInstagramSecrets`. No exception ever carries a response
body, a URL or a token, and they are raised `from None` so httpx errors (which contain
the URL) are never chained.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx2 as httpx

from app.db import utc_now
from app.instagram_oauth import REQUIRED_PERMISSIONS, InstagramIdentity, MetaAppConfig

CODE_EXCHANGE_ENDPOINT = "https://api.instagram.com/oauth/access_token"
LONG_LIVED_ENDPOINT = "https://graph.instagram.com/access_token"
REFRESH_ENDPOINT = "https://graph.instagram.com/refresh_access_token"
# Only versioned endpoints (`/me`) use it; the token endpoints are unversioned.
GRAPH_API_VERSION = "v26.0"
ME_ENDPOINT = f"https://graph.instagram.com/{GRAPH_API_VERSION}/me"
ME_FIELDS = "user_id,id,username,account_type,profile_picture_url"

PROFESSIONAL_ACCOUNT_TYPES = frozenset({"BUSINESS", "MEDIA_CREATOR"})

# Graph error codes (research §9). Everything else in 4xx is a rejection.
_TRANSIENT_CODES = frozenset({1, 2, 4, 17, 32, 613})
_INVALID_TOKEN_CODE = 190


@dataclass(frozen=True)
class ShortLivedToken:
    access_token: str = field(repr=False)
    permissions: frozenset[str]


@dataclass(frozen=True)
class InstagramToken:
    """Long-lived Instagram token, stored as JSON only in the secure storage."""

    access_token: str = field(repr=False)
    issued_at: datetime
    expires_at: datetime
    permissions: frozenset[str]

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "issued_at": self.issued_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
                "permissions": sorted(self.permissions),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "InstagramToken":
        """Parse a stored secret; raise ValueError if it is unusable."""
        try:
            data = json.loads(raw)
            access_token = data["access_token"]
            issued_at = datetime.fromisoformat(data["issued_at"])
            expires_at = datetime.fromisoformat(data["expires_at"])
            permissions = data["permissions"]
        except (TypeError, KeyError, ValueError):
            raise ValueError("Invalid stored credentials.") from None
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Invalid stored credentials.")
        if issued_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("Invalid stored credentials.")
        if not isinstance(permissions, list) or not all(
            isinstance(item, str) for item in permissions
        ):
            raise ValueError("Invalid stored credentials.")
        return cls(access_token, issued_at, expires_at, frozenset(permissions))


class MetaError(Exception):
    message = "Meta returned an error."

    def __init__(self) -> None:
        super().__init__(self.message)


class MetaUnavailable(MetaError):
    message = "Instagram could not be reached or is temporarily limiting requests."


class MetaTokenInvalid(MetaError):
    message = "Instagram no longer accepts the access token."


class MetaPermissionDenied(MetaError):
    message = "Instagram reports that a required permission is missing."

    def __init__(self, permission: str | None = None) -> None:
        super().__init__()
        # Only one of the two required permission names, never free text from Meta.
        self.permission = permission


class MetaRejected(MetaError):
    message = "Instagram rejected the request."


class MetaUnexpectedResponse(MetaError):
    message = "Instagram returned an unexpected response."


def _json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _safe_permission(error: dict[str, Any]) -> str | None:
    """The affected permission, only if Meta names exactly one of the required ones."""
    message = error.get("message")
    if not isinstance(message, str):
        return None
    named = [name for name in sorted(REQUIRED_PERMISSIONS) if name in message]
    return named[0] if len(named) == 1 else None


def _error_for(response: httpx.Response) -> MetaError:
    """Classify a non-200 response (research §9)."""
    if response.status_code >= 500 or response.status_code == 429:
        return MetaUnavailable()
    payload = _json(response) or {}
    if payload.get("error_type") == "OAuthException":
        # Code exchange errors of api.instagram.com (used/unknown code, wrong URI).
        return MetaRejected()
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(error, dict) and isinstance(code, int):
        if code in _TRANSIENT_CODES:
            return MetaUnavailable()
        if code == _INVALID_TOKEN_CODE:
            return MetaTokenInvalid()
        if code == 10 or 200 <= code <= 299:
            return MetaPermissionDenied(_safe_permission(error))
    return MetaRejected()


def _permissions(value: object) -> frozenset[str] | None:
    if isinstance(value, str):
        return frozenset(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    return None


def _id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value:
        return value
    return None


class InstagramGateway:
    def __init__(
        self, client: httpx.Client, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.client = client
        self.clock = clock

    def _send(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.TransportError:
            raise MetaUnavailable() from None
        if response.status_code != 200:
            raise _error_for(response)
        payload = _json(response)
        if payload is None:
            raise MetaUnexpectedResponse()
        return payload

    def exchange_code(self, code: str, config: MetaAppConfig) -> ShortLivedToken:
        """Authorization code → short-lived token with its granted permissions."""
        payload = self._send(
            "POST",
            CODE_EXCHANGE_ENDPOINT,
            data={
                "client_id": config.app_id,
                "client_secret": config.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": config.redirect_uri,
                "code": code,
            },
        )
        # Documented shape: {"data": [{...}]}; the bare object is also accepted.
        data = payload.get("data")
        if data is not None:
            if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                raise MetaUnexpectedResponse()
            payload = data[0]
        access_token = payload.get("access_token")
        permissions = _permissions(payload.get("permissions"))
        if not isinstance(access_token, str) or not access_token or permissions is None:
            raise MetaUnexpectedResponse()
        return ShortLivedToken(access_token, permissions)

    def _long_lived(
        self, payload: dict[str, Any], permissions: frozenset[str]
    ) -> InstagramToken:
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise MetaUnexpectedResponse()
        now = self.clock()
        return InstagramToken(
            access_token, now, now + timedelta(seconds=expires_in), permissions
        )

    def exchange_long_lived(
        self, short_token: ShortLivedToken, config: MetaAppConfig
    ) -> InstagramToken:
        """Short-lived token → long-lived (60 days) token."""
        payload = self._send(
            "GET",
            LONG_LIVED_ENDPOINT,
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": config.app_secret,
                "access_token": short_token.access_token,
            },
        )
        return self._long_lived(payload, short_token.permissions)

    def refresh(self, token: InstagramToken) -> InstagramToken:
        """Renew a long-lived token (≥ 24 h old and still valid); no app secret."""
        payload = self._send(
            "GET",
            REFRESH_ENDPOINT,
            params={
                "grant_type": "ig_refresh_token",
                "access_token": token.access_token,
            },
        )
        return self._long_lived(payload, token.permissions)

    def fetch_me(self, access_token: str) -> InstagramIdentity:
        """Identity of the authorized account; `user_id` is the authoritative ID."""
        payload = self._send(
            "GET",
            ME_ENDPOINT,
            params={"fields": ME_FIELDS, "access_token": access_token},
        )
        user_id = _id(payload.get("user_id"))
        username = payload.get("username")
        if user_id is None or not isinstance(username, str) or not username:
            raise MetaUnexpectedResponse()
        account_type = payload.get("account_type")
        picture = payload.get("profile_picture_url")
        return InstagramIdentity(
            instagram_user_id=user_id,
            username=username,
            account_type=account_type.upper()
            if isinstance(account_type, str)
            else None,
            profile_picture_url=picture
            if isinstance(picture, str) and picture
            else None,
            app_scoped_id=_id(payload.get("id")),
        )
