"""Base scopes vs. the `video.upload` capability (Feature 014, US3): Connect and
Reconnect request three scopes and require all of them, renewals keep requiring only
the base scopes, and a missing `video.upload` only makes Upload to Inbox unavailable
— never `Reconnect required`."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.tiktok_connections import get_valid_credentials
from app.tiktok_gateway import TikTokCredential, TikTokScopeMissing
from app.tiktok_oauth import (
    BASE_SCOPES,
    KNOWN_SCOPES,
    REQUESTED_SCOPES,
    REQUIRED_SCOPES,
    UPLOAD_SCOPE,
)
from tests.conftest import (
    connect_tiktok,
    connect_tiktok_all_scopes,
    connect_tiktok_base_scopes,
    create_tiktok_account,
    get_tiktok_connection,
    poll_tiktok_attempt,
    start_tiktok_authorization,
    tiktok_callback,
    tiktok_rows,
)
from tests.fakes import (
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    TT_ACCESS_SECONDS,
    TT_BASIC,
    TT_PUBLISH,
    TT_UPLOAD,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)

# Inside the 1 h renewal margin of a 24 h access token.
INSIDE_MARGIN = TT_ACCESS_SECONDS - 1800


def _app(client: TestClient) -> FastAPI:
    app: FastAPI = client.app  # type: ignore[assignment]
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


def _secret(store: InMemoryCredentialStore, db_path: Path) -> dict[str, Any]:
    [row] = tiktok_rows(db_path)
    secret: dict[str, Any] = json.loads(store.secrets[row["credential_ref"]])
    return secret


def _account_id(client: TestClient) -> int:
    _, account = create_tiktok_account(client)
    return int(account["id"])


# --- Constants -------------------------------------------------------------------


def test_scope_constants() -> None:
    assert BASE_SCOPES == (TT_BASIC, TT_PUBLISH)
    assert UPLOAD_SCOPE == TT_UPLOAD
    assert REQUESTED_SCOPES == (TT_BASIC, TT_PUBLISH, TT_UPLOAD)
    assert KNOWN_SCOPES == frozenset(REQUESTED_SCOPES)
    # Renewals and reads keep the Feature 012 rules.
    assert REQUIRED_SCOPES == frozenset(BASE_SCOPES)


def test_scope_missing_keeps_known_scope_names_only() -> None:
    assert TikTokScopeMissing(TT_UPLOAD).scope == TT_UPLOAD
    assert TikTokScopeMissing(TT_PUBLISH).scope == TT_PUBLISH
    assert TikTokScopeMissing("video.list").scope is None
    assert TikTokScopeMissing("free text from TikTok").scope is None


# --- Connect / Reconnect -----------------------------------------------------------


def test_authorization_url_requests_the_three_scopes(
    tiktok_client: TestClient,
) -> None:
    account_id = _account_id(tiktok_client)

    response = tiktok_client.post(
        f"/api/accounts/{account_id}/tiktok-connection/authorize"
    )

    assert response.status_code == 201, response.text
    query = parse_qs(urlsplit(response.json()["authorization_url"]).query)
    assert query["scope"] == ["user.info.basic,video.publish,video.upload"]
    assert "video.list" not in response.text


def test_callback_with_the_three_scopes_enables_inbox_upload(
    tiktok_client: TestClient, fake_tiktok: FakeTikTok
) -> None:
    account_id = _account_id(tiktok_client)

    connection = connect_tiktok_all_scopes(tiktok_client, account_id, fake_tiktok)

    assert connection["status"] == "connected"
    permissions = connection["permissions"]
    assert permissions["granted"] == [TT_BASIC, TT_PUBLISH, TT_UPLOAD]
    assert permissions["capabilities"] == {"direct_post": True, "inbox_upload": True}
    assert connection == get_tiktok_connection(tiktok_client, account_id)


def test_first_connect_without_video_upload_fails(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    fake_tiktok.scope = f"{TT_BASIC},{TT_PUBLISH}"
    account_id = _account_id(tiktok_client)
    attempt_id, state, _ = start_tiktok_authorization(
        tiktok_client, account_id, fake_tiktok
    )

    tiktok_callback(tiktok_client, state)

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "tiktok_permission_missing"
    assert TT_UPLOAD in attempt["error"]["message"]
    assert "every requested permission" in attempt["error"]["message"]
    assert "both" not in attempt["error"]["message"]
    assert tiktok_credential_store.secrets == {}
    assert tiktok_rows(db_path) == []
    # Never identified nor stored, but discarded.
    assert fake_tiktok.calls() == ["exchange", "revoke"]


def test_partial_reconnect_keeps_the_previous_connection_untouched(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    account_id = _account_id(tiktok_client)
    before_read = connect_tiktok_base_scopes(
        tiktok_client, account_id, fake_tiktok, tiktok_credential_store, db_path
    )
    before_rows = tiktok_rows(db_path)
    before_secrets = dict(tiktok_credential_store.secrets)
    fake_clock.advance(60)
    fake_tiktok.scope = f"{TT_BASIC},{TT_PUBLISH}"
    attempt_id, state, _ = start_tiktok_authorization(
        tiktok_client, account_id, fake_tiktok
    )

    tiktok_callback(tiktok_client, state)

    attempt = poll_tiktok_attempt(tiktok_client, attempt_id)
    assert attempt["error"]["code"] == "tiktok_permission_missing"
    assert TT_UPLOAD in attempt["error"]["message"]
    # Secret, row, identity and status are byte-for-byte the previous ones.
    assert tiktok_credential_store.secrets == before_secrets
    assert tiktok_rows(db_path) == before_rows
    assert tiktok_rows(db_path, "pending_credential_deletions") == []
    after_read = get_tiktok_connection(tiktok_client, account_id)
    assert after_read == before_read
    assert after_read["status"] == "connected"


def test_reconnect_granting_the_three_scopes_upgrades_the_connection(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    account_id = _account_id(tiktok_client)
    before = connect_tiktok_base_scopes(
        tiktok_client, account_id, fake_tiktok, tiktok_credential_store, db_path
    )

    after = connect_tiktok(tiktok_client, account_id, fake_tiktok)

    assert after["status"] == "connected"
    assert after["identity"] == before["identity"]
    assert after["permissions"]["capabilities"] == {
        "direct_post": True,
        "inbox_upload": True,
    }


# --- Existing two-scope connections ------------------------------------------------


def test_two_scope_connection_stays_connected_without_inbox_upload(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    account_id = _account_id(tiktok_client)

    connection = connect_tiktok_base_scopes(
        tiktok_client, account_id, fake_tiktok, tiktok_credential_store, db_path
    )

    assert connection["status"] == "connected"
    assert connection["permissions"]["granted"] == [TT_BASIC, TT_PUBLISH]
    assert connection["permissions"]["capabilities"] == {
        "direct_post": True,
        "inbox_upload": False,
    }
    credential = _credentials(tiktok_client, account_id)
    assert credential.has_required_scopes()
    assert not credential.has_requested_scopes()
    assert not credential.can_upload_to_inbox()
    assert fake_tiktok.requests == []
    assert tiktok_rows(db_path)[0]["status"] == "connected"


# --- Renewals ------------------------------------------------------------------------


def test_renewal_losing_only_video_upload_stays_connected(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    account_id = _account_id(tiktok_client)
    connect_tiktok_all_scopes(tiktok_client, account_id, fake_tiktok)
    fake_tiktok.refresh_scope = f"{TT_BASIC},{TT_PUBLISH}"
    fake_clock.advance(INSIDE_MARGIN)

    credential = _credentials(tiktok_client, account_id)

    assert credential.access_token == FAKE_TT_REFRESHED_ACCESS_TOKEN
    assert not credential.can_upload_to_inbox()
    # TikTok is the source of truth: the renewed credential is stored.
    secret = _secret(tiktok_credential_store, db_path)
    assert secret["scopes"] == [TT_BASIC, TT_PUBLISH]
    assert secret["scopes_source"] == "token_refresh"
    assert tiktok_rows(db_path)[0]["status"] == "connected"
    read = get_tiktok_connection(tiktok_client, account_id)
    assert read["status"] == "connected"
    assert read["permissions"]["capabilities"] == {
        "direct_post": True,
        "inbox_upload": False,
    }


@pytest.mark.parametrize("refresh_scope", [TT_BASIC, f"{TT_BASIC},{TT_UPLOAD}"])
def test_renewal_losing_video_publish_keeps_feature_012_rules(
    tiktok_client: TestClient,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    refresh_scope: str,
) -> None:
    account_id = _account_id(tiktok_client)
    connect_tiktok_all_scopes(tiktok_client, account_id, fake_tiktok)
    fake_tiktok.refresh_scope = refresh_scope
    fake_clock.advance(INSIDE_MARGIN)

    response = tiktok_client.post(
        f"/api/accounts/{account_id}/tiktok-connection/verify"
    )

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "tiktok_reconnect_required"
    assert TT_PUBLISH in error["message"]
    assert TT_UPLOAD not in error["message"]
    assert tiktok_rows(db_path)[0]["status"] == "reconnect_required"
