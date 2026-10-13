"""Inactive projects and accounts (US7): visible state, no new authorizations, no
confirmation and no Verify; cancelling and Disconnect allowed; deactivating never
disconnects."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
from tests.fakes import FakeThreads, InMemoryCredentialStore


def _deactivate(
    client: TestClient, project_id: int, account_id: int, entities: tuple[str, ...]
) -> None:
    if "account" in entities:
        client.patch(f"/api/accounts/{account_id}", json={"is_active": False})
    if "project" in entities:
        client.patch(f"/api/projects/{project_id}", json={"is_active": False})


INACTIVE_CASES = [
    (("account",), "account_inactive"),
    (("project",), "project_inactive"),
    (("account", "project"), "project_inactive"),
]


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
def test_state_visible_and_kept_when_deactivated(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    entities: tuple[str, ...],
    code: str,
) -> None:
    project_id, account = create_threads_account(threads_client)
    connection = connect_threads(threads_client, account["id"])
    secrets = dict(threads_credential_store.secrets)
    rows = threads_rows(db_path)

    _deactivate(threads_client, project_id, account["id"], entities)

    assert get_threads_connection(threads_client, account["id"]) == connection
    assert threads_credential_store.secrets == secrets
    assert threads_rows(db_path) == rows


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
def test_authorize_rejected(
    threads_client: TestClient,
    fake_threads: FakeThreads,
    entities: tuple[str, ...],
    code: str,
) -> None:
    project_id, account = create_threads_account(threads_client)
    _deactivate(threads_client, project_id, account["id"], entities)

    response = threads_client.post(
        f"/api/accounts/{account['id']}/threads-connection/authorize"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert fake_threads.requests == []


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
@pytest.mark.parametrize("previously_connected", [False, True])
def test_deactivated_between_authorize_and_complete(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    entities: tuple[str, ...],
    code: str,
    previously_connected: bool,
) -> None:
    project_id, account = create_threads_account(threads_client)
    previous: dict[str, Any] | None = None
    if previously_connected:
        previous = connect_threads(threads_client, account["id"])
    secrets = dict(threads_credential_store.secrets)
    rows = threads_rows(db_path)
    attempt_id, state = start_threads_authorization(threads_client, account["id"])
    requests_before = len(fake_threads.requests)
    _deactivate(threads_client, project_id, account["id"], entities)

    response = complete_threads(
        threads_client, attempt_id, threads_redirect_url_for(state)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert len(fake_threads.requests) == requests_before  # Meta is not contacted
    assert threads_credential_store.secrets == secrets
    assert threads_rows(db_path) == rows
    connection = get_threads_connection(threads_client, account["id"])
    if previous is None:
        assert connection["status"] == "not_connected"
    else:
        assert connection == previous


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
def test_cancel_allowed_when_inactive(
    threads_client: TestClient, entities: tuple[str, ...], code: str
) -> None:
    project_id, account = create_threads_account(threads_client)
    attempt_id, _ = start_threads_authorization(threads_client, account["id"])
    _deactivate(threads_client, project_id, account["id"], entities)

    response = threads_client.post(f"/api/threads/oauth/attempts/{attempt_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
@pytest.mark.parametrize("connection_state", ["connected", "reconnect_required", None])
def test_verify_rejected_without_contacting_meta(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    db_path: Path,
    entities: tuple[str, ...],
    code: str,
    connection_state: str | None,
) -> None:
    project_id, account = create_threads_account(threads_client)
    if connection_state is not None:
        connect_threads(threads_client, account["id"])
        if connection_state == "reconnect_required":
            run_sql(
                db_path, "UPDATE threads_connections SET status = ?", connection_state
            )
    _deactivate(threads_client, project_id, account["id"], entities)
    requests_before = len(fake_threads.requests)
    threads_credential_store.unavailable = True  # any access would answer 503

    response = threads_client.post(
        f"/api/accounts/{account['id']}/threads-connection/verify"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert len(fake_threads.requests) == requests_before


def test_disconnect_allowed_when_inactive(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
) -> None:
    project_id, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    _deactivate(threads_client, project_id, account["id"], ("account", "project"))

    response = threads_client.post(
        f"/api/accounts/{account['id']}/threads-connection/disconnect"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_connected"
    assert threads_credential_store.secrets == {}
