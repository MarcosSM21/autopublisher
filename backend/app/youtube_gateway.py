"""Google calls outside the upload protocol: token exchange, refresh, channels.list,
the light videos.list check made after an upload and the videos.list statistics read
of analytics (Feature 027).

There is deliberately no revocation (see research.md, decision 13). Tokens travel only
in form bodies or the Authorization header, never in URLs, and no response body or
token is ever logged or put in an exception message.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx2 as httpx

from app.db import utc_now
from app.youtube_oauth import ChannelInfo, OAuthClientConfig

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"


@dataclass(frozen=True)
class TokenSet:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    expires_at: datetime
    scopes: frozenset[str]

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at.isoformat(),
                "scopes": sorted(self.scopes),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "TokenSet":
        """Parse a stored secret; raise ValueError if it is unusable."""
        try:
            data = json.loads(raw)
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            expires_at = datetime.fromisoformat(data["expires_at"])
            scopes = frozenset(data["scopes"])
        except (TypeError, KeyError, ValueError):
            raise ValueError("Invalid stored credentials.") from None
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise ValueError("Invalid stored credentials.")
        if expires_at.tzinfo is None:
            raise ValueError("Invalid stored credentials.")
        return cls(access_token, refresh_token, expires_at, scopes)


class GoogleError(Exception):
    message = "Google returned an error."

    def __init__(self) -> None:
        super().__init__(self.message)


class GoogleRejected(GoogleError):
    message = "Google rejected the request."


class InvalidGrant(GoogleError):
    message = "Google no longer accepts the stored credentials."


class GoogleUnavailable(GoogleError):
    message = "Google or YouTube could not be reached."


class GoogleUnauthorized(GoogleError):
    message = "YouTube did not accept the access token."


class GoogleForbidden(GoogleError):
    message = "YouTube denied access to the channel."


class GoogleQuotaExceeded(GoogleError):
    """A quota or rate limit; `daily` when it lasts until the daily quota reset."""

    message = "YouTube limited the requests."

    def __init__(self, *, daily: bool) -> None:
        super().__init__()
        self.daily = daily


# Error reasons of the YouTube Data API (`error.errors[0].reason`).
DAILY_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
PERMISSION_REASONS = {"forbidden", "insufficientPermissions"}

# `videos.list` documents no maximum for a comma-separated `id`; only `maxResults`
# (1-50) bounds a page, and it cannot be combined with `id`. Batches never exceed
# that documented page size, and an answer that still announces another page is
# never read as an absence (see `VideoStatistics.missing`).
MAX_IDS_PER_VIDEOS_LIST = 50


@dataclass(frozen=True)
class VideoStatistics:
    """`videos.list` statistics of some videos.

    `found` holds only the numeric statistics fields YouTube returned (absent ones
    stay absent). `missing` lists requested ids YouTube confirmed it does not
    return; ids in neither set are unresolved (e.g. an answer cut into pages).
    """

    found: dict[str, dict[str, int]]
    missing: frozenset[str]


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _reason(response: httpx.Response) -> str | None:
    """Only the error reason is read from Google's answer, never its message."""
    try:
        reason = response.json()["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return reason if isinstance(reason, str) else None


def _counter(value: object) -> int | None:
    """A non-negative integer counter; YouTube sends them as decimal strings."""
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _is_transient(response: httpx.Response) -> bool:
    return response.status_code >= 500 or response.status_code == 429


class GoogleGateway:
    def __init__(
        self, client: httpx.Client, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.client = client
        self.clock = clock

    def _post_token(self, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = self.client.post(TOKEN_ENDPOINT, data=form)
        except httpx.TransportError:
            raise GoogleUnavailable() from None
        if _is_transient(response):
            raise GoogleUnavailable()
        payload = _json(response)
        if response.status_code != 200:
            if (
                payload.get("error") == "invalid_grant"
                and form.get("grant_type") == "refresh_token"
            ):
                raise InvalidGrant()
            raise GoogleRejected()
        if not isinstance(payload.get("access_token"), str):
            raise GoogleRejected()
        return payload

    def _token_set(
        self, payload: dict[str, Any], refresh_token: str | None
    ) -> TokenSet:
        expires_in = payload.get("expires_in")
        seconds = expires_in if isinstance(expires_in, int) else 3600
        scope = payload.get("scope")
        return TokenSet(
            access_token=payload["access_token"],
            refresh_token=refresh_token,
            expires_at=self.clock() + timedelta(seconds=seconds),
            scopes=frozenset(scope.split()) if isinstance(scope, str) else frozenset(),
        )

    def exchange_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client: OAuthClientConfig,
    ) -> TokenSet:
        payload = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "redirect_uri": redirect_uri,
            }
        )
        refresh_token = payload.get("refresh_token")
        return self._token_set(
            payload, refresh_token if isinstance(refresh_token, str) else None
        )

    def refresh(self, tokens: TokenSet, client: OAuthClientConfig) -> TokenSet:
        if tokens.refresh_token is None:
            raise InvalidGrant()
        payload = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
            }
        )
        rotated = payload.get("refresh_token")
        refreshed = self._token_set(
            payload, rotated if isinstance(rotated, str) else tokens.refresh_token
        )
        if not refreshed.scopes:
            refreshed = TokenSet(
                refreshed.access_token,
                refreshed.refresh_token,
                refreshed.expires_at,
                tokens.scopes,
            )
        return refreshed

    def list_my_channels(self, access_token: str) -> list[ChannelInfo]:
        """Channels owned by the authorized identity (`channels.list?mine=true`)."""
        try:
            response = self.client.get(
                CHANNELS_ENDPOINT,
                params={"part": "snippet", "mine": "true", "maxResults": "50"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TransportError:
            raise GoogleUnavailable() from None
        if _is_transient(response):
            raise GoogleUnavailable()
        if response.status_code == 401:
            raise GoogleUnauthorized()
        if response.status_code == 403:
            raise GoogleForbidden()
        if response.status_code != 200:
            raise GoogleRejected()
        items = _json(response).get("items") or []
        channels = []
        for item in items if isinstance(items, list) else []:
            snippet = item.get("snippet") or {}
            thumbnails = snippet.get("thumbnails") or {}
            default = thumbnails.get("default") or {}
            channels.append(
                ChannelInfo(
                    id=item.get("id") or "",
                    title=snippet.get("title") or "",
                    handle=snippet.get("customUrl") or None,
                    thumbnail_url=default.get("url") or None,
                )
            )
        return channels

    def get_video_status(self, access_token: str, video_id: str) -> dict[str, str]:
        """Privacy, upload and processing status of an uploaded video (best effort).

        Only whitelisted, non-sensitive values are returned.
        """
        try:
            response = self.client.get(
                VIDEOS_ENDPOINT,
                params={"part": "status,processingDetails", "id": video_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TransportError:
            raise GoogleUnavailable() from None
        if _is_transient(response):
            raise GoogleUnavailable()
        if response.status_code == 401:
            raise GoogleUnauthorized()
        if response.status_code != 200:
            raise GoogleRejected()
        items = _json(response).get("items")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise GoogleRejected()
        item = items[0]
        status = item.get("status") or {}
        processing = item.get("processingDetails") or {}
        values = {
            "privacy_status": status.get("privacyStatus"),
            "upload_status": status.get("uploadStatus"),
            "processing_status": processing.get("processingStatus"),
        }
        return {key: value for key, value in values.items() if isinstance(value, str)}

    def get_video_statistics(
        self, access_token: str, video_ids: Sequence[str]
    ) -> VideoStatistics:
        """`videos.list?part=statistics` for at most `MAX_IDS_PER_VIDEOS_LIST` ids
        (1 quota unit), from the general quota bucket."""
        ids = list(dict.fromkeys(video_ids))
        if not 1 <= len(ids) <= MAX_IDS_PER_VIDEOS_LIST:
            raise ValueError("videos.list takes 1 to 50 video ids.")
        try:
            response = self.client.get(
                VIDEOS_ENDPOINT,
                params={"part": "statistics", "id": ",".join(ids)},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TransportError:
            raise GoogleUnavailable() from None
        status, reason = response.status_code, _reason(response)
        if status == 429 or reason in RATE_LIMIT_REASONS:
            raise GoogleQuotaExceeded(daily=False)
        if reason in DAILY_QUOTA_REASONS:
            raise GoogleQuotaExceeded(daily=True)
        if status >= 500:
            raise GoogleUnavailable()
        if status == 401:
            raise GoogleUnauthorized()
        if status == 403 and reason in PERMISSION_REASONS:
            raise GoogleForbidden()
        if status == 404 and reason == "videoNotFound" and len(ids) == 1:
            # Documented for this method; only unambiguous with a single id.
            return VideoStatistics({}, frozenset(ids))
        if status != 200:
            raise GoogleRejected()
        payload = _json(response)
        items = payload.get("items")
        if not isinstance(items, list):
            raise GoogleRejected()
        requested = set(ids)
        found: dict[str, dict[str, int]] = {}
        for item in items:
            if not isinstance(item, dict) or item.get("id") not in requested:
                continue
            statistics = item.get("statistics")
            fields = statistics if isinstance(statistics, dict) else {}
            found[item["id"]] = {
                name: counter
                for name, value in fields.items()
                if isinstance(name, str) and (counter := _counter(value)) is not None
            }
        complete = payload.get("nextPageToken") is None
        missing = frozenset(requested - set(found)) if complete else frozenset()
        return VideoStatistics(found, missing)
