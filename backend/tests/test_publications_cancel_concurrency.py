"""Cancel vs publication claim (same guarantee as the PATCH, Feature 024).

The cancel decides and writes inside `write_transaction` (`BEGIN IMMEDIATE`), the
claim is one conditional UPDATE. Every order is forced with barriers (never
`sleep`) and exactly one side wins:

- the cancel holds the writer lock first → the claim waits, then finds the post
  cancelled and does not start;
- the claim commits first → the cancel sees `publishing`: `409
  publication_not_editable`, nothing written.

A running attempt always belongs to a `publishing` post: never `cancelled` (or
`scheduled`) with an execution in progress.
"""

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import app.publications
from app.scheduler import TickReport
from tests.barriers import (
    Background,
    is_claim,
    pause_after_call,
    pause_before_commit,
    statement_reached,
)
from tests.conftest import (
    attempt_rows,
    in_minutes,
    run_tick,
    scheduled_publication,
    wait_idle,
)
from tests.fakes import FakeClock, FakePublisher


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _engine(client: TestClient) -> Engine:
    engine: Engine = _app(client).state.session_factory.kw["bind"]
    return engine


@pytest.fixture
def client(
    fake_scheduler_client: TestClient, fake_publisher: FakePublisher
) -> Iterator[TestClient]:
    """The upload stays blocked, so a started execution is still `running` while
    the test looks at it and can never finish behind the test."""
    fake_publisher.upload_gate = threading.Event()
    try:
        yield fake_scheduler_client
    finally:
        fake_publisher.upload_gate.set()
        wait_idle(fake_scheduler_client)


@pytest.fixture
def due(client: TestClient, fake_clock: FakeClock, db_path: Path) -> int:
    """An armed automatic post whose time has come."""
    at = in_minutes(fake_clock, 5)
    post_id: int = scheduled_publication(client, db_path, at)["publication"]["id"]
    fake_clock.set(at)
    return post_id


def _cancel(client: TestClient, post_id: int) -> Any:
    return client.post(f"/api/publications/{post_id}/cancel")


def _row(db_path: Path, post_id: int) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT status, scheduled_at, auto_publish_enabled FROM publications "
            "WHERE id = ?",
            (post_id,),
        ).fetchone()
    return dict(row)


def writer_lock_held(db_path: Path) -> bool:
    """Whether another connection holds SQLite's writer lock right now: a
    `BEGIN IMMEDIATE` that does not wait fails while it does."""
    connection = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as error:
        assert "locked" in str(error)
        return True
    else:
        connection.execute("ROLLBACK")
        return False
    finally:
        connection.close()


def assert_running_attempts_are_publishing(db_path: Path) -> None:
    """No `cancelled` (or any other) post owns an execution in progress."""
    with sqlite3.connect(db_path) as connection:
        broken = connection.execute(
            "SELECT p.id, p.status FROM publications p JOIN publication_attempts a "
            "ON a.publication_id = p.id "
            "WHERE a.status = 'running' AND p.status != 'publishing'"
        ).fetchall()
    assert broken == []


def _assert_cancelled_and_not_started(
    db_path: Path, post_id: int, before: dict[str, Any], report: TickReport
) -> None:
    assert report.started == []
    assert attempt_rows(db_path) == []
    after = _row(db_path, post_id)
    assert after["status"] == "cancelled"
    # Cancelling keeps the date and disarms.
    assert after["scheduled_at"] == before["scheduled_at"]
    assert after["auto_publish_enabled"] == 0
    assert_running_attempts_are_publishing(db_path)


# --- The claim commits first ----------------------------------------------------------


def test_claim_first_then_cancel_is_not_editable(
    client: TestClient, db_path: Path, due: int
) -> None:
    """The cancel waits for the claim's COMMIT and then reads `publishing`."""
    before = _row(db_path, due)
    factory = _app(client).state.session_factory
    with pause_before_commit(factory, is_claim) as claim:
        ticking = Background(lambda: run_tick(client))
        claim.wait_reached()
        with statement_reached(_engine(client), "BEGIN IMMEDIATE") as waiting:
            cancelling = Background(lambda: _cancel(client, due))
            assert waiting.wait(10)
        claim.release()
        report: TickReport = ticking.result()
        response = cancelling.result()

    assert report.started == [due]
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    after = _row(db_path, due)
    assert after["status"] == "publishing"
    assert after["scheduled_at"] == before["scheduled_at"]
    rows = attempt_rows(db_path)
    assert [(row["status"], row["stage"]) for row in rows] == [("running", "preparing")]
    assert rows[0]["publication_id"] == due
    assert_running_attempts_are_publishing(db_path)


# --- The cancel holds the writer lock first -------------------------------------------


def test_cancel_first_then_claim_finds_it_cancelled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_path: Path, due: int
) -> None:
    """The cancel is paused after its writes, before committing: the claim's
    UPDATE waits for the lock and then finds the post no longer scheduled."""
    before = _row(db_path, due)
    with pause_after_call(monkeypatch, app.publications, "disarm") as cancel:
        cancelling = Background(lambda: _cancel(client, due))
        cancel.wait_reached()
        # The paused cancel holds the writer lock: the claim has to wait for it.
        assert writer_lock_held(db_path)
        with statement_reached(_engine(client), "UPDATE publications") as claiming:
            ticking = Background(lambda: run_tick(client))
            assert claiming.wait(10)
        cancel.release()
        response = cancelling.result()
        report: TickReport = ticking.result()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    _assert_cancelled_and_not_started(db_path, due, before, report)


def test_claim_between_the_cancel_read_and_write_does_not_start(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_path: Path, due: int
) -> None:
    """Lost-update regression. Before, the cancel read without the writer lock:
    a claim committed between its check and its write, and the cancel then wrote
    `cancelled` over `publishing`, leaving the claim's attempt running. Now the
    claim waits for the cancel and finds the post cancelled."""
    before = _row(db_path, due)
    with pause_after_call(
        monkeypatch, app.publications, "get_publication_or_404"
    ) as cancel:
        cancelling = Background(lambda: _cancel(client, due))
        cancel.wait_reached()
        # The paused cancel holds the writer lock: the claim has to wait for it.
        assert writer_lock_held(db_path)
        with statement_reached(_engine(client), "UPDATE publications") as claiming:
            ticking = Background(lambda: run_tick(client))
            assert claiming.wait(10)
        cancel.release()
        response = cancelling.result()
        report: TickReport = ticking.result()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    _assert_cancelled_and_not_started(db_path, due, before, report)
