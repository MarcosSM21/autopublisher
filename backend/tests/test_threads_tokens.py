"""Threads token lifecycle (`get_valid_credentials`, US4): AutoPublisher's renewal
policy, consistency between the secret and SQLite, and the inspection after a refresh.

These service tests use `StubThreadsGateway`, which raises the gateway's semantic
exceptions directly: the policy never depends on Meta's error numbers.
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import threads_connections
from app.errors import AppError
from app.threads_connections import get_valid_credentials
from app.threads_gateway import (
    ThreadsPermissionDenied,
    ThreadsRejected,
    ThreadsToken,
    ThreadsTokenInfo,
    ThreadsTokenInvalid,
    ThreadsUnavailable,
    ThreadsUnexpectedResponse,
)
from tests.conftest import (
    connect_threads,
    create_threads_account,
    get_threads_connection,
    run_sql,
    threads_rows,
)
from tests.fakes import (
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REFRESHED_TOKEN,
    LONG_LIVED_SECONDS,
    TH_ALL_SCOPES,
    TH_BASIC,
    TH_PUBLISH,
    TH_USER_ID,
    FakeClock,
    FakeThreads,
    InMemoryCredentialStore,
    StubThreadsGateway,
)

DAY = timedelta(days=1).total_seconds()
# A 60-day token enters the 7-day renewal window after 53 days.
IN_WINDOW = 54 * DAY


@pytest.fixture
def account_id(threads_client: TestClient) -> int:
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    return int(account["id"])


@pytest.fixture
def stub(fake_clock: FakeClock) -> StubThreadsGateway:
    return StubThreadsGateway(fake_clock)


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _credentials(
    client: TestClient, gateway: StubThreadsGateway, account_id: int
) -> ThreadsToken:
    app = _app(client)
    with app.state.session_factory() as session:
        return get_valid_credentials(
            session,
            app.state.threads_credential_store,
            gateway,  # type: ignore[arg-type]
            account_id,
        )


def _fails(
    client: TestClient, gateway: StubThreadsGateway, account_id: int
) -> AppError:
    with pytest.raises(AppError) as raised:
        _credentials(client, gateway, account_id)
    return raised.value


def _row(db_path: Path) -> dict[str, Any]:
    (row,) = threads_rows(db_path)
    return row


def _secret(store: InMemoryCredentialStore, db_path: Path) -> dict[str, Any]:
    secret: dict[str, Any] = json.loads(store.secrets[_row(db_path)["credential_ref"]])
    return secret


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


# --- Renewal policy (plan scenarios 1–7 and 12) --------------------------------------


def test_token_outside_the_window_is_not_refreshed(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    # Older than 24 h but with more than 7 days left: no refresh.
    fake_clock.advance(2 * DAY)

    token = _credentials(threads_client, stub, account_id)

    assert token.access_token == FAKE_TH_LONG_TOKEN
    assert stub.calls == []


def test_token_inside_the_window_is_refreshed(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    before = _row(db_path)
    fake_clock.advance(IN_WINDOW)

    token = _credentials(threads_client, stub, account_id)

    now = fake_clock.now()
    expected_expiry = now + timedelta(seconds=LONG_LIVED_SECONDS)
    assert token.access_token == FAKE_TH_REFRESHED_TOKEN
    assert token.token_obtained_at == now
    assert token.expires_at == expected_expiry
    # The renewed token is inspected right away.
    assert stub.calls == ["refresh", "debug"]
    after = _row(db_path)
    assert after["credential_ref"] == before["credential_ref"]
    secret = _secret(threads_credential_store, db_path)
    assert secret["access_token"] == FAKE_TH_REFRESHED_TOKEN
    assert datetime.fromisoformat(secret["token_obtained_at"]) == now
    assert datetime.fromisoformat(secret["expires_at"]) == expected_expiry
    read = get_threads_connection(threads_client, account_id)
    assert read["token_obtained_at"] == _iso(now)
    assert read["access_expires_at"] == _iso(expected_expiry)

    # The renewed token is far from its expiry again: no second refresh.
    _credentials(threads_client, stub, account_id)
    assert stub.calls == ["refresh", "debug"]


def test_young_token_inside_the_window_is_used_while_valid(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    fake_threads.expires_in = int(5 * DAY)
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    fake_clock.advance(DAY / 2)

    token = _credentials(threads_client, stub, account["id"])

    assert token.access_token == FAKE_TH_LONG_TOKEN
    assert stub.calls == []


def test_young_token_inside_the_margin_requires_reconnection(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    # Not renewable yet (< 24 h, Meta's condition) and about to expire (AutoPublisher's
    # safety margin).
    fake_threads.expires_in = 600
    _, account = create_threads_account(threads_client)
    connect_threads(threads_client, account["id"])
    fake_clock.advance(360)

    error = _fails(threads_client, stub, account["id"])

    assert error.code == "threads_reconnect_required"
    assert stub.calls == []
    assert _row(db_path)["status"] == "reconnect_required"


@pytest.mark.parametrize("failure", [ThreadsUnavailable(), ThreadsUnexpectedResponse()])
def test_transient_refresh_failure_with_valid_token_returns_current_token(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
) -> None:
    secrets_before = dict(threads_credential_store.secrets)
    fake_clock.advance(IN_WINDOW)
    stub.refresh_error = failure

    with caplog.at_level(logging.WARNING):
        token = _credentials(threads_client, stub, account_id)

    assert token.access_token == FAKE_TH_LONG_TOKEN
    assert _row(db_path)["status"] == "connected"
    assert threads_credential_store.secrets == secrets_before
    assert "temporary" in caplog.text
    assert FAKE_TH_LONG_TOKEN not in caplog.text


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (ThreadsUnavailable(), "threads_unavailable"),
        (ThreadsUnexpectedResponse(), "threads_unexpected_response"),
    ],
)
def test_transient_failure_inside_the_margin_is_an_error(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    failure: Exception,
    code: str,
) -> None:
    fake_clock.advance(LONG_LIVED_SECONDS - 120)
    stub.refresh_error = failure

    error = _fails(threads_client, stub, account_id)

    assert error.code == code
    assert _row(db_path)["status"] == "connected"


def test_expired_token_requires_reconnection_without_calling_meta(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(61 * DAY)

    error = _fails(threads_client, stub, account_id)

    assert error.code == "threads_reconnect_required"
    assert stub.calls == []
    row = _row(db_path)
    assert row["status"] == "reconnect_required"
    assert row["threads_user_id"] == TH_USER_ID


@pytest.mark.parametrize(
    "failure",
    [ThreadsTokenInvalid(), ThreadsPermissionDenied(TH_PUBLISH), ThreadsRejected()],
)
def test_definitive_refresh_rejection_requires_reconnection(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    failure: Exception,
) -> None:
    fake_clock.advance(IN_WINDOW)
    stub.refresh_error = failure

    error = _fails(threads_client, stub, account_id)

    assert error.code == "threads_reconnect_required"
    if isinstance(failure, ThreadsPermissionDenied):
        assert TH_PUBLISH in error.message
    row = _row(db_path)
    assert row["status"] == "reconnect_required"
    assert row["username"] == "cyber.studio"


@pytest.mark.parametrize("secret", [None, "not json", '{"access_token": "x"}'])
def test_missing_or_unreadable_secret_requires_reconnection(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    db_path: Path,
    account_id: int,
    secret: str | None,
) -> None:
    ref = _row(db_path)["credential_ref"]
    if secret is None:
        del threads_credential_store.secrets[ref]
    else:
        threads_credential_store.secrets[ref] = secret

    error = _fails(threads_client, stub, account_id)

    assert error.code == "threads_reconnect_required"
    assert _row(db_path)["status"] == "reconnect_required"


def test_store_unavailable_does_not_change_the_status(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    db_path: Path,
    account_id: int,
) -> None:
    threads_credential_store.unavailable = True

    error = _fails(threads_client, stub, account_id)

    assert error.code == "credential_store_unavailable"
    assert _row(db_path)["status"] == "connected"


def test_concurrent_calls_refresh_once(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(IN_WINDOW)
    stub.refresh_delay = 0.2
    tokens: list[str] = []

    def worker() -> None:
        tokens.append(_credentials(threads_client, stub, account_id).access_token)

    workers = [threading.Thread(target=worker) for _ in range(3)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()

    assert stub.calls.count("refresh") == 1
    assert tokens == [FAKE_TH_REFRESHED_TOKEN] * 3


def test_renewal_window_comes_from_the_module_constant(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_clock.advance(51 * DAY)  # 9 days left
    _credentials(threads_client, stub, account_id)
    assert stub.calls == []

    monkeypatch.setattr(threads_connections, "RENEWAL_WINDOW", timedelta(days=10))
    _credentials(threads_client, stub, account_id)

    assert stub.calls == ["refresh", "debug"]


# --- Consistency between the secret and SQLite (plan scenarios 8–11) ----------------


class _FailingCommits:
    """Replacement for `threads_connections._commit` failing the first N calls."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0
        self.original = threads_connections._commit

    def __call__(self, session: Any) -> None:
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("database is locked")
        self.original(session)


