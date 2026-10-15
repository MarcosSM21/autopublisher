"""Verify of a TikTok connection (US3): live signals (usable token, `user/info`,
`open_id`) versus scopes known from TikTok's last token response, with the fake TikTok
API, an in-memory store and the fake clock. Nothing is ever published."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    connect_tiktok,
    create_tiktok_account,
    get_tiktok_connection,
    run_sql,
    tiktok_rows,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    TT_ACCESS_SECONDS,
    TT_BASIC,
    TT_PUBLISH,
    TT_TOKEN_URL,
    TT_UPLOAD,
    TT_USER_INFO_URL,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)

INSIDE_MARGIN = TT_ACCESS_SECONDS - 1800


@pytest.fixture
def account_id(tiktok_client: TestClient, fake_tiktok: FakeTikTok) -> int:
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    fake_tiktok.requests.clear()
    return int(account["id"])


def _verify(client: TestClient, account_id: int) -> Any:
    return client.post(f"/api/accounts/{account_id}/tiktok-connection/verify")


def _error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error: dict[str, Any] = response.json()["error"]
    assert error["code"] == code
    return error


def _row(db_path: Path) -> dict[str, Any]:
    (row,) = tiktok_rows(db_path)
    return row


def _iso(clock: FakeClock) -> str:
    return clock.now().isoformat().replace("+00:00", "Z")


def _bearer(request: Any) -> str:
    authorization: str = request.headers["authorization"]
    return authorization.removeprefix("Bearer ")


def test_verify_without_renewal_checks_live_signals(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(3600)

    response = _verify(tiktok_client, account_id)

    assert response.status_code == 200, response.text
    read = response.json()
    assert read["status"] == "connected"
    assert read["last_verified_at"] == _iso(fake_clock)
    # Scopes are not rewritten without a renewal: still the exchange's.
    assert read["permissions"]["source"] == "token_exchange"
    assert read["permissions"]["granted"] == [TT_BASIC, TT_PUBLISH, TT_UPLOAD]
    assert fake_tiktok.calls() == ["user_info"]
    [request] = fake_tiktok.requests
    assert _bearer(request) == FAKE_TT_ACCESS_TOKEN


def test_verify_with_renewal_reports_the_renewal_scopes(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(INSIDE_MARGIN)

    response = _verify(tiktok_client, account_id)

    assert response.status_code == 200, response.text
    read = response.json()
    assert read["permissions"]["source"] == "token_refresh"
    assert read["permissions"]["confirmed_at"] == _iso(fake_clock)
    assert fake_tiktok.calls() == ["refresh", "user_info"]
    assert _bearer(fake_tiktok.requests_to("user_info")[0]) == (
        FAKE_TT_REFRESHED_ACCESS_TOKEN
    )


def test_renewal_without_video_publish_requires_reconnection(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    fake_tiktok.refresh_scope = TT_BASIC
    fake_clock.advance(INSIDE_MARGIN)

    error = _error(_verify(tiktok_client, account_id), 409, "tiktok_reconnect_required")

    assert TT_PUBLISH in error["message"]
    assert _row(db_path)["status"] == "reconnect_required"
    assert fake_tiktok.requests_to("user_info") == []


def test_changed_profile_is_updated(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    account_id: int,
) -> None:
    fake_tiktok.display_name = "Cyber Studio Renamed"
    fake_tiktok.avatar_url = "https://p16-sign.tiktokcdn.example/new.jpeg"

    read = _verify(tiktok_client, account_id).json()

    assert read["identity"]["display_name"] == "Cyber Studio Renamed"
    assert read["identity"]["avatar_url"] == (
        "https://p16-sign.tiktokcdn.example/new.jpeg"
    )


def test_different_open_id_is_an_identity_mismatch(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    before = _row(db_path)
    fake_tiktok.user_open_id = "oid-someone-else"
    fake_tiktok.display_name = "Someone Else"

    _error(_verify(tiktok_client, account_id), 409, "tiktok_identity_mismatch")

    after = _row(db_path)
    assert after["status"] == "reconnect_required"
    # The identity is never replaced.
    assert after["open_id"] == before["open_id"]
    assert after["display_name"] == before["display_name"]
    assert after["last_verified_at"] == before["last_verified_at"]


def test_rejected_access_token_is_renewed_and_retried_once(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    fake_tiktok.fault_queue["user_info"] = ["api_access_token_invalid"]

    response = _verify(tiktok_client, account_id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"
    assert fake_tiktok.calls() == ["user_info", "refresh", "user_info"]
    first, retry = fake_tiktok.requests_to("user_info")
    assert _bearer(first) == FAKE_TT_ACCESS_TOKEN
    assert _bearer(retry) == FAKE_TT_REFRESHED_ACCESS_TOKEN
    assert _row(db_path)["status"] == "connected"


def test_rejected_access_token_with_rejected_renewal(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    fake_tiktok.fault_queue["user_info"] = ["api_access_token_invalid"]
    fake_tiktok.faults["refresh"] = "oauth_invalid_grant"

    _error(_verify(tiktok_client, account_id), 409, "tiktok_reconnect_required")

    assert _row(db_path)["status"] == "reconnect_required"
    assert fake_tiktok.calls() == ["user_info", "refresh"]


def test_access_token_rejected_again_after_renewal(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    fake_tiktok.faults["user_info"] = "api_access_token_invalid"

    _error(_verify(tiktok_client, account_id), 409, "tiktok_reconnect_required")

    # Exactly one renewal and one retry.
    assert fake_tiktok.calls() == ["user_info", "refresh", "user_info"]
    assert _row(db_path)["status"] == "reconnect_required"


@pytest.mark.parametrize(
    "fault", ["api_scope_not_authorized", "api_scope_permission_missed"]
)
def test_missing_user_info_scope_requires_reconnection(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    fault: str,
) -> None:
    fake_tiktok.faults["user_info"] = fault

    error = _error(_verify(tiktok_client, account_id), 409, "tiktok_reconnect_required")

    assert TT_BASIC in error["message"]
    assert _row(db_path)["status"] == "reconnect_required"


@pytest.mark.parametrize(
    "fault", ["transport", "timeout", "server_error", "rate_limited"]
)
def test_tiktok_unavailable_keeps_the_connection(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
    fault: str,
) -> None:
    before = _row(db_path)
    fake_tiktok.faults["user_info"] = fault

    _error(_verify(tiktok_client, account_id), 503, "tiktok_unavailable")

    assert _row(db_path) == before


def test_unexpected_user_info_keeps_the_connection(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    before = _row(db_path)
    fake_tiktok.faults["user_info"] = "bad_json"

    _error(_verify(tiktok_client, account_id), 502, "tiktok_unexpected_response")

    assert _row(db_path) == before


def test_missing_secret_requires_reconnection(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    tiktok_credential_store.secrets.clear()

    _error(_verify(tiktok_client, account_id), 409, "tiktok_reconnect_required")

    assert _row(db_path)["status"] == "reconnect_required"
    assert fake_tiktok.requests == []


def test_store_unavailable(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    tiktok_credential_store.unavailable = True

    _error(_verify(tiktok_client, account_id), 503, "credential_store_unavailable")

    assert _row(db_path)["status"] == "connected"
    assert fake_tiktok.requests == []


def test_missing_config_when_renewal_is_needed(
    tiktok_client: TestClient,
    tiktok_app_file: Path,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    account_id: int,
) -> None:
    before = _row(db_path)
    tiktok_app_file.unlink()
    fake_clock.advance(INSIDE_MARGIN)

    _error(_verify(tiktok_client, account_id), 503, "tiktok_oauth_not_configured")

    assert _row(db_path) == before
    assert fake_tiktok.requests == []


def test_not_connected(tiktok_client: TestClient, fake_tiktok: FakeTikTok) -> None:
    _, account = create_tiktok_account(tiktok_client)

    _error(_verify(tiktok_client, account["id"]), 409, "tiktok_not_connected")

    assert fake_tiktok.requests == []


def test_reconnect_required_is_not_verified(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    account_id: int,
) -> None:
    run_sql(db_path, "UPDATE tiktok_connections SET status = 'reconnect_required'")

    _error(_verify(tiktok_client, account_id), 409, "tiktok_reconnect_required")

    assert fake_tiktok.requests == []


def test_verify_only_reads_from_tiktok(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    account_id: int,
) -> None:
    fake_clock.advance(INSIDE_MARGIN)
    fake_tiktok.fault_queue["user_info"] = ["api_access_token_invalid"]

    _verify(tiktok_client, account_id)
    get_tiktok_connection(tiktok_client, account_id)

    # Only OAuth and user/info: never a Content Posting endpoint.
    for request in fake_tiktok.requests:
        assert request.url == TT_TOKEN_URL or request.url.startswith(TT_USER_INFO_URL)
