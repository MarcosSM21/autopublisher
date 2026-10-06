import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import utc_now
from app.errors import AppError, ConflictError
from app.youtube_connections import get_valid_credentials
from tests.conftest import (
    connect_youtube,
    create_account,
    create_project,
    get_connection,
    setup_youtube_account,
)
from tests.fakes import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_ROTATED_REFRESH_TOKEN,
    FakeChannel,
    FakeGoogle,
    InMemoryCredentialStore,
)


@pytest.fixture
def connected(youtube_client: TestClient, fake_google: FakeGoogle) -> dict[str, Any]:
    _, account = setup_youtube_account(youtube_client)
    connect_youtube(youtube_client, fake_google, account["id"])
    return account


@pytest.fixture
def session(youtube_client: TestClient) -> Iterator[Session]:
    factory = youtube_client.app.state.session_factory  # type: ignore[attr-defined]
    with factory() as session:
        yield session


def _valid(client: TestClient, session: Session, account_id: int) -> Any:
    state = client.app.state  # type: ignore[attr-defined]
    return get_valid_credentials(
        session, state.credential_store, state.google_gateway, account_id
    )


def _secret(store: InMemoryCredentialStore) -> dict[str, Any]:
    (raw,) = store.secrets.values()
    secret: dict[str, Any] = json.loads(raw)
    return secret


def _expire(store: InMemoryCredentialStore) -> None:
    (ref,) = store.secrets
    secret = _secret(store)
    secret["expires_at"] = (utc_now() - timedelta(minutes=1)).isoformat()
    store.secrets[ref] = json.dumps(secret)


def _status(client: TestClient, account_id: int) -> str:
    status: str = get_connection(client, account_id)["status"]
    return status


def _refreshes(fake_google: FakeGoogle) -> int:
    return sum(
        1 for r in fake_google.token_requests if r.form["grant_type"] == "refresh_token"
    )


# --- get_valid_credentials ---------------------------------------------------------


def test_valid_token_is_returned_without_contacting_google(
    youtube_client: TestClient,
    connected: dict[str, Any],
    session: Session,
    fake_google: FakeGoogle,
) -> None:
    requests_before = len(fake_google.requests)
    tokens = _valid(youtube_client, session, connected["id"])
    assert tokens.access_token == FAKE_ACCESS_TOKEN
    assert len(fake_google.requests) == requests_before


