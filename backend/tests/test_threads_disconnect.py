"""Disconnecting a Threads account (US3): local credentials only, never Meta."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    complete_threads,
    connect_threads,
    create_publications,
    create_threads_account,
    get_threads_connection,
    import_one,
    make_image,
    run_sql,
    start_threads_authorization,
    threads_redirect_url_for,
    threads_rows,
)
from tests.fakes import FakeThreads, InMemoryCredentialStore


def _disconnect(client: TestClient, account_id: int) -> tuple[int, Any]:
    response = client.post(f"/api/accounts/{account_id}/threads-connection/disconnect")
    return response.status_code, response.json()


@pytest.mark.parametrize("status", ["connected", "reconnect_required"])
def test_disconnect_deletes_secret_then_row(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    project_id, account = create_threads_account(threads_client)
    content = import_one(threads_client, project_id, "a.png", make_image())
    publication = create_publications(
        threads_client, content["content"]["id"], [account["id"]]
    )[0]
    connect_threads(threads_client, account["id"])
    run_sql(db_path, "UPDATE threads_connections SET status = ?", status)
    requests_before = len(fake_threads.requests)
    rows_when_deleting: list[int] = []
    original_delete = threads_credential_store.delete

    def delete(ref: str) -> None:
        rows_when_deleting.append(len(threads_rows(db_path)))
        original_delete(ref)

    monkeypatch.setattr(threads_credential_store, "delete", delete)

    code, body = _disconnect(threads_client, account["id"])

    assert code == 200
    assert body["status"] == "not_connected"
    assert body["identity"] is None
    assert rows_when_deleting == [1]  # the secret goes first, then the row
    assert threads_credential_store.secrets == {}
    assert threads_rows(db_path) == []
    assert len(fake_threads.requests) == requests_before  # Meta is never contacted
    accounts = threads_client.get(f"/api/projects/{project_id}/accounts").json()
    assert accounts == [account]
    assert threads_client.get(f"/api/publications/{publication['id']}").json() == (
        publication
    )


def test_disconnect_is_idempotent(
    threads_client: TestClient, fake_threads: FakeThreads
) -> None:
    _, account = create_threads_account(threads_client)

    for _ in range(2):
        code, body = _disconnect(threads_client, account["id"])
        assert code == 200
        assert body["status"] == "not_connected"
    assert fake_threads.requests == []


def test_disconnect_with_inactive_account_and_project(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
) -> None:
    project_id, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    threads_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})
    threads_client.patch(f"/api/projects/{project_id}", json={"is_active": False})

    code, body = _disconnect(threads_client, account["id"])

    assert code == 200
    assert body["status"] == "not_connected"
    assert threads_credential_store.secrets == {}


def test_disconnect_keeps_connection_when_store_is_unavailable(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])
    rows = threads_rows(db_path)
    threads_credential_store.fail_on = {"delete"}

    code, body = _disconnect(threads_client, account["id"])

    assert code == 503
    assert body["error"]["code"] == "credential_store_unavailable"
    assert threads_rows(db_path) == rows
    assert len(threads_credential_store.secrets) == 1
    assert get_threads_connection(threads_client, account["id"]) == connection

    threads_credential_store.fail_on = set()
    assert _disconnect(threads_client, account["id"])[0] == 200


def test_disconnect_expires_pending_attempts(threads_client: TestClient) -> None:
    _, account = create_threads_account(threads_client)
    attempt_id, state = start_threads_authorization(threads_client, account["id"])

    _disconnect(threads_client, account["id"])

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "threads_oauth_attempt_expired"
