"""Reconnecting and protecting against the wrong Threads account (US5, US6), including
the safe order between the secure store and SQLite (spec FR-029)."""

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import threads_connections
from app.threads_connections import get_valid_credentials
from tests.conftest import (
    complete_threads,
    connect_threads,
    create_threads_account,
    get_threads_connection,
    run_sql,
    start_threads_authorization,
    threads_redirect_url_for,
    threads_rows,
)
from tests.fakes import (
    FAKE_TH_LONG_TOKEN,
    FakeClock,
    FakeThreads,
    InMemoryCredentialStore,
    StubThreadsGateway,
)

OTHER = {"id": "25840000000000002", "username": "new.account", "name": "New"}


def _confirm(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/threads/oauth/attempts/{attempt_id}/confirm")


def _cancel(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/threads/oauth/attempts/{attempt_id}/cancel")


def _reconnect(
    client: TestClient, fake_threads: FakeThreads, account_id: int, **identity: Any
) -> tuple[str, Any]:
    if identity:
        fake_threads.set_identity(**identity)
    attempt_id, state = start_threads_authorization(client, account_id)
    return attempt_id, complete_threads(
        client, attempt_id, threads_redirect_url_for(state)
    )


def _failing_commit(session: Any) -> None:
    raise RuntimeError("database is locked")


@pytest.mark.parametrize("status", ["connected", "reconnect_required"])
def test_reconnect_same_account_replaces_credentials(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
    status: str,
) -> None:
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    (old_row,) = threads_rows(db_path)
    run_sql(db_path, "UPDATE threads_connections SET status = ?", status)
    fake_clock.advance(timedelta(hours=1).total_seconds())

    _, response = _reconnect(
        threads_client,
        fake_threads,
        account["id"],
        username="renamed.studio",
        name=None,
        threads_profile_picture_url=None,
    )

    assert response.status_code == 200, response.text
    attempt = response.json()
    assert attempt["status"] == "completed"
    connection = attempt["connection"]
    assert connection["status"] == "connected"
    assert connection["identity"] == {
        "threads_user_id": old_row["threads_user_id"],
        "username": "renamed.studio",
        "display_name": None,
        "profile_picture_url": None,
    }
    assert connection["token_obtained_at"] == fake_clock.now().isoformat().replace(
        "+00:00", "Z"
    )
    (row,) = threads_rows(db_path)
    assert row["credential_ref"] != old_row["credential_ref"]
    assert list(threads_credential_store.secrets) == [row["credential_ref"]]


def test_different_account_waits_for_confirmation(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    _, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])
    secrets_before = dict(threads_credential_store.secrets)
    rows_before = threads_rows(db_path)

    _, response = _reconnect(threads_client, fake_threads, account["id"], **OTHER)

    assert response.status_code == 200
    attempt = response.json()
    assert attempt["status"] == "awaiting_confirmation"
    assert attempt["connection"] is None
    assert attempt["current_identity"] == connection["identity"]
    assert attempt["new_identity"] == {
        "threads_user_id": OTHER["id"],
        "username": "new.account",
        "display_name": "New",
        "profile_picture_url": "https://scontent.example/th-pic.jpg",
    }
    assert FAKE_TH_LONG_TOKEN not in json.dumps(attempt)
    assert threads_credential_store.secrets == secrets_before
    assert threads_rows(db_path) == rows_before
    assert get_threads_connection(threads_client, account["id"]) == connection


def test_confirm_replaces_identity(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    (old_row,) = threads_rows(db_path)
    attempt_id, _ = _reconnect(threads_client, fake_threads, account["id"], **OTHER)

    response = _confirm(threads_client, attempt_id)

    assert response.status_code == 200, response.text
    attempt = response.json()
    assert attempt["status"] == "completed"
    assert attempt["connection"]["identity"]["threads_user_id"] == OTHER["id"]
    assert attempt["connection"]["identity"]["username"] == "new.account"
    (row,) = threads_rows(db_path)
    assert row["threads_user_id"] == OTHER["id"]
    assert old_row["credential_ref"] not in threads_credential_store.secrets
    assert list(threads_credential_store.secrets) == [row["credential_ref"]]

    again = _confirm(threads_client, attempt_id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "threads_oauth_attempt_not_confirmable"


def test_cancel_keeps_previous_connection(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
) -> None:
    _, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])
    secrets_before = dict(threads_credential_store.secrets)
    attempt_id, _ = _reconnect(threads_client, fake_threads, account["id"], **OTHER)

    response = _cancel(threads_client, attempt_id)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _cancel(threads_client, attempt_id).json()["status"] == "cancelled"
    assert threads_credential_store.secrets == secrets_before
    assert get_threads_connection(threads_client, account["id"]) == connection
    assert _confirm(threads_client, attempt_id).status_code == 409
    app = threads_client.app
    attempt = app.state.threads_attempts.get(attempt_id)  # type: ignore[attr-defined]
    assert attempt.pending_credentials is None


def test_cancel_pending_attempt(threads_client: TestClient) -> None:
    _, account = create_threads_account(threads_client)
    attempt_id, state = start_threads_authorization(threads_client, account["id"])

    assert _cancel(threads_client, attempt_id).json()["status"] == "cancelled"
    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )
    assert response.json()["error"]["code"] == "threads_oauth_state_invalid"


