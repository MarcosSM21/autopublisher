"""No Instagram secret ever reaches SQLite, API responses, error messages or logs.

The only allowed exception is the `state` inside the `authorization_url` returned by
`authorize` (spec FR-026).
"""

import logging
import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app.instagram_connections import RedactInstagramSecrets
from app.instagram_gateway import InstagramToken, ShortLivedToken
from app.instagram_oauth import (
    InstagramAttemptRegistry,
    MetaAppConfig,
    RedirectResult,
)
from tests.conftest import (
    complete_instagram,
    create_instagram_account,
    redirect_url_for,
)
from tests.fakes import (
    FAKE_IG_APP_ID,
    FAKE_IG_APP_SECRET,
    FAKE_IG_CODE,
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REDIRECT_URI,
    FAKE_IG_REFRESHED_TOKEN,
    FAKE_IG_SHORT_TOKEN,
    FAKE_META_ERROR_TEXT,
    FakeClock,
    FakeMeta,
    InMemoryCredentialStore,
)

SECRETS = (
    FAKE_IG_CODE,
    FAKE_IG_SHORT_TOKEN,
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REFRESHED_TOKEN,
    FAKE_IG_APP_SECRET,
)
_UNREDACTED_PARAM = re.compile(
    r"\b(access_token|client_secret)=(?!\[redacted\])[^&\s'\"]+"
)