def test_expired_token_is_refreshed_and_persisted(
    youtube_client: TestClient,
    connected: dict[str, Any],
    session: Session,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    (ref,) = credential_store.secrets
    _expire(credential_store)

    tokens = _valid(youtube_client, session, connected["id"])

    assert tokens.access_token == FAKE_REFRESHED_ACCESS_TOKEN
    assert _refreshes(fake_google) == 1
    assert list(credential_store.secrets) == [ref]
    stored = _secret(credential_store)
    assert stored["access_token"] == FAKE_REFRESHED_ACCESS_TOKEN
    assert stored["refresh_token"] == FAKE_REFRESH_TOKEN
    assert _status(youtube_client, connected["id"]) == "connected"


def test_rotated_refresh_token_is_persisted(
    youtube_client: TestClient,
    connected: dict[str, Any],
    session: Session,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    _expire(credential_store)
    fake_google.refresh_outcome = "rotate"
    _valid(youtube_client, session, connected["id"])
    assert _secret(credential_store)["refresh_token"] == FAKE_ROTATED_REFRESH_TOKEN


def test_invalid_grant_requires_reconnecting(
    youtube_client: TestClient,
    connected: dict[str, Any],
    session: Session,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    _expire(credential_store)
    fake_google.refresh_outcome = "invalid_grant"

    with pytest.raises(ConflictError) as error:
        _valid(youtube_client, session, connected["id"])

    assert error.value.code == "reconnect_required"
    assert _status(youtube_client, connected["id"]) == "reconnect_required"


@pytest.mark.parametrize("outcome", ["server_error", "timeout"])
def test_transient_refresh_failures_keep_the_status(
    youtube_client: TestClient,
    connected: dict[str, Any],
    session: Session,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    outcome: str,
) -> None:
    _expire(credential_store)
    fake_google.refresh_outcome = outcome

    with pytest.raises(AppError) as error:
        _valid(youtube_client, session, connected["id"])

    assert (error.value.status_code, error.value.code) == (503, "youtube_unavailable")
    assert _status(youtube_client, connected["id"]) == "connected"


def test_missing_secret_requires_reconnecting(
    youtube_client: TestClient,
    connected: dict[str, Any],
    session: Session,
    credential_store: InMemoryCredentialStore,
) -> None:
    credential_store.secrets.clear()
    with pytest.raises(ConflictError) as error:
        _valid(youtube_client, session, connected["id"])
    assert error.value.code == "reconnect_required"
    assert _status(youtube_client, connected["id"]) == "reconnect_required"


def test_missing_config_during_refresh(
    youtube_client: TestClient,
    connected: dict[str, Any],
    session: Session,
    credential_store: InMemoryCredentialStore,
    oauth_client_file: Path,
) -> None:
    _expire(credential_store)
    oauth_client_file.unlink()
    with pytest.raises(AppError) as error:
        _valid(youtube_client, session, connected["id"])
    assert (error.value.status_code, error.value.code) == (503, "oauth_not_configured")
    assert _status(youtube_client, connected["id"]) == "connected"


# --- verify ------------------------------------------------------------------------


def _verify(client: TestClient, account_id: int) -> Any:
    return client.post(f"/api/accounts/{account_id}/youtube-connection/verify")


def test_verify_updates_public_channel_data(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    before = get_connection(youtube_client, connected["id"])
    fake_google.channels = [
        FakeChannel("UC_TEST_1", "Renamed", "@renamed", "https://yt3.example.com/n")
    ]

    response = _verify(youtube_client, connected["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == {
        "id": "UC_TEST_1",
        "title": "Renamed",
        "handle": "@renamed",
        "thumbnail_url": "https://yt3.example.com/n",
    }
    assert body["last_verified_at"] >= before["last_verified_at"]
    assert body["status"] == "connected"


@pytest.mark.parametrize(
    "change",
    [
        {"channels": [FakeChannel("UC_SOMEONE_ELSE", "Else")]},
        {"channels": [FakeChannel("UC_TEST_1", "A"), FakeChannel("UC_X", "B")]},
        {"channels_outcome": "forbidden"},
        {"channels_outcome": "unauthorized"},
    ],
)
def test_verify_requires_reconnecting(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
    change: dict[str, Any],
) -> None:
    for key, value in change.items():
        setattr(fake_google, key, value)

    response = _verify(youtube_client, connected["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reconnect_required"
    assert _status(youtube_client, connected["id"]) == "reconnect_required"


def test_verify_retries_once_after_a_401(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    fake_google.channels_outcomes = ["unauthorized"]

    response = _verify(youtube_client, connected["id"])

    assert response.status_code == 200
    assert _refreshes(fake_google) == 1


def test_verify_transient_failure_keeps_connected(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    fake_google.channels_outcome = "server_error"
    response = _verify(youtube_client, connected["id"])
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "youtube_unavailable"
    assert _status(youtube_client, connected["id"]) == "connected"


def test_verify_rejections(youtube_client: TestClient) -> None:
    project, account = setup_youtube_account(youtube_client)
    instagram = create_account(youtube_client, project["id"], "instagram", "cyber")

    response = _verify(youtube_client, account["id"])
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "not_connected",
    )
    response = _verify(youtube_client, instagram["id"])
    assert response.json()["error"]["code"] == "platform_not_supported"


def test_verify_is_allowed_while_inactive(
    youtube_client: TestClient, fake_google: FakeGoogle
) -> None:
    project = create_project(youtube_client, "Paused")
    account = create_account(youtube_client, project["id"], "youtube", "paused")
    connect_youtube(youtube_client, fake_google, account["id"])
    youtube_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})
    youtube_client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    assert _verify(youtube_client, account["id"]).status_code == 200