def test_renewed_secret_with_failed_commit_keeps_the_new_token(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = _row(db_path)
    fake_clock.advance(IN_WINDOW)
    monkeypatch.setattr(threads_connections, "_commit", _FailingCommits(1))

    with caplog.at_level(logging.WARNING):
        token = _credentials(threads_client, stub, account_id)

    # The new token is returned and stays in the secret: never the old one.
    assert token.access_token == FAKE_TH_REFRESHED_TOKEN
    secret = _secret(threads_credential_store, db_path)
    assert secret["access_token"] == FAKE_TH_REFRESHED_TOKEN
    # SQLite still holds the old metadata; the status is unchanged.
    after = _row(db_path)
    assert after["token_obtained_at"] == before["token_obtained_at"]
    assert after["credential_expires_at"] == before["credential_expires_at"]
    assert after["status"] == "connected"
    assert FAKE_TH_REFRESHED_TOKEN not in caplog.text

    # Next access: the secret is read first, SQLite repaired, no second refresh.
    monkeypatch.setattr(threads_connections, "_commit", _FailingCommits(0).original)
    again = _credentials(threads_client, stub, account_id)
    assert again.access_token == FAKE_TH_REFRESHED_TOKEN
    assert stub.calls == ["refresh", "debug"]
    repaired = _row(db_path)
    assert datetime.fromisoformat(secret["token_obtained_at"]) == fake_clock.now()
    read = get_threads_connection(threads_client, account_id)
    assert read["token_obtained_at"] == _iso(fake_clock.now())
    assert read["access_expires_at"] == _iso(
        fake_clock.now() + timedelta(seconds=LONG_LIVED_SECONDS)
    )

    # Idempotent: further accesses change nothing and commit nothing.
    counting = _FailingCommits(0)
    monkeypatch.setattr(threads_connections, "_commit", counting)
    for _ in range(2):
        _credentials(threads_client, stub, account_id)
    assert counting.calls == 0
    assert _row(db_path) == repaired
    assert stub.calls == ["refresh", "debug"]


def test_failed_repair_is_logged_and_the_token_still_returned(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_sql(
        db_path,
        "UPDATE threads_connections SET token_obtained_at = '2020-01-01 00:00:00'",
    )
    monkeypatch.setattr(threads_connections, "_commit", _FailingCommits(1))

    with caplog.at_level(logging.WARNING):
        token = _credentials(threads_client, stub, account_id)

    assert token.access_token == FAKE_TH_LONG_TOKEN
    assert "repair" in caplog.text
    assert stub.calls == []


@pytest.fixture
def stale_expiry(db_path: Path, account_id: int) -> int:
    """SQLite says the token expired, as after a renewal whose commit failed."""
    run_sql(
        db_path,
        "UPDATE threads_connections SET credential_expires_at = '2020-01-01 00:00:00'",
    )
    return account_id


def test_get_repairs_a_stale_expiry_from_a_valid_secret(
    threads_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    stale_expiry: int,
) -> None:
    requests_before = len(fake_threads.requests)

    read = get_threads_connection(threads_client, stale_expiry)

    assert read["status"] == "connected"
    assert read["access_expires_at"] == _iso(
        fake_clock.now() + timedelta(seconds=LONG_LIVED_SECONDS)
    )
    assert len(fake_threads.requests) == requests_before


def test_get_with_stale_expiry_and_unavailable_store_changes_nothing(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    stale_expiry: int,
) -> None:
    threads_credential_store.unavailable = True

    read = get_threads_connection(threads_client, stale_expiry)

    assert read["status"] == "connected"
    assert _row(db_path)["status"] == "connected"


@pytest.mark.parametrize("secret_state", ["expired", "missing"])
def test_get_with_expiry_confirmed_by_the_secret(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    stale_expiry: int,
    secret_state: str,
) -> None:
    ref = _row(db_path)["credential_ref"]
    if secret_state == "missing":
        del threads_credential_store.secrets[ref]
    else:
        secret = json.loads(threads_credential_store.secrets[ref])
        secret["expires_at"] = "2020-01-01T00:00:00+00:00"
        threads_credential_store.secrets[ref] = json.dumps(secret)

    read = get_threads_connection(threads_client, stale_expiry)

    assert read["status"] == "reconnect_required"


# --- data_access_expires_at and the inspection after a refresh (13–15) --------------


def test_stale_data_access_expiry_never_breaks_the_connection(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    run_sql(
        db_path,
        "UPDATE threads_connections SET data_access_expires_at = '2020-01-01 00:00:00'",
    )
    # Before the refresh: the past date is shown but does not change the status.
    read = get_threads_connection(threads_client, account_id)
    assert read["status"] == "connected"
    assert read["data_access_expires_at"] == "2020-01-01T00:00:00Z"
    fake_clock.advance(2 * DAY)
    assert (
        _credentials(threads_client, stub, account_id).access_token
        == FAKE_TH_LONG_TOKEN
    )

    # The token enters the window and is renewed; Meta reports the extended grant.
    extended = fake_clock.now() + timedelta(days=150)
    stub.debug_info = ThreadsTokenInfo(
        True, TH_USER_ID, frozenset(TH_ALL_SCOPES), extended
    )
    fake_clock.advance(IN_WINDOW)
    token = _credentials(threads_client, stub, account_id)

    assert token.access_token == FAKE_TH_REFRESHED_TOKEN
    read = get_threads_connection(threads_client, account_id)
    assert read["status"] == "connected"
    # The official value, never a date computed by adding 90 days.
    assert read["data_access_expires_at"] == _iso(extended)
    assert _row(db_path)["status"] == "connected"


@pytest.mark.parametrize("failure", [ThreadsUnavailable(), ThreadsRejected()])
def test_transient_inspection_failure_keeps_the_new_token(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    failure: Exception,
) -> None:
    before = _row(db_path)
    fake_clock.advance(IN_WINDOW)
    stub.debug_error = failure

    token = _credentials(threads_client, stub, account_id)

    assert token.access_token == FAKE_TH_REFRESHED_TOKEN
    secret = _secret(threads_credential_store, db_path)
    assert secret["access_token"] == FAKE_TH_REFRESHED_TOKEN
    assert secret["scopes"] == TH_ALL_SCOPES
    after = _row(db_path)
    assert after["status"] == "connected"
    assert after["data_access_expires_at"] == before["data_access_expires_at"]


@pytest.mark.parametrize(
    ("info", "error", "code"),
    [
        (
            ThreadsTokenInfo(False, TH_USER_ID, frozenset(TH_ALL_SCOPES), None),
            None,
            "threads_reconnect_required",
        ),
        (
            ThreadsTokenInfo(True, TH_USER_ID, frozenset({TH_BASIC}), None),
            None,
            "threads_reconnect_required",
        ),
        (
            ThreadsTokenInfo(True, "other-user", frozenset(TH_ALL_SCOPES), None),
            None,
            "threads_identity_mismatch",
        ),
        (None, ThreadsTokenInvalid(), "threads_reconnect_required"),
        (None, ThreadsPermissionDenied(), "threads_reconnect_required"),
    ],
)
def test_definitive_inspection_signal_requires_reconnection(
    threads_client: TestClient,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    info: ThreadsTokenInfo | None,
    error: Exception | None,
    code: str,
) -> None:
    fake_clock.advance(IN_WINDOW)
    if info is not None:
        stub.debug_info = info
    stub.debug_error = error

    failure = _fails(threads_client, stub, account_id)

    assert failure.code == code
    row = _row(db_path)
    assert row["status"] == "reconnect_required"
    assert row["threads_user_id"] == TH_USER_ID


def test_failed_scopes_write_after_refresh_keeps_the_new_token(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    extended = fake_clock.now() + timedelta(days=150)
    stub.debug_info = ThreadsTokenInfo(
        True,
        TH_USER_ID,
        frozenset({*TH_ALL_SCOPES, "threads_read_replies"}),
        extended,
    )
    original_set = threads_credential_store.set
    writes: list[str] = []

    def second_write_fails(ref: str, value: str) -> None:
        writes.append(ref)
        if len(writes) == 2:
            threads_credential_store.fail_on = {"set"}
        try:
            original_set(ref, value)
        finally:
            threads_credential_store.fail_on = set()

    monkeypatch.setattr(threads_credential_store, "set", second_write_fails)
    fake_clock.advance(IN_WINDOW)

    with caplog.at_level(logging.WARNING):
        token = _credentials(threads_client, stub, account_id)

    assert len(writes) == 2  # the renewed token, then the failed scopes update
    assert token.access_token == FAKE_TH_REFRESHED_TOKEN
    secret = _secret(threads_credential_store, db_path)
    assert secret["access_token"] == FAKE_TH_REFRESHED_TOKEN
    assert secret["scopes"] == TH_ALL_SCOPES  # last known scopes kept
    row = _row(db_path)
    assert row["status"] == "connected"
    # The non-sensitive official metadata is still saved.
    read = get_threads_connection(threads_client, account_id)
    assert read["data_access_expires_at"] == _iso(extended)
    assert "scopes" in caplog.text
    assert FAKE_TH_REFRESHED_TOKEN not in caplog.text


def test_changed_scopes_after_refresh_are_stored(
    threads_client: TestClient,
    threads_credential_store: InMemoryCredentialStore,
    stub: StubThreadsGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    scopes = frozenset({*TH_ALL_SCOPES, "threads_read_replies"})
    stub.debug_info = ThreadsTokenInfo(True, TH_USER_ID, scopes, None)
    fake_clock.advance(IN_WINDOW)

    token = _credentials(threads_client, stub, account_id)

    assert token.scopes == scopes
    secret = _secret(threads_credential_store, db_path)
    assert secret["scopes"] == sorted(scopes)
    assert secret["access_token"] == FAKE_TH_REFRESHED_TOKEN
    assert datetime.fromisoformat(secret["token_obtained_at"]) == fake_clock.now()
    assert _row(db_path)["data_access_expires_at"] is None
