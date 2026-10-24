"""Delete Account (Feature 021 T020–T021, US6, research §9).

An account goes with every post of it, its connection, its preset memberships and,
after the commit, its local secret (queued in the same transaction: write-ahead).
Connection attempts never block it; they are invalidated only after the commit and
their late results never recreate anything. No platform is ever contacted: no
revoke, no log out. Races are forced with barriers, never `sleep`.
"""

import sqlite3
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app import cleanup as cleanup_module
from app import deletion, youtube_connections
from app.credential_store import CredentialStoreProbe
from app.main import create_app
from app.models import Account
from app.scheduler import TickReport
from app.telegram_connections import account_session
from tests import readmodels
from tests.barriers import (
    Background,
    Gate,
    is_claim,
    pause_before_commit,
    pause_in_prepare,
    statement_reached,
)
from tests.conftest import (
    attempt_rows,
    authorize,
    complete_callback,
    connect_tiktok,
    connect_youtube,
    create_account,
    create_project,
    create_tiktok_account,
    get_attempt,
    in_minutes,
    poll_tiktok_attempt,
    run_sql,
    scheduled_publication,
    wait_idle,
)
from tests.fakes import (
    FakeClock,
    FakeGoogle,
    FakeMediaDeliveryProvider,
    FakePublisher,
    FakeTikTok,
    InMemoryCredentialStore,
)
from tests.fakes_telegram import FAKE_CODE, FAKE_PHONE, FakeTelegramGateway
from tests.test_delete_post import (
    BASE_URL,
    CHANGED,
    PASSWORD,
    _post_with_dependents,
    count,
    delivery,  # noqa: F401 - fixture
    delivery_client,  # noqa: F401 - fixture
    installation,  # noqa: F401 - fixture
    running_attempt,
)
from tests.test_tiktok_reconnect import _awaiting

IN_PROGRESS = (
    "A post of this account is being published right now. Try again when it finishes."
)
GONE = "oauth_state_invalid"


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def probe(status: Any) -> CredentialStoreProbe:
    return CredentialStoreProbe(lambda: status)


def set_probe(client: TestClient, status: str) -> None:
    """The 020 credential store probe, as the delete sees it."""
    _app(client).state.credential_probe = probe(status)


def preview(client: TestClient, account_id: int) -> dict[str, Any]:
    response = client.get(f"/api/accounts/{account_id}/deletion-preview")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def delete(client: TestClient, account_id: int, confirmation: str) -> Any:
    return client.delete(
        f"/api/accounts/{account_id}", params={"confirmation": confirmation}
    )


def confirmed_delete(client: TestClient, account_id: int) -> Any:
    return delete(client, account_id, preview(client, account_id)["confirmation"])


def queued(db_path: Path) -> list[tuple[str, str, int | None]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT credential_ref, platform, account_id "
            "FROM pending_credential_deletions ORDER BY credential_ref"
        ).fetchall()


