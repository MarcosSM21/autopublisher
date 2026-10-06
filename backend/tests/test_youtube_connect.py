import base64
import hashlib
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    authorize,
    complete_callback,
    connect_youtube,
    create_account,
    create_project,
    get_attempt,
    get_connection,
    setup_youtube_account,
)
from tests.fakes import (
    FAKE_ACCESS_TOKEN,
    FAKE_CLIENT_ID,
    FAKE_CLIENT_SECRET,
    FAKE_REFRESH_TOKEN,
    FakeChannel,
    FakeGoogle,
    InMemoryCredentialStore,
    client_config_json,
)


def _connection_row(db_path: Path, account_id: int) -> tuple[Any, ...] | None:
    with sqlite3.connect(db_path) as connection:
        row: tuple[Any, ...] | None = connection.execute(
            "SELECT channel_id, status, credential_ref FROM youtube_connections "
            "WHERE account_id = ?",
            (account_id,),
        ).fetchone()
    return row


# --- Status endpoint (T016) --------------------------------------------------------


def test_status_of_a_new_youtube_account(youtube_client: TestClient) -> None:
    _, account = setup_youtube_account(youtube_client)

    assert get_connection(youtube_client, account["id"]) == {
        "status": "not_connected",
        "channel": None,
        "connected_at": None,
        "last_verified_at": None,
        "oauth_configured": True,
    }


def test_oauth_configured_is_read_on_every_request(
    youtube_client: TestClient, oauth_client_file: Path
) -> None:
    _, account = setup_youtube_account(youtube_client)
    oauth_client_file.unlink()

    response = youtube_client.get(f"/api/accounts/{account['id']}/youtube-connection")
    assert response.json()["oauth_configured"] is False
    for hidden in (FAKE_CLIENT_ID, FAKE_CLIENT_SECRET, str(oauth_client_file)):
        assert hidden not in response.text

    oauth_client_file.write_text(client_config_json())
    assert get_connection(youtube_client, account["id"])["oauth_configured"] is True


def test_status_rejects_other_platforms_and_unknown_accounts(
    youtube_client: TestClient,
) -> None:
    project = create_project(youtube_client, "Cyber")
    instagram = create_account(youtube_client, project["id"], "instagram", "cyber")

    response = youtube_client.get(f"/api/accounts/{instagram['id']}/youtube-connection")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_not_supported"
    response = youtube_client.get("/api/accounts/999/youtube-connection")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- Connect happy path (US1) ------------------------------------------------------


