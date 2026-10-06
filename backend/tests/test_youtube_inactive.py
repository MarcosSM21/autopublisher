from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import (
    authorize,
    complete_callback,
    connect_youtube,
    get_attempt,
    get_connection,
    setup_youtube_account,
)
from tests.fakes import FakeGoogle, InMemoryCredentialStore


def _registry_size(client: TestClient) -> int:
    registry: Any = client.app.state.oauth_attempts  # type: ignore[attr-defined]
    return len(registry._attempts)


def test_authorize_requires_active_account_and_project(
    youtube_client: TestClient,
) -> None:
    project, account = setup_youtube_account(youtube_client)
    url = f"/api/accounts/{account['id']}/youtube-connection/authorize"

    youtube_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})
    response = youtube_client.post(url)
    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "account_inactive",
    )

    youtube_client.patch(f"/api/accounts/{account['id']}", json={"is_active": True})
    youtube_client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    response = youtube_client.post(url)
    assert response.json()["error"]["code"] == "project_inactive"
    assert _registry_size(youtube_client) == 0


def test_deactivating_keeps_the_connection(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    project, account = setup_youtube_account(youtube_client)
    before = connect_youtube(youtube_client, fake_google, account["id"])
    secrets = dict(credential_store.secrets)

    youtube_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})
    youtube_client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    assert get_connection(youtube_client, account["id"]) == before
    assert credential_store.secrets == secrets
    disconnect = youtube_client.post(
        f"/api/accounts/{account['id']}/youtube-connection/disconnect"
    )
    assert disconnect.status_code == 200


def test_confirm_requires_an_active_project(
    youtube_client: TestClient, fake_google: FakeGoogle
) -> None:
    project, account = setup_youtube_account(youtube_client)
    before = connect_youtube(youtube_client, fake_google, account["id"])
    fake_google.set_channel("UC_NEW_2", "New")
    body, state = authorize(youtube_client, account["id"])
    complete_callback(youtube_client, state)
    youtube_client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = youtube_client.post(
        f"/api/youtube/oauth/attempts/{body['attempt_id']}/confirm"
    )

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "project_inactive",
    )
    assert get_attempt(youtube_client, body["attempt_id"])["status"] == "failed"
    assert get_connection(youtube_client, account["id"]) == before
