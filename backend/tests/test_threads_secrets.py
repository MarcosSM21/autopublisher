"""No Threads secret ever reaches SQLite, API responses, error messages or logs.

The only allowed exception is the `state` inside the `authorization_url` returned by
`authorize` (spec FR-027).
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

from app.threads_connections import RedactThreadsSecrets
from app.threads_gateway import ShortLivedToken, ThreadsToken
from app.threads_oauth import (
    RedirectResult,
    ThreadsAppConfig,
    ThreadsAttemptRegistry,
)
from tests.conftest import (
    complete_threads,
    create_threads_account,
    threads_redirect_url_for,
)
from tests.fakes import (
    FAKE_META_ERROR_TEXT,
    FAKE_TH_APP_ID,
    FAKE_TH_APP_SECRET,
    FAKE_TH_CODE,
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REDIRECT_URI,
    FAKE_TH_REFRESHED_TOKEN,
    FAKE_TH_SHORT_TOKEN,
    TH_PUBLISH,
    FakeClock,
    FakeThreads,
    InMemoryCredentialStore,
)

SECRETS = (
    FAKE_TH_CODE,
    FAKE_TH_SHORT_TOKEN,
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REFRESHED_TOKEN,
    FAKE_TH_APP_SECRET,
)
_UNREDACTED_PARAM = re.compile(
    r"\b(access_token|input_token|client_secret|code|state)=(?!\[redacted\])[^&\s'\"]+"
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
            f"/api/accounts/{account_id}/threads-connection/authorize"
        )
        assert response.status_code == 201, response.text
        self.authorize_responses.append(response)
        url = response.json()["authorization_url"]
        state = parse_qs(urlsplit(url).query)["state"][0]
        self.states.append(state)
        return response.json()["attempt_id"], state

    def complete(self, account_id: int, redirect: str | None = None) -> httpx.Response:
        attempt_id, state = self.authorize(account_id)
        response = complete_threads(
            self.client, attempt_id, redirect or threads_redirect_url_for(state)
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
    # Scopes live only in the secret, never in SQLite.
    assert TH_PUBLISH not in dump
    for response in flow.responses:
        assert FAKE_TH_REDIRECT_URI not in response.text
        assert FAKE_META_ERROR_TEXT not in response.text
    # `authorize` exposes its own state inside the authorization URL, nothing else.
    for response in flow.authorize_responses:
        for secret in SECRETS:
            assert secret not in response.text
    assert not _UNREDACTED_PARAM.search(logs)
    assert not re.search(r"Bearer\s+(?!\[redacted\])\S", logs)
    # Only the secure store holds the long-lived token.
    assert any(FAKE_TH_REFRESHED_TOKEN in value for value in store.secrets.values())


def test_full_flows_leak_no_secret(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("httpx2", "httpcore2.http11", "uvicorn.access", "app"):
        caplog.set_level(logging.DEBUG, logger=name)
    flow = Flow(threads_client)
    _, account = create_threads_account(threads_client)
    account_id = account["id"]

    # Failures first: denied, invalid pasted URL, exchange failure, missing scope,
    # unexpected response, unknown attempt.
    _, state = flow.authorize(account_id)
    flow.responses.append(
        complete_threads(
            threads_client,
            flow.authorize(account_id)[0],
            f"{FAKE_TH_REDIRECT_URI}?error=access_denied&state={flow.states[-1]}",
        )
    )
    attempt_id, pending_state = flow.authorize(account_id)
    flow.responses.append(
        complete_threads(
            threads_client,
            attempt_id,
            "https://localhost.evil.example/autopublisher/threads/callback"
            f"?code={FAKE_TH_CODE}&state={pending_state}",
        )
    )
    for endpoint, fault in (
        ("code", "graph_100"),
        ("long_lived", "graph_190"),
        ("debug", "graph_10"),
        ("me", "missing_fields"),
    ):
        fake_threads.faults = {endpoint: fault}
        assert flow.complete(account_id).status_code >= 400
    fake_threads.faults = {}
    fake_threads.debug_scopes = ["threads_basic"]
    assert flow.complete(account_id).status_code == 422
    fake_threads.debug_scopes = ["threads_basic", "threads_content_publish"]
    flow.responses.append(
        complete_threads(threads_client, "unknown", threads_redirect_url_for(state))
    )

    # Connect, read, refresh through Verify inside the renewal window, verify again.
    assert flow.complete(account_id).json()["status"] == "completed"
    flow.call("get", f"/api/accounts/{account_id}/threads-connection")
    fake_clock.advance(timedelta(days=54).total_seconds())
    assert (
        flow.call(
            "post", f"/api/accounts/{account_id}/threads-connection/verify"
        ).status_code
        == 200
    )
    assert fake_threads.requests_to("refresh")
    flow.call("post", f"/api/accounts/{account_id}/threads-connection/verify")

    # Reconnect with another Threads account and confirm the change.
    fake_threads.set_identity(id="25840000000000002", username="new.account")
    attempt = flow.complete(account_id).json()
    assert attempt["status"] == "awaiting_confirmation"
    confirmed = flow.call(
        "post", f"/api/threads/oauth/attempts/{attempt['attempt_id']}/confirm"
    )
    assert confirmed.json()["status"] == "completed"

    # Refresh again so the stored token is the refreshed one.
    fake_clock.advance(timedelta(days=54).total_seconds())
    flow.call("post", f"/api/accounts/{account_id}/threads-connection/verify")

    assert_no_secrets(db_path, flow, caplog, threads_credential_store)


def _record(message: str, *args: Any) -> logging.LogRecord:
    return logging.LogRecord("httpx2", logging.INFO, __file__, 1, message, args, None)


def test_log_filter_redacts_query_secrets_bearer_and_app_tokens() -> None:
    record = _record(
        'HTTP Request: %s %s "%s %d %s"',
        "GET",
        "https://graph.threads.net/access_token?grant_type=th_exchange_token"
        f"&client_secret={FAKE_TH_APP_SECRET}&access_token={FAKE_TH_SHORT_TOKEN}",
        "HTTP/1.1",
        200,
        "OK",
    )
    debug = _record(
        "GET https://graph.threads.net/v1.0/debug_token"
        f"?input_token={FAKE_TH_LONG_TOKEN}&access_token={FAKE_TH_LONG_TOKEN}"
    )
    other = _record(
        f"code={FAKE_TH_CODE}&state=abc Authorization: Bearer {FAKE_TH_LONG_TOKEN}"
    )
    app_token = _record(
        f"token TH|{FAKE_TH_APP_ID}|{FAKE_TH_APP_SECRET} and "
        f"TH%7C{FAKE_TH_APP_ID}%7C{FAKE_TH_APP_SECRET}"
    )

    for item in (record, debug, other, app_token):
        RedactThreadsSecrets().filter(item)

    message = record.getMessage()
    assert FAKE_TH_APP_SECRET not in message
    assert FAKE_TH_SHORT_TOKEN not in message
    assert "grant_type=th_exchange_token" in message
    assert "client_secret=[redacted]" in message
    assert FAKE_TH_LONG_TOKEN not in debug.getMessage()
    assert "input_token=[redacted]" in debug.getMessage()
    assert other.getMessage() == (
        "code=[redacted]&state=[redacted] Authorization: Bearer [redacted]"
    )
    assert FAKE_TH_APP_SECRET not in app_token.getMessage()
    assert FAKE_TH_APP_ID not in app_token.getMessage()


def test_log_filter_keeps_unrelated_messages() -> None:
    record = _record("Account %s connected", 7)

    RedactThreadsSecrets().filter(record)

    assert record.getMessage() == "Account 7 connected"
    assert record.args == (7,)


def test_reprs_hide_secrets() -> None:
    config = ThreadsAppConfig(FAKE_TH_APP_ID, FAKE_TH_APP_SECRET, FAKE_TH_REDIRECT_URI)
    clock = FakeClock()
    now = clock.now()
    token = ThreadsToken(FAKE_TH_LONG_TOKEN, now, now, frozenset())
    short = ShortLivedToken(FAKE_TH_SHORT_TOKEN, "2584")
    redirect = RedirectResult("state-value-1", FAKE_TH_CODE)
    attempt = ThreadsAttemptRegistry(clock.now).create(1, "state-value-2")
    attempt.pending_credentials = token

    text = " ".join(repr(item) for item in (config, token, short, redirect, attempt))

    for secret in (*SECRETS, "state-value-1", "state-value-2"):
        assert secret not in text