def test_connect_youtube_account(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    body, state = authorize(youtube_client, account["id"])

    params = parse_qs(urlsplit(body["authorization_url"]).query)
    assert params["client_id"] == [FAKE_CLIENT_ID]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["select_account consent"]
    assert params["code_challenge_method"] == ["S256"]
    assert body["expires_at"]
    assert get_attempt(youtube_client, body["attempt_id"])["status"] == "pending"

    response = complete_callback(youtube_client, state)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "connected" in response.text
    exchange = fake_google.token_requests[0].form
    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(exchange["code_verifier"].encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    assert params["code_challenge"] == [challenge]

    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["status"] == "completed"
    connection = attempt["connection"]
    assert connection["status"] == "connected"
    assert connection["channel"] == {
        "id": "UC_TEST_1",
        "title": "Cyber Channel",
        "handle": "@cyberchannel",
        "thumbnail_url": "https://yt3.example.com/cyber.jpg",
    }
    assert connection["connected_at"] is not None
    assert get_connection(youtube_client, account["id"]) == connection

    row = _connection_row(db_path, account["id"])
    assert row is not None
    channel_id, status, credential_ref = row
    assert (channel_id, status) == ("UC_TEST_1", "connected")
    assert list(credential_store.secrets) == [credential_ref]
    secret = credential_store.secrets[credential_ref]
    assert FAKE_ACCESS_TOKEN in secret and FAKE_REFRESH_TOKEN in secret


def test_connecting_does_not_modify_the_account(
    youtube_client: TestClient, fake_google: FakeGoogle
) -> None:
    """FR-017: the channel's handle and title never overwrite the account's."""
    project, account = setup_youtube_account(youtube_client, handle="mychannel")
    fake_google.set_channel("UC_OTHER", "A Different Title", "@different")
    _, state = authorize(youtube_client, account["id"])
    assert complete_callback(youtube_client, state).status_code == 200

    accounts = youtube_client.get(f"/api/projects/{project['id']}/accounts").json()
    assert accounts == [account]


def test_authorize_rejections(
    youtube_client: TestClient, oauth_client_file: Path
) -> None:
    project = create_project(youtube_client, "Cyber")
    instagram = create_account(youtube_client, project["id"], "instagram", "cyber")
    youtube = create_account(youtube_client, project["id"], "youtube", "cyber")

    response = youtube_client.post(
        f"/api/accounts/{instagram['id']}/youtube-connection/authorize"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_not_supported"
    response = youtube_client.post("/api/accounts/999/youtube-connection/authorize")
    assert response.status_code == 404

    oauth_client_file.unlink()
    response = youtube_client.post(
        f"/api/accounts/{youtube['id']}/youtube-connection/authorize"
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "oauth_not_configured"
    registry = youtube_client.app.state.oauth_attempts  # type: ignore[attr-defined]
    assert registry._attempts == {}


def test_deactivated_before_callback_is_rejected_without_contacting_google(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    project, account = setup_youtube_account(youtube_client)
    body, state = authorize(youtube_client, account["id"])
    youtube_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})

    response = complete_callback(youtube_client, state)

    assert response.status_code == 400
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "account_inactive"
    assert fake_google.requests == []
    assert credential_store.secrets == {}

    youtube_client.patch(f"/api/accounts/{account['id']}", json={"is_active": True})
    body, state = authorize(youtube_client, account["id"])
    youtube_client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    complete_callback(youtube_client, state)
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["error"]["code"] == "project_inactive"
    assert fake_google.requests == []


# --- Errors and cancellation (US2) -------------------------------------------------


def _registry(client: TestClient) -> Any:
    return client.app.state.oauth_attempts  # type: ignore[attr-defined]


def _advance_registry(client: TestClient, minutes: float) -> None:
    from datetime import timedelta

    from app.db import utc_now

    offset = timedelta(minutes=minutes)
    _registry(client).clock = lambda: utc_now() + offset


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"error": "access_denied"}, "oauth_cancelled"),
        ({"error": "server_error"}, "oauth_provider_error"),
        ({"code": None}, "oauth_callback_invalid"),
    ],
)
def test_callback_failures_without_exchange(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    params: dict[str, Any],
    code: str,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    body, state = authorize(youtube_client, account["id"])

    response = complete_callback(
        youtube_client, state, code=params.get("code"), error=params.get("error")
    )

    assert response.status_code == 400
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert (attempt["status"], attempt["error"]["code"]) == ("failed", code)
    assert attempt["error"]["message"] in response.text
    assert fake_google.requests == []
    assert credential_store.secrets == {}
    assert get_connection(youtube_client, account["id"])["status"] == "not_connected"


def test_invalid_states_are_rejected_without_side_effects(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    _, account = setup_youtube_account(youtube_client)

    for state in (None, "unknown-state"):
        response = complete_callback(youtube_client, state)
        assert response.status_code == 400
        assert "invalid or has expired" in response.text

    # Reused state: a second callback after a successful one.
    _, state = authorize(youtube_client, account["id"])
    assert complete_callback(youtube_client, state).status_code == 200
    requests_before = len(fake_google.requests)
    secrets_before = dict(credential_store.secrets)
    response = complete_callback(youtube_client, state)
    assert response.status_code == 400
    assert len(fake_google.requests) == requests_before
    assert credential_store.secrets == secrets_before


def test_superseded_and_expired_states_are_rejected(
    youtube_client: TestClient, fake_google: FakeGoogle
) -> None:
    _, account = setup_youtube_account(youtube_client)
    first, first_state = authorize(youtube_client, account["id"])
    authorize(youtube_client, account["id"])

    assert complete_callback(youtube_client, first_state).status_code == 400
    assert get_attempt(youtube_client, first["attempt_id"])["status"] == "expired"

    _, state = authorize(youtube_client, account["id"])
    _advance_registry(youtube_client, 11)
    response = complete_callback(youtube_client, state)
    assert response.status_code == 400
    assert "invalid or has expired" in response.text
    assert fake_google.requests == []


@pytest.mark.parametrize(
    ("setting", "value", "code"),
    [
        ("exchange_outcome", "rejected", "oauth_exchange_failed"),
        ("exchange_outcome", "server_error", "youtube_unavailable"),
        ("exchange_outcome", "timeout", "youtube_unavailable"),
        ("exchange_outcome", "partial_scope", "oauth_scope_insufficient"),
        ("exchange_outcome", "no_refresh", "oauth_offline_access_missing"),
        ("channels_outcome", "server_error", "youtube_unavailable"),
        ("channels", [], "youtube_no_channel"),
        (
            "channels",
            [FakeChannel("UC_A", "A"), FakeChannel("UC_B", "B")],
            "youtube_channel_ambiguous",
        ),
    ],
)
def test_exchange_and_identification_failures(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    setting: str,
    value: Any,
    code: str,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    body, state = authorize(youtube_client, account["id"])
    setattr(fake_google, setting, value)

    response = complete_callback(youtube_client, state)

    assert response.status_code == 400
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert (attempt["status"], attempt["error"]["code"]) == ("failed", code)
    assert credential_store.secrets == {}
    assert _connection_row(db_path, account["id"]) is None
    assert get_connection(youtube_client, account["id"])["status"] == "not_connected"
    if code == "youtube_channel_ambiguous":
        assert "Select the right channel" in attempt["error"]["message"]


def test_failures_keep_an_existing_connection(
    youtube_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    before = connect_youtube(youtube_client, fake_google, account["id"])
    secrets_before = dict(credential_store.secrets)
    _, state = authorize(youtube_client, account["id"])

    complete_callback(youtube_client, state, error="access_denied")

    assert get_connection(youtube_client, account["id"]) == before
    assert credential_store.secrets == secrets_before


def test_store_unavailable_on_connect(
    youtube_client: TestClient,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, account = setup_youtube_account(youtube_client)
    body, state = authorize(youtube_client, account["id"])
    credential_store.unavailable = True

    response = complete_callback(youtube_client, state)

    assert response.status_code == 400
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["error"]["code"] == "credential_store_unavailable"
    assert _connection_row(db_path, account["id"]) is None


def test_unexpected_errors_give_a_generic_500_page(
    youtube_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.youtube_gateway import GoogleGateway

    def explode(self: GoogleGateway, access_token: str) -> list[Any]:
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr(GoogleGateway, "list_my_channels", explode)
    _, account = setup_youtube_account(youtube_client)
    body, state = authorize(youtube_client, account["id"])

    response = complete_callback(youtube_client, state)

    assert response.status_code == 500
    assert "hunter2" not in response.text
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["error"]["code"] == "internal_error"
    assert "hunter2" not in attempt["error"]["message"]
