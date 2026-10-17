"""Needs attention (research.md §7): one case per rule, dedup and folding, scope,
and the guarantee that the overview never writes nor uses the network."""

import socket
import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import Platform
from app.publishing import PublishProblem
from tests.conftest import (
    create_account,
    create_project,
    make_scheduler_app,
    run_sql,
)
from tests.fakes import FakeClock, FakePublisher
from tests.readmodels import connect, failed_attempt, post

Account = dict[str, Any]


@pytest.fixture
def telegram_publisher() -> FakePublisher:
    return FakePublisher(accepts_text_only=True)


@pytest.fixture
def overview_client(
    db_path: Path,
    media_dir: Path,
    fake_clock: FakeClock,
    telegram_publisher: FakePublisher,
) -> Iterator[TestClient]:
    app = make_scheduler_app(db_path, media_dir, fake_clock)
    with TestClient(app) as client:
        assert isinstance(client.app, FastAPI)
        client.app.state.publishers[Platform.TELEGRAM] = telegram_publisher
        yield client


def overview(client: TestClient, project_id: int | None = None) -> dict[str, Any]:
    params = {} if project_id is None else {"project_id": project_id}
    response = client.get("/api/overview", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def telegram_account(
    client: TestClient, db_path: Path, now: datetime, project: str = "Cyber"
) -> Account:
    """A connected Telegram account (ready) in a new project."""
    project_id = create_project(client, project)["id"]
    account = create_account(client, project_id, "telegram", "cyber")
    connect(db_path, account, now)
    return account


HOUR = timedelta(hours=1)
Setup = Callable[[TestClient, Path, datetime, Account, FakePublisher], None]


def _manual_review(c: TestClient, db: Path, now: datetime, a: Account, _: Any) -> None:
    failed_attempt(db, post(db, a, now, status="failed"), now, uncertain=True)


def _failed(c: TestClient, db: Path, now: datetime, a: Account, _: Any) -> None:
    failed_attempt(db, post(db, a, now, status="failed"), now)


def _missed_automatic(
    c: TestClient, db: Path, now: datetime, a: Account, _: Any
) -> None:
    post(db, a, now, scheduled_at=now - HOUR, armed=True)


def _missed_manual(c: TestClient, db: Path, now: datetime, a: Account, _: Any) -> None:
    post(db, a, now, scheduled_at=now - timedelta(minutes=5))


def _missed_paused(c: TestClient, db: Path, now: datetime, a: Account, _: Any) -> None:
    post(db, a, now, scheduled_at=now - timedelta(minutes=5), armed=True)
    c.put("/api/automation", json={"paused": True})


def _needs_action(c: TestClient, db: Path, now: datetime, a: Account, _: Any) -> None:
    post(db, a, now, status="awaiting_user_action")


def _reconnect(c: TestClient, db: Path, now: datetime, a: Account, _: Any) -> None:
    run_sql(db, "UPDATE telegram_connections SET status = 'reconnect_required'")


def _incomplete(
    c: TestClient, db: Path, now: datetime, a: Account, fake: FakePublisher
) -> None:
    publication_id = post(db, a, now, scheduled_at=now + HOUR)
    fake.problems[publication_id] = [
        PublishProblem("telegram_text_too_long", "The text is too long.")
    ]


def _unverifiable(
    c: TestClient, db: Path, now: datetime, a: Account, fake: FakePublisher
) -> None:
    post(db, a, now, scheduled_at=now + HOUR, armed=True)

    def unavailable(*_: object) -> None:
        raise RuntimeError("secure storage unavailable")

    fake.check = unavailable  # type: ignore[method-assign, assignment]


def _expiring(c: TestClient, db: Path, now: datetime, a: Account, _: Any) -> None:
    instagram = create_account(c, a["project_id"], "instagram", "cyber")
    connect(db, instagram, now, expires_at=now + timedelta(days=3))


@pytest.mark.parametrize(
    ("setup", "kind", "label", "target", "detail"),
    [
        (_manual_review, "manual_review", "Review", "post",
         "This post may have published. Check it before trying again."),
        (_failed, "failed", "Retry", "post", "The platform rejected the post."),
        (_missed_automatic, "missed", "Publish now", "post", None),
        (_missed_manual, "missed", "Publish now", "post", None),
        (_missed_paused, "missed", "Resume automation", "settings", None),
        (_needs_action, "needs_action", "Check status", "post", None),
        (_reconnect, "reconnect", "Reconnect", "account", None),
        (_incomplete, "incomplete", "Complete", "post", "The text is too long."),
        (_unverifiable, "incomplete", "Complete", "post",
         "Couldn't verify requirements"),
        (_expiring, "expiring", "Reconnect", "account", None),
    ],
)  # fmt: skip
def test_attention_rule(
    overview_client: TestClient,
    db_path: Path,
    fake_clock: FakeClock,
    telegram_publisher: FakePublisher,
    setup: Setup,
    kind: str,
    label: str,
    target: str,
    detail: str | None,
) -> None:
    now = fake_clock.now()
    account = telegram_account(overview_client, db_path, now)
    setup(overview_client, db_path, now, account, telegram_publisher)

    [item] = overview(overview_client)["attention"]

    assert (item["kind"], item["action"]["label"]) == (kind, label)
    assert item["action"]["target"]["type"] == target
    if detail is not None:
        assert item["detail"] == detail
    if target == "post":
        assert item["action"]["target"]["id"] == item["post"]["id"]
        assert item["action"]["target"]["project_id"] == account["project_id"]


def test_one_item_per_post_priority_order_and_folding(
    overview_client: TestClient,
    db_path: Path,
    fake_clock: FakeClock,
    telegram_publisher: FakePublisher,
) -> None:
    now = fake_clock.now()
    account = telegram_account(overview_client, db_path, now)
    run_sql(db_path, "UPDATE telegram_connections SET status = 'reconnect_required'")
    reconnect = PublishProblem("telegram_reconnect_required", "Reconnect Telegram.")
    # Failed with an uncertain result: only "needs review", never also "failed".
    failed_attempt(db_path, post(db_path, account, now, status="failed"), now,
                   uncertain=True)  # fmt: skip
    # Missed and also incomplete: only "missed".
    missed = post(db_path, account, now, scheduled_at=now - HOUR, armed=True)
    telegram_publisher.problems[missed] = [reconnect]
    # Upcoming with only the connection problem: folded into the account item.
    folded = post(db_path, account, now, scheduled_at=now + HOUR)
    telegram_publisher.problems[folded] = [reconnect]
    # Upcoming with another problem too: its own item.
    other = post(db_path, account, now, scheduled_at=now + 2 * HOUR)
    telegram_publisher.problems[other] = [
        reconnect,
        PublishProblem("telegram_text_too_long", "The text is too long."),
    ]

    attention = overview(overview_client)["attention"]

    assert [item["kind"] for item in attention] == [
        "manual_review",
        "missed",
        "reconnect",
        "incomplete",
    ]
    assert attention[2]["affected_posts"] == 1
    assert attention[3]["post"]["id"] == other
    post_ids = [item["post"]["id"] for item in attention if item["post"]]
    assert len(post_ids) == len(set(post_ids))


def test_project_filter_and_inactive_projects_and_accounts(
    overview_client: TestClient,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    now = fake_clock.now()
    active = telegram_account(overview_client, db_path, now, "Active")
    # Inactive account with an expiring login: no "expiring", its post still counts.
    instagram = create_account(overview_client, active["project_id"], "instagram", "ig")
    connect(db_path, instagram, now, expires_at=now + timedelta(days=2))
    run_sql(db_path, "UPDATE accounts SET is_active = 0 WHERE id = ?", instagram["id"])
    post(db_path, instagram, now, status="awaiting_user_action")
    # Inactive project: only failed / needs review / needs action.
    dormant = telegram_account(overview_client, db_path, now, "Dormant")
    run_sql(db_path, "UPDATE telegram_connections SET status = 'reconnect_required' "
            "WHERE account_id = ?", dormant["id"])  # fmt: skip
    failed_attempt(db_path, post(db_path, dormant, now, status="failed"), now)
    post(db_path, dormant, now, status="awaiting_user_action")
    post(db_path, dormant, now, scheduled_at=now - HOUR, armed=True)
    post(db_path, dormant, now, scheduled_at=now + HOUR)
    run_sql(db_path, "UPDATE projects SET is_active = 0 WHERE id = ?",
            dormant["project_id"])  # fmt: skip

    everything = overview(overview_client)
    kinds = {(item["project"]["id"], item["kind"]) for item in everything["attention"]}
    assert kinds == {
        (active["project_id"], "needs_action"),
        (dormant["project_id"], "failed"),
        (dormant["project_id"], "needs_action"),
    }
    assert everything["upcoming"] == []  # inactive projects never plan ahead

    scoped = overview(overview_client, active["project_id"])
    assert {item["project"]["id"] for item in scoped["attention"]} == {
        active["project_id"]
    }
    assert [project["id"] for project in scoped["projects"]] == [active["project_id"]]
    assert scoped["projects"][0]["accounts_active"] == 1
    assert scoped["projects"][0]["accounts_ready"] == 1
    assert scoped["projects"][0]["attention_count"] == 1
    assert overview_client.get("/api/overview?project_id=999").status_code == 404


def _rows(db_path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(db_path) as connection:
        tables = [
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ]
        return {
            table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(),
                          key=repr)
            for table in tables
        }  # fmt: skip


def test_overview_never_writes_nor_uses_the_network(
    overview_client: TestClient,
    db_path: Path,
    fake_clock: FakeClock,
    telegram_publisher: FakePublisher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = fake_clock.now()
    account = telegram_account(overview_client, db_path, now)
    failed_attempt(db_path, post(db_path, account, now, status="failed"), now,
                   uncertain=True)  # fmt: skip
    post(db_path, account, now, status="awaiting_user_action")
    upcoming = post(db_path, account, now, scheduled_at=now + HOUR, armed=True)
    telegram_publisher.problems[upcoming] = [
        PublishProblem("telegram_text_too_long", "The text is too long.")
    ]
    # Real publishers' local checks, too: YouTube, Instagram, Threads and TikTok.
    for platform in ("youtube", "instagram", "threads", "tiktok"):
        other = create_account(overview_client, account["project_id"], platform, "c")
        connect(db_path, other, now, expires_at=now + timedelta(days=1))
        post(db_path, other, now, scheduled_at=now + HOUR, armed=True)
    overview_client.put("/api/automation", json={"paused": True})
    before = _rows(db_path)

    def no_network(*_: object, **__: object) -> None:
        raise AssertionError("the overview must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert isinstance(overview_client.app, FastAPI)
    monkeypatch.setattr(overview_client.app.state, "telegram_gateway", None)

    body = overview(overview_client)
    health = overview_client.get(
        f"/api/projects/{account['project_id']}/account-health"
    )
    platforms = overview_client.get("/api/platforms")

    assert health.status_code == 200 and platforms.status_code == 200
    assert body["automation"]["paused"] is True
    assert body["attention"]
    assert _rows(db_path) == before
    assert telegram_publisher.reconcile_calls == []
    assert telegram_publisher.follow_up_calls == []
    assert telegram_publisher.prepare_calls == []
    assert telegram_publisher.upload_calls == []
