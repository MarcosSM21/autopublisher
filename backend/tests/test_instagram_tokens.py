"""Instagram token lifecycle (`get_valid_credentials`, US4).

These service tests use `StubInstagramGateway`, which raises the gateway's semantic
exceptions directly: the policy never depends on Meta's error numbers.
"""

import json
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import AppError
from app.instagram_connections import get_valid_credentials
from app.instagram_gateway import (
    InstagramToken,
    MetaPermissionDenied,
    MetaRejected,
    MetaTokenInvalid,
    MetaUnavailable,
)
from tests.conftest import (
    connect_instagram,
    create_instagram_account,
    get_instagram_connection,
    instagram_rows,
)
from tests.fakes import (
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REFRESHED_TOKEN,
    IG_PUBLISH,
    LONG_LIVED_SECONDS,
    FakeClock,
    FakeMeta,
    InMemoryCredentialStore,
    StubInstagramGateway,
)

DAY = timedelta(days=1).total_seconds()


@pytest.fixture
def account_id(instagram_client: TestClient) -> int:
    _, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])
    return int(account["id"])


@pytest.fixture
def stub(fake_clock: FakeClock) -> StubInstagramGateway:
    return StubInstagramGateway(fake_clock)


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _credentials(
    client: TestClient, gateway: StubInstagramGateway, account_id: int
) -> InstagramToken:
    app = _app(client)
    with app.state.session_factory() as session:
        return get_valid_credentials(
            session,
            app.state.instagram_credential_store,
            gateway,  # type: ignore[arg-type]
            account_id,
        )


def _fails(
    client: TestClient, gateway: StubInstagramGateway, account_id: int
) -> AppError:
    with pytest.raises(AppError) as raised:
        _credentials(client, gateway, account_id)
    return raised.value


def _status(db_path: Path) -> str:
    (row,) = instagram_rows(db_path)
    status: str = row["status"]
    return status


def test_young_token_is_used_without_refresh(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(DAY - 60)

    token = _credentials(instagram_client, stub, account_id)

    assert token.access_token == FAKE_IG_LONG_TOKEN
    assert stub.calls == []


def test_token_older_than_a_day_is_refreshed(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    (before,) = instagram_rows(db_path)
    fake_clock.advance(DAY)

    token = _credentials(instagram_client, stub, account_id)

    assert token.access_token == FAKE_IG_REFRESHED_TOKEN
    assert stub.calls == ["refresh"]
    (after,) = instagram_rows(db_path)
    assert after["credential_ref"] == before["credential_ref"]
    assert after["credential_expires_at"] != before["credential_expires_at"]
    stored = json.loads(instagram_credential_store.secrets[after["credential_ref"]])
    assert stored["access_token"] == FAKE_IG_REFRESHED_TOKEN
    expected = fake_clock.now() + timedelta(seconds=LONG_LIVED_SECONDS)
    expiry = get_instagram_connection(instagram_client, account_id)["access_expires_at"]
    assert expiry == expected.isoformat().replace("+00:00", "Z")

    # The renewed token is young again: no second refresh.
    _credentials(instagram_client, stub, account_id)
    assert stub.calls == ["refresh"]


def test_transient_failure_with_valid_token_returns_current_token(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(2 * DAY)
    stub.refresh_error = MetaUnavailable()

    token = _credentials(instagram_client, stub, account_id)

    assert token.access_token == FAKE_IG_LONG_TOKEN
    assert _status(db_path) == "connected"


def test_transient_failure_with_expiring_token(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(LONG_LIVED_SECONDS - 120)
    stub.refresh_error = MetaUnavailable()

    error = _fails(instagram_client, stub, account_id)

    assert (error.status_code, error.code) == (503, "instagram_unavailable")
    assert _status(db_path) == "connected"


@pytest.mark.parametrize(
    "failure",
    [MetaTokenInvalid(), MetaPermissionDenied(IG_PUBLISH), MetaRejected()],
)
def test_definitive_refresh_rejection(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
    failure: Exception,
) -> None:
    fake_clock.advance(2 * DAY)
    stub.refresh_error = failure

    error = _fails(instagram_client, stub, account_id)

    assert (error.status_code, error.code) == (409, "instagram_reconnect_required")
    (row,) = instagram_rows(db_path)
    assert row["status"] == "reconnect_required"
    assert row["username"] == "cyber.studio"
    assert row["instagram_user_id"] == "17841400000000001"


def test_expired_token_needs_reconnect_without_network(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_clock.advance(LONG_LIVED_SECONDS + 1)

    error = _fails(instagram_client, stub, account_id)

    assert error.code == "instagram_reconnect_required"
    assert stub.calls == []
    assert _status(db_path) == "reconnect_required"


def test_expiring_young_token_cannot_be_renewed(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_meta: FakeMeta,
    db_path: Path,
) -> None:
    fake_meta.expires_in = 60  # expires before it is 24 h old
    _, account = create_instagram_account(instagram_client, handle="short")
    connect_instagram(instagram_client, account["id"])

    error = _fails(instagram_client, stub, account["id"])

    assert error.code == "instagram_reconnect_required"
    assert stub.calls == []


@pytest.mark.parametrize("secret", [None, "not json", '{"access_token": "x"}'])
def test_missing_or_unreadable_secret(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    stub: StubInstagramGateway,
    db_path: Path,
    account_id: int,
    secret: str | None,
) -> None:
    (row,) = instagram_rows(db_path)
    if secret is None:
        del instagram_credential_store.secrets[row["credential_ref"]]
    else:
        instagram_credential_store.secrets[row["credential_ref"]] = secret

    error = _fails(instagram_client, stub, account_id)

    assert error.code == "instagram_reconnect_required"
    assert _status(db_path) == "reconnect_required"
    assert (
        get_instagram_connection(instagram_client, account_id)["identity"] is not None
    )


def test_store_unavailable(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    stub: StubInstagramGateway,
    db_path: Path,
    account_id: int,
) -> None:
    instagram_credential_store.unavailable = True

    error = _fails(instagram_client, stub, account_id)

    assert (error.status_code, error.code) == (503, "credential_store_unavailable")
    assert _status(db_path) == "connected"


def test_not_connected_and_reconnect_required(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    _, other = create_instagram_account(instagram_client, "Other", handle="other")
    assert _fails(instagram_client, stub, other["id"]).code == "instagram_not_connected"

    fake_clock.advance(LONG_LIVED_SECONDS + 1)
    _fails(instagram_client, stub, account_id)
    stub.calls.clear()
    assert (
        _fails(instagram_client, stub, account_id).code
        == "instagram_reconnect_required"
    )
    assert stub.calls == []


def test_concurrent_calls_refresh_once(
    instagram_client: TestClient,
    stub: StubInstagramGateway,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(2 * DAY)
    stub.refresh_delay = 0.2
    results: list[Any] = []

    def run() -> None:
        results.append(_credentials(instagram_client, stub, account_id).access_token)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert stub.calls == ["refresh"]
    assert results == [FAKE_IG_REFRESHED_TOKEN, FAKE_IG_REFRESHED_TOKEN]


def test_get_marks_expired_connection_without_calling_meta(
    instagram_client: TestClient,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    requests_before = len(fake_meta.requests)
    fake_clock.advance(LONG_LIVED_SECONDS)

    connection = get_instagram_connection(instagram_client, account_id)

    assert connection["status"] == "reconnect_required"
    assert connection["identity"]["username"] == "cyber.studio"
    assert len(fake_meta.requests) == requests_before
