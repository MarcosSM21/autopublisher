"""TikTok credential lifecycle (`get_valid_credentials`, US3): the on-demand renewal
policy, refresh-token rotation and the consistency between the secret (source of
truth) and the SQLite mirror — the 15 mandatory cases of plan.md, with the fake TikTok
API, an in-memory store and the fake clock."""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tiktok_connections
from app.credential_store import CredentialStoreUnavailable
from app.errors import AppError
from app.tiktok_connections import get_valid_credentials
from app.tiktok_gateway import TikTokCredential
from tests.conftest import (
    connect_tiktok,
    create_tiktok_account,
    get_tiktok_connection,
    run_sql,
    tiktok_rows,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_CLIENT_KEY,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    FAKE_TT_ROTATED_REFRESH_TOKEN,
    TT_ACCESS_SECONDS,
    TT_BASIC,
    TT_PUBLISH,
    TT_REFRESH_SECONDS,
    TT_UPLOAD,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)

HOUR = 3600.0
# The access token lives 24 h: these leave 2 h, 30 min, 1 h exactly and 3 min.
OUTSIDE_MARGIN = TT_ACCESS_SECONDS - 2 * HOUR
INSIDE_MARGIN = TT_ACCESS_SECONDS - 0.5 * HOUR
AT_MARGIN = TT_ACCESS_SECONDS - HOUR
NOT_USABLE = TT_ACCESS_SECONDS - 180
TEMPORARY_FAULTS = [
    "transport",
    "timeout",
    "server_error",
    "rate_limited",
    "oauth_temporarily_unavailable",
    "oauth200_server_error",
]


@pytest.fixture
def account_id(tiktok_client: TestClient, fake_tiktok: FakeTikTok) -> int:
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    fake_tiktok.requests.clear()
    return int(account["id"])


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _credentials(client: TestClient, account_id: int) -> TikTokCredential:
    app = _app(client)
    with app.state.session_factory() as session:
        return get_valid_credentials(
            session,
            app.state.tiktok_credential_store,
            app.state.tiktok_gateway,
            account_id,
        )


def _fails(client: TestClient, account_id: int) -> AppError:
    with pytest.raises(AppError) as raised:
        _credentials(client, account_id)
    return raised.value


def _row(db_path: Path) -> dict[str, Any]:
    (row,) = tiktok_rows(db_path)
    return row


def _secret(store: InMemoryCredentialStore, db_path: Path) -> dict[str, Any]:
    secret: dict[str, Any] = json.loads(store.secrets[_row(db_path)["credential_ref"]])
    return secret


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class _FailingCommits:
    """Replacement for `tiktok_connections._commit` failing its first `failures`
    calls."""

    original = staticmethod(tiktok_connections._commit)

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self, session: Any) -> None:
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("database is locked")
        self.original(session)


# --- Renewal policy (cases 1–3) -----------------------------------------------------


