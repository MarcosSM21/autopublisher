"""Meta calls for Instagram Login: code exchange, long-lived token exchange, refresh,
`/me` (Feature 008 research §5, §8, §9) and Content Publishing (Feature 009 research
§1, §18).

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
GRAPH_ROOT = f"https://graph.instagram.com/{GRAPH_API_VERSION}"
# Container creation and media_publish can take long on Meta's side.
PUBLISH_TIMEOUT_SECONDS = 60

PROFESSIONAL_ACCOUNT_TYPES = frozenset({"BUSINESS", "MEDIA_CREATOR"})

# Graph error codes (research §9). Everything else in 4xx is a rejection.
_TRANSIENT_CODES = frozenset({1, 2, 4, 17, 32, 613})
_INVALID_TOKEN_CODE = 190
# Error subcodes documented for Instagram Content Publishing (2207xxx).
_PUBLISHING_SUBCODES = (2207000, 2207999)


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


class MetaPublishRejected(MetaRejected):
    """An explicit Graph error carrying only its (non-sensitive) numbers, so callers
    can classify Content Publishing failures (Feature 009 research §18)."""

    def __init__(self, code: int | None, subcode: int | None) -> None:
        super().__init__()
        self.code = code
        self.subcode = subcode


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
        subcode = error.get("error_subcode")
        subcode = subcode if isinstance(subcode, int) else None
        if code == _INVALID_TOKEN_CODE:
            return MetaTokenInvalid()
        if code == 10 or 200 <= code <= 299:
            return MetaPermissionDenied(_safe_permission(error))
        if (
            subcode is not None
            and _PUBLISHING_SUBCODES[0] <= subcode <= (_PUBLISHING_SUBCODES[1])
        ):
            # Content Publishing errors are explicit, even under "transient" codes.
            return MetaPublishRejected(code, subcode)
        if code in _TRANSIENT_CODES:
            return MetaUnavailable()
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

    # --- Content Publishing (Feature 009) ------------------------------------------
    # POST parameters go in the form body: the signed media URL must never appear in
    # a request URL, which HTTP client logs record.

    def _create_container(
        self, ig_user_id: str, access_token: str, data: dict[str, str]
    ) -> str:
        payload = self._send(
            "POST",
            f"{GRAPH_ROOT}/{ig_user_id}/media",
            data={**data, "access_token": access_token},
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        container_id = _id(payload.get("id"))
        if container_id is None:
            raise MetaUnexpectedResponse()
        return container_id

    def create_image_container(
        self,
        ig_user_id: str,
        access_token: str,
        *,
        image_url: str,
        caption: str,
        alt_text: str | None,
        is_ai_generated: bool,
    ) -> str:
        data = {
            "image_url": image_url,
            "is_ai_generated": "true" if is_ai_generated else "false",
        }
        if caption:
            data["caption"] = caption
        if alt_text:
            data["alt_text"] = alt_text
        return self._create_container(ig_user_id, access_token, data)

    def create_reel_container(
        self,
        ig_user_id: str,
        access_token: str,
        *,
        video_url: str,
        caption: str,
        share_to_feed: bool,
        is_ai_generated: bool,
    ) -> str:
        data = {
            "media_type": "REELS",
            "video_url": video_url,
            "share_to_feed": "true" if share_to_feed else "false",
            "is_ai_generated": "true" if is_ai_generated else "false",
        }
        if caption:
            data["caption"] = caption
        return self._create_container(ig_user_id, access_token, data)

    def container_status(self, container_id: str, access_token: str) -> str:
        """`status_code` of a container (IN_PROGRESS, FINISHED, ERROR, ...)."""
        payload = self._send(
            "GET",
            f"{GRAPH_ROOT}/{container_id}",
            params={"fields": "status_code,status", "access_token": access_token},
        )
        status = payload.get("status_code")
        if not isinstance(status, str) or not status:
            raise MetaUnexpectedResponse()
        return status.upper()

    def publish(self, ig_user_id: str, container_id: str, access_token: str) -> str:
        """`media_publish`: creates the visible post and returns its media id."""
        payload = self._send(
            "POST",
            f"{GRAPH_ROOT}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        media_id = _id(payload.get("id"))
        if media_id is None:
            raise MetaUnexpectedResponse()
        return media_id

    def media_permalink(self, media_id: str, access_token: str) -> str | None:
        payload = self._send(
            "GET",
            f"{GRAPH_ROOT}/{media_id}",
            params={"fields": "id,permalink", "access_token": access_token},
        )
        permalink = payload.get("permalink")
        if isinstance(permalink, str) and permalink.startswith("https://"):
            return permalink
        return None

    def publishing_limit(
        self, ig_user_id: str, access_token: str
    ) -> tuple[int, int] | None:
        """(quota_usage, quota_total) from Meta, or None if the shape is unexpected."""
        payload = self._send(
            "GET",
            f"{GRAPH_ROOT}/{ig_user_id}/content_publishing_limit",
            params={"fields": "quota_usage,config", "access_token": access_token},
        )
        data = payload.get("data")
        item = data[0] if isinstance(data, list) and data else payload
        if not isinstance(item, dict):
            return None
        usage = item.get("quota_usage")
        config = item.get("config")
        total = config.get("quota_total") if isinstance(config, dict) else None
        if (
            isinstance(usage, int)
            and not isinstance(usage, bool)
            and isinstance(total, int)
            and not isinstance(total, bool)
        ):
            return usage, total
        return None
