"""Reconnecting a TikTok account (US5): a new credential reference replaces the old
one in a crash-safe order, and a different TikTok account is only linked after an
explicit confirmation."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import tiktok_connections
from app.config import TIKTOK_ATTEMPT_TTL
from app.credential_store import CredentialStoreUnavailable
from tests.conftest import (
    connect_tiktok,
    create_tiktok_account,
    get_tiktok_connection,
    poll_tiktok_attempt,
    run_sql,
    start_tiktok_authorization,
    tiktok_callback,
    tiktok_rows,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_OPEN_ID,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)

RESULT = "/api/tiktok/oauth/result?outcome="
OTHER_OPEN_ID = "-000fake-tt-other-open-id-b52e90"


@pytest.fixture
def account_id(tiktok_client: TestClient, fake_tiktok: FakeTikTok) -> int:
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    fake_tiktok.requests.clear()
    return int(account["id"])


def _row(db_path: Path) -> dict[str, Any]:
    (row,) = tiktok_rows(db_path)
    return row


def _orphans(db_path: Path) -> list[dict[str, Any]]:
    return tiktok_rows(db_path, "pending_credential_deletions")


def _reconnect(
    client: TestClient, account_id: int, fake_tiktok: FakeTikTok, outcome: str
) -> str:
    attempt_id, state, _ = start_tiktok_authorization(client, account_id, fake_tiktok)
    response = tiktok_callback(client, state)
    assert response.status_code == 303
    assert response.headers["location"] == RESULT + outcome
    return attempt_id


def _awaiting(client: TestClient, account_id: int, fake_tiktok: FakeTikTok) -> str:
    """Reconnect with another TikTok account: the attempt waits for confirmation."""
    fake_tiktok.open_id = OTHER_OPEN_ID
    fake_tiktok.display_name = "Other Studio"
    fake_tiktok.avatar_url = "https://p16-sign.tiktokcdn.example/other.jpeg"
    attempt_id = _reconnect(client, account_id, fake_tiktok, "confirm_required")
    fake_tiktok.requests.clear()
    return attempt_id


def _confirm(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/confirm")


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error: dict[str, Any] = response.json()["error"]
    assert error["code"] == code
    return error


# --- Same TikTok account ------------------------------------------------------------


@pytest.mark.parametrize("status", ["connected", "reconnect_required"])
def test_reconnecting_the_same_account_replaces_the_credential(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    run_sql(db_path, "UPDATE tiktok_connections SET status = ?", status)
    before = _row(db_path)
    fake_clock.advance(60)
    refs_when_deleting: list[str] = []
    original_delete = tiktok_credential_store.delete

    def delete(ref: str) -> None:
        refs_when_deleting.append(_row(db_path)["credential_ref"])
        original_delete(ref)

    monkeypatch.setattr(tiktok_credential_store, "delete", delete)

    _reconnect(tiktok_client, account_id, fake_tiktok, "connected")

    after = _row(db_path)
    assert after["status"] == "connected"
    assert after["credential_ref"] != before["credential_ref"]
    assert after["connected_at"] != before["connected_at"]
    # The old secret is deleted only once the new reference is committed.
    assert refs_when_deleting == [after["credential_ref"]]
    assert list(tiktok_credential_store.secrets) == [after["credential_ref"]]
    assert _orphans(db_path) == []
    assert fake_tiktok.requests_to("revoke") == []


def test_commit_failure_keeps_the_previous_connection(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _row(db_path)
    secrets_before = dict(tiktok_credential_store.secrets)

    def failing_write(*args: Any) -> None:
        raise RuntimeError("disk full")  # inside the final write_transaction

    monkeypatch.setattr(tiktok_connections, "adopt_connected_identity", failing_write)

    attempt_id = _reconnect(tiktok_client, account_id, fake_tiktok, "failed")

    assert poll_tiktok_attempt(tiktok_client, attempt_id)["error"]["code"] == (
        "internal_error"
    )
    # New secret deleted; previous row, reference and secret intact; no orphan.
    assert _row(db_path) == before
    assert tiktok_credential_store.secrets == secrets_before
    assert _orphans(db_path) == []


def test_old_secret_delete_failure_leaves_a_registered_orphan(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_ref = _row(db_path)["credential_ref"]
    original_delete = tiktok_credential_store.delete
    original_get = tiktok_credential_store.get
    reads: list[str] = []

    def delete(ref: str) -> None:
        if ref == old_ref:
            raise CredentialStoreUnavailable()
        original_delete(ref)

    def get(ref: str) -> str | None:
        reads.append(ref)
        return original_get(ref)

    monkeypatch.setattr(tiktok_credential_store, "delete", delete)
    monkeypatch.setattr(tiktok_credential_store, "get", get)

    _reconnect(tiktok_client, account_id, fake_tiktok, "connected")

    new_ref = _row(db_path)["credential_ref"]
    assert new_ref != old_ref
    assert [orphan["credential_ref"] for orphan in _orphans(db_path)] == [old_ref]
    # The new connection is valid and usable; the old reference is never read.
    response = tiktok_client.post(
        f"/api/accounts/{account_id}/tiktok-connection/verify"
    )
    assert response.status_code == 200, response.text
    assert old_ref not in reads


# --- Another TikTok account: explicit confirmation ----------------------------------


def test_different_account_waits_for_confirmation(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    before = _row(db_path)
    secrets_before = dict(tiktok_credential_store.secrets)

    attempt_id = _awaiting(tiktok_client, account_id, fake_tiktok)

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["status"] == "awaiting_confirmation"
    assert attempt["current_identity"] == {
        "display_name": "Cyber Studio",
        "avatar_url": "https://p16-sign.tiktokcdn.example/avatar.jpeg",
        "open_id_suffix": FAKE_TT_OPEN_ID[-6:],
    }
    assert attempt["new_identity"] == {
        "display_name": "Other Studio",
        "avatar_url": "https://p16-sign.tiktokcdn.example/other.jpeg",
        "open_id_suffix": OTHER_OPEN_ID[-6:],
    }
    # Nothing changed and nothing was discarded yet.
    assert _row(db_path) == before
    assert tiktok_credential_store.secrets == secrets_before
    assert fake_tiktok.requests == []
    connection = get_tiktok_connection(tiktok_client, account_id)
    assert connection["identity"]["open_id"] == FAKE_TT_OPEN_ID


def test_confirm_links_the_new_account(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    old_ref = _row(db_path)["credential_ref"]
    attempt_id = _awaiting(tiktok_client, account_id, fake_tiktok)

    response = _confirm(tiktok_client, attempt_id)

    assert response.status_code == 200, response.text
    attempt = response.json()
    assert attempt["status"] == "completed"
    assert attempt["connection"]["identity"]["open_id"] == OTHER_OPEN_ID
    row = _row(db_path)
    assert row["open_id"] == OTHER_OPEN_ID
    assert row["display_name"] == "Other Studio"
    assert row["credential_ref"] != old_ref
    assert list(tiktok_credential_store.secrets) == [row["credential_ref"]]
    assert _orphans(db_path) == []
    assert fake_tiktok.requests == []
    _error(
        _confirm(tiktok_client, attempt_id), 409, "tiktok_oauth_attempt_not_confirmable"
    )


@pytest.mark.parametrize("how", ["cancel", "expiry"])
def test_cancelled_or_expired_change_discards_the_credential(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    how: str,
) -> None:
    before = _row(db_path)
    secrets_before = dict(tiktok_credential_store.secrets)
    attempt_id = _awaiting(tiktok_client, account_id, fake_tiktok)

    if how == "cancel":
        response = tiktok_client.post(f"/api/tiktok/oauth/attempts/{attempt_id}/cancel")
        assert response.json()["status"] == "cancelled"
    else:
        fake_clock.advance(TIKTOK_ATTEMPT_TTL.total_seconds() + 1)
        assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "expired"
        _error(_confirm(tiktok_client, attempt_id), 410, "tiktok_oauth_attempt_expired")

    # Never stored, revoked best-effort; the connection is intact.
    [revoke] = fake_tiktok.requests_to("revoke")
    assert revoke.form["token"] == FAKE_TT_ACCESS_TOKEN
    assert _row(db_path) == before
    assert tiktok_credential_store.secrets == secrets_before


def test_connection_changed_since_the_warning(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    attempt_id = _awaiting(tiktok_client, account_id, fake_tiktok)
    response = tiktok_client.post(
        f"/api/accounts/{account_id}/tiktok-connection/remove-local"
    )
    assert response.status_code == 200, response.text

    _error(_confirm(tiktok_client, attempt_id), 410, "tiktok_oauth_attempt_expired")

    # Removing the connection expired the pending change and discarded it.
    assert len(fake_tiktok.requests_to("revoke")) == 1
    assert tiktok_rows(db_path) == []
    assert tiktok_credential_store.secrets == {}


def test_connection_replaced_since_the_warning(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    attempt_id = _awaiting(tiktok_client, account_id, fake_tiktok)
    run_sql(db_path, "UPDATE tiktok_connections SET open_id = 'oid-changed'")

    _error(_confirm(tiktok_client, attempt_id), 409, "tiktok_connection_changed")

    assert len(fake_tiktok.requests_to("revoke")) == 1
    assert _row(db_path)["open_id"] == "oid-changed"
    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "tiktok_connection_changed"


def test_confirm_rechecks_uniqueness(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
) -> None:
    project_id, account = create_tiktok_account(tiktok_client)
    account_id = account["id"]
    connect_tiktok(tiktok_client, account_id, fake_tiktok)
    attempt_id = _awaiting(tiktok_client, account_id, fake_tiktok)
    # Meanwhile the other TikTok account is linked to another account of the project.
    _, holder = create_tiktok_account(
        tiktok_client, handle="holder", project_id=project_id
    )
    connect_tiktok(tiktok_client, holder["id"], fake_tiktok)
    fake_tiktok.requests.clear()

    error = _error(
        _confirm(tiktok_client, attempt_id), 409, "tiktok_account_already_connected"
    )

    assert "@holder" in error["message"]
    assert len(fake_tiktok.requests_to("revoke")) == 1
    connection = get_tiktok_connection(tiktok_client, account_id)
    assert connection["identity"]["open_id"] == FAKE_TT_OPEN_ID


@pytest.mark.parametrize("entity", ["account", "project"])
def test_confirm_rechecks_active_entities(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    entity: str,
) -> None:
    attempt_id = _awaiting(tiktok_client, account_id, fake_tiktok)
    if entity == "account":
        run_sql(db_path, "UPDATE accounts SET is_active = 0 WHERE id = ?", account_id)
    else:
        run_sql(db_path, "UPDATE projects SET is_active = 0")

    _error(_confirm(tiktok_client, attempt_id), 409, f"{entity}_inactive")

    assert len(fake_tiktok.requests_to("revoke")) == 1
    assert _row(db_path)["open_id"] == FAKE_TT_OPEN_ID


def test_confirm_errors(tiktok_client: TestClient, account_id: int) -> None:
    _error(_confirm(tiktok_client, "unknown"), 404, "tiktok_oauth_attempt_not_found")
    attempt_id, _, _ = start_tiktok_authorization(tiktok_client, account_id)
    # A pending attempt is not awaiting any confirmation.
    _error(
        _confirm(tiktok_client, attempt_id), 409, "tiktok_oauth_attempt_not_confirmable"
    )
