"""Disconnecting a TikTok account (US4): official revocation, honest outcomes
(`revoked` only when TikTok confirmed it) and the explicit local removal."""

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.tiktok_connections import get_valid_credentials
from tests.conftest import (
    connect_tiktok,
    create_account,
    create_publications,
    create_tiktok_account,
    get_tiktok_connection,
    import_one,
    make_image,
    run_sql,
    tiktok_rows,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_CLIENT_KEY,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    TT_ACCESS_SECONDS,
    TT_REFRESH_SECONDS,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)

# Leaves 3 minutes of access token: inside EXPIRY_MARGIN.
NOT_USABLE = TT_ACCESS_SECONDS - 180


@pytest.fixture
def connected(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> tuple[int, dict[str, Any]]:
    """(project_id, account) of a connected TikTok account."""
    project_id, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    fake_tiktok.requests.clear()
    return project_id, account


@pytest.fixture
def account_id(connected: tuple[int, dict[str, Any]]) -> int:
    return int(connected[1]["id"])


def _disconnect(client: TestClient, account_id: int) -> Any:
    return client.post(f"/api/accounts/{account_id}/tiktok-connection/disconnect")


def _remove_local(client: TestClient, account_id: int) -> Any:
    return client.post(f"/api/accounts/{account_id}/tiktok-connection/remove-local")


def _ok(response: Any, revocation: str) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["revocation"] == revocation
    assert body["connection"]["status"] == "not_connected"
    assert body["connection"]["identity"] is None
    return body


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error: dict[str, Any] = response.json()["error"]
    assert error["code"] == code
    return error


def _snapshot(
    store: InMemoryCredentialStore, db_path: Path
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    return dict(store.secrets), tiktok_rows(db_path)


# --- Revocation confirmed -----------------------------------------------------------


@pytest.mark.parametrize("answer", [None, "empty_body"])
@pytest.mark.parametrize("status", ["connected", "reconnect_required"])
def test_confirmed_revocation_deletes_secret_then_row(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str | None,
    status: str,
) -> None:
    project_id, account = create_tiktok_account(tiktok_client)
    content = import_one(tiktok_client, project_id, "a.png", make_image())
    [publication] = create_publications(
        tiktok_client, content["content"]["id"], [account["id"]]
    )
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    run_sql(db_path, "UPDATE tiktok_connections SET status = ?", status)
    fake_tiktok.requests.clear()
    if answer is not None:
        fake_tiktok.faults["revoke"] = answer
    rows_when_deleting: list[int] = []
    original_delete = tiktok_credential_store.delete

    def delete(ref: str) -> None:
        rows_when_deleting.append(len(tiktok_rows(db_path)))
        original_delete(ref)

    monkeypatch.setattr(tiktok_credential_store, "delete", delete)

    _ok(_disconnect(tiktok_client, account["id"]), "revoked")

    [revoke] = fake_tiktok.requests
    assert revoke.form == {
        "client_key": FAKE_TT_CLIENT_KEY,
        "client_secret": FAKE_TT_CLIENT_SECRET,
        "token": FAKE_TT_ACCESS_TOKEN,
    }
    assert rows_when_deleting == [1]  # the secret goes first, then the row
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    accounts = tiktok_client.get(f"/api/projects/{project_id}/accounts").json()
    assert accounts == [account]
    assert tiktok_client.get(f"/api/publications/{publication['id']}").json() == (
        publication
    )
    assert get_tiktok_connection(tiktok_client, account["id"])["status"] == (
        "not_connected"
    )


def test_access_token_inside_the_margin_is_renewed_before_revoking(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_clock.advance(NOT_USABLE)
    stored_at_delete: list[str] = []
    original_delete = tiktok_credential_store.delete

    def delete(ref: str) -> None:
        secret = json.loads(tiktok_credential_store.secrets[ref])
        stored_at_delete.append(secret["access_token"])
        original_delete(ref)

    monkeypatch.setattr(tiktok_credential_store, "delete", delete)

    _ok(_disconnect(tiktok_client, account_id), "revoked")

    assert fake_tiktok.calls() == ["refresh", "revoke"]
    assert fake_tiktok.requests_to("revoke")[0].form["token"] == (
        FAKE_TT_REFRESHED_ACCESS_TOKEN
    )
    # The renewed credential was persisted before revoking.
    assert stored_at_delete == [FAKE_TT_REFRESHED_ACCESS_TOKEN]
    assert tiktok_credential_store.secrets == {}


# --- Credential invalid according to TikTok -----------------------------------------


# The real Sandbox answers a revoked authorization with HTTP 200 and
# `error=invalid_grant` (V-17).
@pytest.mark.parametrize(
    "fault",
    ["oauth200_invalid_grant", "oauth_invalid_grant", "api_access_token_invalid"],
)
def test_revoke_rejecting_the_credential_is_already_invalid(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    fault: str,
) -> None:
    fake_tiktok.faults["revoke"] = fault

    _ok(_disconnect(tiktok_client, account_id), "already_invalid")

    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []


def test_expired_authorization_is_already_invalid_without_calling_tiktok(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(TT_REFRESH_SECONDS + 1)

    _ok(_disconnect(tiktok_client, account_id), "already_invalid")

    assert fake_tiktok.requests == []
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []


def test_rejected_renewal_before_revoking_is_already_invalid(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(NOT_USABLE)
    fake_tiktok.faults["refresh"] = "oauth_invalid_grant"

    _ok(_disconnect(tiktok_client, account_id), "already_invalid")

    assert fake_tiktok.calls() == ["refresh"]
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []


# --- Revocation not confirmed: nothing is deleted -----------------------------------


@pytest.mark.parametrize(
    "fault",
    [
        "transport",
        "timeout",
        "server_error",
        "rate_limited",
        "oauth_invalid_client",
        "oauth_invalid_request",
        "oauth200_server_error",
        "bad_json",
    ],
)
def test_ambiguous_revocation_keeps_everything(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    fault: str,
) -> None:
    before = _snapshot(tiktok_credential_store, db_path)
    fake_tiktok.faults["revoke"] = fault

    error = _error(_disconnect(tiktok_client, account_id), 503, "tiktok_revoke_failed")

    assert "locally" in error["message"]
    assert _snapshot(tiktok_credential_store, db_path) == before


def test_temporary_renewal_failure_before_revoking(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    before = _snapshot(tiktok_credential_store, db_path)
    fake_clock.advance(NOT_USABLE)
    fake_tiktok.faults["refresh"] = "server_error"

    _error(_disconnect(tiktok_client, account_id), 503, "tiktok_revoke_failed")

    assert fake_tiktok.calls() == ["refresh"]
    assert _snapshot(tiktok_credential_store, db_path) == before


def test_missing_config_keeps_everything(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    tiktok_app_file: Path,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    before = _snapshot(tiktok_credential_store, db_path)
    tiktok_app_file.unlink()

    _error(_disconnect(tiktok_client, account_id), 503, "tiktok_revoke_failed")

    assert fake_tiktok.requests == []
    assert _snapshot(tiktok_credential_store, db_path) == before


# --- The three local failures, asserted distinctly ----------------------------------


@pytest.mark.parametrize("secret_state", ["missing", "unreadable"])
def test_secret_missing_is_reported_without_contacting_tiktok(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    secret_state: str,
) -> None:
    ref = tiktok_rows(db_path)[0]["credential_ref"]
    if secret_state == "missing":
        del tiktok_credential_store.secrets[ref]
    else:
        tiktok_credential_store.secrets[ref] = "{broken"
    before = _snapshot(tiktok_credential_store, db_path)

    error = _error(
        _disconnect(tiktok_client, account_id), 409, "tiktok_credential_missing"
    )

    assert "Manage app permissions" in error["message"]
    assert fake_tiktok.requests == []
    assert _snapshot(tiktok_credential_store, db_path) == before


def test_store_unavailable_changes_nothing(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    before = _snapshot(tiktok_credential_store, db_path)
    tiktok_credential_store.unavailable = True

    _error(_disconnect(tiktok_client, account_id), 503, "credential_store_unavailable")

    assert fake_tiktok.requests == []
    tiktok_credential_store.unavailable = False
    assert _snapshot(tiktok_credential_store, db_path) == before


def test_secret_delete_failure_after_revoking_keeps_the_row(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    tiktok_credential_store.fail_on = {"delete"}

    _error(_disconnect(tiktok_client, account_id), 503, "credential_store_unavailable")

    assert fake_tiktok.calls() == ["revoke"]
    assert len(tiktok_rows(db_path)) == 1


# --- Idempotence, inactive entities and concurrency ---------------------------------


def test_not_connected_is_idempotent(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok, account_id: int
) -> None:
    _ok(_disconnect(tiktok_client, account_id), "revoked")

    _ok(_disconnect(tiktok_client, account_id), "not_connected")
    _ok(_remove_local(tiktok_client, account_id), "not_connected")

    assert fake_tiktok.calls() == ["revoke"]


@pytest.mark.parametrize("entity", ["account", "project"])
def test_inactive_entities_can_disconnect_including_the_renewal(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
    entity: str,
) -> None:
    project_id, account = connected
    table = "accounts" if entity == "account" else "projects"
    run_sql(
        db_path,
        f"UPDATE {table} SET is_active = 0 WHERE id = ?",
        account["id"] if entity == "account" else project_id,
    )
    fake_clock.advance(NOT_USABLE)

    _ok(_disconnect(tiktok_client, account["id"]), "revoked")

    assert fake_tiktok.calls() == ["refresh", "revoke"]
    assert tiktok_credential_store.secrets == {}


def test_concurrent_disconnect_waits_for_a_renewal(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    app = tiktok_client.app
    assert isinstance(app, FastAPI)
    fake_clock.advance(TT_ACCESS_SECONDS - 1800)
    renewing = threading.Event()

    def slow_refresh() -> None:
        renewing.set()
        time.sleep(0.3)

    fake_tiktok.refresh_hook = slow_refresh

    def renew() -> None:
        with app.state.session_factory() as session:
            get_valid_credentials(
                session,
                app.state.tiktok_credential_store,
                app.state.tiktok_gateway,
                account_id,
            )

    renewal = threading.Thread(target=renew)
    renewal.start()
    assert renewing.wait(5)
    response = _disconnect(tiktok_client, account_id)
    renewal.join()

    _ok(response, "revoked")
    # The disconnect ran after the renewal and revoked the renewed token.
    assert fake_tiktok.calls() == ["refresh", "revoke"]
    assert fake_tiktok.requests_to("revoke")[0].form["token"] == (
        FAKE_TT_REFRESHED_ACCESS_TOKEN
    )
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []


# --- Remove locally without revoking ------------------------------------------------


def test_remove_locally_after_a_failed_revocation(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    connected: tuple[int, dict[str, Any]],
) -> None:
    project_id, account = connected
    fake_tiktok.faults["revoke"] = "server_error"
    _error(_disconnect(tiktok_client, account["id"]), 503, "tiktok_revoke_failed")
    calls_before = fake_tiktok.calls()

    _ok(_remove_local(tiktok_client, account["id"]), "not_revoked")

    assert fake_tiktok.calls() == calls_before  # TikTok is never contacted
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    accounts = tiktok_client.get(f"/api/projects/{project_id}/accounts").json()
    assert accounts == [account]


def test_remove_locally_after_a_missing_secret(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    tiktok_credential_store.secrets.clear()
    _error(_disconnect(tiktok_client, account_id), 409, "tiktok_credential_missing")

    _ok(_remove_local(tiktok_client, account_id), "not_revoked")

    assert fake_tiktok.requests == []
    assert tiktok_rows(db_path) == []


def test_remove_locally_with_store_unavailable_changes_nothing(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    account_id: int,
) -> None:
    before = _snapshot(tiktok_credential_store, db_path)
    tiktok_credential_store.unavailable = True

    _error(
        _remove_local(tiktok_client, account_id), 503, "credential_store_unavailable"
    )

    tiktok_credential_store.unavailable = False
    assert _snapshot(tiktok_credential_store, db_path) == before


@pytest.mark.parametrize("route", ["disconnect", "remove-local"])
def test_other_platforms_are_rejected(tiktok_client: TestClient, route: str) -> None:
    project_id, _ = create_tiktok_account(tiktok_client)
    other = create_account(tiktok_client, project_id, "threads", "other")

    response = tiktok_client.post(
        f"/api/accounts/{other['id']}/tiktok-connection/{route}"
    )

    _error(response, 409, "platform_not_supported")
