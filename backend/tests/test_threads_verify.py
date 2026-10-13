"""Verify connection (US4), on the gateway's semantic classification.

The route runs against `StubThreadsGateway`, so no test here depends on Meta's error
numbers. Verify is read-only towards Threads: only the documented read endpoints
(and the token refresh) are ever used.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.threads_gateway import (
    ThreadsPermissionDenied,
    ThreadsRejected,
    ThreadsTokenInfo,
    ThreadsTokenInvalid,
    ThreadsUnavailable,
    ThreadsUnexpectedResponse,
)
from app.threads_oauth import ThreadsIdentity
from tests.conftest import (
    connect_threads,
    create_account,
    create_project,
    create_threads_account,
    get_threads_connection,
    run_sql,
    threads_rows,
)
from tests.fakes import (
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REFRESHED_TOKEN,
    TH_ALL_SCOPES,
    TH_BASIC,
    TH_PUBLISH,
    TH_USER_ID,
    FakeClock,
    FakeThreads,
    InMemoryCredentialStore,
    StubThreadsGateway,
)

DAY = timedelta(days=1).total_seconds()


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _connect(client: TestClient, account_id: int) -> None:
    """Connect through the fake Threads API even when the stub is installed."""
    state = _app(client).state
    current = state.threads_gateway
    state.threads_gateway = getattr(state, "real_threads_gateway", current)
    try:
        connect_threads(client, account_id)
    finally:
        state.threads_gateway = current


@pytest.fixture
def connected(threads_client: TestClient) -> tuple[int, dict[str, Any]]:
    project_id, account = create_threads_account(threads_client)
    _connect(threads_client, account["id"])
    return project_id, account


@pytest.fixture
def stub(threads_client: TestClient, fake_clock: FakeClock) -> StubThreadsGateway:
    gateway = StubThreadsGateway(fake_clock)
    state = _app(threads_client).state
    state.real_threads_gateway = state.threads_gateway
    state.threads_gateway = gateway
    return gateway


def _verify(client: TestClient, account_id: int) -> Any:
    return client.post(f"/api/accounts/{account_id}/threads-connection/verify")


def _row(db_path: Path) -> dict[str, Any]:
    (row,) = threads_rows(db_path)
    return row


def _secret(store: InMemoryCredentialStore, db_path: Path) -> dict[str, Any]:
    secret: dict[str, Any] = json.loads(store.secrets[_row(db_path)["credential_ref"]])
    return secret


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_verify_updates_public_data(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, account = connected
    secret_before = _secret(threads_credential_store, db_path)
    fake_clock.advance(3600)
    stub.identity = ThreadsIdentity(TH_USER_ID, "renamed", "Renamed", None)
    later = fake_clock.now() + timedelta(days=80)
    stub.debug_info = ThreadsTokenInfo(
        True, TH_USER_ID, frozenset(TH_ALL_SCOPES), later
    )
    writes: list[str] = []
    original_set = threads_credential_store.set

    def recording_set(ref: str, value: str) -> None:
        writes.append(ref)
        original_set(ref, value)

    monkeypatch.setattr(threads_credential_store, "set", recording_set)

    response = _verify(threads_client, account["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "connected"
    assert body["identity"] == {
        "threads_user_id": TH_USER_ID,
        "username": "renamed",
        "display_name": "Renamed",
        "profile_picture_url": None,
    }
    assert body["last_verified_at"] == _iso(fake_clock.now())
    assert body["data_access_expires_at"] == _iso(later)
    assert stub.calls == ["debug", "me"]
    # Unchanged confirmed scopes: the secret is not rewritten.
    assert writes == []
    assert _secret(threads_credential_store, db_path) == secret_before


def test_verify_rewrites_only_changed_scopes(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    before = _secret(threads_credential_store, db_path)
    scopes = frozenset({*TH_ALL_SCOPES, "threads_read_replies"})
    stub.debug_info = ThreadsTokenInfo(True, TH_USER_ID, scopes, None)

    assert _verify(threads_client, account["id"]).status_code == 200

    after = _secret(threads_credential_store, db_path)
    assert after["scopes"] == sorted(scopes)
    for field in ("access_token", "token_obtained_at", "expires_at"):
        assert after[field] == before[field]


def test_failed_scopes_write_is_an_error_without_state_change(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    secret_before = _secret(threads_credential_store, db_path)
    row_before = _row(db_path)
    stub.debug_info = ThreadsTokenInfo(
        True, TH_USER_ID, frozenset({*TH_ALL_SCOPES, "threads_read_replies"}), None
    )
    threads_credential_store.fail_on = {"set"}
    fake_clock.advance(3600)

    response = _verify(threads_client, account["id"])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "credential_store_unavailable"
    assert _secret(threads_credential_store, db_path) == secret_before
    row = _row(db_path)
    assert row["status"] == "connected"
    assert row["last_verified_at"] == row_before["last_verified_at"]
    assert row["data_access_expires_at"] == row_before["data_access_expires_at"]


def test_missing_scope_does_not_depend_on_writing_the_secret(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    stub.debug_info = ThreadsTokenInfo(True, TH_USER_ID, frozenset({TH_BASIC}), None)
    threads_credential_store.fail_on = {"set"}

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_reconnect_required"
    assert _row(db_path)["status"] == "reconnect_required"


def test_verify_refreshes_a_token_inside_the_window(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    fake_clock.advance(54 * DAY)

    response = _verify(threads_client, account["id"])

    assert response.status_code == 200
    # Refresh, inspection of the renewed token, then Verify's own checks.
    assert stub.calls == ["refresh", "debug", "debug", "me"]


def test_verify_without_threads_app_config(
    threads_client: TestClient,
    threads_app_file: Path,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    threads_app_file.unlink()
    fake_clock.advance(54 * DAY)

    response = _verify(threads_client, account["id"])

    assert response.status_code == 200
    assert response.json()["oauth_configured"] is False


@pytest.mark.parametrize("source", ["debug", "me"])
def test_identity_mismatch(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    source: str,
) -> None:
    _, account = connected
    if source == "debug":
        stub.debug_info = ThreadsTokenInfo(
            True, "other-user", frozenset(TH_ALL_SCOPES), None
        )
    else:
        stub.identity = ThreadsIdentity("other-user", "someone.else")

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_identity_mismatch"
    row = _row(db_path)
    assert row["status"] == "reconnect_required"
    assert row["threads_user_id"] == TH_USER_ID
    assert row["username"] == "cyber.studio"


@pytest.mark.parametrize(
    ("scopes", "missing"),
    [({TH_BASIC}, TH_PUBLISH), ({TH_PUBLISH}, TH_BASIC)],
)
def test_scope_withdrawn(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    scopes: set[str],
    missing: str,
) -> None:
    _, account = connected
    stub.debug_info = ThreadsTokenInfo(True, TH_USER_ID, frozenset(scopes), None)

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "threads_reconnect_required"
    assert missing in error["message"]
    assert "permission" in error["message"]
    row = _row(db_path)
    assert row["status"] == "reconnect_required"
    assert row["username"] == "cyber.studio"


@pytest.mark.parametrize("permission", [TH_PUBLISH, None])
def test_permission_denied_by_meta(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    permission: str | None,
) -> None:
    _, account = connected
    stub.debug_error = ThreadsPermissionDenied(permission)

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "threads_reconnect_required"
    if permission:
        assert permission in error["message"]
    assert _row(db_path)["status"] == "reconnect_required"


@pytest.mark.parametrize("source", ["invalid_token", "is_valid_false"])
def test_token_rejected(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    source: str,
) -> None:
    _, account = connected
    if source == "invalid_token":
        stub.me_error = ThreadsTokenInvalid()
    else:
        stub.debug_info = ThreadsTokenInfo(
            False, TH_USER_ID, frozenset(TH_ALL_SCOPES), None
        )

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_reconnect_required"
    assert _row(db_path)["status"] == "reconnect_required"


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ThreadsUnavailable(), 503, "threads_unavailable"),
        (ThreadsUnexpectedResponse(), 502, "threads_unexpected_response"),
        (ThreadsRejected(), 502, "threads_unexpected_response"),
    ],
)
@pytest.mark.parametrize("source", ["debug", "me"])
def test_failures_without_state_change(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    failure: Exception,
    status: int,
    code: str,
    source: str,
) -> None:
    _, account = connected
    setattr(stub, f"{source}_error", failure)
    before = _row(db_path)

    response = _verify(threads_client, account["id"])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert _row(db_path) == before


def test_verify_is_read_only_towards_threads(
    threads_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    connected: tuple[int, dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Against the fake Threads API: only the documented endpoints are requested."""
    _, account = connected
    fake_threads.requests.clear()
    fake_clock.advance(54 * DAY)

    with caplog.at_level(logging.INFO):
        response = _verify(threads_client, account["id"])

    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    requested = [(r.method, r.url.split("?")[0]) for r in fake_threads.requests]
    assert requested == [
        ("GET", "https://graph.threads.net/refresh_access_token"),
        ("GET", "https://graph.threads.net/v1.0/debug_token"),
        ("GET", "https://graph.threads.net/v1.0/debug_token"),
        ("GET", "https://graph.threads.net/v1.0/me"),
    ]
    for record in caplog.records:
        message = record.getMessage()
        assert FAKE_TH_LONG_TOKEN not in message
        assert FAKE_TH_REFRESHED_TOKEN not in message


