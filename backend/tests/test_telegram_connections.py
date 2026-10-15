"""Telegram account connection: login, session storage, Verify, channels and the
per-account session lock (Feature 015). The Telegram boundary is faked."""

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import telegram_connections
from app.errors import AppError
from app.telegram_connections import SessionWaitStopped, account_session
from app.telegram_gateway import (
    TelegramIdentity,
    TelegramRateLimited,
    TelegramUnauthorized,
)
from tests.conftest import (
    FUTURE,
    create_account,
    create_project,
    create_publications,
    run_sql,
    setup_project,
)
from tests.fakes import FakeClock, InMemoryCredentialStore
from tests.fakes_telegram import (
    CHANNEL,
    FAKE_CODE,
    FAKE_PASSWORD,
    FAKE_PHONE,
    FINAL_SESSION,
    PASSWORD_SESSION,
    SECRETS,
    FakeTelegramGateway,
    stored_secret,
)


def base(account_id: int) -> str:
    return f"/api/accounts/{account_id}/telegram-connection"


def telegram_account(client: TestClient) -> int:
    project = create_project(client, "Tg")
    account_id: int = create_account(client, project["id"], "telegram", "tg")["id"]
    return account_id


def connect(client: TestClient, account_id: int) -> dict[str, Any]:
    url = base(account_id)
    response = client.post(f"{url}/login/start", json={"phone": FAKE_PHONE})
    assert response.status_code == 200, response.text
    response = client.post(f"{base(account_id)}/login/code", json={"code": FAKE_CODE})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def connection_row(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM telegram_connections").fetchone()
    return dict(row)


def database_text(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        return "\n".join(connection.iterdump())


# --- Per-account session lock --------------------------------------------------------


def test_lock_allows_one_holder_and_is_released_after_errors() -> None:
    with account_session(9001, wait=False):
        with pytest.raises(AppError) as busy:
            with account_session(9001, wait=False):
                pass
        assert busy.value.code == "telegram_busy"
        # Another account is never blocked.
        with account_session(9002, wait=False):
            pass

    with pytest.raises(RuntimeError):
        with account_session(9001, wait=False):
            raise RuntimeError("boom")
    with account_session(9001, wait=False):
        pass


def test_waiting_holder_proceeds_after_release_or_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telegram_connections, "LOCK_POLL_SECONDS", 0.01)
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with account_session(9003, wait=False):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(5)
    with pytest.raises(SessionWaitStopped):
        with account_session(9003, wait=True, should_stop=lambda: True):
            pass
    threading.Timer(0.05, release.set).start()
    started = time.monotonic()
    with account_session(9003, wait=True, should_stop=lambda: False):
        assert time.monotonic() - started >= 0.04
    thread.join(5)


def test_interactive_routes_answer_busy_while_the_session_is_in_use(
    telegram_client: TestClient,
) -> None:
    account_id = telegram_account(telegram_client)
    connect(telegram_client, account_id)
    with account_session(account_id, wait=False):
        for method, path, body in (
            ("post", "/verify", None),
            ("get", "/channels", None),
            ("put", "/channel", {"channel_id": CHANNEL.channel_id}),
        ):
            response = telegram_client.request(
                method, f"{base(account_id)}{path}", json=body
            )
            assert response.status_code == 409, path
            assert response.json()["error"]["code"] == "telegram_busy"
    assert telegram_client.get(base(account_id)).status_code == 200


# --- Login ------------------------------------------------------------------------


def test_login_with_code_connects_and_keeps_the_session_only_in_the_store(
    telegram_client: TestClient,
    telegram_credential_store: InMemoryCredentialStore,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    account_id = telegram_account(telegram_client)
    started = telegram_client.post(
        f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE}
    ).json()
    assert started["login"]["step"] == "code"
    assert started["status"] == "not_connected"

    body = telegram_client.post(
        f"{base(account_id)}/login/code", json={"code": FAKE_CODE}
    ).json()
    assert body["status"] == "connected"
    assert body["login"] is None
    assert body["identity"] == {
        "telegram_user_id": "111222333",
        "display_name": "Test User",
        "username": "tester",
    }
    assert fake_telegram.configs[0].api_id == 1234567

    row = connection_row(db_path)
    assert stored_secret(telegram_credential_store, row["credential_ref"]) == {
        "v": 1,
        "session": FINAL_SESSION,
        "user_id": "111222333",
    }
    exposed = (
        database_text(db_path)
        + str(started)
        + str(body)
        + telegram_client.get(base(account_id)).text
        + caplog.text
    )
    for secret in SECRETS:
        assert secret not in exposed


def test_login_with_two_step_password(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    fake_telegram.requires_password = True
    account_id = telegram_account(telegram_client)
    telegram_client.post(f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE})
    step = telegram_client.post(
        f"{base(account_id)}/login/code", json={"code": FAKE_CODE}
    ).json()
    assert step["login"]["step"] == "password"
    assert step["status"] == "not_connected"

    wrong = telegram_client.post(
        f"{base(account_id)}/login/password", json={"password": "nope"}
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "telegram_login_invalid"

    done = telegram_client.post(
        f"{base(account_id)}/login/password", json={"password": FAKE_PASSWORD}
    ).json()
    assert done["status"] == "connected"
    assert fake_telegram.sessions_used[-1] == PASSWORD_SESSION
    assert FAKE_PASSWORD not in caplog.text + str(done) + wrong.text


def test_login_errors_and_pending_login_lifecycle(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    fake_clock: FakeClock,
) -> None:
    account_id = telegram_account(telegram_client)
    code_url = f"{base(account_id)}/login/code"
    # No pending login.
    response = telegram_client.post(code_url, json={"code": FAKE_CODE})
    assert response.json()["error"]["code"] == "telegram_login_not_pending"

    telegram_client.post(f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE})
    wrong = telegram_client.post(code_url, json={"code": "99999"})
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "telegram_login_invalid"

    # Cancelled.
    telegram_client.post(f"{base(account_id)}/login/cancel")
    response = telegram_client.post(code_url, json={"code": FAKE_CODE})
    assert response.json()["error"]["code"] == "telegram_login_not_pending"

    # Expired.
    telegram_client.post(f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE})
    fake_clock.advance(11 * 60)
    response = telegram_client.post(code_url, json={"code": FAKE_CODE})
    assert response.json()["error"]["code"] == "telegram_login_not_pending"

    # FloodWait while sending the code.
    fake_telegram.errors["send_code"] = TelegramRateLimited(120)
    response = telegram_client.post(
        f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE}
    )
    assert response.status_code == 429
    assert "120 seconds" in response.json()["error"]["message"]