def test_expiry_while_awaiting_confirmation(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
) -> None:
    _, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])
    secrets_before = dict(threads_credential_store.secrets)
    attempt_id, _ = _reconnect(threads_client, fake_threads, account["id"], **OTHER)
    fake_clock.advance(timedelta(minutes=10).total_seconds())

    response = _confirm(threads_client, attempt_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_oauth_attempt_not_confirmable"
    assert threads_credential_store.secrets == secrets_before
    assert get_threads_connection(threads_client, account["id"]) == connection


def test_disconnect_while_awaiting_confirmation(
    threads_client: TestClient, fake_threads: FakeThreads
) -> None:
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    attempt_id, _ = _reconnect(threads_client, fake_threads, account["id"], **OTHER)
    threads_client.post(f"/api/accounts/{account['id']}/threads-connection/disconnect")

    response = _confirm(threads_client, attempt_id)

    # Disconnecting expires the attempt, so it is no longer confirmable.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_oauth_attempt_not_confirmable"


def test_connection_replaced_meanwhile(
    threads_client: TestClient, fake_threads: FakeThreads, db_path: Path
) -> None:
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    attempt_id, _ = _reconnect(threads_client, fake_threads, account["id"], **OTHER)
    run_sql(db_path, "UPDATE threads_connections SET threads_user_id = '2584_X'")

    response = _confirm(threads_client, attempt_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_connection_changed"


def test_unknown_attempt(threads_client: TestClient) -> None:
    for response in (
        _confirm(threads_client, "missing"),
        _cancel(threads_client, "missing"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "threads_oauth_attempt_not_found"


@pytest.mark.parametrize(
    ("entity", "code"),
    [("account", "account_inactive"), ("project", "project_inactive")],
)
def test_deactivated_before_confirm(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    entity: str,
    code: str,
) -> None:
    project_id, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    secrets_before = dict(threads_credential_store.secrets)
    attempt_id, _ = _reconnect(threads_client, fake_threads, account["id"], **OTHER)
    path = (
        f"/api/accounts/{account['id']}"
        if entity == "account"
        else f"/api/projects/{project_id}"
    )
    threads_client.patch(path, json={"is_active": False})

    response = _confirm(threads_client, attempt_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert threads_credential_store.secrets == secrets_before


def test_confirm_respects_project_uniqueness(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    project_id, account = create_threads_account(threads_client, handle="first")
    connect_threads(threads_client, account["id"])
    attempt_id, _ = _reconnect(threads_client, fake_threads, account["id"], **OTHER)
    # Meanwhile another account of the project links the new Threads account.
    _, holder = create_threads_account(
        threads_client, handle="holder", project_id=project_id
    )
    connect_threads(threads_client, holder["id"], fake_threads, **OTHER)
    secrets_before = dict(threads_credential_store.secrets)

    response = _confirm(threads_client, attempt_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "threads_account_already_connected"
    assert "@holder" in error["message"]
    assert threads_credential_store.secrets == secrets_before
    assert len(threads_rows(db_path)) == 2


# --- Safe order between the secure store and SQLite (FR-029) -------------------------


def _valid_token(client: TestClient, fake_clock: FakeClock, account_id: int) -> str:
    app = client.app
    assert isinstance(app, FastAPI)
    with app.state.session_factory() as session:
        token = get_valid_credentials(
            session,
            app.state.threads_credential_store,
            StubThreadsGateway(fake_clock),  # type: ignore[arg-type]
            account_id,
        )
    return token.access_token


@pytest.mark.parametrize("flow", ["reconnect", "confirm"])
def test_commit_failure_keeps_the_previous_connection(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flow: str,
) -> None:
    _, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])
    rows_before = threads_rows(db_path)
    secrets_before = dict(threads_credential_store.secrets)
    stored: list[str] = []
    original_set = threads_credential_store.set

    def recording_set(ref: str, value: str) -> None:
        stored.append(ref)
        original_set(ref, value)

    monkeypatch.setattr(threads_credential_store, "set", recording_set)
    if flow == "reconnect":
        monkeypatch.setattr(threads_connections, "_commit", _failing_commit)
        attempt_id, response = _reconnect(threads_client, fake_threads, account["id"])
    else:
        attempt_id, waiting = _reconnect(
            threads_client, fake_threads, account["id"], **OTHER
        )
        assert waiting.json()["status"] == "awaiting_confirmation"
        monkeypatch.setattr(threads_connections, "_commit", _failing_commit)
        response = _confirm(threads_client, attempt_id)

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert "locked" not in error["message"]
    assert FAKE_TH_LONG_TOKEN not in json.dumps(error)
    # The new secret was stored and then deleted; the previous one is untouched.
    assert len(stored) == 1
    assert stored[0] not in threads_credential_store.secrets
    assert threads_credential_store.secrets == secrets_before
    assert threads_rows(db_path) == rows_before
    monkeypatch.setattr(
        threads_connections, "_commit", lambda session: session.commit()
    )
    assert get_threads_connection(threads_client, account["id"]) == connection
    # The previous credential is still usable.
    assert _valid_token(threads_client, fake_clock, account["id"]) == FAKE_TH_LONG_TOKEN
    # The attempt finished as failed.
    app = threads_client.app
    attempt = app.state.threads_attempts.get(attempt_id)  # type: ignore[attr-defined]
    assert attempt.status == "failed"
    assert attempt.error["code"] == "internal_error"


def test_old_secret_deletion_failure_leaves_an_orphan(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    (old_row,) = threads_rows(db_path)
    threads_credential_store.fail_on = {"delete"}

    with caplog.at_level(logging.WARNING):
        _, response = _reconnect(threads_client, fake_threads, account["id"])

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    (row,) = threads_rows(db_path)
    assert row["credential_ref"] != old_row["credential_ref"]
    # The new credential is authoritative; the old entry is orphaned and logged.
    assert set(threads_credential_store.secrets) == {
        old_row["credential_ref"],
        row["credential_ref"],
    }
    assert "Could not delete stored Threads credentials" in caplog.text
    assert old_row["credential_ref"] not in caplog.text