def test_access_token_outside_the_margin_is_not_renewed(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(OUTSIDE_MARGIN)

    credential = _credentials(tiktok_client, account_id)

    assert credential.access_token == FAKE_TT_ACCESS_TOKEN
    assert fake_tiktok.requests == []


@pytest.mark.parametrize("elapsed", [INSIDE_MARGIN, AT_MARGIN, TT_ACCESS_SECONDS + 60])
def test_access_token_inside_the_margin_or_expired_is_renewed(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    elapsed: float,
) -> None:
    ref = _row(db_path)["credential_ref"]
    fake_clock.advance(elapsed)
    now = fake_clock.now()

    credential = _credentials(tiktok_client, account_id)

    assert credential.access_token == FAKE_TT_REFRESHED_ACCESS_TOKEN
    [request] = fake_tiktok.requests_to("refresh")
    assert request.form == {
        "client_key": FAKE_TT_CLIENT_KEY,
        "client_secret": FAKE_TT_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": FAKE_TT_REFRESH_TOKEN,
    }
    assert fake_tiktok.calls() == ["refresh"]
    # The whole secret is replaced under the same reference.
    assert list(tiktok_credential_store.secrets) == [ref]
    secret = _secret(tiktok_credential_store, db_path)
    assert secret["access_token"] == FAKE_TT_REFRESHED_ACCESS_TOKEN
    assert secret["refresh_token"] == FAKE_TT_ROTATED_REFRESH_TOKEN
    access_expires = now + timedelta(seconds=TT_ACCESS_SECONDS)
    refresh_expires = now + timedelta(seconds=TT_REFRESH_SECONDS)
    assert datetime.fromisoformat(secret["access_expires_at"]) == access_expires
    assert datetime.fromisoformat(secret["refresh_expires_at"]) == refresh_expires
    assert secret["scopes"] == [TT_BASIC, TT_PUBLISH, TT_UPLOAD]
    assert secret["scopes_source"] == "token_refresh"
    assert datetime.fromisoformat(secret["obtained_at"]) == now
    # The SQLite mirror follows the secret; the status is unchanged.
    read = get_tiktok_connection(tiktok_client, account_id)
    assert read["status"] == "connected"
    assert read["access_expires_at"] == _iso(access_expires)
    assert read["refresh_expires_at"] == _iso(refresh_expires)
    assert read["permissions"]["source"] == "token_refresh"
    assert read["permissions"]["confirmed_at"] == _iso(now)


def test_margins_come_from_the_module_constants() -> None:
    assert timedelta(hours=1) == tiktok_connections.REFRESH_MARGIN
    assert timedelta(minutes=5) == tiktok_connections.EXPIRY_MARGIN


# --- Refresh-token rotation (cases 4–5) ---------------------------------------------


def test_rotated_refresh_token_is_used_by_the_next_renewal(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(INSIDE_MARGIN)
    _credentials(tiktok_client, account_id)
    fake_clock.advance(INSIDE_MARGIN)

    _credentials(tiktok_client, account_id)

    first, second = fake_tiktok.requests_to("refresh")
    assert first.form["refresh_token"] == FAKE_TT_REFRESH_TOKEN
    # Never the old one again: TikTok may have invalidated it.
    assert second.form["refresh_token"] == FAKE_TT_ROTATED_REFRESH_TOKEN
    secret = _secret(tiktok_credential_store, db_path)
    assert secret["refresh_token"] == FAKE_TT_ROTATED_REFRESH_TOKEN


def test_non_rotated_refresh_token_is_kept_with_the_returned_expiries(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_tiktok.rotate_refresh_token = False
    fake_tiktok.expires_in = 7200
    fake_tiktok.refresh_expires_in = 3_000_000
    fake_clock.advance(INSIDE_MARGIN)
    now = fake_clock.now()

    _credentials(tiktok_client, account_id)

    secret = _secret(tiktok_credential_store, db_path)
    assert secret["refresh_token"] == FAKE_TT_REFRESH_TOKEN
    assert datetime.fromisoformat(secret["access_expires_at"]) == now + timedelta(
        seconds=7200
    )
    assert datetime.fromisoformat(secret["refresh_expires_at"]) == now + timedelta(
        seconds=3_000_000
    )


# --- Failures of the renewal (cases 6–10, 14) ---------------------------------------


@pytest.mark.parametrize("fault", TEMPORARY_FAULTS)
def test_temporary_failure_with_usable_token_returns_the_current_one(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    fault: str,
) -> None:
    secrets_before = dict(tiktok_credential_store.secrets)
    row_before = _row(db_path)
    fake_tiktok.faults["refresh"] = fault
    fake_clock.advance(INSIDE_MARGIN)

    credential = _credentials(tiktok_client, account_id)

    assert credential.access_token == FAKE_TT_ACCESS_TOKEN
    assert tiktok_credential_store.secrets == secrets_before
    assert _row(db_path) == row_before


@pytest.mark.parametrize("fault", TEMPORARY_FAULTS)
def test_temporary_failure_without_usable_token_is_unavailable(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    fault: str,
) -> None:
    secrets_before = dict(tiktok_credential_store.secrets)
    fake_tiktok.faults["refresh"] = fault
    fake_clock.advance(NOT_USABLE)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (503, "tiktok_unavailable")
    # Never reconnect_required for a temporary failure.
    assert _row(db_path)["status"] == "connected"
    assert tiktok_credential_store.secrets == secrets_before


def test_unexpected_renewal_answer_without_usable_token(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_tiktok.faults["refresh"] = "missing_fields"
    fake_clock.advance(NOT_USABLE)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (502, "tiktok_unexpected_response")
    assert _row(db_path)["status"] == "connected"


def test_invalid_grant_requires_reconnection(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    secrets_before = dict(tiktok_credential_store.secrets)
    fake_tiktok.faults["refresh"] = "oauth_invalid_grant"
    fake_clock.advance(INSIDE_MARGIN)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (409, "tiktok_reconnect_required")
    assert _row(db_path)["status"] == "reconnect_required"
    assert tiktok_credential_store.secrets == secrets_before
    assert get_tiktok_connection(tiktok_client, account_id)["status"] == (
        "reconnect_required"
    )


def test_expired_refresh_token_requires_reconnection_without_calling_tiktok(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(TT_REFRESH_SECONDS + 1)

    error = _fails(tiktok_client, account_id)

    assert error.code == "tiktok_reconnect_required"
    assert "expired" in error.message
    assert _row(db_path)["status"] == "reconnect_required"
    assert fake_tiktok.requests == []


def test_renewal_without_video_publish_requires_reconnection(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_tiktok.refresh_scope = TT_BASIC
    fake_clock.advance(INSIDE_MARGIN)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (409, "tiktok_reconnect_required")
    assert TT_PUBLISH in error.message
    assert _row(db_path)["status"] == "reconnect_required"
    # The secret records what TikTok granted in its last answer.
    assert _secret(tiktok_credential_store, db_path)["scopes"] == [TT_BASIC]
    read = get_tiktok_connection(tiktok_client, account_id)
    assert read["permissions"]["granted"] == [TT_BASIC]


def test_renewal_for_another_open_id_is_an_identity_mismatch(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    secrets_before = dict(tiktok_credential_store.secrets)
    fake_tiktok.refresh_open_id = "oid-someone-else"
    fake_clock.advance(INSIDE_MARGIN)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (409, "tiktok_identity_mismatch")
    assert _row(db_path)["status"] == "reconnect_required"
    # The other identity's credential is never stored.
    assert tiktok_credential_store.secrets == secrets_before


@pytest.mark.parametrize(
    "fault",
    ["oauth_invalid_client", "oauth_unauthorized_client", "oauth200_invalid_request"],
)
def test_client_rejection_changes_nothing(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    fault: str,
) -> None:
    secrets_before = dict(tiktok_credential_store.secrets)
    row_before = _row(db_path)
    fake_tiktok.faults["refresh"] = fault
    fake_clock.advance(INSIDE_MARGIN)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (503, "tiktok_oauth_not_configured")
    assert _row(db_path) == row_before
    assert tiktok_credential_store.secrets == secrets_before


def test_missing_config_when_renewal_is_needed_changes_nothing(
    tiktok_client: TestClient,
    tiktok_app_file: Path,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    row_before = _row(db_path)
    tiktok_app_file.unlink()
    fake_clock.advance(INSIDE_MARGIN)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (503, "tiktok_oauth_not_configured")
    assert _row(db_path) == row_before
    assert fake_tiktok.requests == []


@pytest.mark.parametrize("secret_state", ["missing", "unreadable"])
def test_missing_secret_requires_reconnection(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    secret_state: str,
) -> None:
    ref = _row(db_path)["credential_ref"]
    if secret_state == "missing":
        del tiktok_credential_store.secrets[ref]
    else:
        tiktok_credential_store.secrets[ref] = "{not json"

    error = _fails(tiktok_client, account_id)

    assert error.code == "tiktok_reconnect_required"
    assert _row(db_path)["status"] == "reconnect_required"
    assert fake_tiktok.requests == []


def test_store_unavailable_changes_nothing(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    account_id: int,
) -> None:
    tiktok_credential_store.unavailable = True

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (503, "credential_store_unavailable")
    assert _row(db_path)["status"] == "connected"


@pytest.mark.parametrize("status", ["not_connected", "reconnect_required"])
def test_requires_a_usable_connection(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    status: str,
) -> None:
    _, account = create_tiktok_account(tiktok_client, handle="other")
    if status == "reconnect_required":
        connect_tiktok(tiktok_client, account["id"], fake_tiktok)
        run_sql(db_path, "UPDATE tiktok_connections SET status = 'reconnect_required'")

    error = _fails(tiktok_client, account["id"])

    assert error.code == f"tiktok_{status}"


# --- Consistency between the secret and SQLite (cases 11–12) ------------------------


def test_renewed_secret_with_failed_commit_keeps_the_new_credential(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = _row(db_path)
    fake_clock.advance(INSIDE_MARGIN)
    monkeypatch.setattr(tiktok_connections, "_commit", _FailingCommits(1))

    with caplog.at_level(logging.WARNING):
        credential = _credentials(tiktok_client, account_id)

    # The new credential is returned and stays in the secret: never the old one.
    assert credential.access_token == FAKE_TT_REFRESHED_ACCESS_TOKEN
    secret = _secret(tiktok_credential_store, db_path)
    assert secret["access_token"] == FAKE_TT_REFRESHED_ACCESS_TOKEN
    assert secret["refresh_token"] == FAKE_TT_ROTATED_REFRESH_TOKEN
    after = _row(db_path)
    assert after["access_expires_at"] == before["access_expires_at"]
    assert after["status"] == "connected"
    assert FAKE_TT_REFRESHED_ACCESS_TOKEN not in caplog.text

    # Next access: the secret is read first, the mirror repaired, no second renewal.
    counting = _FailingCommits(0)
    monkeypatch.setattr(tiktok_connections, "_commit", counting)
    again = _credentials(tiktok_client, account_id)
    assert again.access_token == FAKE_TT_REFRESHED_ACCESS_TOKEN
    assert counting.calls == 1
    assert fake_tiktok.calls() == ["refresh"]
    repaired = _row(db_path)
    read = get_tiktok_connection(tiktok_client, account_id)
    assert read["access_expires_at"] == secret["access_expires_at"].replace(
        "+00:00", "Z"
    )

    # Idempotent: further accesses change nothing and commit nothing.
    counting = _FailingCommits(0)
    monkeypatch.setattr(tiktok_connections, "_commit", counting)
    for _ in range(2):
        _credentials(tiktok_client, account_id)
    assert counting.calls == 0
    assert _row(db_path) == repaired
    assert fake_tiktok.calls() == ["refresh"]


def test_store_write_is_retried_once(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tiktok_credential_store.set
    attempts: list[str] = []

    def flaky_set(ref: str, value: str) -> None:
        attempts.append(ref)
        if len(attempts) == 1:
            raise CredentialStoreUnavailable()
        original(ref, value)

    monkeypatch.setattr(tiktok_credential_store, "set", flaky_set)
    fake_clock.advance(INSIDE_MARGIN)

    credential = _credentials(tiktok_client, account_id)

    assert credential.access_token == FAKE_TT_REFRESHED_ACCESS_TOKEN
    assert len(attempts) == 2
    secret = _secret(tiktok_credential_store, db_path)
    assert secret["access_token"] == FAKE_TT_REFRESHED_ACCESS_TOKEN


def test_store_write_failing_twice_keeps_the_previous_secret(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    secrets_before = dict(tiktok_credential_store.secrets)
    row_before = _row(db_path)
    tiktok_credential_store.fail_on = {"set"}
    fake_clock.advance(INSIDE_MARGIN)

    error = _fails(tiktok_client, account_id)

    assert (error.status_code, error.code) == (503, "credential_store_unavailable")
    assert tiktok_credential_store.secrets == secrets_before
    assert _row(db_path) == row_before


# --- Concurrency (case 13) ----------------------------------------------------------


def test_concurrent_renewals_call_tiktok_once(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(INSIDE_MARGIN)
    fake_tiktok.refresh_hook = lambda: time.sleep(0.2)
    tokens: list[str] = []

    def worker() -> None:
        tokens.append(_credentials(tiktok_client, account_id).access_token)

    workers = [threading.Thread(target=worker) for _ in range(3)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()

    # One renewal: a rotated refresh token is never sent twice.
    assert fake_tiktok.calls() == ["refresh"]
    assert tokens == [FAKE_TT_REFRESHED_ACCESS_TOKEN] * 3


# --- GET repair rules (case 15) -----------------------------------------------------


@pytest.fixture
def stale_mirror(db_path: Path, account_id: int) -> int:
    """SQLite says the authorization expired, as after a renewal whose commit
    failed."""
    run_sql(
        db_path,
        "UPDATE tiktok_connections SET refresh_expires_at = '2020-01-01 00:00:00'",
    )
    return account_id


def test_get_repairs_a_stale_mirror_from_a_valid_secret(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    stale_mirror: int,
) -> None:
    read = get_tiktok_connection(tiktok_client, stale_mirror)

    assert read["status"] == "connected"
    secret = _secret(tiktok_credential_store, db_path)
    assert read["refresh_expires_at"] == secret["refresh_expires_at"].replace(
        "+00:00", "Z"
    )
    assert fake_tiktok.requests == []


@pytest.mark.parametrize("secret_state", ["expired", "missing"])
def test_get_with_expiry_confirmed_by_the_secret(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    stale_mirror: int,
    secret_state: str,
) -> None:
    ref = _row(db_path)["credential_ref"]
    if secret_state == "missing":
        del tiktok_credential_store.secrets[ref]
    else:
        secret = json.loads(tiktok_credential_store.secrets[ref])
        secret["refresh_expires_at"] = "2020-01-01T00:00:00+00:00"
        tiktok_credential_store.secrets[ref] = json.dumps(secret)

    read = get_tiktok_connection(tiktok_client, stale_mirror)

    assert read["status"] == "reconnect_required"
    assert _row(db_path)["status"] == "reconnect_required"


def test_get_with_stale_mirror_and_unavailable_store_changes_nothing(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    stale_mirror: int,
) -> None:
    tiktok_credential_store.unavailable = True

    read = get_tiktok_connection(tiktok_client, stale_mirror)

    assert read["status"] == "connected"
    assert read["permissions"] is None
    assert _row(db_path)["status"] == "connected"


def test_get_never_calls_tiktok_nor_renews(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(TT_ACCESS_SECONDS + 60)

    read = get_tiktok_connection(tiktok_client, account_id)

    assert read["status"] == "connected"
    assert fake_tiktok.requests == []
