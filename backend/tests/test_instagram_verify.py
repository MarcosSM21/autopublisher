"""Verify connection (US4), on the gateway's semantic classification.

The route runs against `StubInstagramGateway`, so no test here depends on Meta's
error numbers.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.instagram_gateway import (
    MetaPermissionDenied,
    MetaRejected,
    MetaTokenInvalid,
    MetaUnavailable,
    MetaUnexpectedResponse,
)
from tests.conftest import (
    connect_instagram,
    create_account,
    create_instagram_account,
    create_project,
    get_instagram_connection,
    instagram_rows,
    run_sql,
)
from tests.fakes import (
    IG_BASIC,
    IG_PUBLISH,
    FakeClock,
    InMemoryCredentialStore,
    StubInstagramGateway,
)


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _connect(client: TestClient, account_id: int) -> None:
    """Connect through the fake-Meta gateway even when the stub is installed."""
    state = _app(client).state
    current = state.instagram_gateway
    state.instagram_gateway = getattr(state, "real_instagram_gateway", current)
    try:
        connect_instagram(client, account_id)
    finally:
        state.instagram_gateway = current


@pytest.fixture
def connected(instagram_client: TestClient) -> tuple[int, dict[str, Any]]:
    project_id, account = create_instagram_account(instagram_client)
    _connect(instagram_client, account["id"])
    return project_id, account


@pytest.fixture
def stub(instagram_client: TestClient, fake_clock: FakeClock) -> StubInstagramGateway:
    gateway = StubInstagramGateway(fake_clock)
    state = _app(instagram_client).state
    state.real_instagram_gateway = state.instagram_gateway
    state.instagram_gateway = gateway
    return gateway


def _verify(client: TestClient, account_id: int) -> Any:
    return client.post(f"/api/accounts/{account_id}/instagram-connection/verify")


def _row(db_path: Path) -> dict[str, Any]:
    (row,) = instagram_rows(db_path)
    return row


def test_verify_updates_public_data(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    fake_clock.advance(timedelta(hours=1).total_seconds())
    stub.identity.update(
        username="renamed.studio",
        account_type="MEDIA_CREATOR",
        profile_picture_url=None,
    )

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "connected"
    assert body["identity"] == {
        "instagram_user_id": "17841400000000001",
        "username": "renamed.studio",
        "account_type": "MEDIA_CREATOR",
        "profile_picture_url": None,
    }
    assert body["last_verified_at"] == fake_clock.now().isoformat().replace(
        "+00:00", "Z"
    )
    assert stub.calls == ["me"]


def test_verify_refreshes_an_old_token(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    fake_clock.advance(timedelta(days=2).total_seconds())

    assert _verify(instagram_client, account["id"]).status_code == 200
    assert stub.calls == ["refresh", "me"]


def test_verify_without_meta_app_config(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    instagram_app_file: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    instagram_app_file.unlink()

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 200
    assert response.json()["oauth_configured"] is False


def test_identity_mismatch(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    stub.identity.update(instagram_user_id="17841400000000999", username="other")

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "instagram_identity_mismatch"
    row = _row(db_path)
    assert row["status"] == "reconnect_required"
    assert row["instagram_user_id"] == "17841400000000001"
    assert row["username"] == "cyber.studio"


@pytest.mark.parametrize("account_type", [None, "PERSONAL"])
def test_no_longer_professional(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    account_type: str | None,
) -> None:
    _, account = connected
    stub.identity["account_type"] = account_type

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "instagram_account_not_professional"
    assert "Business or Creator" in error["message"]
    assert _row(db_path)["status"] == "reconnect_required"
    assert _row(db_path)["account_type"] == "BUSINESS"


@pytest.mark.parametrize("permission", [IG_BASIC, IG_PUBLISH, None])
def test_permission_withdrawn(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    permission: str | None,
) -> None:
    _, account = connected
    stub.me_error = MetaPermissionDenied(permission)

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "instagram_reconnect_required"
    assert "permission is missing or was withdrawn" in error["message"]
    if permission is not None:
        assert permission in error["message"]
    else:
        assert IG_BASIC not in error["message"]
        assert IG_PUBLISH not in error["message"]
    row = _row(db_path)
    assert row["status"] == "reconnect_required"
    assert row["username"] == "cyber.studio"
    connection = get_instagram_connection(instagram_client, account["id"])
    assert connection["identity"]["instagram_user_id"] == "17841400000000001"


def test_stored_permissions_incomplete(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    stub: StubInstagramGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    ref = _row(db_path)["credential_ref"]
    instagram_credential_store.secrets[ref] = instagram_credential_store.secrets[
        ref
    ].replace(f'"{IG_PUBLISH}"', "")
    instagram_credential_store.secrets[ref] = instagram_credential_store.secrets[
        ref
    ].replace(", ]", "]")

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "instagram_reconnect_required"
    assert IG_PUBLISH in error["message"]
    assert stub.calls == []


def test_token_rejected(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    stub.me_error = MetaTokenInvalid()

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "instagram_reconnect_required"
    assert _row(db_path)["status"] == "reconnect_required"


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (MetaUnavailable(), 503, "instagram_unavailable"),
        (MetaUnexpectedResponse(), 502, "instagram_unexpected_response"),
        (MetaRejected(), 502, "instagram_unexpected_response"),
    ],
)
def test_failures_without_state_change(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    failure: Exception,
    status: int,
    code: str,
) -> None:
    _, account = connected
    before = _row(db_path)
    stub.me_error = failure

    response = _verify(instagram_client, account["id"])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert _row(db_path) == before


def test_reconnect_required_is_not_verified(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    _, account = connected
    run_sql(db_path, "UPDATE instagram_connections SET status = 'reconnect_required'")

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "instagram_reconnect_required"
    assert stub.calls == []
    # There is no way back to `connected` through Verify.
    assert _row(db_path)["status"] == "reconnect_required"


def test_not_connected(
    instagram_client: TestClient, stub: StubInstagramGateway
) -> None:
    _, account = create_instagram_account(instagram_client)

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "instagram_not_connected"


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
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    stub: StubInstagramGateway,
    db_path: Path,
    inactive: tuple[str, ...],
    code: str,
    connection_state: str | None,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    if connection_state is not None:
        _connect(instagram_client, account["id"])
        run_sql(
            db_path, "UPDATE instagram_connections SET status = ?", connection_state
        )
    if "account" in inactive:
        instagram_client.patch(
            f"/api/accounts/{account['id']}", json={"is_active": False}
        )
    if "project" in inactive:
        instagram_client.patch(f"/api/projects/{project_id}", json={"is_active": False})
    instagram_credential_store.unavailable = True  # any access would answer 503
    stub.calls.clear()

    response = _verify(instagram_client, account["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert stub.calls == []


def test_other_platform_takes_precedence_over_inactive(
    instagram_client: TestClient, stub: StubInstagramGateway
) -> None:
    project = create_project(instagram_client, "Cyber")
    youtube = create_account(instagram_client, project["id"], "youtube", "cyber")
    instagram_client.patch(f"/api/accounts/{youtube['id']}", json={"is_active": False})

    response = _verify(instagram_client, youtube["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_not_supported"


def test_unknown_account(
    instagram_client: TestClient, stub: StubInstagramGateway
) -> None:
    assert _verify(instagram_client, 999).status_code == 404