def test_reconnect_required_is_not_verified(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    run_sql(db_path, "UPDATE threads_connections SET status = 'reconnect_required'")

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_reconnect_required"
    assert stub.calls == []
    assert _row(db_path)["status"] == "reconnect_required"


def test_not_connected(threads_client: TestClient, stub: StubThreadsGateway) -> None:
    _, account = create_threads_account(threads_client)

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_not_connected"


@pytest.mark.parametrize(
    ("inactive", "code"),
    [
        (("account",), "account_inactive"),
        (("project",), "project_inactive"),
        (("account", "project"), "project_inactive"),
    ],
)
@pytest.mark.parametrize("connection_state", ["connected", "reconnect_required", None])
def test_inactive_precedence(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    db_path: Path,
    inactive: tuple[str, ...],
    code: str,
    connection_state: str | None,
) -> None:
    project_id, account = create_threads_account(threads_client)
    if connection_state is not None:
        _connect(threads_client, account["id"])
        run_sql(db_path, "UPDATE threads_connections SET status = ?", connection_state)
    if "account" in inactive:
        threads_client.patch(
            f"/api/accounts/{account['id']}", json={"is_active": False}
        )
    if "project" in inactive:
        threads_client.patch(f"/api/projects/{project_id}", json={"is_active": False})
    threads_credential_store.unavailable = True  # any access would answer 503
    stub.calls.clear()

    response = _verify(threads_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert stub.calls == []


def test_other_platform_takes_precedence_over_inactive(
    threads_client: TestClient, stub: StubThreadsGateway
) -> None:
    project = create_project(threads_client, "Cyber")
    instagram = create_account(threads_client, project["id"], "instagram", "cyber")
    threads_client.patch(f"/api/accounts/{instagram['id']}", json={"is_active": False})

    response = _verify(threads_client, instagram["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_not_supported"


def test_unknown_account(threads_client: TestClient, stub: StubThreadsGateway) -> None:
    assert _verify(threads_client, 999).status_code == 404


def test_data_access_expiry_is_read_as_official_utc(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    official = datetime(2027, 3, 1, 12, tzinfo=UTC)
    stub.debug_info = ThreadsTokenInfo(
        True, TH_USER_ID, frozenset(TH_ALL_SCOPES), official
    )

    _verify(threads_client, account["id"])

    assert get_threads_connection(threads_client, account["id"])[
        "data_access_expires_at"
    ] == _iso(official)
