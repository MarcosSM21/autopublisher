"""Late connection results (Feature 021, research §9b): the final step of every
connection flow writes inside its own `write_transaction` and reads the account
again there. A result arriving after the account was deleted never recreates an
account, a connection or an active secret, and never contacts the platform.

The account is deleted right after the secret was written (hook on `store.set`),
or by a concurrent `write_transaction` that commits while the flow waits for the
writer lock. Barriers are `threading.Event`s, never sleeps."""

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import write_transaction
from tests.conftest import (
    authorize,
    complete_callback,
    complete_instagram,
    complete_threads,
    connect_youtube,
    create_account,
    create_instagram_account,
    create_project,
    create_threads_account,
    create_tiktok_account,
    get_attempt,
    poll_tiktok_attempt,
    redirect_url_for,
    run_sql,
    start_instagram_authorization,
    start_threads_authorization,
    start_tiktok_authorization,
    threads_redirect_url_for,
    tiktok_callback,
)
from tests.fakes import FakeGoogle, InMemoryCredentialStore
from tests.fakes_telegram import FAKE_CODE, FAKE_PHONE, FakeTelegramGateway

GONE = "oauth_state_invalid"


def _rows(db_path: Path, table: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(f"SELECT * FROM {table}").fetchall()


def _queued(db_path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT credential_ref, platform FROM pending_credential_deletions"
        ).fetchall()


def _delete_account(db_path: Path, account_id: int) -> None:
    """What Delete Account commits for an account without posts or connection."""
    run_sql(db_path, "DELETE FROM accounts WHERE id = ?", account_id)


def _after_set(store: InMemoryCredentialStore, action: Callable[[], None]) -> list[str]:
    """Run `action` right after the flow wrote its secret; returns written refs."""
    written: list[str] = []
    original = store.set

    def set_then_act(ref: str, value: str) -> None:
        original(ref, value)
        written.append(ref)
        action()

    store.set = set_then_act  # type: ignore[method-assign]
    return written


# --- YouTube (representative OAuth platform) ---------------------------------------


@pytest.fixture
def youtube_account(youtube_client: TestClient) -> int:
    project = create_project(youtube_client, "Cyber")
    account_id: int = create_account(youtube_client, project["id"], "youtube", "cy")[
        "id"
    ]
    return account_id


def test_youtube_result_for_a_deleted_account_creates_nothing(
    youtube_client: TestClient,
    youtube_account: int,
    credential_store: InMemoryCredentialStore,
    fake_google: FakeGoogle,
    db_path: Path,
) -> None:
    body, state = authorize(youtube_client, youtube_account)
    requests_at_delete: list[int] = []

    def delete() -> None:
        _delete_account(db_path, youtube_account)
        requests_at_delete.append(len(fake_google.requests))

    written = _after_set(credential_store, delete)

    response = complete_callback(youtube_client, state)

    assert response.status_code == 400
    assert "no longer valid" in response.text
    attempt = get_attempt(youtube_client, body["attempt_id"])
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == GONE
    assert len(written) == 1
    assert credential_store.secrets == {}  # the secret just written is gone
    assert _rows(db_path, "youtube_connections") == []
    assert _rows(db_path, "accounts") == []
    assert _queued(db_path) == []
    # Google is never contacted after the account disappeared.
    assert len(fake_google.requests) == requests_at_delete[0]


def test_youtube_secret_is_queued_when_the_store_cannot_delete_it(
    youtube_client: TestClient,
    youtube_account: int,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    _, state = authorize(youtube_client, youtube_account)

    def delete_and_lock_the_store() -> None:
        _delete_account(db_path, youtube_account)
        credential_store.fail_on = {"delete"}

    written = _after_set(credential_store, delete_and_lock_the_store)

    response = complete_callback(youtube_client, state)

    assert response.status_code == 400
    assert _rows(db_path, "youtube_connections") == []
    # Never an active secret without owner: it waits in the cleanup queue.
    assert _queued(db_path) == [(written[0], "youtube")]


def test_youtube_completion_waits_for_a_concurrent_deletion_and_sees_it(
    youtube_client: TestClient,
    youtube_account: int,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    """Both are `BEGIN IMMEDIATE`: the deletion holds the writer lock, the final
    step waits for its COMMIT (no self-deadlock) and then finds no account."""
    app = youtube_client.app
    assert isinstance(app, FastAPI)
    deleting = threading.Event()
    secret_written = threading.Event()
    errors: list[BaseException] = []

    def deletion() -> None:
        try:
            with write_transaction(app.state.session_factory) as session:
                session.execute(
                    text("DELETE FROM accounts WHERE id = :id"),
                    {"id": youtube_account},
                )
                deleting.set()
                assert secret_written.wait(timeout=10)
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)
            deleting.set()

    _, state = authorize(youtube_client, youtube_account)
    _after_set(credential_store, secret_written.set)
    thread = threading.Thread(target=deletion)
    thread.start()
    assert deleting.wait(timeout=10)

    response = complete_callback(youtube_client, state)
    thread.join(timeout=10)

    assert errors == []
    assert response.status_code == 400
    assert "no longer valid" in response.text
    assert credential_store.secrets == {}
    assert _rows(db_path, "youtube_connections") == []


def test_youtube_result_committed_first_keeps_its_connection(
    youtube_client: TestClient,
    youtube_account: int,
    credential_store: InMemoryCredentialStore,
    fake_google: FakeGoogle,
    db_path: Path,
) -> None:
    connection = connect_youtube(youtube_client, fake_google, youtube_account)

    assert connection["status"] == "connected"
    ((ref,),) = _rows_of(db_path, "SELECT credential_ref FROM youtube_connections")
    assert list(credential_store.secrets) == [ref]


# --- Instagram, Threads, TikTok (same contract) ------------------------------------


@dataclass
class OAuthFlow:
    client: TestClient
    store: InMemoryCredentialStore
    fake: Any
    table: str
    platform: str
    create: Callable[[TestClient], int]
    run: Callable[[TestClient, int, Any], str | None]  # → final error code


def _meta_run(
    start: Callable[[TestClient, int], tuple[str, str]],
    complete: Callable[[TestClient, str, str], Any],
    url_for: Callable[[str], str],
) -> Callable[[TestClient, int, Any], str | None]:
    def run(client: TestClient, account_id: int, fake: Any) -> str | None:
        attempt_id, state = start(client, account_id)
        response = complete(client, attempt_id, url_for(state))
        if response.status_code == 200:
            return None
        code: str = response.json()["error"]["code"]
        return code

    return run


def _tiktok_run(client: TestClient, account_id: int, fake: Any) -> str | None:
    attempt_id, state, _ = start_tiktok_authorization(client, account_id, fake)
    assert tiktok_callback(client, state).status_code == 303
    attempt = poll_tiktok_attempt(client, attempt_id)
    if attempt["status"] == "completed":
        return None
    code: str = attempt["error"]["code"]
    return code


@pytest.fixture(params=["instagram", "threads", "tiktok"])
def flow(request: pytest.FixtureRequest) -> OAuthFlow:
    platform: str = request.param
    if platform == "instagram":
        return OAuthFlow(
            request.getfixturevalue("instagram_client"),
            request.getfixturevalue("instagram_credential_store"),
            request.getfixturevalue("fake_meta"),
            "instagram_connections",
            platform,
            lambda client: int(create_instagram_account(client)[1]["id"]),
            _meta_run(
                start_instagram_authorization, complete_instagram, redirect_url_for
            ),
        )
    if platform == "threads":
        return OAuthFlow(
            request.getfixturevalue("threads_client"),
            request.getfixturevalue("threads_credential_store"),
            request.getfixturevalue("fake_threads"),
            "threads_connections",
            platform,
            lambda client: int(create_threads_account(client)[1]["id"]),
            _meta_run(
                start_threads_authorization, complete_threads, threads_redirect_url_for
            ),
        )
    return OAuthFlow(
        request.getfixturevalue("tiktok_client"),
        request.getfixturevalue("tiktok_credential_store"),
        request.getfixturevalue("fake_tiktok"),
        "tiktok_connections",
        platform,
        lambda client: int(create_tiktok_account(client)[1]["id"]),
        _tiktok_run,
    )


@pytest.mark.parametrize("store_fails", [False, True])
def test_oauth_result_for_a_deleted_account_creates_nothing(
    flow: OAuthFlow, db_path: Path, store_fails: bool
) -> None:
    account_id = flow.create(flow.client)
    requests_at_delete: list[int] = []

    def delete() -> None:
        _delete_account(db_path, account_id)
        requests_at_delete.append(len(flow.fake.requests))
        if store_fails:
            flow.store.fail_on = {"delete"}

    written = _after_set(flow.store, delete)

    assert flow.run(flow.client, account_id, flow.fake) == GONE

    assert len(written) == 1
    assert _rows(db_path, flow.table) == []
    assert _rows(db_path, "accounts") == []
    if store_fails:
        assert _queued(db_path) == [(written[0], flow.platform)]
    else:
        assert flow.store.secrets == {}
        assert _queued(db_path) == []
    # No platform contact after the deletion: no revocation (TikTok included).
    assert len(flow.fake.requests) == requests_at_delete[0]


def test_oauth_result_for_an_existing_account_connects(
    flow: OAuthFlow, db_path: Path
) -> None:
    account_id = flow.create(flow.client)

    assert flow.run(flow.client, account_id, flow.fake) is None

    assert len(_rows(db_path, flow.table)) == 1
    assert len(flow.store.secrets) == 1


# --- Telegram ----------------------------------------------------------------------


def _telegram_base(account_id: int) -> str:
    return f"/api/accounts/{account_id}/telegram-connection"


@pytest.fixture
def telegram_account(telegram_client: TestClient) -> int:
    project = create_project(telegram_client, "Tg")
    account_id: int = create_account(telegram_client, project["id"], "telegram", "tg")[
        "id"
    ]
    return account_id


def _login(client: TestClient, account_id: int) -> Any:
    started = client.post(
        f"{_telegram_base(account_id)}/login/start", json={"phone": FAKE_PHONE}
    )
    assert started.status_code == 200, started.text
    return client.post(
        f"{_telegram_base(account_id)}/login/code", json={"code": FAKE_CODE}
    )


@pytest.mark.parametrize("store_fails", [False, True])
def test_telegram_login_for_a_deleted_account_creates_nothing(
    telegram_client: TestClient,
    telegram_account: int,
    telegram_credential_store: InMemoryCredentialStore,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
    store_fails: bool,
) -> None:
    calls_at_delete: list[int] = []

    def delete() -> None:
        _delete_account(db_path, telegram_account)
        calls_at_delete.append(len(fake_telegram.calls))
        if store_fails:
            telegram_credential_store.fail_on = {"delete"}

    written = _after_set(telegram_credential_store, delete)

    response = _login(telegram_client, telegram_account)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == GONE
    assert _rows(db_path, "telegram_connections") == []
    assert _rows(db_path, "accounts") == []
    if store_fails:
        assert _queued(db_path) == [(written[0], "telegram")]
    else:
        assert telegram_credential_store.secrets == {}
    assert len(fake_telegram.calls) == calls_at_delete[0]  # no log out either


def test_telegram_renewal_for_a_deleted_account_deletes_the_renewed_secret(
    telegram_client: TestClient,
    telegram_account: int,
    telegram_credential_store: InMemoryCredentialStore,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
) -> None:
    assert _login(telegram_client, telegram_account).status_code == 200
    ((ref,),) = _rows_of(db_path, "SELECT credential_ref FROM telegram_connections")
    run_sql(db_path, "UPDATE telegram_connections SET status = 'reconnect_required'")

    def delete() -> None:
        # Delete Account removes the connection and queues its reference.
        run_sql(db_path, "DELETE FROM telegram_connections")
        run_sql(
            db_path,
            "INSERT INTO pending_credential_deletions VALUES (?, 'telegram', ?, "
            "'2026-10-24 10:00:00')",
            ref,
            telegram_account,
        )
        _delete_account(db_path, telegram_account)

    written = _after_set(telegram_credential_store, delete)

    response = _login(telegram_client, telegram_account)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == GONE
    assert written == [ref]  # the renewal rewrote the existing reference
    assert telegram_credential_store.secrets == {}
    assert _rows(db_path, "telegram_connections") == []
    assert _queued(db_path) == [(ref, "telegram")]  # idempotent later cleanup


def test_telegram_login_for_an_existing_account_connects(
    telegram_client: TestClient,
    telegram_account: int,
    telegram_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    response = _login(telegram_client, telegram_account)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"
    assert len(_rows(db_path, "telegram_connections")) == 1
    assert len(telegram_credential_store.secrets) == 1


def _rows_of(db_path: Path, sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(sql).fetchall()