def test_reconnect_with_another_telegram_user_is_rejected(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
) -> None:
    account_id = telegram_account(telegram_client)
    connect(telegram_client, account_id)
    already = telegram_client.post(
        f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE}
    )
    assert already.json()["error"]["code"] == "telegram_already_connected"

    run_sql(db_path, "UPDATE telegram_connections SET status = 'reconnect_required'")
    fake_telegram.identity = TelegramIdentity("999", "Someone Else", None)
    telegram_client.post(f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE})
    response = telegram_client.post(
        f"{base(account_id)}/login/code", json={"code": FAKE_CODE}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "telegram_identity_mismatch"
    # The unused session is revoked, the stored identity is unchanged.
    assert fake_telegram.logged_out == [FINAL_SESSION]
    assert connection_row(db_path)["telegram_user_id"] == "111222333"


def test_configuration_and_platform_are_required(
    telegram_client: TestClient,
    telegram_app_file: Path,
) -> None:
    project = create_project(telegram_client, "Mixed")
    other = create_account(telegram_client, project["id"], "threads", "th")
    response = telegram_client.post(
        f"{base(other['id'])}/login/start", json={"phone": FAKE_PHONE}
    )
    assert response.json()["error"]["code"] == "platform_not_supported"

    account_id = create_account(telegram_client, project["id"], "telegram", "tg")["id"]
    telegram_app_file.unlink()
    assert telegram_client.get(base(account_id)).json()["configured"] is False
    response = telegram_client.post(
        f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "telegram_not_configured"


# --- Verify -----------------------------------------------------------------------


def test_verify_refreshes_identity_or_requires_reconnect(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    fake_clock: FakeClock,
) -> None:
    account_id = telegram_account(telegram_client)
    not_connected = telegram_client.post(f"{base(account_id)}/verify")
    assert not_connected.json()["error"]["code"] == "telegram_not_connected"

    first = connect(telegram_client, account_id)
    fake_clock.advance(60)
    fake_telegram.identity = TelegramIdentity("111222333", "Renamed", None)
    body = telegram_client.post(f"{base(account_id)}/verify").json()
    assert body["status"] == "connected"
    assert body["identity"]["display_name"] == "Renamed"
    assert body["last_verified_at"] > first["last_verified_at"]
    assert fake_telegram.sessions_used[-1] == FINAL_SESSION

    fake_telegram.errors["get_me"] = TelegramUnauthorized()
    revoked = telegram_client.post(f"{base(account_id)}/verify")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "reconnect_required"

    # A session that now belongs to another user is not accepted either.
    telegram_client.post(f"{base(account_id)}/login/start", json={"phone": FAKE_PHONE})
    telegram_client.post(f"{base(account_id)}/login/code", json={"code": FAKE_CODE})
    fake_telegram.identity = TelegramIdentity("999", "Other", None)
    other = telegram_client.post(f"{base(account_id)}/verify").json()
    assert other["status"] == "reconnect_required"


# --- Channels ---------------------------------------------------------------------


def test_channels_are_listed_and_selected_without_the_access_hash(
    telegram_client: TestClient,
    db_path: Path,
) -> None:
    account_id = telegram_account(telegram_client)
    connect(telegram_client, account_id)
    listed = telegram_client.get(f"{base(account_id)}/channels")
    assert listed.status_code == 200
    assert listed.json()["channels"][0] == {
        "channel_id": CHANNEL.channel_id,
        "title": "Test channel",
        "username": "testchan",
    }
    assert CHANNEL.access_hash not in listed.text

    not_eligible = telegram_client.put(
        f"{base(account_id)}/channel", json={"channel_id": "42"}
    )
    assert not_eligible.status_code == 422
    assert not_eligible.json()["error"]["code"] == "telegram_channel_not_eligible"

    chosen = telegram_client.put(
        f"{base(account_id)}/channel", json={"channel_id": CHANNEL.channel_id}
    )
    assert chosen.status_code == 200
    assert chosen.json()["channel"]["title"] == "Test channel"
    assert CHANNEL.access_hash not in chosen.text
    row = connection_row(db_path)
    assert row["channel_id"] == CHANNEL.channel_id
    assert row["channel_access_hash"] == CHANNEL.access_hash


def test_channel_change_is_blocked_while_publications_are_pending(
    telegram_client: TestClient,
    db_path: Path,
) -> None:
    project, content, accounts = setup_project(telegram_client, ("telegram",))
    account_id = accounts[0]["id"]
    connect(telegram_client, account_id)
    publication = create_publications(
        telegram_client, content["id"], [account_id], scheduled_at=FUTURE
    )[0]
    assert telegram_client.get(base(account_id)).json()["channel_change_blocked"]
    blocked = telegram_client.put(
        f"{base(account_id)}/channel", json={"channel_id": CHANNEL.channel_id}
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "telegram_channel_change_blocked"

    run_sql(
        db_path,
        "UPDATE publications SET status = 'publishing' WHERE id = ?",
        publication["id"],
    )
    blocked = telegram_client.put(
        f"{base(account_id)}/channel", json={"channel_id": CHANNEL.channel_id}
    )
    assert blocked.json()["error"]["code"] == "telegram_channel_change_blocked"

    run_sql(
        db_path,
        "UPDATE publications SET status = 'failed' WHERE id = ?",
        publication["id"],
    )
    allowed = telegram_client.put(
        f"{base(account_id)}/channel", json={"channel_id": CHANNEL.channel_id}
    )
    assert allowed.status_code == 200


def test_listing_channels_with_a_revoked_session_requires_reconnect(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
) -> None:
    account_id = telegram_account(telegram_client)
    connect(telegram_client, account_id)
    fake_telegram.errors["list_channels"] = TelegramUnauthorized()
    response = telegram_client.get(f"{base(account_id)}/channels")
    assert response.json()["error"]["code"] == "telegram_reconnect_required"
    assert telegram_client.get(base(account_id)).json()["status"] == (
        "reconnect_required"
    )