class Flow:
    """Runs requests and remembers every response and issued state."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.responses: list[httpx.Response] = []
        self.authorize_responses: list[httpx.Response] = []
        self.states: list[str] = []

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response: httpx.Response = getattr(self.client, method)(path, **kwargs)
        self.responses.append(response)
        return response

    def authorize(self, account_id: int) -> tuple[str, str]:
        response = self.client.post(
            f"/api/accounts/{account_id}/instagram-connection/authorize"
        )
        assert response.status_code == 201, response.text
        self.authorize_responses.append(response)
        url = response.json()["authorization_url"]
        state = parse_qs(urlsplit(url).query)["state"][0]
        self.states.append(state)
        return response.json()["attempt_id"], state

    def complete(self, account_id: int, redirect: str | None = None) -> httpx.Response:
        attempt_id, state = self.authorize(account_id)
        response = complete_instagram(
            self.client, attempt_id, redirect or redirect_url_for(state)
        )
        self.responses.append(response)
        return response


def assert_no_secrets(
    db_path: Path,
    flow: Flow,
    caplog: pytest.LogCaptureFixture,
    store: InMemoryCredentialStore,
) -> None:
    secrets = [*SECRETS, *flow.states]
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
    raw_db = db_path.read_bytes()
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert caplog.records, "logs were captured"
    for secret in secrets:
        assert secret not in dump
        assert secret.encode() not in raw_db
        assert secret not in logs
        for response in flow.responses:
            assert secret not in response.text
    for response in flow.responses:
        assert FAKE_IG_REDIRECT_URI not in response.text
        assert FAKE_META_ERROR_TEXT not in response.text
    # `authorize` exposes its own state inside the authorization URL, nothing else.
    for response in flow.authorize_responses:
        for secret in SECRETS:
            assert secret not in response.text
    assert not _UNREDACTED_PARAM.search(logs)
    assert not re.search(r"Bearer\s+(?!\[redacted\])\S", logs)
    # Only the secure store holds the long-lived token.
    assert any(FAKE_IG_REFRESHED_TOKEN in value for value in store.secrets.values())


def test_full_flows_leak_no_secret(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("httpx2", "httpcore2.http11", "uvicorn.access", "app"):
        caplog.set_level(logging.DEBUG, logger=name)
    flow = Flow(instagram_client)
    project_id, account = create_instagram_account(instagram_client)
    account_id = account["id"]

    # Failures first: provider error, exchange failure, unexpected response, store.
    _, state = flow.authorize(account_id)
    flow.responses.append(
        complete_instagram(
            instagram_client,
            flow.authorize(account_id)[0],
            f"{FAKE_IG_REDIRECT_URI}?error=access_denied&state={flow.states[-1]}",
        )
    )
    for endpoint, fault in (
        ("code", "oauth_exception"),
        ("long_lived", "graph_190"),
        ("me", "missing_fields"),
    ):
        fake_meta.faults = {endpoint: fault}
        assert flow.complete(account_id).status_code >= 400
    fake_meta.faults = {}
    flow.responses.append(
        complete_instagram(instagram_client, "unknown", redirect_url_for(state))
    )

    # Connect, read, refresh through Verify, verify again.
    assert flow.complete(account_id).json()["status"] == "completed"
    flow.call("get", f"/api/accounts/{account_id}/instagram-connection")
    fake_clock.advance(timedelta(days=2).total_seconds())
    assert (
        flow.call(
            "post", f"/api/accounts/{account_id}/instagram-connection/verify"
        ).status_code
        == 200
    )
    assert fake_meta.requests_to("refresh")
    flow.call("post", f"/api/accounts/{account_id}/instagram-connection/verify")

    # Reconnect with another Instagram account and confirm the change.
    fake_meta.set_identity(user_id="17841400000000002", username="new.account")
    attempt = flow.complete(account_id).json()
    assert attempt["status"] == "awaiting_confirmation"
    confirmed = flow.call(
        "post", f"/api/instagram/oauth/attempts/{attempt['attempt_id']}/confirm"
    )
    assert confirmed.json()["status"] == "completed"

    # Refresh again so the stored token is the refreshed one.
    fake_clock.advance(timedelta(days=2).total_seconds())
    flow.call("post", f"/api/accounts/{account_id}/instagram-connection/verify")

    assert_no_secrets(db_path, flow, caplog, instagram_credential_store)


def _record(message: str, *args: Any) -> logging.LogRecord:
    return logging.LogRecord("httpx2", logging.INFO, __file__, 1, message, args, None)


def test_log_filter_redacts_query_secrets_and_bearer() -> None:
    record = _record(
        'HTTP Request: %s %s "%s %d %s"',
        "GET",
        "https://graph.instagram.com/access_token?grant_type=ig_exchange_token"
        f"&client_secret={FAKE_IG_APP_SECRET}&access_token={FAKE_IG_SHORT_TOKEN}",
        "HTTP/1.1",
        200,
        "OK",
    )
    other = _record(
        f"code={FAKE_IG_CODE}&state=abc Authorization: Bearer {FAKE_IG_LONG_TOKEN}"
    )

    for item in (record, other):
        RedactInstagramSecrets().filter(item)

    message = record.getMessage()
    assert FAKE_IG_APP_SECRET not in message
    assert FAKE_IG_SHORT_TOKEN not in message
    assert "grant_type=ig_exchange_token" in message
    assert "client_secret=[redacted]" in message
    assert other.getMessage() == (
        "code=[redacted]&state=[redacted] Authorization: Bearer [redacted]"
    )


def test_log_filter_keeps_unrelated_messages() -> None:
    record = _record("Account %s connected", 7)

    RedactInstagramSecrets().filter(record)

    assert record.getMessage() == "Account 7 connected"
    assert record.args == (7,)


def test_reprs_hide_secrets() -> None:
    config = MetaAppConfig(FAKE_IG_APP_ID, FAKE_IG_APP_SECRET, FAKE_IG_REDIRECT_URI)
    clock = FakeClock()
    now = clock.now()
    token = InstagramToken(FAKE_IG_LONG_TOKEN, now, now, frozenset())
    short = ShortLivedToken(FAKE_IG_SHORT_TOKEN, frozenset())
    redirect = RedirectResult("state-value-1", FAKE_IG_CODE)
    attempt = InstagramAttemptRegistry(clock.now).create(1, "state-value-2")
    attempt.pending_credentials = token

    text = " ".join(repr(item) for item in (config, token, short, redirect, attempt))

    for secret in (*SECRETS, "state-value-1", "state-value-2"):
        assert secret not in text
