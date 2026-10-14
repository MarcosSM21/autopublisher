"""Inactive projects and accounts (US7, research §18): only status, cancel, Disconnect
and remove-local are allowed; active operations are rejected before any request to
TikTok or the secure storage."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    connect_tiktok,
    create_tiktok_account,
    get_tiktok_connection,
    poll_tiktok_attempt,
    start_tiktok_authorization,
    tiktok_callback,
    tiktok_rows,
)
from tests.fakes import FakeTikTok, InMemoryCredentialStore

ENTITIES = ["account", "project"]


@pytest.fixture
def connected(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> tuple[int, dict[str, Any]]:
    project_id, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    fake_tiktok.requests.clear()
    return project_id, account


def _deactivate(
    client: TestClient, entity: str, project_id: int, account_id: int
) -> None:
    if entity == "account":
        response = client.patch(
            f"/api/accounts/{account_id}", json={"is_active": False}
        )
    else:
        response = client.patch(
            f"/api/projects/{project_id}", json={"is_active": False}
        )
    assert response.status_code == 200, response.text


def _error(response: Any, code: str) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("entity", ENTITIES)
def test_deactivating_keeps_the_connection_and_its_status(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    entity: str,
) -> None:
    project_id, account = connected
    rows_before = tiktok_rows(db_path)
    secrets_before = dict(tiktok_credential_store.secrets)

    _deactivate(tiktok_client, entity, project_id, account["id"])

    assert get_tiktok_connection(tiktok_client, account["id"])["status"] == "connected"
    assert tiktok_rows(db_path) == rows_before
    assert tiktok_credential_store.secrets == secrets_before
    assert fake_tiktok.requests == []  # never revoked


@pytest.mark.parametrize("entity", ENTITIES)
@pytest.mark.parametrize("operation", ["authorize", "verify"])
def test_active_operations_are_rejected_first(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    connected: tuple[int, dict[str, Any]],
    entity: str,
    operation: str,
) -> None:
    project_id, account = connected
    _deactivate(tiktok_client, entity, project_id, account["id"])
    # Any access to the store would fail differently.
    tiktok_credential_store.unavailable = True

    response = tiktok_client.post(
        f"/api/accounts/{account['id']}/tiktok-connection/{operation}"
    )

    _error(response, f"{entity}_inactive")
    assert fake_tiktok.requests == []


@pytest.mark.parametrize("entity", ENTITIES)
def test_callback_after_deactivation_fails_without_exchanging(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    entity: str,
) -> None:
    project_id, account = create_tiktok_account(tiktok_client)
    attempt_id, state, _ = start_tiktok_authorization(
        tiktok_client, account["id"], fake_tiktok
    )
    _deactivate(tiktok_client, entity, project_id, account["id"])

    response = tiktok_callback(tiktok_client, state)

    assert response.headers["location"].endswith("outcome=failed")
    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == f"{entity}_inactive"
    assert fake_tiktok.requests == []
    assert tiktok_rows(db_path) == []


@pytest.mark.parametrize("entity", ENTITIES)
def test_confirm_is_rejected_and_the_pending_credential_discarded(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    entity: str,
) -> None:
    project_id, account = connected
    fake_tiktok.open_id = "-000fake-tt-other-open-id-b52e90"
    attempt_id, state, _ = start_tiktok_authorization(
        tiktok_client, account["id"], fake_tiktok
    )
    tiktok_callback(tiktok_client, state)
    rows_before = tiktok_rows(db_path)
    fake_tiktok.requests.clear()
    _deactivate(tiktok_client, entity, project_id, account["id"])

    response = tiktok_client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/confirm")

    _error(response, f"{entity}_inactive")
    assert fake_tiktok.calls() == ["revoke"]
    assert tiktok_rows(db_path) == rows_before


@pytest.mark.parametrize("entity", ENTITIES)
def test_cancel_is_allowed(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    connected: tuple[int, dict[str, Any]],
    entity: str,
) -> None:
    project_id, account = connected
    attempt_id, _, _ = start_tiktok_authorization(
        tiktok_client, account["id"], fake_tiktok
    )
    _deactivate(tiktok_client, entity, project_id, account["id"])

    response = tiktok_client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"


@pytest.mark.parametrize("entity", ENTITIES)
@pytest.mark.parametrize(
    ("route", "revocation"),
    [("disconnect", "revoked"), ("remove-local", "not_revoked")],
)
def test_disconnect_and_local_removal_are_allowed(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    entity: str,
    route: str,
    revocation: str,
) -> None:
    project_id, account = connected
    _deactivate(tiktok_client, entity, project_id, account["id"])

    response = tiktok_client.post(
        f"/api/accounts/{account['id']}/tiktok-connection/{route}"
    )

    assert response.status_code == 200, response.text
    assert response.json()["revocation"] == revocation
    assert tiktok_rows(db_path) == []
    assert tiktok_credential_store.secrets == {}
