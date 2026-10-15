"""Connecting a TikTok account: happy path (US1) and every error path of the callback
(US2), with the fake TikTok API, an in-memory store and the fake clock."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tiktok_connections
from app.config import TIKTOK_ATTEMPT_TTL
from app.tiktok_gateway import TikTokCredential
from tests.conftest import (
    TIKTOK_BASE_URL,
    connect_tiktok,
    create_account,
    create_project,
    create_tiktok_account,
    get_tiktok_connection,
    make_tiktok_app,
    poll_tiktok_attempt,
    run_sql,
    start_tiktok_authorization,
    tiktok_callback,
    tiktok_rows,
    tiktok_test_client,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_CLIENT_KEY,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_CODE,
    FAKE_TT_ERROR_TEXT,
    FAKE_TT_OPEN_ID,
    FAKE_TT_REDIRECT_URI,
    FAKE_TT_REFRESH_TOKEN,
    TT_ACCESS_SECONDS,
    TT_ALL_SCOPES,
    TT_BASIC,
    TT_PUBLISH,
    TT_REFRESH_SECONDS,
    TT_UPLOAD,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
    threads_app_config_json,
    tiktok_app_config_json,
)

ACCOUNT_ROUTES = (
    ("get", "/api/accounts/{id}/tiktok-connection"),
    ("post", "/api/accounts/{id}/tiktok-connection/authorize"),
)
RESULT = "/api/tiktok/oauth/result?outcome="
MARKER = "provider-marker-71c3"


def _error(response: Any) -> dict[str, Any]:
    error: dict[str, Any] = response.json()["error"]
    return error


def _app(client: TestClient) -> FastAPI:
    app: FastAPI = client.app  # type: ignore[assignment]
    return app


def _assert_redirect(response: Any, outcome: str) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == RESULT + outcome
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


def _secrets(state: str = "", verifier: str = "") -> list[str]:
    values = [
        FAKE_TT_ACCESS_TOKEN,
        FAKE_TT_REFRESH_TOKEN,
        FAKE_TT_CODE,
        FAKE_TT_CLIENT_SECRET,
        FAKE_TT_ERROR_TEXT,
        MARKER,
    ]
    return values + [value for value in (state, verifier) if value]


def _assert_clean(text: str, *secrets: str) -> None:
    for secret in _secrets(*secrets):
        assert secret not in text, secret


# --- US1: happy path ------------------------------------------------------------


def test_not_connected_status(tiktok_client: TestClient) -> None:
    _, account = create_tiktok_account(tiktok_client)

    assert get_tiktok_connection(tiktok_client, account["id"]) == {
        "status": "not_connected",
        "identity": None,
        "connected_at": None,
        "last_verified_at": None,
        "access_expires_at": None,
        "refresh_expires_at": None,
        "permissions": None,
        "oauth_configured": True,
    }


def test_authorize_returns_the_documented_url(tiktok_client: TestClient) -> None:
    _, account = create_tiktok_account(tiktok_client)

    response = tiktok_client.post(
        f"/api/accounts/{account['id']}/tiktok-connection/authorize"
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"attempt_id", "authorization_url", "expires_at"}
    parts = urlsplit(body["authorization_url"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://www.tiktok.com/v2/auth/authorize/"
    )
    query = parse_qs(parts.query)
    assert set(query) == {
        "client_key",
        "scope",
        "response_type",
        "redirect_uri",
        "state",
        "code_challenge",
        "code_challenge_method",
    }
    assert query["client_key"] == [FAKE_TT_CLIENT_KEY]
    assert query["scope"] == ["user.info.basic,video.publish,video.upload"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [FAKE_TT_REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 64
    assert FAKE_TT_CLIENT_SECRET not in response.text
    attempt = poll_tiktok_attempt(tiktok_client, body["attempt_id"])
    assert attempt == {
        "attempt_id": body["attempt_id"],
        "account_id": account["id"],
        "status": "pending",
        "expires_at": body["expires_at"],
        "error": None,
        "current_identity": None,
        "new_identity": None,
        "connection": None,
    }


def test_callback_connects_the_account(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    attempt_id, state, challenge = start_tiktok_authorization(
        tiktok_client, account["id"], fake_tiktok
    )

    response = tiktok_callback(
        tiktok_client, state, scopes="user.info.basic,video.publish,video.upload"
    )

    _assert_redirect(response, "connected")
    _assert_clean(response.headers["location"], state)
    page = tiktok_client.get(response.headers["location"])
    assert page.status_code == 200
    assert "TikTok account connected" in page.text
    assert "<script" not in page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    _assert_clean(page.text, state)
    assert "Cyber Studio" not in page.text

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["status"] == "completed"
    now = fake_clock.now()
    connection = attempt["connection"]
    assert connection["status"] == "connected"
    assert connection["identity"] == {
        "open_id": FAKE_TT_OPEN_ID,
        "display_name": "Cyber Studio",
        "avatar_url": fake_tiktok.avatar_url,
    }
    assert connection["permissions"]["granted"] == [TT_BASIC, TT_PUBLISH, TT_UPLOAD]
    assert connection["permissions"]["source"] == "token_exchange"
    assert connection == get_tiktok_connection(tiktok_client, account["id"])

    # Token exchange exactly once, with the verifier of the challenge; then user/info.
    assert fake_tiktok.calls() == ["exchange", "user_info"]
    [exchange] = fake_tiktok.requests_to("exchange")
    verifier = exchange.form["code_verifier"]
    assert hashlib.sha256(verifier.encode()).hexdigest() == challenge
    assert exchange.form["code"] == FAKE_TT_CODE
    assert exchange.form["redirect_uri"] == FAKE_TT_REDIRECT_URI

    [row] = tiktok_rows(db_path)
    secret = json.loads(tiktok_credential_store.secrets[row["credential_ref"]])
    assert set(secret) == {
        "version",
        "open_id",
        "access_token",
        "refresh_token",
        "access_expires_at",
        "refresh_expires_at",
        "scopes",
        "scopes_source",
        "obtained_at",
    }
    credential = TikTokCredential.from_json(
        tiktok_credential_store.secrets[row["credential_ref"]]
    )
    assert credential.access_token == FAKE_TT_ACCESS_TOKEN
    assert credential.refresh_token == FAKE_TT_REFRESH_TOKEN
    assert credential.obtained_at == now
    assert (credential.access_expires_at - now).total_seconds() == TT_ACCESS_SECONDS
    assert (credential.refresh_expires_at - now).total_seconds() == TT_REFRESH_SECONDS
    assert connection["access_expires_at"].startswith(
        credential.access_expires_at.isoformat()[:19]
    )
    assert connection["refresh_expires_at"].startswith(
        credential.refresh_expires_at.isoformat()[:19]
    )
    assert row["status"] == "connected"
    assert tiktok_rows(db_path, "tiktok_credential_orphans") == []
    _assert_clean(json.dumps(tiktok_rows(db_path), default=str), state, verifier)
    _assert_clean(json.dumps(attempt), state, verifier)


@pytest.mark.parametrize(
    "query",
    [
        "outcome=unknown",
        "",
        "outcome=connected&outcome=failed",
        "outcome=%3Cscript%3Ealert(1)%3C%2Fscript%3E",
        f"outcome={MARKER}",
    ],
)
def test_result_page_never_reflects_the_query(
    tiktok_client: TestClient, query: str
) -> None:
    page = tiktok_client.get(f"/api/tiktok/oauth/result?{query}")

    assert page.status_code == 200
    assert "Authorization not valid" in page.text
    assert "<script" not in page.text
    assert MARKER not in page.text
    assert page.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("outcome", "title"),
    [
        ("connected", "TikTok account connected"),
        ("confirm_required", "Confirm the TikTok account"),
        ("cancelled", "Connection cancelled"),
        ("failed", "Connection failed"),
        ("invalid", "Authorization not valid"),
    ],
)
def test_result_pages(tiktok_client: TestClient, outcome: str, title: str) -> None:
    page = tiktok_client.get(f"/api/tiktok/oauth/result?outcome={outcome}&x={MARKER}")

    assert title in page.text
    assert "You can close this tab and return to AutoPublisher." in page.text
    assert MARKER not in page.text


def test_restart_keeps_the_connection(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    before = connect_tiktok(tiktok_client, account["id"], fake_tiktok)

    app = make_tiktok_app(
        db_path, media_dir, tiktok_credential_store, fake_tiktok, fake_clock
    )
    with tiktok_test_client(app) as restarted:
        assert get_tiktok_connection(restarted, account["id"]) == before


@pytest.mark.parametrize("platform", ["youtube", "instagram", "threads", "x"])
@pytest.mark.parametrize(("method", "path"), ACCOUNT_ROUTES)
def test_other_platforms_are_rejected(
    tiktok_client: TestClient, method: str, path: str, platform: str
) -> None:
    project = create_project(tiktok_client, "Cyber")
    other = create_account(tiktok_client, project["id"], platform, "cyber")

    response = getattr(tiktok_client, method)(path.format(id=other["id"]))

    assert response.status_code == 409
    assert _error(response)["code"] == "platform_not_supported"


@pytest.mark.parametrize(("method", "path"), ACCOUNT_ROUTES)
def test_unknown_account(tiktok_client: TestClient, method: str, path: str) -> None:
    response = getattr(tiktok_client, method)(path.format(id=999))

    assert response.status_code == 404


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{",
        json.dumps({"client_key": "k"}),
        tiktok_app_config_json(redirect_uri="http://127.0.0.1:8000/x"),
    ],
)
def test_missing_or_invalid_config(
    tiktok_client: TestClient, tiktok_app_file: Path, content: str | None
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    if content is None:
        tiktok_app_file.unlink()
    else:
        tiktok_app_file.write_text(content)

    response = tiktok_client.post(
        f"/api/accounts/{account['id']}/tiktok-connection/authorize"
    )

    assert response.status_code == 503
    assert _error(response)["code"] == "tiktok_oauth_not_configured"
    assert _app(tiktok_client).state.tiktok_attempts._attempts == {}
    assert (
        get_tiktok_connection(tiktok_client, account["id"])["oauth_configured"] is False
    )


def test_backend_on_another_port_is_not_configured(
    tiktok_client: TestClient,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    other_port = tiktok_test_client(
        _app(tiktok_client), base_url="http://127.0.0.1:8001"
    )

    response = other_port.post(
        f"/api/accounts/{account['id']}/tiktok-connection/authorize"
    )

    assert response.status_code == 503
    assert _error(response)["code"] == "tiktok_oauth_not_configured"
    assert "port" in _error(response)["message"]
    assert _app(tiktok_client).state.tiktok_attempts._attempts == {}


def test_oauth_configured_changes_without_restart(
    tiktok_client: TestClient, tiktok_app_file: Path
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    content = tiktok_app_file.read_text()
    tiktok_app_file.unlink()
    assert (
        get_tiktok_connection(tiktok_client, account["id"])["oauth_configured"] is False
    )

    tiktok_app_file.write_text(content)

    assert (
        get_tiktok_connection(tiktok_client, account["id"])["oauth_configured"] is True
    )


def test_threads_config_does_not_configure_tiktok(
    tiktok_client: TestClient,
    tiktok_app_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads_file = tmp_path / "threads-app.json"
    threads_file.write_text(threads_app_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_THREADS_APP_FILE", str(threads_file))
    tiktok_app_file.unlink()
    _, account = create_tiktok_account(tiktok_client)

    assert (
        get_tiktok_connection(tiktok_client, account["id"])["oauth_configured"] is False
    )


# --- Identity rules and uniqueness ----------------------------------------------


def test_same_open_id_reconnects_normally(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    [before] = tiktok_rows(db_path)
    fake_clock.advance(60)

    connection = connect_tiktok(tiktok_client, account["id"], fake_tiktok)

    [after] = tiktok_rows(db_path)
    assert after["credential_ref"] != before["credential_ref"]
    assert list(tiktok_credential_store.secrets) == [after["credential_ref"]]
    assert tiktok_rows(db_path, "tiktok_credential_orphans") == []
    assert connection["connected_at"] != before["connected_at"]
    assert fake_tiktok.requests_to("revoke") == []


def _link_holder(db_path: Path, account_id: int, project_id: int) -> None:
    """Link `FAKE_TT_OPEN_ID` to an account directly in the database."""
    run_sql(
        db_path,
        "INSERT INTO tiktok_connections (account_id, project_id, open_id, status, "
        "credential_ref, access_expires_at, refresh_expires_at, connected_at, "
        "updated_at) VALUES (?, ?, ?, 'connected', 'holder-ref', "
        "'2026-10-15 10:00:00', '2027-10-15 10:00:00', '2026-10-14 10:00:00', "
        "'2026-10-14 10:00:00')",
        account_id,
        project_id,
        FAKE_TT_OPEN_ID,
    )


@pytest.mark.parametrize("holder_active", [True, False])
def test_open_id_already_linked_in_the_project(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    holder_active: bool,
) -> None:
    project_id, holder = create_tiktok_account(tiktok_client, handle="holder")
    _, account = create_tiktok_account(
        tiktok_client, handle="second", project_id=project_id
    )
    _link_holder(db_path, holder["id"], project_id)
    if not holder_active:
        run_sql(db_path, "UPDATE accounts SET is_active = 0 WHERE id = ?", holder["id"])
    attempt_id, state, _ = start_tiktok_authorization(
        tiktok_client, account["id"], fake_tiktok
    )

    response = tiktok_callback(tiktok_client, state)

    _assert_redirect(response, "failed")
    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "tiktok_account_already_connected"
    assert "@holder" in attempt["error"]["message"]
    assert tiktok_credential_store.secrets == {}
    assert [row["account_id"] for row in tiktok_rows(db_path)] == [holder["id"]]
    assert len(fake_tiktok.requests_to("revoke")) == 1


def test_open_id_of_another_project_is_allowed(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    _, first = create_tiktok_account(tiktok_client, "One")
    _, second = create_tiktok_account(tiktok_client, "Two")

    connect_tiktok(tiktok_client, first["id"], fake_tiktok)
    connection = connect_tiktok(tiktok_client, second["id"], fake_tiktok)

    assert connection["status"] == "connected"


def test_open_id_is_available_after_the_holder_disconnects(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    project_id, holder = create_tiktok_account(tiktok_client, handle="holder")
    _, account = create_tiktok_account(
        tiktok_client, handle="second", project_id=project_id
    )
    connect_tiktok(tiktok_client, holder["id"], fake_tiktok)
    response = tiktok_client.post(
        f"/api/accounts/{holder['id']}/tiktok-connection/disconnect"
    )
    assert response.status_code == 200, response.text

    connection = connect_tiktok(tiktok_client, account["id"], fake_tiktok)

    assert connection["identity"]["open_id"] == FAKE_TT_OPEN_ID


def test_racing_completions_link_at_most_one_account(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both completions pass the pre-check (as when they run at the same time): the
    unique key decides and the loser stores nothing."""
    project_id, first = create_tiktok_account(tiktok_client, handle="first")
    _, second = create_tiktok_account(
        tiktok_client, handle="second", project_id=project_id
    )
    _, first_state, _ = start_tiktok_authorization(
        tiktok_client, first["id"], fake_tiktok
    )
    second_attempt, second_state, _ = start_tiktok_authorization(
        tiktok_client, second["id"], fake_tiktok
    )
    monkeypatch.setattr(
        tiktok_connections, "ensure_identity_available", lambda *args: None
    )

    _assert_redirect(tiktok_callback(tiktok_client, first_state), "connected")
    _assert_redirect(tiktok_callback(tiktok_client, second_state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, second_attempt)
    assert attempt["error"]["code"] == "tiktok_account_already_connected"
    assert "@first" in attempt["error"]["message"]
    [row] = tiktok_rows(db_path)
    assert row["account_id"] == first["id"]
    assert list(tiktok_credential_store.secrets) == [row["credential_ref"]]
    assert len(fake_tiktok.requests_to("revoke")) == 1


def test_other_platforms_never_affect_tiktok_uniqueness(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok, db_path: Path
) -> None:
    project_id, account = create_tiktok_account(tiktok_client)
    threads = create_account(tiktok_client, project_id, "threads", "threads-handle")
    create_account(tiktok_client, project_id, "youtube", "youtube-handle")
    run_sql(
        db_path,
        "INSERT INTO threads_connections (account_id, project_id, threads_user_id, "
        "username, status, credential_ref, token_obtained_at, credential_expires_at, "
        "connected_at, updated_at) VALUES (?, ?, ?, 'threads-handle', 'connected', "
        "'threads-ref', '2026-10-14 10:00:00', '2026-12-14 10:00:00', "
        "'2026-10-14 10:00:00', '2026-10-14 10:00:00')",
        threads["id"],
        project_id,
        FAKE_TT_OPEN_ID,
    )

    connection = connect_tiktok(tiktok_client, account["id"], fake_tiktok)

    assert connection["status"] == "connected"


# --- US2: error paths -----------------------------------------------------------


def _start(client: TestClient, fake: FakeTikTok) -> tuple[dict[str, Any], str, str]:
    _, account = create_tiktok_account(client)
    attempt_id, state, _ = start_tiktok_authorization(client, account["id"], fake)
    return account, attempt_id, state


def _assert_untouched(
    db_path: Path, store: InMemoryCredentialStore, fake: FakeTikTok
) -> None:
    assert tiktok_rows(db_path) == []
    assert store.secrets == {}
    assert fake.requests_to("exchange") == []


def test_non_loopback_client_is_invalid(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)
    remote = tiktok_test_client(_app(tiktok_client), client=("192.168.1.5", 1))

    _assert_redirect(tiktok_callback(remote, state), "invalid")

    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "pending"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_non_loopback_server_is_invalid(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)
    public = tiktok_test_client(_app(tiktok_client), base_url="http://10.0.0.5:8000")

    _assert_redirect(tiktok_callback(public, state), "invalid")
    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "pending"


@pytest.mark.parametrize("state", [None, "unknown-state"])
def test_missing_or_unknown_state_is_invalid(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    state: str | None,
) -> None:
    _, attempt_id, _ = _start(tiktok_client, fake_tiktok)

    _assert_redirect(tiktok_callback(tiktok_client, state), "invalid")

    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "pending"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_state_of_a_superseded_attempt_is_invalid(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    account, first_id, first_state = _start(tiktok_client, fake_tiktok)
    second_id, _, _ = start_tiktok_authorization(
        tiktok_client, account["id"], fake_tiktok
    )

    _assert_redirect(tiktok_callback(tiktok_client, first_state), "invalid")

    assert poll_tiktok_attempt(tiktok_client, first_id)["status"] == "expired"
    assert poll_tiktok_attempt(tiktok_client, second_id)["status"] == "pending"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_cancelled_attempt_then_callback_is_invalid(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    response = tiktok_client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    # Idempotent.
    again = tiktok_client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/cancel")
    assert again.json()["status"] == "cancelled"
    _assert_redirect(tiktok_callback(tiktok_client, state), "invalid")
    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "cancelled"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_cancel_errors(tiktok_client: TestClient, fake_tiktok: FakeTikTok) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)
    tiktok_callback(tiktok_client, state)

    finished = tiktok_client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/cancel")
    unknown = tiktok_client.post("/api/tiktok/oauth/attempts/nope/cancel")

    assert finished.status_code == 409
    assert _error(finished)["code"] == "tiktok_oauth_attempt_not_confirmable"
    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "tiktok_oauth_attempt_not_found"


def test_cancel_is_allowed_with_inactive_entities(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    account, attempt_id, _ = _start(tiktok_client, fake_tiktok)
    tiktok_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})

    response = tiktok_client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/cancel")

    assert response.json()["status"] == "cancelled"


def test_state_after_restart_is_invalid(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    app = make_tiktok_app(
        db_path, media_dir, tiktok_credential_store, fake_tiktok, fake_clock
    )
    with tiktok_test_client(app) as restarted:
        _assert_redirect(tiktok_callback(restarted, state), "invalid")
        missing = restarted.get(f"/api/tiktok/oauth/attempts/{attempt_id}")
        assert missing.status_code == 404
        assert _error(missing)["code"] == "tiktok_oauth_attempt_not_found"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_expired_attempt_is_invalid(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)
    fake_clock.advance(TIKTOK_ATTEMPT_TTL.total_seconds() + 1)

    _assert_redirect(tiktok_callback(tiktok_client, state), "invalid")

    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "expired"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


@pytest.mark.parametrize(
    "params",
    [
        [("code", FAKE_TT_CODE), ("code", "other")],
        [("code", FAKE_TT_CODE), ("scopes", "a"), ("scopes", "b")],
        [("error", "x"), ("error_description", "a"), ("error_description", "b")],
        [("code", FAKE_TT_CODE), ("error", "access_denied")],
        [],
        [("code", "")],
        [("code", "c" * 1025)],
    ],
)
def test_malformed_callbacks_fail_the_attempt(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    params: list[tuple[str, str]],
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    response = tiktok_client.get(
        "/api/tiktok/oauth/callback",
        params=[*params, ("state", state)],
        follow_redirects=False,
    )

    _assert_redirect(response, "failed")
    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "tiktok_oauth_callback_invalid"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_duplicated_state_is_invalid(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    response = tiktok_client.get(
        "/api/tiktok/oauth/callback",
        params=[("code", FAKE_TT_CODE), ("state", state), ("state", state)],
        follow_redirects=False,
    )

    _assert_redirect(response, "invalid")
    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "pending"


def test_access_denied_is_cancelled(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    response = tiktok_callback(
        tiktok_client, state, code=None, error="access_denied", error_description=MARKER
    )

    _assert_redirect(response, "cancelled")
    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "tiktok_oauth_denied"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_provider_error_never_shows_its_description(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    response = tiktok_callback(
        tiktok_client,
        state,
        code=None,
        error=f"server_error_{MARKER}",
        error_description=MARKER,
    )

    _assert_redirect(response, "failed")
    page = tiktok_client.get(response.headers["location"])
    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_oauth_provider_error"
    for text in (response.headers["location"], page.text, json.dumps(attempt)):
        assert MARKER not in text
    assert MARKER not in caplog.text
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_second_callback_after_success_is_invalid(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)
    _assert_redirect(tiktok_callback(tiktok_client, state), "connected")

    _assert_redirect(tiktok_callback(tiktok_client, state), "invalid")

    assert len(fake_tiktok.requests_to("exchange")) == 1
    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "completed"


def test_second_callback_while_processing_is_invalid(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)
    # The first callback consumed the state and is exchanging the code.
    assert _app(tiktok_client).state.tiktok_attempts.consume_state(state) is not None
    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "processing"

    _assert_redirect(tiktok_callback(tiktok_client, state), "invalid")

    assert fake_tiktok.requests_to("exchange") == []


def test_rejected_exchange(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    # The challenge is not registered: the fake rejects the verifier (PKCE mismatch).
    attempt_id, state, _ = start_tiktok_authorization(tiktok_client, account["id"])

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_token_exchange_failed"
    assert fake_tiktok.calls() == ["exchange"]
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []


@pytest.mark.parametrize("fault", ["oauth_invalid_grant", "oauth_invalid_client"])
def test_exchange_rejections_are_called_once(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok, fault: str
) -> None:
    fake_tiktok.faults["exchange"] = fault
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_token_exchange_failed"
    assert len(fake_tiktok.requests_to("exchange")) == 1


@pytest.mark.parametrize(
    ("scope", "missing"),
    [
        (TT_BASIC, TT_PUBLISH),
        (TT_PUBLISH, TT_BASIC),
        ("", TT_BASIC),
        (f"{TT_BASIC},{TT_PUBLISH}", TT_UPLOAD),
        (f"{TT_BASIC},{TT_UPLOAD}", TT_PUBLISH),
    ],
)
def test_partial_scopes_are_rejected(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    scope: str,
    missing: str,
) -> None:
    fake_tiktok.scope = scope
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    response = tiktok_callback(tiktok_client, state, scopes=TT_ALL_SCOPES)

    _assert_redirect(response, "failed")
    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_permission_missing"
    assert missing in attempt["error"]["message"]
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    # Never identified nor stored, but discarded.
    assert fake_tiktok.calls() == ["exchange", "revoke"]


@pytest.mark.parametrize("user_open_id", ["", "oid-someone-else"])
def test_incoherent_open_id(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    user_open_id: str,
) -> None:
    fake_tiktok.user_open_id = user_open_id
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_unexpected_response"
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    assert fake_tiktok.calls() == ["exchange", "user_info", "revoke"]


@pytest.mark.parametrize(
    ("endpoint", "fault"),
    [
        ("exchange", "transport"),
        ("exchange", "timeout"),
        ("exchange", "server_error"),
        ("exchange", "rate_limited"),
        ("user_info", "timeout"),
        ("user_info", "server_error"),
    ],
)
def test_tiktok_unavailable(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    endpoint: str,
    fault: str,
) -> None:
    fake_tiktok.faults[endpoint] = fault
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_unavailable"
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    assert len(fake_tiktok.requests_to("exchange")) == 1


def test_user_info_scope_missing(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    fake_tiktok.faults["user_info"] = "api_scope_not_authorized"
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_permission_missing"
    assert TT_BASIC in attempt["error"]["message"]


def test_store_unavailable(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)
    tiktok_credential_store.unavailable = True

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "credential_store_unavailable"
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    assert len(fake_tiktok.requests_to("revoke")) == 1


def test_commit_failure_after_storing_the_secret(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    def failing_commit(session: Any) -> None:
        assert len(tiktok_credential_store.secrets) == 1
        raise RuntimeError("disk full")

    monkeypatch.setattr(tiktok_connections, "_commit", failing_commit)

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "internal_error"
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    assert len(fake_tiktok.requests_to("revoke")) == 1


@pytest.mark.parametrize("fault", ["server_error", "oauth_invalid_client", "bad_json"])
def test_failing_discard_never_changes_the_outcome(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok, fault: str
) -> None:
    fake_tiktok.scope = TT_BASIC
    fake_tiktok.faults["revoke"] = fault
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_permission_missing"


def test_discard_credential_swallows_missing_config(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_app_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    tiktok_app_file.unlink()
    gateway = _app(tiktok_client).state.tiktok_gateway
    credential = TikTokCredential.from_json(
        json.dumps(
            {
                "version": 1,
                "open_id": FAKE_TT_OPEN_ID,
                "access_token": FAKE_TT_ACCESS_TOKEN,
                "refresh_token": FAKE_TT_REFRESH_TOKEN,
                "access_expires_at": "2026-10-15T10:00:00+00:00",
                "refresh_expires_at": "2027-10-15T10:00:00+00:00",
                "scopes": [TT_BASIC],
                "scopes_source": "token_exchange",
                "obtained_at": "2026-10-14T10:00:00+00:00",
            }
        )
    )

    tiktok_connections.discard_credential(gateway, credential, 7)

    assert fake_tiktok.requests == []
    assert "account 7 (failed)" in caplog.text
    _assert_clean(caplog.text)


def test_inactive_account_fails_without_exchanging(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    account, attempt_id, state = _start(tiktok_client, fake_tiktok)
    tiktok_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "account_inactive"
    _assert_untouched(db_path, tiktok_credential_store, fake_tiktok)


def test_unexpected_error_is_internal(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, attempt_id, state = _start(tiktok_client, fake_tiktok)

    def broken(*args: Any) -> None:
        raise RuntimeError(f"boom {FAKE_TT_ACCESS_TOKEN}")

    monkeypatch.setattr(tiktok_connections, "complete_connection", broken)

    _assert_redirect(tiktok_callback(tiktok_client, state), "failed")

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred. Please try again.",
    }
    assert len(fake_tiktok.requests_to("revoke")) == 1


def test_attempt_not_found(tiktok_client: TestClient) -> None:
    response = tiktok_client.get("/api/tiktok/oauth/attempts/nope")

    assert response.status_code == 404
    assert _error(response)["code"] == "tiktok_oauth_attempt_not_found"


def test_no_secret_leaks_in_responses_or_logs(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, account = create_tiktok_account(tiktok_client)
    attempt_id, state, challenge = start_tiktok_authorization(
        tiktok_client, account["id"], fake_tiktok
    )
    callback = tiktok_callback(tiktok_client, state)
    page = tiktok_client.get(callback.headers["location"])
    attempt = tiktok_client.get(f"/api/tiktok/oauth/attempts/{attempt_id}")
    connection = tiktok_client.get(f"/api/accounts/{account['id']}/tiktok-connection")
    verifier = fake_tiktok.requests_to("exchange")[0].form["code_verifier"]

    for text in (
        callback.headers["location"],
        callback.text,
        page.text,
        attempt.text,
        connection.text,
        caplog.text,
    ):
        _assert_clean(text, state, verifier)
        assert challenge not in text


def test_callback_access_log_is_redacted() -> None:
    log_filter = tiktok_connections.RedactTikTokCallbackQuery()
    for path in (
        f"/api/tiktok/oauth/callback?code={FAKE_TT_CODE}&state=s",
        f"/api/tiktok/oauth/callback/?code={FAKE_TT_CODE}",
    ):
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            0,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:5000", "GET", path, "1.1", 303),
            None,
        )
        assert log_filter.filter(record)
        assert record.getMessage() == (
            '127.0.0.1:5000 - "GET /api/tiktok/oauth/callback?[redacted] HTTP/1.1" 303'
        )


def test_http_client_logs_are_redacted() -> None:
    log_filter = tiktok_connections.RedactTikTokSecrets()
    message = (
        "GET https://www.tiktok.com/v2/auth/authorize/?client_key=k&state=s "
        f"code={FAKE_TT_CODE}&code_verifier=v&access_token={FAKE_TT_ACCESS_TOKEN} "
        f"refresh_token={FAKE_TT_REFRESH_TOKEN} client_secret={FAKE_TT_CLIENT_SECRET} "
        f"token=t Authorization: Bearer {FAKE_TT_ACCESS_TOKEN}"
    )
    record = logging.LogRecord("httpx2", logging.INFO, "", 0, message, (), None)

    assert log_filter.filter(record)

    _assert_clean(record.getMessage())
    assert "code_verifier=v" not in record.getMessage()
    assert "authorize/?[redacted]" in record.getMessage()


def test_base_url_matches_the_default_redirect_uri() -> None:
    assert FAKE_TT_REDIRECT_URI.startswith(TIKTOK_BASE_URL)
