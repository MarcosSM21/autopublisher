"""PATCH vs publication claim (Feature 024, FR-030–FR-033, research R2/R15).

The PATCH decides and writes inside `write_transaction` (`BEGIN IMMEDIATE`), the
claim is one conditional UPDATE. Every order is forced with barriers (never `sleep`)
and exactly one side wins:

- the PATCH holds the writer lock first → the claim waits, then sees the new date
  and does not start;
- the claim commits first → the PATCH sees `publishing`: `409
  publication_not_editable`, nothing written.

Never a publication left `scheduled` while it has a `running` attempt.
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
    FUTURE,
    LATER,
    attempt_rows,
    get_publication,
    in_minutes,
    run_tick,
    scheduled_publication,
    wait_idle,
)
from tests.fakes import FakeClock, FakePublisher

RESCHEDULE = {"scheduled_at": FUTURE, "auto_publish_enabled": True}


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


def _patch(client: TestClient, post_id: int, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/publications/{post_id}", json=body)


def _row(db_path: Path, post_id: int) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT status, scheduled_at, auto_publish_enabled FROM publications "
            "WHERE id = ?",
            (post_id,),
        ).fetchone()
    return dict(row)


def assert_no_scheduled_with_running_attempt(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        broken = connection.execute(
            "SELECT p.id FROM publications p JOIN publication_attempts a "
            "ON a.publication_id = p.id "
            "WHERE p.status = 'scheduled' AND a.status = 'running'"
        ).fetchall()
    assert broken == []


def _assert_rescheduled_and_not_started(
    client: TestClient, db_path: Path, post_id: int, report: TickReport
) -> None:
    assert report.started == []
    assert attempt_rows(db_path) == []
    publication = get_publication(client, post_id)
    assert publication["status"] == "scheduled"
    assert publication["scheduled_at"] == FUTURE
    assert publication["auto_publish_enabled"] is True
    assert_no_scheduled_with_running_attempt(db_path)


def _assert_rescheduled(response: Any) -> None:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["scheduled_at"] == FUTURE
    assert body["auto_publish_enabled"] is True
    assert body["display_state"] == "scheduled_automatic"


# --- The claim commits first ----------------------------------------------------------


def test_claim_first_then_patch_is_not_editable(
    client: TestClient, db_path: Path, due: int
) -> None:
    """The PATCH waits for the claim's COMMIT and then reads `publishing`."""
    before = _row(db_path, due)
    factory = _app(client).state.session_factory
    with pause_before_commit(factory, is_claim) as claim:
        ticking = Background(lambda: run_tick(client))
        claim.wait_reached()
        with statement_reached(_engine(client), "BEGIN IMMEDIATE") as patch_waiting:
            patching = Background(lambda: _patch(client, due, RESCHEDULE))
            assert patch_waiting.wait(10)
        claim.release()
        report: TickReport = ticking.result()
        response = patching.result()

    assert report.started == [due]
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    after = _row(db_path, due)
    assert after["status"] == "publishing"
    assert after["scheduled_at"] == before["scheduled_at"]
    # Disarmed by the claim itself; the PATCH's `true` was not written.
    assert after["auto_publish_enabled"] == 0
    rows = attempt_rows(db_path)
    assert [(row["status"], row["stage"]) for row in rows] == [("running", "preparing")]
    assert rows[0]["publication_id"] == due
    assert_no_scheduled_with_running_attempt(db_path)


# --- The PATCH holds the writer lock first -------------------------------------------


def test_patch_first_then_claim_sees_the_new_date(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_path: Path, due: int
) -> None:
    """The PATCH is paused after its mutations, before committing: the claim's
    UPDATE waits for the lock and then finds the post out of its window."""
    with pause_after_call(monkeypatch, app.publications, "_set_consent") as patch:
        patching = Background(lambda: _patch(client, due, RESCHEDULE))
        patch.wait_reached()
        with statement_reached(_engine(client), "UPDATE publications") as claiming:
            ticking = Background(lambda: run_tick(client))
            assert claiming.wait(10)
        patch.release()
        response = patching.result()
        report: TickReport = ticking.result()

    _assert_rescheduled(response)
    _assert_rescheduled_and_not_started(client, db_path, due, report)


def test_claim_between_the_patch_read_and_write_does_not_start(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_path: Path, due: int
) -> None:
    """Lost-update regression. Before Feature 024 the PATCH read without the
    writer lock: a claim committed between its editability check and its write,
    and the PATCH then wrote `scheduled` over `publishing` with a running attempt.
    Now the claim waits for the PATCH and sees the new date."""
    with pause_after_call(monkeypatch, app.publications, "ensure_editable") as patch:
        patching = Background(lambda: _patch(client, due, RESCHEDULE))
        patch.wait_reached()
        with statement_reached(_engine(client), "UPDATE publications") as claiming:
            ticking = Background(lambda: run_tick(client))
            assert claiming.wait(10)
        patch.release()
        response = patching.result()
        report: TickReport = ticking.result()

    _assert_rescheduled(response)
    _assert_rescheduled_and_not_started(client, db_path, due, report)


# --- Two PATCHes ---------------------------------------------------------------------


def test_two_concurrent_reschedules_last_commit_wins(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db_path: Path, due: int
) -> None:
    with pause_after_call(monkeypatch, app.publications, "ensure_editable") as first:
        first_patch = Background(lambda: _patch(client, due, RESCHEDULE))
        first.wait_reached()
        with statement_reached(_engine(client), "BEGIN IMMEDIATE") as second_waiting:
            second_patch = Background(
                lambda: _patch(
                    client, due, {"scheduled_at": LATER, "auto_publish_enabled": True}
                )
            )
            assert second_waiting.wait(10)
        first.release()
        first_response = first_patch.result()
        second_response = second_patch.result()

    _assert_rescheduled(first_response)
    assert second_response.status_code == 200, second_response.text
    publication = get_publication(client, due)
    assert publication["scheduled_at"] == LATER
    assert publication["auto_publish_enabled"] is True
    assert publication["status"] == "scheduled"
    assert attempt_rows(db_path) == []
    assert_no_scheduled_with_running_attempt(db_path)
