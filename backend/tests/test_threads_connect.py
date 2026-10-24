"""Connecting a Threads account: success, errors and uniqueness (US1, US2, US6)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import threads_connections
from tests.conftest import (
    complete_threads,
    connect_threads,
    create_account,
    create_project,
    create_threads_account,
    get_threads_connection,
    make_threads_app,
    run_sql,
    start_threads_authorization,
    stop,
    threads_redirect_url_for,
    threads_rows,
)
from tests.fakes import (
    FAKE_META_ERROR_TEXT,
    FAKE_TH_CODE,
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REDIRECT_URI,
    FAKE_TH_SHORT_TOKEN,
    LONG_LIVED_SECONDS,
    TH_ALL_SCOPES,
    TH_BASIC,
    TH_DATA_ACCESS_EXPIRES_AT,
    TH_PUBLISH,
    TH_USER_ID,
    FakeClock,
    FakeThreads,
    InMemoryCredentialStore,
    threads_app_config_json,
)
from tests.test_accounts import ACCOUNT_FIELDS

ROUTES = (
    ("get", "/api/accounts/{id}/threads-connection"),
    ("post", "/api/accounts/{id}/threads-connection/authorize"),
    ("post", "/api/accounts/{id}/threads-connection/verify"),
    ("post", "/api/accounts/{id}/threads-connection/disconnect"),
)


def _error(response: Any) -> dict[str, Any]:
    error: dict[str, Any] = response.json()["error"]
    return error


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


# --- US1: connect --------------------------------------------------------------------


def test_new_account_is_not_connected(threads_client: TestClient) -> None:
    _, account = create_threads_account(threads_client)

    assert get_threads_connection(threads_client, account["id"]) == {
        "status": "not_connected",
        "identity": None,
        "connected_at": None,
        "last_verified_at": None,
        "token_obtained_at": None,
        "access_expires_at": None,
        "data_access_expires_at": None,
        "oauth_configured": True,
    }


def test_authorize_returns_attempt_and_url(threads_client: TestClient) -> None:
    _, account = create_threads_account(threads_client)

    response = threads_client.post(
        f"/api/accounts/{account['id']}/threads-connection/authorize"
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"attempt_id", "authorization_url", "expires_at"}
    assert body["authorization_url"].startswith(
        "https://threads.com/oauth/authorize?client_id=9876543210&redirect_uri="
    )
    assert "scope=threads_basic%2Cthreads_content_publish" in body["authorization_url"]
    assert "code_challenge" not in body["authorization_url"]


def test_connect_threads_account(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    _, account = create_threads_account(threads_client)
    attempt_id, state = start_threads_authorization(threads_client, account["id"])

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 200, response.text
    attempt = response.json()
    assert attempt["status"] == "completed"
    assert attempt["attempt_id"] == attempt_id
    assert attempt["error"] is None
    connection = attempt["connection"]
    assert connection["status"] == "connected"
    assert connection["identity"] == {
        "threads_user_id": TH_USER_ID,
        "username": "cyber.studio",
        "display_name": "Cyber Studio",
        "profile_picture_url": "https://scontent.example/th-pic.jpg",
    }
    now = fake_clock.now()
    assert connection["token_obtained_at"] == _iso(now)
    assert connection["access_expires_at"] == _iso(
        now + timedelta(seconds=LONG_LIVED_SECONDS)
    )
    assert connection["data_access_expires_at"] == _iso(
        datetime.fromtimestamp(TH_DATA_ACCESS_EXPIRES_AT, UTC)
    )
    assert connection["connected_at"] == _iso(now)
    assert connection["last_verified_at"] == connection["connected_at"]
    assert get_threads_connection(threads_client, account["id"]) == connection

    # Only the long-lived token is stored, only in the secure store.
    (row,) = threads_rows(db_path)
    assert row["threads_user_id"] == TH_USER_ID
    secret = json.loads(threads_credential_store.secrets[row["credential_ref"]])
    assert set(secret) == {"access_token", "token_obtained_at", "expires_at", "scopes"}
    assert secret["access_token"] == FAKE_TH_LONG_TOKEN
    assert secret["scopes"] == TH_ALL_SCOPES
    assert len(threads_credential_store.secrets) == 1
    assert FAKE_TH_SHORT_TOKEN not in json.dumps(threads_credential_store.secrets)
    # The SQLite dates mirror the secret.
    assert datetime.fromisoformat(secret["token_obtained_at"]) == now
    assert row["token_obtained_at"].startswith(now.strftime("%Y-%m-%d %H:%M:%S"))

    # Requests in the documented order; the single-use code is exchanged once.
    urls = [request.url.split("?")[0] for request in fake_threads.requests]
    assert urls == [
        "https://graph.threads.net/oauth/access_token",
        "https://graph.threads.net/access_token",
        "https://graph.threads.net/v1.0/debug_token",
        "https://graph.threads.net/v1.0/me",
    ]


def test_account_fields_unchanged_after_connecting(threads_client: TestClient) -> None:
    project_id, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])

    response = threads_client.get(f"/api/projects/{project_id}/accounts")
    (read,) = response.json()
    assert set(read) == ACCOUNT_FIELDS
    assert read["handle"] == account["handle"]
    assert read["display_name"] == account["display_name"]


def test_connection_survives_restart(
    threads_client: TestClient,
    db_path: Path,
    media_dir: Path,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
) -> None:
    _, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])

    stop(threads_client)
    app = make_threads_app(
        db_path, media_dir, threads_credential_store, fake_threads, fake_clock
    )
    with TestClient(app) as restarted:
        assert get_threads_connection(restarted, account["id"]) == connection


@pytest.mark.parametrize("platform", ["instagram", "youtube", "x"])
@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_other_platforms_are_rejected(
    threads_client: TestClient, method: str, path: str, platform: str
) -> None:
    project = create_project(threads_client, "Cyber")
    other = create_account(threads_client, project["id"], platform, "cyber")

    response = getattr(threads_client, method)(path.format(id=other["id"]))

    assert response.status_code == 409
    assert _error(response)["code"] == "platform_not_supported"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_unknown_account(threads_client: TestClient, method: str, path: str) -> None:
    response = getattr(threads_client, method)(path.format(id=999))

    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not json",
        threads_app_config_json(app_secret=""),
        threads_app_config_json(redirect_uri="http://localhost/cb"),
    ],
)
def test_not_configured(
    threads_client: TestClient, threads_app_file: Path, content: str | None
) -> None:
    if content is None:
        threads_app_file.unlink()
    else:
        threads_app_file.write_text(content)
    _, account = create_threads_account(threads_client)

    assert (
        get_threads_connection(threads_client, account["id"])["oauth_configured"]
        is False
    )
    response = threads_client.post(
        f"/api/accounts/{account['id']}/threads-connection/authorize"
    )

    assert response.status_code == 503
    error = _error(response)
    assert error["code"] == "threads_oauth_not_configured"
    assert str(threads_app_file) not in error["message"]
    app = threads_client.app
    assert not app.state.threads_attempts._attempts  # type: ignore[attr-defined]


def test_instagram_config_does_not_configure_threads(
    threads_client: TestClient,
    threads_app_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instagram_file = tmp_path / "instagram-app.json"
    instagram_file.write_text(threads_app_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_INSTAGRAM_APP_FILE", str(instagram_file))
    threads_app_file.unlink()
    _, account = create_threads_account(threads_client)

    response = threads_client.post(
        f"/api/accounts/{account['id']}/threads-connection/authorize"
    )

    assert response.status_code == 503
    assert _error(response)["code"] == "threads_oauth_not_configured"


def test_configuration_changes_without_restart(
    threads_client: TestClient, threads_app_file: Path
) -> None:
    _, account = create_threads_account(threads_client)
    content = threads_app_file.read_text()
    threads_app_file.unlink()
    assert not get_threads_connection(threads_client, account["id"])["oauth_configured"]

    threads_app_file.write_text(content)

    assert get_threads_connection(threads_client, account["id"])["oauth_configured"]


# --- US2: errors ---------------------------------------------------------------------


def _assert_nothing_stored(
    store: InMemoryCredentialStore, db_path: Path, account_id: int
) -> None:
    assert store.secrets == {}
    assert all(row["account_id"] != account_id for row in threads_rows(db_path))


def _assert_safe(error: dict[str, Any], state: str) -> None:
    text = json.dumps(error)
    for secret in (
        FAKE_TH_CODE,
        state,
        FAKE_TH_REDIRECT_URI,
        FAKE_META_ERROR_TEXT,
        FAKE_TH_SHORT_TOKEN,
        FAKE_TH_LONG_TOKEN,
    ):
        assert secret not in text


@pytest.fixture
def started(threads_client: TestClient) -> tuple[dict[str, Any], str, str]:
    _, account = create_threads_account(threads_client)
    attempt_id, state = start_threads_authorization(threads_client, account["id"])
    return account, attempt_id, state


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("access_denied", "threads_oauth_denied"),
        ("server_error", "threads_oauth_provider_error"),
        ("unauthorized_client", "threads_oauth_provider_error"),
    ],
)
def test_provider_errors(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    error: str,
    code: str,
) -> None:
    account, attempt_id, state = started
    redirect = (
        f"{FAKE_TH_REDIRECT_URI}?error={error}&error_reason=user_denied"
        f"&error_description={FAKE_META_ERROR_TEXT}&state={state}"
    )

    response = complete_threads(threads_client, attempt_id, redirect)

    assert response.status_code == 400
    assert _error(response)["code"] == code
    _assert_safe(_error(response), state)
    _assert_nothing_stored(threads_credential_store, db_path, account["id"])
    assert fake_threads.requests == []
    again = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )
    assert _error(again)["code"] == "threads_oauth_state_invalid"


@pytest.mark.parametrize(
    "template",
    [
        "not a url",
        "https://localhost:99999/autopublisher/threads/callback?code={c}&state={s}",
        "http://localhost/autopublisher/threads/callback?code={c}&state={s}",
        "https://localhost.evil.example/autopublisher/threads/callback"
        "?code={c}&state={s}",
        "https://evil.example/localhost/autopublisher/threads/callback"
        "?code={c}&state={s}",
        "https://localhost:8443/autopublisher/threads/callback?code={c}&state={s}",
        "https://localhost/autopublisher/threads/callback-other?code={c}&state={s}",
        "https://localhost/autopublisher/threads/callback/?code={c}&state={s}",
        "https://user@localhost/autopublisher/threads/callback?code={c}&state={s}",
        "https://localhost/autopublisher/threads/callback?code={c}&code=x&state={s}",
        "https://localhost/autopublisher/threads/callback?state={s}",
    ],
)
def test_invalid_redirect_url_keeps_attempt_pending(
    threads_client: TestClient,
    fake_threads: FakeThreads,
    started: tuple[dict[str, Any], str, str],
    template: str,
) -> None:
    _, attempt_id, state = started

    response = complete_threads(
        threads_client, attempt_id, template.format(c=FAKE_TH_CODE, s=state)
    )

    assert response.status_code == 400
    assert _error(response)["code"] == "threads_oauth_redirect_url_invalid"
    _assert_safe(_error(response), state)
    assert fake_threads.requests == []
    assert (
        complete_threads(
            threads_client, attempt_id, threads_redirect_url_for(state)
        ).status_code
        == 200
    )


def test_wrong_state_keeps_attempt_pending(
    threads_client: TestClient,
    fake_threads: FakeThreads,
    started: tuple[dict[str, Any], str, str],
) -> None:
    _, attempt_id, state = started

    for wrong in (
        threads_redirect_url_for("not-the-state"),
        f"{FAKE_TH_REDIRECT_URI}?code=c",
    ):
        response = complete_threads(threads_client, attempt_id, wrong)
        assert response.status_code == 400
        assert _error(response)["code"] == "threads_oauth_state_invalid"
    assert fake_threads.requests == []

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_redirect_reused_after_completion(
    threads_client: TestClient, started: tuple[dict[str, Any], str, str]
) -> None:
    _, attempt_id, state = started
    redirect = threads_redirect_url_for(state)
    assert complete_threads(threads_client, attempt_id, redirect).status_code == 200

    response = complete_threads(threads_client, attempt_id, redirect)

    assert response.status_code == 400
    assert _error(response)["code"] == "threads_oauth_state_invalid"


def test_state_of_another_account(threads_client: TestClient) -> None:
    project_id, first = create_threads_account(threads_client)
    _, second = create_threads_account(
        threads_client, handle="other", project_id=project_id
    )
    first_attempt, _ = start_threads_authorization(threads_client, first["id"])
    _, second_state = start_threads_authorization(threads_client, second["id"])

    response = complete_threads(
        threads_client, first_attempt, threads_redirect_url_for(second_state)
    )

    assert response.status_code == 400
    assert _error(response)["code"] == "threads_oauth_state_invalid"


def test_superseded_attempt_expires(
    threads_client: TestClient, started: tuple[dict[str, Any], str, str]
) -> None:
    account, attempt_id, state = started
    start_threads_authorization(threads_client, account["id"])

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 410
    assert _error(response)["code"] == "threads_oauth_attempt_expired"


def test_attempt_expires_after_ten_minutes(
    threads_client: TestClient,
    fake_clock: FakeClock,
    started: tuple[dict[str, Any], str, str],
) -> None:
    _, attempt_id, state = started
    fake_clock.advance(timedelta(minutes=10).total_seconds())

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 410
    assert _error(response)["code"] == "threads_oauth_attempt_expired"


def test_attempt_lost_after_restart(
    threads_client: TestClient,
    db_path: Path,
    media_dir: Path,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    started: tuple[dict[str, Any], str, str],
) -> None:
    _, attempt_id, state = started
    stop(threads_client)
    app = make_threads_app(
        db_path, media_dir, threads_credential_store, fake_threads, fake_clock
    )
    with TestClient(app) as restarted:
        response = complete_threads(
            restarted, attempt_id, threads_redirect_url_for(state)
        )

    assert response.status_code == 410
    assert _error(response)["code"] == "threads_oauth_attempt_expired"


@pytest.mark.parametrize(
    "body", [{}, {"redirect_url": ""}, {"redirect_url": "x" * 4097}, {"other": 1}]
)
def test_invalid_body(
    threads_client: TestClient,
    started: tuple[dict[str, Any], str, str],
    body: dict[str, Any],
) -> None:
    _, attempt_id, state = started

    response = threads_client.post(
        f"/api/threads/oauth/attempts/{attempt_id}/complete", json=body
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "validation_error"
    assert (
        complete_threads(
            threads_client, attempt_id, threads_redirect_url_for(state)
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("endpoint", "fault", "status", "code"),
    [
        ("code", "graph_100", 502, "threads_token_exchange_failed"),
        ("code", "graph_190", 502, "threads_token_exchange_failed"),
        ("long_lived", "graph_190", 502, "threads_token_exchange_failed"),
        ("long_lived", "graph_100", 502, "threads_token_exchange_failed"),
        ("code", "server_error", 503, "threads_unavailable"),
        ("code", "transport", 503, "threads_unavailable"),
        ("long_lived", "rate_limited", 503, "threads_unavailable"),
        ("debug", "server_error", 503, "threads_unavailable"),
        ("me", "graph_4", 503, "threads_unavailable"),
        ("code", "bad_json", 502, "threads_unexpected_response"),
        ("long_lived", "missing_fields", 502, "threads_unexpected_response"),
        ("debug", "missing_fields", 502, "threads_unexpected_response"),
        ("me", "missing_fields", 502, "threads_unexpected_response"),
        ("debug", "graph_10", 422, "threads_permission_missing"),
        ("debug", "graph_100", 422, "threads_permission_missing"),
        ("debug", "graph_190", 422, "threads_permission_missing"),
    ],
)
def test_meta_failures(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    endpoint: str,
    fault: str,
    status: int,
    code: str,
) -> None:
    account, attempt_id, state = started
    fake_threads.faults[endpoint] = fault

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == status
    assert _error(response)["code"] == code
    _assert_safe(_error(response), state)
    _assert_nothing_stored(threads_credential_store, db_path, account["id"])
    # The single-use code was exchanged exactly once.
    assert len(fake_threads.requests_to("code")) == 1
    # The attempt failed: it cannot be completed again.
    fake_threads.faults.clear()
    again = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )
    assert _error(again)["code"] == "threads_oauth_state_invalid"


@pytest.mark.parametrize(
    ("scopes", "missing"),
    [([TH_BASIC], TH_PUBLISH), ([TH_PUBLISH], TH_BASIC), ([], TH_BASIC)],
)
def test_missing_scope(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    scopes: list[str],
    missing: str,
) -> None:
    account, attempt_id, state = started
    fake_threads.debug_scopes = scopes

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "threads_permission_missing"
    assert missing in error["message"]
    _assert_nothing_stored(threads_credential_store, db_path, account["id"])
    assert fake_threads.requests_to("me") == []


def test_invalid_token_per_debug_token(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
) -> None:
    account, attempt_id, state = started
    fake_threads.debug_is_valid = False

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "threads_permission_missing"
    _assert_nothing_stored(threads_credential_store, db_path, account["id"])


@pytest.mark.parametrize("missing", ["is_valid", "scopes"])
def test_unconfirmable_grant(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    missing: str,
) -> None:
    account, attempt_id, state = started
    setattr(fake_threads, f"debug_{missing}", None)

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 502
    assert _error(response)["code"] == "threads_unexpected_response"
    _assert_nothing_stored(threads_credential_store, db_path, account["id"])


@pytest.mark.parametrize("source", ["exchange", "debug"])
def test_incoherent_user_id(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    source: str,
) -> None:
    account, attempt_id, state = started
    if source == "exchange":
        fake_threads.exchange_user_id = "99999"
    else:
        fake_threads.debug_user_id = "99999"

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 502
    assert _error(response)["code"] == "threads_unexpected_response"
    _assert_nothing_stored(threads_credential_store, db_path, account["id"])


def test_store_unavailable(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
) -> None:
    _, attempt_id, state = started
    threads_credential_store.unavailable = True

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 503
    assert _error(response)["code"] == "credential_store_unavailable"
    assert threads_rows(db_path) == []


def test_commit_failure_after_storing_the_secret(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    account, attempt_id, state = started
    stored: list[str] = []
    original_set = threads_credential_store.set

    def recording_set(ref: str, value: str) -> None:
        stored.append(ref)
        original_set(ref, value)

    def failing_write(*args: Any) -> None:
        # Inside the final write_transaction.
        raise RuntimeError(f"database is locked {FAKE_TH_LONG_TOKEN}")

    monkeypatch.setattr(threads_credential_store, "set", recording_set)
    monkeypatch.setattr(threads_connections, "adopt_connected_identity", failing_write)

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == "internal_error"
    _assert_safe(error, state)
    assert "locked" not in error["message"]
    # The new secret was stored, then deleted immediately; no row was created.
    assert len(stored) == 1
    assert threads_credential_store.secrets == {}
    assert threads_rows(db_path) == []
    assert get_threads_connection(threads_client, account["id"])["status"] == (
        "not_connected"
    )
    for record in caplog.records:
        assert FAKE_TH_LONG_TOKEN not in record.getMessage()
    again = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )
    assert _error(again)["code"] == "threads_oauth_state_invalid"


def test_failure_keeps_previous_connection(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    _, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])
    secrets_before = dict(threads_credential_store.secrets)
    rows_before = threads_rows(db_path)
    attempt_id, state = start_threads_authorization(threads_client, account["id"])
    fake_threads.faults["long_lived"] = "graph_190"

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 502
    assert threads_credential_store.secrets == secrets_before
    assert threads_rows(db_path) == rows_before
    assert get_threads_connection(threads_client, account["id"]) == connection


# --- US6: one Threads account per project --------------------------------------------


@pytest.mark.parametrize("holder_active", [True, False])
def test_same_threads_account_twice_in_a_project(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    holder_active: bool,
) -> None:
    project_id, holder = create_threads_account(threads_client, handle="holder")
    connect_threads(threads_client, holder["id"])
    if not holder_active:
        run_sql(db_path, "UPDATE accounts SET is_active = 0 WHERE id = ?", holder["id"])
    _, second = create_threads_account(
        threads_client, handle="second", project_id=project_id
    )
    attempt_id, state = start_threads_authorization(threads_client, second["id"])

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 409
    error = _error(response)
    assert error["code"] == "threads_account_already_connected"
    assert "@holder" in error["message"]
    assert len(threads_credential_store.secrets) == 1
    assert len(threads_rows(db_path)) == 1


def test_same_threads_account_in_another_project(threads_client: TestClient) -> None:
    _, first = create_threads_account(threads_client, "Cyber")
    _, second = create_threads_account(threads_client, "Other")
    connect_threads(threads_client, first["id"])

    connection = connect_threads(threads_client, second["id"])

    assert connection["status"] == "connected"


def test_allowed_after_disconnecting_the_holder(threads_client: TestClient) -> None:
    project_id, holder = create_threads_account(threads_client, handle="holder")
    connect_threads(threads_client, holder["id"])
    threads_client.post(f"/api/accounts/{holder['id']}/threads-connection/disconnect")
    _, second = create_threads_account(
        threads_client, handle="second", project_id=project_id
    )

    assert connect_threads(threads_client, second["id"])["status"] == "connected"


def test_same_username_different_id_is_allowed(
    threads_client: TestClient, fake_threads: FakeThreads
) -> None:
    project_id, first = create_threads_account(threads_client, handle="first")
    connect_threads(threads_client, first["id"])
    _, second = create_threads_account(
        threads_client, handle="second", project_id=project_id
    )

    connection = connect_threads(
        threads_client, second["id"], fake_threads, id="25840000000000999"
    )

    assert connection["identity"]["username"] == "cyber.studio"


def test_instagram_connection_never_blocks_threads(
    threads_client: TestClient, db_path: Path
) -> None:
    project_id, account = create_threads_account(threads_client)
    instagram = create_account(threads_client, project_id, "instagram", "cyber")
    # An Instagram connection whose ID even matches the Threads user ID.
    run_sql(
        db_path,
        "INSERT INTO instagram_connections (account_id, project_id, instagram_user_id, "
        "username, account_type, status, credential_ref, credential_expires_at, "
        "connected_at, updated_at) VALUES (?, ?, ?, 'cyber', 'BUSINESS', 'connected', "
        "'ig-ref', '2026-12-12 10:00:00', '2026-10-13 10:00:00', "
        "'2026-10-13 10:00:00')",
        instagram["id"],
        project_id,
        TH_USER_ID,
    )

    assert connect_threads(threads_client, account["id"])["status"] == "connected"


def test_race_is_caught_by_the_constraint(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, holder = create_threads_account(threads_client, handle="holder")
    connect_threads(threads_client, holder["id"])
    _, second = create_threads_account(
        threads_client, handle="second", project_id=project_id
    )
    # Simulate a concurrent request that passed the rule check first.
    monkeypatch.setattr(
        threads_connections, "ensure_identity_available", lambda *args: None
    )
    attempt_id, state = start_threads_authorization(threads_client, second["id"])

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 409
    assert _error(response)["code"] == "threads_account_already_connected"
    assert len(threads_credential_store.secrets) == 1
    assert len(threads_rows(db_path)) == 1
