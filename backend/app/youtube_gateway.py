"""The only code that talks to Google: token exchange, refresh and channels.list.

There is deliberately no revocation (see research.md, decision 13). Tokens travel only
in form bodies or the Authorization header, never in URLs, and no response body or
token is ever logged or put in an exception message.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx2 as httpx

from app.db import utc_now
from app.youtube_oauth import ChannelInfo, OAuthClientConfig

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"


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


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


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
