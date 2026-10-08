"""No duplicated executions (User Story 5): concurrent cycles, several schedulers and
"Publish now" racing the scheduler start at most one attempt per publication."""

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import ConflictError
from app.models import AttemptTrigger
from app.publishing import PublishFailure, start_publication
from app.scheduler import Scheduler, TickReport
from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    run_sql,
    run_tick,
    scheduled_publication,
    wait_idle,
)
from tests.fakes import UPLOAD_URL, FakeClock, FakeGoogle, FakePublisher


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _second_scheduler(client: TestClient) -> Scheduler:
    """Another scheduler instance over the same database and services."""
    state = _app(client).state
    first: Scheduler = state.scheduler
    return Scheduler(
        first.session_factory, first.ctx, first.runner, first.publishers, first.settings
    )


def _in_parallel(*calls: Callable[[], Any]) -> list[Any]:
    results: list[Any] = [None] * len(calls)
    errors: list[BaseException] = []

    def run(index: int, call: Callable[[], Any]) -> None:
        try:
            results[index] = call()
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    threads = [
        threading.Thread(target=run, args=(index, call))
        for index, call in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert errors == []
    return results


def _barrier(fake_publisher: FakePublisher, parties: int) -> None:
    barrier = threading.Barrier(parties, timeout=5)

    def wait(_: int) -> None:
        barrier.wait()

    fake_publisher.prepare_hook = wait


@pytest.fixture
def due(fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path) -> int:
    at = in_minutes(fake_clock, 5)
    publication_id: int = scheduled_publication(fake_scheduler_client, db_path, at)[
        "publication"
    ]["id"]
    fake_clock.set(at)
    return publication_id


def test_two_concurrent_cycles_start_one_execution(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    due: int,
) -> None:
    _barrier(fake_publisher, 2)
    scheduler: Scheduler = _app(fake_scheduler_client).state.scheduler

    reports: list[TickReport] = _in_parallel(scheduler.run_once, scheduler.run_once)

    assert sorted(len(report.started) for report in reports) == [0, 1]
    wait_idle(fake_scheduler_client)
    assert len(attempt_rows(db_path)) == 1
    assert fake_publisher.upload_calls == [due]


def test_two_schedulers_start_one_execution(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    due: int,
) -> None:
    _barrier(fake_publisher, 2)
    first: Scheduler = _app(fake_scheduler_client).state.scheduler
    second = _second_scheduler(fake_scheduler_client)

    _in_parallel(first.run_once, second.run_once)

    wait_idle(fake_scheduler_client)
    assert len(attempt_rows(db_path)) == 1
    assert fake_publisher.upload_calls == [due]


def test_cycle_and_publish_now_start_one_execution(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    due: int,
) -> None:
    _barrier(fake_publisher, 2)

    def publish_now() -> int:
        response = fake_scheduler_client.post(
            f"/api/publications/{due}/publish", json={}
        )
        return response.status_code

    report, status = _in_parallel(lambda: run_tick(fake_scheduler_client), publish_now)

    wait_idle(fake_scheduler_client)
    rows = attempt_rows(db_path)
    assert len(rows) == 1
    assert fake_publisher.upload_calls == [due]
    if rows[0]["trigger"] == "manual":
        assert status == 202
        assert report.started == []
    else:
        assert status == 409
        assert report.started == [due]


def test_consecutive_cycles_during_an_upload_start_nothing_more(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    due: int,
) -> None:
    gate = threading.Event()
    fake_publisher.upload_gate = gate

    run_tick(fake_scheduler_client)
    for _ in range(3):
        fake_clock.advance(30)
        assert run_tick(fake_scheduler_client).started == []
    gate.set()

    wait_idle(fake_scheduler_client)
    assert len(attempt_rows(db_path)) == 1
    assert get_publication(fake_scheduler_client, due)["status"] == "published"


@pytest.mark.parametrize("status", ["publishing", "published", "failed", "cancelled"])
def test_other_statuses_are_never_started_automatically(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    due: int,
    status: str,
) -> None:
    published_at = "'2026-10-07 10:00:00'" if status == "published" else "NULL"
    run_sql(
        db_path,
        f"UPDATE publications SET status = ?, auto_publish_enabled = 0, "
        f"published_at = {published_at} WHERE id = ?",
        status,
        due,
    )
    state = _app(fake_scheduler_client).state

    assert run_tick(fake_scheduler_client).started == []
    with state.session_factory() as session, pytest.raises(ConflictError):
        start_publication(
            session,
            due,
            confirm_remote_checked=False,
            ctx=state.publish_context,
            runner=state.publication_runner,
            publishers=state.publishers,
            trigger=AttemptTrigger.SCHEDULED,
            clock=fake_clock.now,
        )
    assert fake_publisher.prepare_calls == []
    assert attempt_rows(db_path) == []


@pytest.mark.parametrize(
    "change",
    [
        {"auto_publish_enabled": False},
        {"scheduled_at": "2100-01-01T10:00:00Z"},
        {"scheduled_at": None},
        "cancel",
    ],
)
def test_changes_during_the_preflight_prevent_the_start(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    due: int,
    change: Any,
) -> None:
    def hook(_: int) -> None:
        if change == "cancel":
            fake_scheduler_client.post(f"/api/publications/{due}/cancel")
        else:
            fake_scheduler_client.patch(f"/api/publications/{due}", json=change)

    fake_publisher.prepare_hook = hook

    assert run_tick(fake_scheduler_client).started == []

    assert attempt_rows(db_path) == []
    assert fake_publisher.upload_calls == []


def test_concurrent_cycles_open_one_upload_session_on_youtube(
    scheduler_client: TestClient,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    scheduled_publication(scheduler_client, db_path, at, fake_google=fake_google)
    fake_clock.set(at)
    first: Scheduler = _app(scheduler_client).state.scheduler
    second = _second_scheduler(scheduler_client)

    _in_parallel(first.run_once, second.run_once, first.run_once)

    wait_idle(scheduler_client)
    sessions = [
        request
        for request in fake_google.requests
        if request.method == "POST" and request.url.startswith(UPLOAD_URL)
    ]
    assert len(sessions) == 1
    assert len(fake_google.videos_created) == 1
    assert len(attempt_rows(db_path)) == 1


# --- Several publications due at once (User Story 7) --------------------------------


def _due_many(client: TestClient, db_path: Path, at: datetime, count: int) -> list[int]:
    return [
        scheduled_publication(client, db_path, at, project_name=f"P{index}")[
            "publication"
        ]["id"]
        for index in range(count)
    ]


def _running_scheduled(db_path: Path) -> int:
    return sum(
        1
        for row in attempt_rows(db_path)
        if row["status"] == "running" and row["trigger"] == "scheduled"
    )


def _block_uploads(
    fake_publisher: FakePublisher, ids: list[int]
) -> dict[int, threading.Event]:
    gates = {publication_id: threading.Event() for publication_id in ids}
    fake_publisher.upload_gates.update(gates)
    return gates


def test_due_publications_start_in_a_stable_order(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    first_at_time, second_at_time = _due_many(fake_scheduler_client, db_path, at, 2)
    earlier = scheduled_publication(
        fake_scheduler_client,
        db_path,
        at - timedelta(minutes=1),
        project_name="Earlier",
    )["publication"]["id"]
    assert earlier > second_at_time > first_at_time
    _block_uploads(fake_publisher, [first_at_time, second_at_time, earlier])
    fake_clock.set(at)

    report = run_tick(fake_scheduler_client)

    assert report.started == [earlier, first_at_time]
    assert report.skipped_capacity == [second_at_time]
    for gate in fake_publisher.upload_gates.values():
        gate.set()
    wait_idle(fake_scheduler_client)


def test_at_most_two_automatic_executions_at_once(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    ids = _due_many(fake_scheduler_client, db_path, at, 4)
    gates = _block_uploads(fake_publisher, ids)
    fake_clock.set(at)

    report = run_tick(fake_scheduler_client)
    assert report.started == ids[:2]
    assert report.skipped_capacity == ids[2:]
    assert fake_publisher.prepare_calls == ids[:2]

    fake_clock.advance(30)
    assert run_tick(fake_scheduler_client).started == []
    assert fake_publisher.prepare_calls == ids[:2]

    # A published upload frees its slot.
    gates[ids[0]].set()
    wait_for_status(fake_scheduler_client, ids[0], "published")
    fake_clock.advance(30)
    assert run_tick(fake_scheduler_client).started == [ids[2]]

    # A failed upload frees its slot too.
    fake_publisher.upload_failures[ids[1]] = PublishFailure(
        "network_error", "Network error.", determined=True
    )
    gates[ids[1]].set()
    wait_for_status(fake_scheduler_client, ids[1], "failed")
    fake_clock.advance(30)
    assert run_tick(fake_scheduler_client).started == [ids[3]]

    for gate in gates.values():
        gate.set()
    wait_idle(fake_scheduler_client)
    assert len(attempt_rows(db_path)) == 4


def test_manual_executions_do_not_use_automatic_slots(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    manual = [
        scheduled_publication(
            fake_scheduler_client, db_path, at + timedelta(hours=1), project_name=name
        )["publication"]["id"]
        for name in ("M1", "M2")
    ]
    automatic = _due_many(fake_scheduler_client, db_path, at, 3)
    gates = _block_uploads(fake_publisher, manual + automatic)
    for publication_id in manual:
        response = fake_scheduler_client.post(
            f"/api/publications/{publication_id}/publish", json={}
        )
        assert response.status_code == 202, response.text
    fake_clock.set(at)

    assert run_tick(fake_scheduler_client).started == automatic[:2]

    # With both automatic slots in use, "Publish now" still works.
    extra = scheduled_publication(
        fake_scheduler_client, db_path, at + timedelta(hours=2), project_name="M3"
    )["publication"]["id"]
    gates[extra] = threading.Event()
    fake_publisher.upload_gates[extra] = gates[extra]
    response = fake_scheduler_client.post(f"/api/publications/{extra}/publish", json={})
    assert response.status_code == 202, response.text
    assert _running_scheduled(db_path) == 2

    for gate in gates.values():
        gate.set()
    wait_idle(fake_scheduler_client)


def test_concurrent_schedulers_never_exceed_the_limit(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    ids = _due_many(fake_scheduler_client, db_path, at, 4)
    gates = _block_uploads(fake_publisher, ids)
    fake_clock.set(at)
    # Each cycle waits for the other before its first preflight, so both have
    # already counted two free slots.
    barrier = threading.Barrier(2, timeout=5)
    local = threading.local()

    def first_preflight_together(_: int) -> None:
        if not getattr(local, "waited", False):
            local.waited = True
            barrier.wait()

    fake_publisher.prepare_hook = first_preflight_together
    first: Scheduler = _app(fake_scheduler_client).state.scheduler
    second = _second_scheduler(fake_scheduler_client)

    reports: list[TickReport] = _in_parallel(first.run_once, second.run_once)

    assert _running_scheduled(db_path) == 2
    assert sum(len(report.started) for report in reports) == 2
    assert all(report.failed == [] for report in reports)
    for gate in gates.values():
        gate.set()
    wait_idle(fake_scheduler_client)


def test_waiting_beyond_the_window_leaves_it_overdue(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    ids = _due_many(fake_scheduler_client, db_path, at, 4)
    gates = _block_uploads(fake_publisher, ids)
    fake_clock.set(at)
    run_tick(fake_scheduler_client)

    fake_clock.set(at + timedelta(minutes=11))
    assert run_tick(fake_scheduler_client).started == []

    for publication_id in ids[2:]:
        publication = get_publication(fake_scheduler_client, publication_id)
        assert publication["status"] == "scheduled"
        assert publication["auto_publish_state"] == "overdue"
    assert fake_publisher.prepare_calls == ids[:2]
    for gate in gates.values():
        gate.set()
    wait_idle(fake_scheduler_client)


def wait_for_status(client: TestClient, publication_id: int, status: str) -> None:
    deadline = time.monotonic() + 5
    while get_publication(client, publication_id)["status"] != status:
        assert time.monotonic() < deadline, f"publication never became {status}"
        time.sleep(0.01)
