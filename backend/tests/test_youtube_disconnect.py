from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import (
    authorize,
    connect_youtube,
    create_account,
    create_project,
    create_publications,
    get_attempt,
    get_connection,
    import_one,
    make_image,
    run_sql,
    setup_youtube_account,
)
from tests.fakes import FakeGoogle, InMemoryCredentialStore


def _disconnect(client: TestClient, account_id: int) -> tuple[int, Any]:
    response = client.post(f"/api/accounts/{account_id}/youtube-connection/disconnect")
    return response.status_code, response.json()


def test_disconnect_deletes_local_credentials_only(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    project, account = setup_youtube_account(youtube_client)
    content = import_one(youtube_client, project["id"], "a.png", make_image())
    publication = create_publications(
        youtube_client, content["content"]["id"], [account["id"]]
    )[0]
    connect_youtube(youtube_client, fake_google, account["id"])
    requests_before = len(fake_google.requests)

    status, body = _disconnect(youtube_client, account["id"])

    assert status == 200
    assert body["status"] == "not_connected" and body["channel"] is None
    assert credential_store.secrets == {}
    assert get_connection(youtube_client, account["id"])["status"] == "not_connected"
    assert len(fake_google.requests) == requests_before  # Google is never contacted
    accounts = youtube_client.get(f"/api/projects/{project['id']}/accounts").json()
    assert accounts == [account]
    assert youtube_client.get(f"/api/publications/{publication['id']}").json() == (
        publication
    )


def test_disconnect_reconnect_required_without_config(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    oauth_client_file: Path,
    db_path: Path,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    connect_youtube(youtube_client, fake_google, account["id"])
    run_sql(db_path, "UPDATE youtube_connections SET status = 'reconnect_required'")
    oauth_client_file.unlink()

    assert _disconnect(youtube_client, account["id"])[0] == 200
    assert credential_store.secrets == {}


def test_disconnect_inactive_account_and_project(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    project, account = setup_youtube_account(youtube_client)
    other = create_account(youtube_client, project["id"], "youtube", "second")
    connect_youtube(youtube_client, fake_google, account["id"])
    connect_youtube(youtube_client, fake_google, other["id"], channel_id="UC_TEST_2")
    youtube_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})
    youtube_client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    assert _disconnect(youtube_client, account["id"])[0] == 200
    assert _disconnect(youtube_client, other["id"])[0] == 200
    assert credential_store.secrets == {}


def test_disconnect_is_idempotent_and_tolerates_missing_secret(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    assert _disconnect(youtube_client, account["id"])[0] == 200

    connect_youtube(youtube_client, fake_google, account["id"])
    credential_store.secrets.clear()
    assert _disconnect(youtube_client, account["id"])[0] == 200
    assert get_connection(youtube_client, account["id"])["status"] == "not_connected"


def test_disconnect_rejections(youtube_client: TestClient) -> None:
    project = create_project(youtube_client, "Cyber")
    instagram = create_account(youtube_client, project["id"], "instagram", "cyber")

    status, body = _disconnect(youtube_client, instagram["id"])
    assert (status, body["error"]["code"]) == (409, "platform_not_supported")
    assert _disconnect(youtube_client, 999)[0] == 404


def test_disconnect_keeps_the_connection_when_the_store_is_unavailable(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    before = connect_youtube(youtube_client, fake_google, account["id"])
    secrets = dict(credential_store.secrets)
    credential_store.fail_on = {"delete"}

    status, body = _disconnect(youtube_client, account["id"])

    assert (status, body["error"]["code"]) == (503, "credential_store_unavailable")
    assert get_connection(youtube_client, account["id"]) == before
    assert credential_store.secrets == secrets

    credential_store.fail_on = set()
    assert _disconnect(youtube_client, account["id"])[0] == 200
    assert credential_store.secrets == {}
    assert get_connection(youtube_client, account["id"])["status"] == "not_connected"


def test_disconnect_expires_pending_attempts(
    youtube_client: TestClient, fake_google: FakeGoogle
) -> None:
    _, account = setup_youtube_account(youtube_client)
    connect_youtube(youtube_client, fake_google, account["id"])
    body, _ = authorize(youtube_client, account["id"])

    _disconnect(youtube_client, account["id"])

    assert get_attempt(youtube_client, body["attempt_id"])["status"] == "expired"