def youtube_ref(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        ((ref,),) = connection.execute(
            "SELECT credential_ref FROM youtube_connections"
        ).fetchall()
    return str(ref)


class RecordingStore:
    """Records the order of `set`/`delete` calls of an in-memory store."""

    def __init__(self, store: InMemoryCredentialStore) -> None:
        self.calls: list[str] = []
        original_set, original_delete = store.set, store.delete

        def set_(ref: str, value: str) -> None:
            self.calls.append("set")
            original_set(ref, value)

        def delete_(ref: str) -> None:
            self.calls.append("delete")
            original_delete(ref)

        store.set = set_  # type: ignore[method-assign]
        store.delete = delete_  # type: ignore[method-assign]


@pytest.fixture
def client(youtube_client: TestClient) -> TestClient:
    set_probe(youtube_client, "available")
    return youtube_client


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


@pytest.fixture
def connected(
    client: TestClient, fake_google: FakeGoogle, project: dict[str, Any]
) -> dict[str, Any]:
    account = create_account(client, project["id"], "youtube", "cyberchannel")
    connect_youtube(client, fake_google, account["id"])
    return account


# --- Removal ------------------------------------------------------------------------


def test_delete_account_removes_its_posts_connection_and_secret(
    client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    project: dict[str, Any],
    connected: dict[str, Any],
) -> None:
    now = FakeClock().now()
    other = create_account(client, project["id"], "youtube", "other")
    for status in ("unscheduled", "scheduled", "published", "published"):
        at = now + timedelta(hours=1) if status == "scheduled" else None
        readmodels.post(db_path, connected, now, status=status, scheduled_at=at)
    kept_post = readmodels.post(db_path, other, now, status="unscheduled")
    for name, ids in (
        ("Mine", [connected["id"]]),
        ("Both", [connected["id"], other["id"]]),
    ):
        response = client.post(
            f"/api/projects/{project['id']}/distribution-presets",
            json={"name": name, "account_ids": ids},
        )
        assert response.status_code == 201, response.text
    ref = youtube_ref(db_path)
    assert list(credential_store.secrets) == [ref]

    body = preview(client, connected["id"])

    assert body["kind"] == "account" and body["id"] == connected["id"]
    assert body["name"] == "YouTube @cyberchannel"
    assert body["counts"] == {
        "unpublished_posts": 2,
        "remote_posts": 2,
        "needs_review_posts": 0,
        "accounts": 1,
        "posts": 4,
        "media": 0,
        "subfolders": 0,
        "media_to_unsorted": 0,
    }
    assert body["summary"] == [
        "2 unpublished posts and 2 published posts will also be removed from "
        "AutoPublisher.",
        "Content already published on platforms is not affected.",
        "Your @cyberchannel account on YouTube is not affected.",
    ]
    assert body["blocker"] is None
    requests_before = len(fake_google.requests)

    assert delete(client, connected["id"], body["confirmation"]).status_code == 204

    assert credential_store.secrets == {}
    assert queued(db_path) == []
    assert count(db_path, "youtube_connections") == 0
    assert count(db_path, "publications") == 1
    assert len(fake_google.requests) == requests_before  # no revoke, no call at all
    # Read models: Accounts (and the Publish selector), presets, Posts (also
    # History and Calendar), Home.
    accounts = client.get(f"/api/projects/{project['id']}/accounts").json()
    assert [account["id"] for account in accounts] == [other["id"]]
    health = client.get(f"/api/projects/{project['id']}/account-health").json()
    assert [item["account_id"] for item in health] == [other["id"]]
    presets = client.get(f"/api/projects/{project['id']}/distribution-presets").json()
    assert {preset["name"]: preset["account_ids"] for preset in presets} == {
        "Mine": [],  # kept, without destinations
        "Both": [other["id"]],
    }
    posts = client.get(f"/api/projects/{project['id']}/publications").json()
    assert [post["id"] for post in posts] == [kept_post]
    overview = client.get("/api/overview").json()
    assert overview["upcoming"] == []
    assert "Account removed" not in str(overview)

    again = delete(client, connected["id"], body["confirmation"])
    assert again.status_code == 404
    assert again.json()["error"]["message"] == "Account not found."
    assert queued(db_path) == []


def test_needs_review_posts_get_the_generic_warning(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    now = FakeClock().now()
    account = create_account(client, project["id"], "telegram", "cybernews")
    for _ in range(2):
        post_id = readmodels.post(db_path, account, now, status="failed")
        readmodels.failed_attempt(db_path, post_id, now, uncertain=True)

    assert preview(client, account["id"])["summary"] == [
        "2 published posts will also be removed from AutoPublisher.",
        "Content already published on platforms is not affected.",
        "2 posts may already have been published. Check the platforms before "
        "publishing this content again.",
        "Your @cybernews account on Telegram is not affected.",
    ]


def test_token_follows_the_connection_and_the_posts(
    client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    project: dict[str, Any],
) -> None:
    """Connection completion wins: a preview taken before it is stale (its secret
    now goes too); a fresh one deletes normally, never a 409 for the connection."""
    account = create_account(client, project["id"], "youtube", "cyberchannel")
    before = preview(client, account["id"])["confirmation"]
    # Renaming the account changes nothing.
    response = client.patch(
        f"/api/accounts/{account['id']}", json={"display_name": "Renamed"}
    )
    assert response.status_code == 200, response.text
    assert preview(client, account["id"])["confirmation"] == before

    connect_youtube(client, fake_google, account["id"])

    stale = delete(client, account["id"], before)
    assert stale.status_code == 409
    assert stale.json()["error"]["message"] == CHANGED
    assert count(db_path, "youtube_connections") == 1
    assert confirmed_delete(client, account["id"]).status_code == 204
    assert count(db_path, "youtube_connections") == count(db_path, "accounts") == 0


# --- Credential cleanup -------------------------------------------------------------


def test_unavailable_store_keeps_the_delete_and_queues_the_secret(
    client: TestClient,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    connected: dict[str, Any],
) -> None:
    ref = youtube_ref(db_path)
    credential_store.fail_on = {"delete"}

    assert confirmed_delete(client, connected["id"]).status_code == 204

    assert count(db_path, "accounts") == count(db_path, "youtube_connections") == 0
    assert queued(db_path) == [(ref, "youtube", connected["id"])]
    assert list(credential_store.secrets) == [ref]  # never used again: no connection


@pytest.mark.parametrize("status", ["locked", "unavailable"])
def test_locked_store_is_not_touched_and_start_up_cleans_later(
    client: TestClient,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    media_dir: Path,
    connected: dict[str, Any],
    status: str,
) -> None:
    ref = youtube_ref(db_path)
    set_probe(client, status)
    recording = RecordingStore(credential_store)

    assert confirmed_delete(client, connected["id"]).status_code == 204

    assert recording.calls == []  # no prompt, no unlock
    assert queued(db_path) == [(ref, "youtube", connected["id"])]

    # A later start with the store available cleans it (research §16).
    client.__exit__(None, None, None)
    app = create_app(
        db_path,
        media_dir,
        credential_store=credential_store,
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        tiktok_credential_store=InMemoryCredentialStore(),
        credential_probe=probe("available"),
    )
    with TestClient(app):
        app.state.credential_cleanup.join(10)
    assert credential_store.secrets == {}
    assert queued(db_path) == []


def test_an_in_flight_refresh_finishes_before_the_secret_is_deleted(
    client: TestClient,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    connected: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = youtube_ref(db_path)
    token = preview(client, connected["id"])["confirmation"]
    recording = RecordingStore(credential_store)
    cleanup_started = threading.Event()
    real_cleanup = cleanup_module.run_credential_cleanup

    def cleanup(*args: Any) -> None:
        cleanup_started.set()
        real_cleanup(*args)

    monkeypatch.setattr(deletion, "run_credential_cleanup", cleanup)
    refresh = Gate()

    def refreshing() -> None:
        with youtube_connections.credential_lock(connected["id"]):
            refresh.pause()
            credential_store.set(ref, "refreshed")

    renewal = Background(refreshing)
    refresh.wait_reached()
    deleting = Background(lambda: delete(client, connected["id"], token))
    assert cleanup_started.wait(10)  # committed; waiting for the lock
    assert recording.calls == []
    refresh.release()

    renewal.result()
    assert deleting.result().status_code == 204
    assert recording.calls == ["set", "delete"]
    assert credential_store.secrets == {}
    assert queued(db_path) == []


# --- Rejected delete: nothing anywhere ----------------------------------------------


def test_rejected_delete_keeps_attempts_and_secrets(
    client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    connected: dict[str, Any],
) -> None:
    token = preview(client, connected["id"])["confirmation"]
    readmodels.post(db_path, connected, FakeClock().now(), status="unscheduled")
    body, state = authorize(client, connected["id"])
    secrets = dict(credential_store.secrets)

    response = delete(client, connected["id"], token)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "deletion_changed"
    assert credential_store.secrets == secrets
    assert queued(db_path) == []
    assert get_attempt(client, body["attempt_id"])["status"] != "expired"
    assert complete_callback(client, state).status_code == 200  # still completable
    assert get_attempt(client, body["attempt_id"])["status"] == "completed"


def test_a_publishing_post_blocks_the_account_and_keeps_its_attempts(
    telegram_client: TestClient,
    telegram_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    set_probe(telegram_client, "available")
    project = create_project(telegram_client, "Tg")
    account = create_account(telegram_client, project["id"], "telegram", "tg")
    _login(telegram_client, account["id"])
    secrets = dict(telegram_credential_store.secrets)
    now = FakeClock().now()
    busy = readmodels.post(db_path, account, now, status="publishing")
    running_attempt(db_path, busy, now)
    # A renewal login in progress.
    run_sql(db_path, "UPDATE telegram_connections SET status = 'reconnect_required'")
    started = telegram_client.post(
        f"{_telegram_base(account['id'])}/login/start", json={"phone": FAKE_PHONE}
    )
    assert started.status_code == 200, started.text

    body = preview(telegram_client, account["id"])
    assert body["blocker"] == {"code": "post_in_progress", "message": IN_PROGRESS}
    response = delete(telegram_client, account["id"], body["confirmation"])

    assert response.status_code == 409
    assert response.json()["error"]["message"] == IN_PROGRESS
    assert _app(telegram_client).state.telegram_logins.get(account["id"]) is not None
    assert telegram_credential_store.secrets == secrets
    assert count(db_path, "telegram_connections") == 1
    assert queued(db_path) == []


def test_failure_mid_delete_changes_nothing(
    client: TestClient,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    connected: dict[str, Any],
) -> None:
    """Posts deleted and the secret queued, then the account row itself fails."""
    readmodels.post(db_path, connected, FakeClock().now(), status="unscheduled")
    body, _ = authorize(client, connected["id"])
    token = preview(client, connected["id"])["confirmation"]
    secrets = dict(credential_store.secrets)
    engine: Engine = _app(client).state.session_factory.kw["bind"]

    def fail(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if statement.startswith("DELETE FROM accounts"):
            raise RuntimeError("disk I/O error")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = delete(
            TestClient(_app(client), raise_server_exceptions=False),
            connected["id"],
            token,
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)

    assert response.status_code == 500
    assert count(db_path, "accounts") == count(db_path, "publications") == 1
    assert count(db_path, "youtube_connections") == 1
    assert queued(db_path) == []
    assert credential_store.secrets == secrets
    assert get_attempt(client, body["attempt_id"])["status"] == "pending"
    assert delete(client, connected["id"], token).status_code == 204


# --- Connection attempts: invalidated after the commit, late results discarded ------


def test_pending_attempts_are_invalidated_after_the_commit(
    client: TestClient, project: dict[str, Any]
) -> None:
    account = create_account(client, project["id"], "youtube", "cyberchannel")
    body, state = authorize(client, account["id"])

    assert confirmed_delete(client, account["id"]).status_code == 204

    assert get_attempt(client, body["attempt_id"])["status"] == "expired"
    late = complete_callback(client, state)
    assert late.status_code == 400
    assert "Authorization not valid" in late.text
    assert count(Path(_db(client)), "accounts") == 0


def _db(client: TestClient) -> str:
    engine: Engine = _app(client).state.session_factory.kw["bind"]
    return str(engine.url.database)


def test_oauth_result_after_the_delete_creates_nothing(
    client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    db_path: Path,
    project: dict[str, Any],
) -> None:
    """End to end: the callback already holds its tokens and wrote the secret; the
    account is deleted through the endpoint; the final step then finds no account."""
    account = create_account(client, project["id"], "youtube", "cyberchannel")
    token = preview(client, account["id"])["confirmation"]
    body, state = authorize(client, account["id"])
    deleted: list[int] = []
    _after_set(
        credential_store,
        lambda: deleted.append(delete(client, account["id"], token).status_code),
    )

    response = complete_callback(client, state)

    assert deleted == [204]
    assert response.status_code == 400
    assert "no longer valid" in response.text
    attempt = get_attempt(client, body["attempt_id"])
    assert attempt["status"] == "failed" and attempt["error"]["code"] == GONE
    assert credential_store.secrets == {}
    assert count(db_path, "accounts") == count(db_path, "youtube_connections") == 0
    assert queued(db_path) == []


def _after_set(store: InMemoryCredentialStore, action: Callable[[], None]) -> None:
    original = store.set
    fired = threading.Event()

    def set_then_act(ref: str, value: str) -> None:
        original(ref, value)
        if not fired.is_set():
            fired.set()
            action()

    store.set = set_then_act  # type: ignore[method-assign]


def test_tiktok_pending_credential_is_dropped_without_revoke(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
) -> None:
    set_probe(tiktok_client, "available")
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    attempt_id = _awaiting(tiktok_client, account["id"], fake_tiktok)
    registry = _app(tiktok_client).state.tiktok_attempts

    def never_revoke(*_: Any) -> None:
        raise AssertionError("a delete must never revoke on TikTok")

    registry.discard = never_revoke

    assert confirmed_delete(tiktok_client, account["id"]).status_code == 204

    assert fake_tiktok.requests == []  # no revoke, no call at all
    assert poll_tiktok_attempt(tiktok_client, attempt_id)["status"] == "expired"
    assert count(db_path, "tiktok_connections") == count(db_path, "accounts") == 0
    assert tiktok_credential_store.secrets == {}
    assert queued(db_path) == []


def _telegram_base(account_id: int) -> str:
    return f"/api/accounts/{account_id}/telegram-connection"


def _login(client: TestClient, account_id: int) -> None:
    started = client.post(
        f"{_telegram_base(account_id)}/login/start", json={"phone": FAKE_PHONE}
    )
    assert started.status_code == 200, started.text
    done = client.post(
        f"{_telegram_base(account_id)}/login/code", json={"code": FAKE_CODE}
    )
    assert done.status_code == 200, done.text


def test_telegram_login_finishing_after_the_delete_creates_nothing(
    telegram_client: TestClient,
    telegram_credential_store: InMemoryCredentialStore,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
) -> None:
    """The code step holds `account_session` while the delete commits: no deadlock
    with `write_transaction`, and no log out."""
    set_probe(telegram_client, "available")
    project = create_project(telegram_client, "Tg")
    account = create_account(telegram_client, project["id"], "telegram", "tg")
    token = preview(telegram_client, account["id"])["confirmation"]
    started = telegram_client.post(
        f"{_telegram_base(account['id'])}/login/start", json={"phone": FAKE_PHONE}
    )
    assert started.status_code == 200
    deleted: list[int] = []
    calls_at_delete: list[int] = []

    def delete_now() -> None:
        deleted.append(delete(telegram_client, account["id"], token).status_code)
        calls_at_delete.append(len(fake_telegram.calls))

    _after_set(telegram_credential_store, delete_now)

    response = telegram_client.post(
        f"{_telegram_base(account['id'])}/login/code", json={"code": FAKE_CODE}
    )

    assert deleted == [204]
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == GONE
    assert telegram_credential_store.secrets == {}
    assert count(db_path, "telegram_connections") == count(db_path, "accounts") == 0
    assert "log_out" not in fake_telegram.calls
    assert len(fake_telegram.calls) == calls_at_delete[0]
    assert _app(telegram_client).state.telegram_logins.get(account["id"]) is None


def test_telegram_step_in_progress_never_blocks_and_cleanup_waits_for_it(
    telegram_client: TestClient,
    telegram_credential_store: InMemoryCredentialStore,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_probe(telegram_client, "available")
    project = create_project(telegram_client, "Tg")
    account = create_account(telegram_client, project["id"], "telegram", "tg")
    _login(telegram_client, account["id"])
    calls_before = len(fake_telegram.calls)
    token = preview(telegram_client, account["id"])["confirmation"]
    cleanup_started = threading.Event()
    real_cleanup = cleanup_module.run_credential_cleanup

    def cleanup(*args: Any) -> None:
        cleanup_started.set()
        real_cleanup(*args)

    monkeypatch.setattr(deletion, "run_credential_cleanup", cleanup)
    step = Gate()

    def holding_step() -> None:
        with account_session(account["id"], wait=False):
            step.pause()

    holder = Background(holding_step)
    step.wait_reached()
    deleting = Background(lambda: delete(telegram_client, account["id"], token))
    assert cleanup_started.wait(10)  # committed while the step holds the session
    assert count(db_path, "accounts") == 0
    assert len(telegram_credential_store.secrets) == 1  # cleanup waits for the step
    step.release()

    holder.result()
    assert deleting.result().status_code == 204
    assert telegram_credential_store.secrets == {}
    assert queued(db_path) == []
    assert len(fake_telegram.calls) == calls_before  # no log out


# --- Temporary delivery objects -----------------------------------------------------


def test_pending_delivery_objects_are_still_released_after_the_delete(
    delivery_client: TestClient,  # noqa: F811
    delivery: FakeMediaDeliveryProvider,  # noqa: F811
    db_path: Path,
) -> None:
    client = delivery_client
    project = create_project(client, "Cyber")
    account = create_account(client, project["id"], "instagram", "cyber")
    _post_with_dependents(db_path, account, FakeClock().now(), delivery)

    assert confirmed_delete(client, account["id"]).status_code == 204

    pending = "object_key = 'pending/key.jpg' AND attempt_id IS NULL"
    assert count(db_path, "temporary_media_objects", pending) == 1
    assert delivery.delete_calls == []  # nothing remote during the delete
    assert _app(client).state.temporary_media.sweep() == 0
    assert delivery.delete_calls == ["pending/key.jpg"]


# --- Publication start vs Delete Account --------------------------------------------


@pytest.fixture
def due(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> dict[str, Any]:
    """An armed automatic post whose time has come, plus a draft of the account."""
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    readmodels.post(db_path, setup["account"], fake_clock.now(), status="unscheduled")
    fake_clock.set(at)
    return setup


def test_delete_account_first_then_scheduler_claim(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    due: dict[str, Any],
) -> None:
    client = fake_scheduler_client
    account_id = due["account"]["id"]
    token = preview(client, account_id)["confirmation"]
    factory = _app(client).state.session_factory
    engine: Engine = factory.kw["bind"]

    def deleted(session: Session) -> bool:
        query = select(func.count()).select_from(Account)
        return session.scalar(query.where(Account.id == account_id)) == 0

    prepare = pause_in_prepare(fake_publisher)
    tick = Background(lambda: _run_tick(client))
    prepare.wait_reached()
    with (
        pause_before_commit(factory, deleted) as commit,
        statement_reached(engine, "UPDATE publications SET status") as claim,
    ):
        deleting = Background(lambda: delete(client, account_id, token))
        commit.wait_reached()
        prepare.release()
        assert claim.wait(10)
        commit.release()
        assert deleting.result().status_code == 204
        report: TickReport = tick.result()

    assert report.started == [] and report.failed == []
    assert attempt_rows(db_path) == []
    assert fake_publisher.upload_calls == []
    assert count(db_path, "publications") == count(db_path, "accounts") == 0


def _run_tick(client: TestClient) -> TickReport:
    report: TickReport = _app(client).state.scheduler.run_once()
    return report


@pytest.mark.parametrize("entrypoint", ["scheduler", "publish-now"])
def test_claim_first_blocks_the_account_delete(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    due: dict[str, Any],
    entrypoint: str,
) -> None:
    client = fake_scheduler_client
    account_id = due["account"]["id"]
    post_id = due["publication"]["id"]
    token = preview(client, account_id)["confirmation"]
    fake_publisher.upload_gate = threading.Event()
    factory = _app(client).state.session_factory

    def start() -> Any:
        if entrypoint == "scheduler":
            return _run_tick(client)
        return client.post(f"/api/publications/{post_id}/publish", json={})

    with pause_before_commit(factory, is_claim) as claim:
        starting = Background(start)
        claim.wait_reached()
        deleting = Background(lambda: delete(client, account_id, token))
        claim.release()
        starting.result()
        response = deleting.result()

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "post_in_progress",
        "message": IN_PROGRESS,
        "fields": [],
    }
    assert count(db_path, "accounts") == 1
    assert count(db_path, "publications") == 2
    fake_publisher.upload_gate.set()
    wait_idle(client)
    assert count(db_path, "publications", "status = 'published'") == 1


# --- Installation guards ------------------------------------------------------------


def test_account_routes_are_private_and_guarded(installation: TestClient) -> None:  # noqa: F811
    client = installation
    assert (
        client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    )
    project = create_project(client, "Cyber")
    account = create_account(client, project["id"], "youtube", "cyber")
    token = preview(client, account["id"])["confirmation"]
    url = f"/api/accounts/{account['id']}"

    anonymous = TestClient(
        client.app,
        base_url=BASE_URL,
        client=("127.0.0.1", 50000),
        headers={"origin": BASE_URL},
    )
    for response in (
        anonymous.get(f"{url}/deletion-preview"),
        anonymous.delete(url, params={"confirmation": token}),
    ):
        assert response.status_code == 401
    cross_site = client.delete(
        url, params={"confirmation": token}, headers={"origin": "http://evil.example"}
    )
    assert cross_site.json()["error"]["code"] == "origin_not_allowed"
    foreign_host = client.delete(
        url, params={"confirmation": token}, headers={"host": "evil.example"}
    )
    assert foreign_host.json()["error"]["code"] == "host_not_allowed"
    # The token is no authorization: a forged one is just a changed scope.
    forged = client.delete(url, params={"confirmation": "v1:" + "0" * 64})
    assert forged.status_code == 409
    assert client.get("/api/accounts/9999/deletion-preview").status_code == 404
    assert client.delete(url, params={"confirmation": token}).status_code == 204
