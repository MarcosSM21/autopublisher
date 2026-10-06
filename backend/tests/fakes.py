"""In-memory stand-ins for Google and the system keyring, so tests never go online."""

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx2 as httpx

from app.credential_store import CredentialStoreUnavailable

TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

# Distinctive values so leak tests can search for them anywhere.
FAKE_ACCESS_TOKEN = "fake-access-token-7f3a2c"
FAKE_REFRESHED_ACCESS_TOKEN = "fake-refreshed-access-token-41bd9e"
FAKE_REFRESH_TOKEN = "fake-refresh-token-9c2e51"
FAKE_ROTATED_REFRESH_TOKEN = "fake-rotated-refresh-token-a81f07"
FAKE_AUTH_CODE = "fake-auth-code-58d1b4"
FAKE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
FAKE_CLIENT_SECRET = "fake-client-secret-for-tests-3e6c"

SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
ALL_SCOPES = f"{SCOPE_READONLY} {SCOPE_UPLOAD}"


class InMemoryCredentialStore:
    """CredentialStore double; `fail_on` makes the named operations unavailable."""

    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}
        self.fail_on: set[str] = set()

    @property
    def unavailable(self) -> bool:
        return self.fail_on == {"get", "set", "delete"}

    @unavailable.setter
    def unavailable(self, value: bool) -> None:
        self.fail_on = {"get", "set", "delete"} if value else set()

    def _check(self, operation: str) -> None:
        if operation in self.fail_on:
            raise CredentialStoreUnavailable()

    def get(self, ref: str) -> str | None:
        self._check("get")
        return self.secrets.get(ref)

    def set(self, ref: str, value: str) -> None:
        self._check("set")
        self.secrets[ref] = value

    def delete(self, ref: str) -> None:
        self._check("delete")
        self.secrets.pop(ref, None)


@dataclass
class FakeChannel:
    id: str
    title: str
    handle: str | None = None
    thumbnail_url: str | None = None


@dataclass
class RecordedRequest:
    method: str
    url: str
    form: dict[str, str]
    headers: dict[str, str]


@dataclass
class FakeGoogle:
    """Programmable Google OAuth + YouTube endpoints served via httpx MockTransport.

    Outcomes:
    - exchange: ok | no_refresh | partial_scope | rejected | server_error |
      rate_limited | timeout
    - refresh: ok | rotate | invalid_grant | rejected | server_error | timeout
    - channels (queue, then default): ok | unauthorized | forbidden | server_error |
      timeout
    """

    exchange_outcome: str = "ok"
    refresh_outcome: str = "ok"
    channels_outcome: str = "ok"
    channels_outcomes: list[str] = field(default_factory=list)
    channels: list[FakeChannel] = field(
        default_factory=lambda: [
            FakeChannel(
                "UC_TEST_1",
                "Cyber Channel",
                "@cyberchannel",
                "https://yt3.example.com/cyber.jpg",
            )
        ]
    )
    expires_in: int = 3600
    requests: list[RecordedRequest] = field(default_factory=list)

    def set_channel(
        self, channel_id: str, title: str = "Cyber Channel", handle: str | None = None
    ) -> None:
        self.channels = [FakeChannel(channel_id, title, handle)]

    @property
    def token_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.url.startswith(TOKEN_URL)]

    @property
    def channel_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.url.startswith(CHANNELS_URL)]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode() if request.content else ""
        form = {key: values[0] for key, values in parse_qs(body).items()}
        self.requests.append(
            RecordedRequest(
                request.method, str(request.url), form, dict(request.headers)
            )
        )
        url = str(request.url)
        if url == TOKEN_URL and request.method == "POST":
            if form.get("grant_type") == "authorization_code":
                return self._exchange(request)
            if form.get("grant_type") == "refresh_token":
                return self._refresh(request)
        if url.startswith(CHANNELS_URL) and request.method == "GET":
            return self._channels(request)
        raise AssertionError(f"Unexpected request to Google: {request.method} {url}")

    @staticmethod
    def _error(status: int, error: str, request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": error}, request=request)

    def _common_failure(
        self, outcome: str, request: httpx.Request
    ) -> httpx.Response | None:
        if outcome == "server_error":
            return self._error(503, "backend_error", request)
        if outcome == "rate_limited":
            return self._error(429, "rate_limit_exceeded", request)
        if outcome == "timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        return None

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        outcome = self.exchange_outcome
        failure = self._common_failure(outcome, request)
        if failure is not None:
            return failure
        if outcome == "rejected":
            return self._error(400, "invalid_grant", request)
        payload: dict[str, Any] = {
            "access_token": FAKE_ACCESS_TOKEN,
            "expires_in": self.expires_in,
            "token_type": "Bearer",
            "scope": SCOPE_READONLY if outcome == "partial_scope" else ALL_SCOPES,
        }
        if outcome != "no_refresh":
            payload["refresh_token"] = FAKE_REFRESH_TOKEN
        return httpx.Response(200, json=payload, request=request)

    def _refresh(self, request: httpx.Request) -> httpx.Response:
        outcome = self.refresh_outcome
        failure = self._common_failure(outcome, request)
        if failure is not None:
            return failure
        if outcome == "invalid_grant":
            return self._error(400, "invalid_grant", request)
        if outcome == "rejected":
            return self._error(401, "invalid_client", request)
        payload: dict[str, Any] = {
            "access_token": FAKE_REFRESHED_ACCESS_TOKEN,
            "expires_in": self.expires_in,
            "token_type": "Bearer",
            "scope": ALL_SCOPES,
        }
        if outcome == "rotate":
            payload["refresh_token"] = FAKE_ROTATED_REFRESH_TOKEN
        return httpx.Response(200, json=payload, request=request)

    def _channels(self, request: httpx.Request) -> httpx.Response:
        outcome = (
            self.channels_outcomes.pop(0)
            if self.channels_outcomes
            else self.channels_outcome
        )
        failure = self._common_failure(outcome, request)
        if failure is not None:
            return failure
        if outcome == "unauthorized":
            return httpx.Response(401, json={"error": {"code": 401}}, request=request)
        if outcome == "forbidden":
            return httpx.Response(
                403,
                json={
                    "error": {
                        "code": 403,
                        "errors": [{"reason": "insufficientPermissions"}],
                    }
                },
                request=request,
            )
        items = []
        for channel in self.channels:
            snippet: dict[str, Any] = {"title": channel.title}
            if channel.handle:
                snippet["customUrl"] = channel.handle
            if channel.thumbnail_url:
                snippet["thumbnails"] = {"default": {"url": channel.thumbnail_url}}
            items.append({"id": channel.id, "snippet": snippet})
        return httpx.Response(200, json={"items": items}, request=request)


def client_config_json() -> str:
    return json.dumps(
        {
            "installed": {
                "client_id": FAKE_CLIENT_ID,
                "client_secret": FAKE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    )
