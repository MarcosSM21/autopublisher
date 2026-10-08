"""Disconnecting an Instagram account (US3): local credentials only, never Meta."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    complete_instagram,
    connect_instagram,
    create_instagram_account,
    create_publications,
    get_instagram_connection,
    import_one,
    instagram_rows,
    make_image,
    redirect_url_for,
    run_sql,
    start_instagram_authorization,
)
from tests.fakes import FakeMeta, InMemoryCredentialStore


def _disconnect(client: TestClient, account_id: int) -> tuple[int, Any]:
    response = client.post(
        f"/api/accounts/{account_id}/instagram-connection/disconnect"
    )
    return response.status_code, response.json()


@pytest.mark.parametrize("status", ["connected", "reconnect_required"])
def test_disconnect_deletes_secret_then_row(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    content = import_one(instagram_client, project_id, "a.png", make_image())
    publication = create_publications(
        instagram_client, content["content"]["id"], [account["id"]]
    )[0]
    connect_instagram(instagram_client, account["id"])
    run_sql(db_path, "UPDATE instagram_connections SET status = ?", status)
    requests_before = len(fake_meta.requests)
    rows_when_deleting: list[int] = []
    original_delete = instagram_credential_store.delete

    def delete(ref: str) -> None:
        rows_when_deleting.append(len(instagram_rows(db_path)))
        original_delete(ref)

    monkeypatch.setattr(instagram_credential_store, "delete", delete)

    code, body = _disconnect(instagram_client, account["id"])

    assert code == 200
    assert body["status"] == "not_connected"
    assert body["identity"] is None
    assert rows_when_deleting == [1]  # the secret goes first, then the row
    assert instagram_credential_store.secrets == {}
    assert instagram_rows(db_path) == []
    assert len(fake_meta.requests) == requests_before  # Meta is never contacted
    accounts = instagram_client.get(f"/api/projects/{project_id}/accounts").json()
    assert accounts == [account]
    assert instagram_client.get(f"/api/publications/{publication['id']}").json() == (
        publication
    )


def test_disconnect_is_idempotent(instagram_client: TestClient) -> None:
    _, account = create_instagram_account(instagram_client)

    for _ in range(2):
        code, body = _disconnect(instagram_client, account["id"])
        assert code == 200
        assert body["status"] == "not_connected"


def test_disconnect_with_inactive_account_and_project(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    instagram_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})
    instagram_client.patch(f"/api/projects/{project_id}", json={"is_active": False})

    code, body = _disconnect(instagram_client, account["id"])

    assert code == 200
    assert body["status"] == "not_connected"
    assert instagram_credential_store.secrets == {}


def test_disconnect_keeps_connection_when_store_is_unavailable(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connection = connect_instagram(instagram_client, account["id"])
    rows = instagram_rows(db_path)
    instagram_credential_store.fail_on = {"delete"}

    code, body = _disconnect(instagram_client, account["id"])

    assert code == 503
    assert body["error"]["code"] == "credential_store_unavailable"
    assert instagram_rows(db_path) == rows
    assert len(instagram_credential_store.secrets) == 1
    assert get_instagram_connection(instagram_client, account["id"]) == connection

    instagram_credential_store.fail_on = set()
    assert _disconnect(instagram_client, account["id"])[0] == 200


def test_disconnect_expires_pending_attempts(instagram_client: TestClient) -> None:
    _, account = create_instagram_account(instagram_client)
    attempt_id, state = start_instagram_authorization(instagram_client, account["id"])

    _disconnect(instagram_client, account["id"])

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "instagram_oauth_attempt_expired"
