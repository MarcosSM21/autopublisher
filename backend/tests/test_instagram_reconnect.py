"""Reconnecting and protecting against the wrong Instagram account (US5, US6)."""

import json
from datetime import timedelta
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
    run_sql,
    start_instagram_authorization,
)
from tests.fakes import (
    FAKE_IG_LONG_TOKEN,
    FakeClock,
    FakeMeta,
    InMemoryCredentialStore,
)

OTHER = {"user_id": "17841400000000002", "id": "9002", "username": "new.account"}


def _confirm(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/instagram/oauth/attempts/{attempt_id}/confirm")


def _cancel(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/instagram/oauth/attempts/{attempt_id}/cancel")


def _reconnect(
    client: TestClient, fake_meta: FakeMeta, account_id: int, **identity: Any
) -> tuple[str, Any]:
    fake_meta.set_identity(**identity)
    attempt_id, state = start_instagram_authorization(client, account_id)
    return attempt_id, complete_instagram(client, attempt_id, redirect_url_for(state))


@pytest.mark.parametrize("status", ["connected", "reconnect_required"])
def test_reconnect_same_account_replaces_credentials(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
    status: str,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    (old_row,) = instagram_rows(db_path)
    run_sql(db_path, "UPDATE instagram_connections SET status = ?", status)
    fake_clock.advance(timedelta(hours=1).total_seconds())

    _, response = _reconnect(
        instagram_client,
        fake_meta,
        account["id"],
        username="renamed.studio",
        account_type="Media_Creator",
        profile_picture_url=None,
    )

    assert response.status_code == 200, response.text
    attempt = response.json()
    assert attempt["status"] == "completed"
    connection = attempt["connection"]
    assert connection["status"] == "connected"
    assert connection["identity"] == {
        "instagram_user_id": "17841400000000001",
        "username": "renamed.studio",
        "account_type": "MEDIA_CREATOR",
        "profile_picture_url": None,
    }
    (row,) = instagram_rows(db_path)
    assert row["credential_ref"] != old_row["credential_ref"]
    assert list(instagram_credential_store.secrets) == [row["credential_ref"]]


def test_different_account_waits_for_confirmation(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connection = connect_instagram(instagram_client, account["id"])
    secrets_before = dict(instagram_credential_store.secrets)
    rows_before = instagram_rows(db_path)

    _, response = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)

    assert response.status_code == 200
    attempt = response.json()
    assert attempt["status"] == "awaiting_confirmation"
    assert attempt["connection"] is None
    assert attempt["current_identity"] == connection["identity"]
    assert attempt["new_identity"] == {
        "instagram_user_id": "17841400000000002",
        "username": "new.account",
        "account_type": "BUSINESS",
        "profile_picture_url": "https://scontent.example.com/cyber.jpg",
    }
    assert FAKE_IG_LONG_TOKEN not in json.dumps(attempt)
    assert instagram_credential_store.secrets == secrets_before
    assert instagram_rows(db_path) == rows_before
    assert get_instagram_connection(instagram_client, account["id"]) == connection


def test_confirm_replaces_identity(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    (old_row,) = instagram_rows(db_path)
    attempt_id, _ = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)

    response = _confirm(instagram_client, attempt_id)

    assert response.status_code == 200, response.text
    attempt = response.json()
    assert attempt["status"] == "completed"
    assert attempt["connection"]["identity"]["instagram_user_id"] == OTHER["user_id"]
    assert attempt["connection"]["identity"]["username"] == "new.account"
    (row,) = instagram_rows(db_path)
    assert row["instagram_user_id"] == OTHER["user_id"]
    assert old_row["credential_ref"] not in instagram_credential_store.secrets
    assert list(instagram_credential_store.secrets) == [row["credential_ref"]]

    again = _confirm(instagram_client, attempt_id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "instagram_oauth_attempt_not_confirmable"


def test_cancel_keeps_previous_connection(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connection = connect_instagram(instagram_client, account["id"])
    secrets_before = dict(instagram_credential_store.secrets)
    attempt_id, _ = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)

    response = _cancel(instagram_client, attempt_id)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _cancel(instagram_client, attempt_id).json()["status"] == "cancelled"
    assert instagram_credential_store.secrets == secrets_before
    assert get_instagram_connection(instagram_client, account["id"]) == connection
    assert _confirm(instagram_client, attempt_id).status_code == 409
    app = instagram_client.app
    attempt = app.state.instagram_attempts.get(attempt_id)  # type: ignore[attr-defined]
    assert attempt.pending_credentials is None


def test_cancel_pending_attempt(instagram_client: TestClient) -> None:
    _, account = create_instagram_account(instagram_client)
    attempt_id, state = start_instagram_authorization(instagram_client, account["id"])

    assert _cancel(instagram_client, attempt_id).json()["status"] == "cancelled"
    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))
    assert response.json()["error"]["code"] == "instagram_oauth_state_invalid"


def test_expiry_while_awaiting_confirmation(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connection = connect_instagram(instagram_client, account["id"])
    secrets_before = dict(instagram_credential_store.secrets)
    attempt_id, _ = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)
    fake_clock.advance(timedelta(minutes=10).total_seconds())

    response = _confirm(instagram_client, attempt_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "instagram_oauth_attempt_not_confirmable"
    assert instagram_credential_store.secrets == secrets_before
    assert get_instagram_connection(instagram_client, account["id"]) == connection


def test_connection_changed_meanwhile(
    instagram_client: TestClient, fake_meta: FakeMeta
) -> None:
    _, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    attempt_id, _ = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)
    instagram_client.post(
        f"/api/accounts/{account['id']}/instagram-connection/disconnect"
    )

    response = _confirm(instagram_client, attempt_id)

    assert response.status_code in (409,)
    # Disconnecting expires the attempt, so it is no longer confirmable.
    assert response.json()["error"]["code"] == "instagram_oauth_attempt_not_confirmable"


def test_connection_replaced_meanwhile(
    instagram_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    _, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    attempt_id, _ = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)
    run_sql(db_path, "UPDATE instagram_connections SET instagram_user_id = '1784_X'")

    response = _confirm(instagram_client, attempt_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "instagram_connection_changed"


def test_unknown_attempt(instagram_client: TestClient) -> None:
    for response in (
        _confirm(instagram_client, "missing"),
        _cancel(instagram_client, "missing"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "instagram_oauth_attempt_not_found"


@pytest.mark.parametrize(
    ("entity", "code"),
    [("account", "account_inactive"), ("project", "project_inactive")],
)
def test_deactivated_before_confirm(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    entity: str,
    code: str,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    secrets_before = dict(instagram_credential_store.secrets)
    attempt_id, _ = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)
    path = (
        f"/api/accounts/{account['id']}"
        if entity == "account"
        else f"/api/projects/{project_id}"
    )
    instagram_client.patch(path, json={"is_active": False})

    response = _confirm(instagram_client, attempt_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert instagram_credential_store.secrets == secrets_before


def test_confirm_respects_project_uniqueness(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
) -> None:
    project_id, account = create_instagram_account(instagram_client, handle="first")
    connect_instagram(instagram_client, account["id"])
    attempt_id, _ = _reconnect(instagram_client, fake_meta, account["id"], **OTHER)
    # Meanwhile another account of the project links the new Instagram account.
    _, holder = create_instagram_account(
        instagram_client, handle="holder", project_id=project_id
    )
    connect_instagram(instagram_client, holder["id"], fake_meta, **OTHER)
    secrets_before = dict(instagram_credential_store.secrets)

    response = _confirm(instagram_client, attempt_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "instagram_account_already_connected"
    assert "@holder" in error["message"]
    assert instagram_credential_store.secrets == secrets_before
    assert len(instagram_rows(db_path)) == 2
