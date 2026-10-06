from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.db import utc_now
from tests.conftest import (
    authorize,
    complete_callback,
    connect_youtube,
    create_account,
    create_project,
    get_attempt,
    get_connection,
    run_sql,
    setup_youtube_account,
)
from tests.fakes import FakeGoogle, InMemoryCredentialStore


def _advance_registry(client: TestClient, delta: timedelta) -> None:
    registry = client.app.state.oauth_attempts  # type: ignore[attr-defined]
    registry.clock = lambda: utc_now() + delta


def _confirm(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/youtube/oauth/attempts/{attempt_id}/confirm")


def _cancel(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/youtube/oauth/attempts/{attempt_id}/cancel")


def _change_channel(
    client: TestClient, fake_google: FakeGoogle, account_id: int
) -> dict[str, Any]:
    """Reconnect authorizing UC_NEW_2; return the attempt awaiting confirmation."""
    fake_google.set_channel("UC_NEW_2", "New Channel")
    body, state = authorize(client, account_id)
    response = complete_callback(client, state)
    assert response.status_code == 200
    assert "confirm" in response.text
    attempt = get_attempt(client, body["attempt_id"])
    assert attempt["status"] == "awaiting_confirmation"
    return attempt


@pytest.fixture
def connected(youtube_client: TestClient, fake_google: FakeGoogle) -> dict[str, Any]:
    _, account = setup_youtube_account(youtube_client)
    connect_youtube(youtube_client, fake_google, account["id"])
    return account


# --- Reconnect (US5) ---------------------------------------------------------------


def test_reconnect_after_disconnect_asks_for_consent_again(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    youtube_client.post(
        f"/api/accounts/{connected['id']}/youtube-connection/disconnect"
    )

    body, state = authorize(youtube_client, connected["id"])
    params = parse_qs(urlsplit(body["authorization_url"]).query)
    assert params["prompt"] == ["select_account consent"]
    assert params["access_type"] == ["offline"]
    complete_callback(youtube_client, state)

    assert get_connection(youtube_client, connected["id"])["status"] == "connected"


@pytest.mark.parametrize("initial", ["connected", "reconnect_required"])
def test_reconnect_same_channel_replaces_credentials(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    initial: str,
) -> None:
    run_sql(db_path, "UPDATE youtube_connections SET status = ?", initial)
    (old_ref,) = credential_store.secrets
    before = get_connection(youtube_client, connected["id"])

    connect_youtube(youtube_client, fake_google, connected["id"])

    (new_ref,) = credential_store.secrets
    assert new_ref != old_ref
    after = get_connection(youtube_client, connected["id"])
    assert after["status"] == "connected"
    assert after["channel"] == before["channel"]
    assert after["connected_at"] >= before["connected_at"]


def test_different_channel_waits_for_confirmation(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    before = get_connection(youtube_client, connected["id"])
    secrets_before = dict(credential_store.secrets)

    attempt = _change_channel(youtube_client, fake_google, connected["id"])

    assert attempt["current_channel"]["id"] == "UC_TEST_1"
    assert attempt["current_channel"]["title"] == "Cyber Channel"
    assert attempt["new_channel"]["id"] == "UC_NEW_2"
    assert attempt["new_channel"]["title"] == "New Channel"
    assert get_connection(youtube_client, connected["id"]) == before
    assert credential_store.secrets == secrets_before

    response = _confirm(youtube_client, attempt["attempt_id"])

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    after = get_connection(youtube_client, connected["id"])
    assert after["channel"]["id"] == "UC_NEW_2"
    assert len(credential_store.secrets) == 1
    assert set(credential_store.secrets) != set(secrets_before)


def test_cancelling_the_change_keeps_the_connection(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    before = get_connection(youtube_client, connected["id"])
    secrets_before = dict(credential_store.secrets)
    attempt = _change_channel(youtube_client, fake_google, connected["id"])

    response = _cancel(youtube_client, attempt["attempt_id"])

    assert response.json()["status"] == "cancelled"
    assert _cancel(youtube_client, attempt["attempt_id"]).status_code == 200
    assert get_connection(youtube_client, connected["id"]) == before
    assert credential_store.secrets == secrets_before


def test_expired_change_cannot_be_confirmed(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
) -> None:
    before = get_connection(youtube_client, connected["id"])
    attempt = _change_channel(youtube_client, fake_google, connected["id"])
    attempt_id = attempt["attempt_id"]

    _advance_registry(youtube_client, timedelta(minutes=10, seconds=1))
    assert get_attempt(youtube_client, attempt_id)["status"] == "expired"
    response = _confirm(youtube_client, attempt_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "oauth_attempt_not_confirmable"
    assert get_connection(youtube_client, connected["id"]) == before

    _advance_registry(youtube_client, timedelta(minutes=20, seconds=2))
    response = youtube_client.get(f"/api/youtube/oauth/attempts/{attempt_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "oauth_attempt_not_found"


def test_confirm_rechecks_the_current_connection(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    attempt = _change_channel(youtube_client, fake_google, connected["id"])
    youtube_client.post(
        f"/api/accounts/{connected['id']}/youtube-connection/disconnect"
    )

    response = _confirm(youtube_client, attempt["attempt_id"])

    # Disconnecting expired the attempt, so it can no longer be confirmed.
    assert response.status_code == 409
    assert get_connection(youtube_client, connected["id"])["status"] == (
        "not_connected"
    )


def test_confirm_detects_a_changed_connection(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
    db_path: Path,
) -> None:
    attempt = _change_channel(youtube_client, fake_google, connected["id"])
    run_sql(db_path, "UPDATE youtube_connections SET channel_id = 'UC_ELSEWHERE'")

    response = _confirm(youtube_client, attempt["attempt_id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connection_changed"
    assert get_attempt(youtube_client, attempt["attempt_id"])["status"] == "failed"


def test_confirm_requires_an_active_account(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    attempt = _change_channel(youtube_client, fake_google, connected["id"])
    youtube_client.patch(f"/api/accounts/{connected['id']}", json={"is_active": False})

    response = _confirm(youtube_client, attempt["attempt_id"])

    assert response.json()["error"]["code"] == "account_inactive"
    assert get_attempt(youtube_client, attempt["attempt_id"])["status"] == "failed"
    assert get_connection(youtube_client, connected["id"])["channel"]["id"] == (
        "UC_TEST_1"
    )


def test_attempt_state_errors(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    body, state = authorize(youtube_client, connected["id"])
    complete_callback(youtube_client, state)  # same channel → completed

    for action in (_confirm, _cancel):
        response = action(youtube_client, body["attempt_id"])
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "oauth_attempt_not_confirmable"
    assert _confirm(youtube_client, "unknown").status_code == 404
    assert _cancel(youtube_client, "unknown").json()["error"]["code"] == (
        "oauth_attempt_not_found"
    )


# --- One channel per project (US6) -------------------------------------------------


def test_same_channel_in_the_same_project_is_rejected(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    second = create_account(youtube_client, connected["project_id"], "youtube", "dup")
    secrets_before = dict(credential_store.secrets)
    body, state = authorize(youtube_client, second["id"])

    response = complete_callback(youtube_client, state)

    assert response.status_code == 400
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["error"]["code"] == "channel_already_connected"
    assert "@cyberchannel" in attempt["error"]["message"]
    assert credential_store.secrets == secrets_before
    assert get_connection(youtube_client, second["id"])["status"] == "not_connected"


def test_inactive_holder_still_blocks_the_channel(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    youtube_client.patch(f"/api/accounts/{connected['id']}", json={"is_active": False})
    second = create_account(youtube_client, connected["project_id"], "youtube", "dup")
    body, state = authorize(youtube_client, second["id"])
    complete_callback(youtube_client, state)
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["error"]["code"] == "channel_already_connected"


def test_same_channel_in_another_project_is_allowed(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    other_project = create_project(youtube_client, "Other")
    other = create_account(youtube_client, other_project["id"], "youtube", "cyber")
    connect_youtube(youtube_client, fake_google, other["id"])
    assert get_connection(youtube_client, other["id"])["status"] == "connected"


def test_channel_is_free_after_disconnecting_the_holder(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    second = create_account(youtube_client, connected["project_id"], "youtube", "dup")
    youtube_client.post(
        f"/api/accounts/{connected['id']}/youtube-connection/disconnect"
    )
    connect_youtube(youtube_client, fake_google, second["id"])
    assert get_connection(youtube_client, second["id"])["status"] == "connected"


def test_confirmed_change_to_a_taken_channel_is_rejected(
    youtube_client: TestClient, connected: dict[str, Any], fake_google: FakeGoogle
) -> None:
    second = create_account(youtube_client, connected["project_id"], "youtube", "dup")
    connect_youtube(youtube_client, fake_google, second["id"], channel_id="UC_NEW_2")
    attempt = _change_channel(youtube_client, fake_google, connected["id"])

    response = _confirm(youtube_client, attempt["attempt_id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "channel_already_connected"
    assert get_connection(youtube_client, connected["id"])["channel"]["id"] == (
        "UC_TEST_1"
    )


def test_race_on_the_unique_index_is_reported_as_a_conflict(
    youtube_client: TestClient,
    connected: dict[str, Any],
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import youtube_connections

    # Simulate a concurrent request that passed the code-level check first.
    monkeypatch.setattr(
        youtube_connections, "ensure_channel_available", lambda *args: None
    )
    second = create_account(youtube_client, connected["project_id"], "youtube", "dup")
    secrets_before = dict(credential_store.secrets)
    body, state = authorize(youtube_client, second["id"])

    complete_callback(youtube_client, state)

    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["error"]["code"] == "channel_already_connected"
    assert credential_store.secrets == secrets_before
    assert get_connection(youtube_client, second["id"])["status"] == "not_connected"
