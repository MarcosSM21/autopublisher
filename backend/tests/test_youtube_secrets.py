"""No secret ever reaches SQLite, API responses, the callback page, logs or URLs."""

import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    authorize,
    complete_callback,
    get_attempt,
    get_connection,
    setup_youtube_account,
)
from tests.fakes import (
    FAKE_ACCESS_TOKEN,
    FAKE_AUTH_CODE,
    FAKE_CLIENT_SECRET,
    FAKE_REFRESH_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FakeGoogle,
)

SECRETS = (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_AUTH_CODE,
    FAKE_CLIENT_SECRET,
)


def assert_no_secrets(
    db_path: Path,
    responses: Iterable[httpx.Response],
    caplog: pytest.LogCaptureFixture,
    fake_google: FakeGoogle,
    extra: Iterable[str] = (),
) -> None:
    secrets = [*SECRETS, *extra]
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
    # The test client logs the URLs it requests itself (including the callback the
    # browser would open); only the application's own logs are checked.
    app_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith("httpx2")
    )
    for secret in secrets:
        assert secret not in dump
        assert secret not in app_logs
        for response in responses:
            assert secret not in response.text
        for request in fake_google.requests:
            assert secret not in request.url


def _verifier(fake_google: FakeGoogle) -> str:
    return fake_google.token_requests[0].form["code_verifier"]


def test_connect_flow_leaks_no_secret(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, account = setup_youtube_account(youtube_client)
    responses = [
        youtube_client.get(f"/api/accounts/{account['id']}/youtube-connection"),
        youtube_client.post(
            f"/api/accounts/{account['id']}/youtube-connection/authorize"
        ),
    ]
    body, state = authorize(youtube_client, account["id"])
    responses.append(complete_callback(youtube_client, state))
    responses.append(
        youtube_client.get(f"/api/youtube/oauth/attempts/{body['attempt_id']}")
    )
    responses.append(
        youtube_client.get(f"/api/accounts/{account['id']}/youtube-connection")
    )
    assert get_attempt(youtube_client, body["attempt_id"])["status"] == "completed"

    verifier = _verifier(fake_google)
    assert all(verifier not in r.text for r in responses[2:])
    assert_no_secrets(db_path, responses, caplog, fake_google, extra=[verifier])


def test_verify_leaks_no_secret(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, account = setup_youtube_account(youtube_client)
    fake_google.expires_in = 0  # forces a refresh on verify
    _, state = authorize(youtube_client, account["id"])
    complete_callback(youtube_client, state)

    response = youtube_client.post(
        f"/api/accounts/{account['id']}/youtube-connection/verify"
    )

    assert response.status_code == 200
    assert any(
        r.form.get("grant_type") == "refresh_token" for r in fake_google.requests
    )
    assert_no_secrets(db_path, [response], caplog, fake_google)


def test_disconnect_leaks_no_secret(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, account = setup_youtube_account(youtube_client)
    _, state = authorize(youtube_client, account["id"])
    complete_callback(youtube_client, state)

    response = youtube_client.post(
        f"/api/accounts/{account['id']}/youtube-connection/disconnect"
    )

    assert response.status_code == 200
    assert get_connection(youtube_client, account["id"])["status"] == "not_connected"
    assert_no_secrets(db_path, [response], caplog, fake_google)


def test_callback_access_logs_are_redacted() -> None:
    from app.youtube_connections import RedactOAuthCallbackQuery

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:5000",
            "GET",
            f"/api/youtube/oauth/callback?state=abc&code={FAKE_AUTH_CODE}",
            "1.1",
            200,
        ),
        None,
    )
    assert RedactOAuthCallbackQuery().filter(record)
    message = record.getMessage()
    assert FAKE_AUTH_CODE not in message
    assert "state=abc" not in message
    assert "/api/youtube/oauth/callback?[redacted]" in message


def test_access_log_filter_is_installed(youtube_client: TestClient) -> None:
    from app.youtube_connections import RedactOAuthCallbackQuery

    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, RedactOAuthCallbackQuery) for f in filters) == 1
