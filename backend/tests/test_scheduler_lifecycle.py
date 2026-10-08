"""The scheduler thread: start-up order, restarts around the automatic window,
clean stop and resilience to failed cycles (Feature 007, User Story 3)."""

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main, scheduler
from app.scheduler import Scheduler, SchedulerSettings
from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    make_scheduler_app,
    run_sql,
    scheduled_publication,
)
from tests.fakes import FakeClock, FakeGoogle, InMemoryCredentialStore


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.01)


def _scheduler(client: TestClient) -> Scheduler:
    app = client.app
    assert isinstance(app, FastAPI)
    instance: Scheduler = app.state.scheduler
    return instance


@pytest.fixture
def restart(
    db_path: Path,
    media_dir: Path,
    oauth_client_file: Path,
    credential_store: InMemoryCredentialStore,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
) -> Callable[..., Any]:
    """Start the whole app with a running scheduler thread (large interval: the
    next cycle only runs when the test wakes it)."""

    @contextmanager
    def start(**options: Any) -> Iterator[TestClient]:
        settings: dict[str, Any] = {"autostart": True, "interval": 3600.0}
        settings.update(options)
        app = make_scheduler_app(
            db_path,
            media_dir,
            fake_clock,
            credential_store=credential_store,
            fake_google=fake_google,
            **settings,
        )
        with TestClient(app) as client:
            yield client

    return start


@pytest.fixture
def armed_at(
    scheduler_client: TestClient,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
    db_path: Path,
) -> tuple[int, datetime]:
    """An armed, publishable publication created by a first (stopped) process."""
    at = in_minutes(fake_clock, 30)
    setup = scheduled_publication(
        scheduler_client, db_path, at, fake_google=fake_google
    )
    publication_id: int = setup["publication"]["id"]
    return publication_id, at


def _first_cycle_done(client: TestClient) -> None:
    wait_for(lambda: _scheduler(client).last_check_at is not None)


def test_restart_before_the_time_keeps_the_schedule(
    restart: Callable[..., Any],
    armed_at: tuple[int, datetime],
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id, at = armed_at
    fake_clock.set(at - timedelta(minutes=5))

    with restart() as client:
        _first_cycle_done(client)
        assert attempt_rows(db_path) == []
        assert get_publication(client, publication_id)["auto_publish_enabled"]

        fake_clock.set(at)
        _scheduler(client).wake()
        wait_for(lambda: len(attempt_rows(db_path)) == 1)

    assert attempt_rows(db_path)[0]["trigger"] == "scheduled"


@pytest.mark.parametrize(
    "delay", [timedelta(minutes=3), timedelta(minutes=9), timedelta(minutes=10)]
)
def test_restart_within_the_window_publishes(
    restart: Callable[..., Any],
    armed_at: tuple[int, datetime],
    fake_clock: FakeClock,
    db_path: Path,
    delay: timedelta,
) -> None:
    _, at = armed_at
    fake_clock.set(at + delay)

    with restart():
        wait_for(lambda: len(attempt_rows(db_path)) == 1)

    assert attempt_rows(db_path)[0]["trigger"] == "scheduled"


def test_restart_after_the_window_leaves_it_overdue(
    restart: Callable[..., Any],
    armed_at: tuple[int, datetime],
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id, at = armed_at
    fake_clock.set(at + timedelta(minutes=11))

    with restart() as client:
        _first_cycle_done(client)
        publication = get_publication(client, publication_id)

    assert attempt_rows(db_path) == []
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_enabled"] is True
    assert publication["auto_publish_state"] == "overdue"


def test_recovery_runs_before_the_first_cycle(
    restart: Callable[..., Any],
    armed_at: tuple[int, datetime],
    scheduler_client: TestClient,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    due_id, at = armed_at
    interrupted = scheduled_publication(
        scheduler_client, db_path, at, fake_google=fake_google, project_name="Other"
    )["publication"]["id"]
    run_sql(
        db_path,
        "UPDATE publications SET status = 'publishing', auto_publish_enabled = 0 "
        "WHERE id = ?",
        interrupted,
    )
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (publication_id, platform, trigger, "
        "status, stage, started_at, bytes_sent, total_bytes, submitted, details, "
        "warnings) VALUES (?, 'youtube', 'scheduled', 'running', 'uploading', "
        "'2026-10-07 10:00:00', 5, 10, '{}', '{}', '[]')",
        interrupted,
    )
    order: list[str] = []
    original_recover = main.recover_interrupted_attempts  # type: ignore[attr-defined]
    original_candidates = scheduler.Scheduler._candidates

    def recover(*args: Any) -> int:
        order.append("recovery started")
        result = original_recover(*args)
        order.append("recovery finished")
        return result

    def candidates(self: Scheduler, now: datetime) -> list[Any]:
        order.append("candidates selected")
        return original_candidates(self, now)

    monkeypatch.setattr(main, "recover_interrupted_attempts", recover)
    monkeypatch.setattr(scheduler.Scheduler, "_candidates", candidates)
    fake_clock.set(at)

    def due_attempt_finished() -> bool:
        return any(
            row["publication_id"] == due_id and row["status"] != "running"
            for row in attempt_rows(db_path)
        )

    with restart() as client:
        # Wait, while the app is still running, until the simulated upload of the
        # due publication has finished: otherwise stopping the app would mark it
        # `interrupted` and the shutdown, not the upload, would decide the result.
        wait_for(due_attempt_finished)
        recovered = get_publication(client, interrupted)

    assert order[:3] == [
        "recovery started",
        "recovery finished",
        "candidates selected",
    ]
    assert recovered["status"] == "failed"
    assert recovered["latest_attempt"]["error"]["code"] == "interrupted"
    rows = attempt_rows(db_path)
    assert len(rows) == 2
    started = [row for row in rows if row["status"] != "failed"]
    assert [row["publication_id"] for row in started] == [due_id]
    assert started[0]["status"] == "succeeded"


def test_stop_is_prompt_while_waiting(restart: Callable[..., Any]) -> None:
    with restart() as client:
        instance = _scheduler(client)
        _first_cycle_done(client)
        assert instance.running
        began = time.monotonic()
    assert time.monotonic() - began < 2
    assert not instance.running


def test_injected_wait_is_used(restart: Callable[..., Any]) -> None:
    waits: list[float] = []
    released = threading.Event()

    def wait(seconds: float) -> None:
        waits.append(seconds)
        released.wait(0.02)

    with restart(wait=wait, interval=30.0):
        wait_for(lambda: len(waits) >= 2)

    assert set(waits) == {30.0}


def test_failed_cycle_does_not_stop_the_scheduler(
    restart: Callable[..., Any],
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []
    original = scheduler.Scheduler._candidates

    def flaky(self: Scheduler, now: datetime) -> list[Any]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("secret ya29.token in a message")
        return original(self, now)

    monkeypatch.setattr(scheduler.Scheduler, "_candidates", flaky)
    caplog.set_level(logging.DEBUG)

    with restart() as client:
        wait_for(lambda: len(calls) == 1)
        _scheduler(client).wake()
        wait_for(lambda: _scheduler(client).last_check_at is not None)
        assert _scheduler(client).running

    assert "RuntimeError" in caplog.text
    assert "ya29" not in caplog.text


def test_autostart_false_never_starts_the_thread(
    scheduler_client: TestClient,
) -> None:
    assert _scheduler(scheduler_client).running is False
    assert SchedulerSettings().autostart is True
