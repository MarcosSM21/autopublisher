"""No TikTok secret ever leaves the secure storage (Polish): after every flow of the
feature — connect, renewal, Verify, rejected token, reconnect with the same and with
another account, failures, Disconnect and remove-local — the SQLite dump, the captured
logs, every response, every result page and every outgoing query string are clean."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app.tiktok_connections import HTTP_LOGGERS
from app.tiktok_gateway import TikTokCredential
from app.tiktok_oauth import TikTokAppConfig, TikTokAttemptRegistry, TikTokIdentity
from tests.conftest import create_tiktok_account, start_tiktok_authorization
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_CODE,
    FAKE_TT_ERROR_TEXT,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    FAKE_TT_ROTATED_REFRESH_TOKEN,
    TT_ACCESS_SECONDS,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)

FIXED_SECRETS = (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_ROTATED_REFRESH_TOKEN,
    FAKE_TT_CODE,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_ERROR_TEXT,
)
OTHER_OPEN_ID = "-000fake-tt-other-open-id-b52e90"


class Flow:
    """Drives the API and keeps every response text plus the OAuth values used."""

    def __init__(self, client: TestClient, fake: FakeTikTok) -> None:
        self.client = client
        self.fake = fake
        self.texts: list[str] = []
        self.oauth_values: list[str] = []

    def keep(self, response: httpx.Response) -> httpx.Response:
        self.texts.append(response.text)
        self.texts.append(json.dumps(dict(response.headers)))
        return response

    def post(self, path: str) -> httpx.Response:
        return self.keep(self.client.post(path))

    def authorize(self, account_id: int) -> tuple[str, str]:
        # The authorize response is the one place where `state` and the challenge
        # legitimately appear (inside `authorization_url`).
        attempt_id, state, challenge = start_tiktok_authorization(
            self.client, account_id, self.fake
        )
        self.oauth_values += [state, challenge]
        return attempt_id, state

    def callback(self, account_id: int) -> str:
        attempt_id, state = self.authorize(account_id)
        response = self.keep(
            self.client.get(
                "/api/tiktok/oauth/callback",
                params={"code": FAKE_TT_CODE, "state": state},
                follow_redirects=False,
            )
        )
        self.keep(self.client.get(response.headers["location"]))
        self.keep(self.client.get(f"/api/tiktok/oauth/attempts/{attempt_id}"))
        return attempt_id

    def read(self, account_id: int) -> None:
        self.keep(self.client.get(f"/api/accounts/{account_id}/tiktok-connection"))


def test_full_flows_leak_no_secret(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    for name in HTTP_LOGGERS:
        caplog.set_level(logging.DEBUG, logger=name)
    flow = Flow(tiktok_client, fake_tiktok)
    _, account = create_tiktok_account(tiktok_client)
    account_id = account["id"]
    base = f"/api/accounts/{account_id}/tiktok-connection"

    # Connect, then renew through Verify and recover from a rejected token.
    flow.callback(account_id)
    flow.read(account_id)
    fake_clock.advance(TT_ACCESS_SECONDS - 1800)
    flow.post(f"{base}/verify")
    fake_tiktok.fault_queue["user_info"] = ["api_access_token_invalid"]
    flow.post(f"{base}/verify")
    # Failures carrying TikTok's error text.
    fake_tiktok.faults["user_info"] = "server_error"
    flow.post(f"{base}/verify")
    fake_tiktok.faults.clear()
    # Reconnect with the same account, then with another one (confirmed).
    flow.callback(account_id)
    fake_tiktok.open_id = OTHER_OPEN_ID
    attempt_id = flow.callback(account_id)
    flow.post(f"/api/tiktok/oauth/attempts/{attempt_id}/confirm")
    flow.read(account_id)
    # Disconnect: ambiguous revocation first, then confirmed.
    fake_tiktok.faults["revoke"] = "oauth_invalid_request"
    flow.post(f"{base}/disconnect")
    fake_tiktok.faults.clear()
    flow.post(f"{base}/disconnect")
    # Connect again and remove locally.
    flow.callback(account_id)
    flow.post(f"{base}/remove-local")
    # Partial scopes and a rejected exchange.
    fake_tiktok.scope = "user.info.basic"
    flow.callback(account_id)
    fake_tiktok.scope = "user.info.basic,video.publish"
    fake_tiktok.faults["exchange"] = "oauth_invalid_grant"
    flow.callback(account_id)
    fake_tiktok.faults.clear()

    verifiers = [
        request.form["code_verifier"] for request in fake_tiktok.requests_to("exchange")
    ]
    assert len(verifiers) == 6
    secrets = [*FIXED_SECRETS, *verifiers, *flow.oauth_values]
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert caplog.records, "logs were captured"
    for secret in secrets:
        assert secret not in dump, secret
        assert secret not in logs, secret
        for text in flow.texts:
            assert secret not in text, secret
    # Secrets only ever travel in form bodies or the Authorization header.
    for request in fake_tiktok.requests:
        query = urlsplit(request.url).query
        for secret in secrets:
            assert secret not in query, secret
    # The secure storage is the only place holding a credential.
    assert tiktok_credential_store.secrets == {}


def test_reprs_hide_secrets(fake_clock: FakeClock) -> None:
    credential = TikTokCredential.from_json(
        json.dumps(
            {
                "version": 1,
                "open_id": "oid",
                "access_token": FAKE_TT_ACCESS_TOKEN,
                "refresh_token": FAKE_TT_REFRESH_TOKEN,
                "access_expires_at": "2026-10-15T10:00:00+00:00",
                "refresh_expires_at": "2027-10-15T10:00:00+00:00",
                "scopes": ["user.info.basic", "video.publish"],
                "scopes_source": "token_exchange",
                "obtained_at": "2026-10-14T10:00:00+00:00",
            }
        )
    )
    config = TikTokAppConfig(
        client_key="key",
        client_secret=FAKE_TT_CLIENT_SECRET,
        redirect_uri="http://127.0.0.1:8000/api/tiktok/oauth/callback",
    )
    registry = TikTokAttemptRegistry(fake_clock.now)
    attempt = registry.create(1, "state-value-secret", "verifier-value-secret")
    identity = TikTokIdentity(open_id="oid", display_name=None, avatar_url=None)
    registry.await_confirmation(attempt, identity, credential)
    texts: list[Any] = [repr(credential), repr(config), repr(attempt)]

    for text in texts:
        for secret in (
            FAKE_TT_ACCESS_TOKEN,
            FAKE_TT_REFRESH_TOKEN,
            FAKE_TT_CLIENT_SECRET,
            "state-value-secret",
            "verifier-value-secret",
        ):
            assert secret not in text
