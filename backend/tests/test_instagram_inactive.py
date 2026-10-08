"""Inactive projects and accounts (US7): visible state, no new authorizations and no
Verify; Disconnect allowed; deactivating never disconnects."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    complete_instagram,
    connect_instagram,
    create_instagram_account,
    get_instagram_connection,
    instagram_rows,
    redirect_url_for,
    start_instagram_authorization,
)
from tests.fakes import FakeMeta, InMemoryCredentialStore


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
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    db_path: Path,
    entities: tuple[str, ...],
    code: str,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    connection = connect_instagram(instagram_client, account["id"])
    secrets = dict(instagram_credential_store.secrets)
    rows = instagram_rows(db_path)

    _deactivate(instagram_client, project_id, account["id"], entities)

    assert get_instagram_connection(instagram_client, account["id"]) == connection
    assert instagram_credential_store.secrets == secrets
    assert instagram_rows(db_path) == rows


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
def test_authorize_rejected(
    instagram_client: TestClient, entities: tuple[str, ...], code: str
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    _deactivate(instagram_client, project_id, account["id"], entities)

    response = instagram_client.post(
        f"/api/accounts/{account['id']}/instagram-connection/authorize"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
@pytest.mark.parametrize("previously_connected", [False, True])
def test_deactivated_between_authorize_and_complete(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
    entities: tuple[str, ...],
    code: str,
    previously_connected: bool,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    previous: dict[str, Any] | None = None
    if previously_connected:
        previous = connect_instagram(instagram_client, account["id"])
    secrets = dict(instagram_credential_store.secrets)
    rows = instagram_rows(db_path)
    attempt_id, state = start_instagram_authorization(instagram_client, account["id"])
    requests_before = len(fake_meta.requests)
    _deactivate(instagram_client, project_id, account["id"], entities)

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert len(fake_meta.requests) == requests_before  # Meta is not contacted
    assert instagram_credential_store.secrets == secrets
    assert instagram_rows(db_path) == rows
    connection = get_instagram_connection(instagram_client, account["id"])
    if previous is None:
        assert connection["status"] == "not_connected"
    else:
        assert connection == previous


@pytest.mark.parametrize(("entities", "code"), INACTIVE_CASES)
def test_verify_rejected_without_contacting_meta(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    entities: tuple[str, ...],
    code: str,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    _deactivate(instagram_client, project_id, account["id"], entities)
    requests_before = len(fake_meta.requests)
    instagram_credential_store.unavailable = True

    response = instagram_client.post(
        f"/api/accounts/{account['id']}/instagram-connection/verify"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert len(fake_meta.requests) == requests_before


def test_disconnect_allowed_when_inactive(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    _deactivate(instagram_client, project_id, account["id"], ("account", "project"))

    response = instagram_client.post(
        f"/api/accounts/{account['id']}/instagram-connection/disconnect"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_connected"
    assert instagram_credential_store.secrets == {}
