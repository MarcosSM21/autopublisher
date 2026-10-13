"""Minimum container age before `threads_publish` (research.md §10): a container is
published only when it is FINISHED and at least 30 s old, measured from its
persisted creation time with the injectable clock. Nothing really sleeps: the fake
sleep only advances the fake clock."""

import dataclasses
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import UNCERTAIN_STAGES, AttemptStage, Platform
from app.publishing import recover_interrupted_attempts
from app.threads_publishing import MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS
from tests.conftest import (
    publish_and_wait,
    run_sql,
    threads_run_rows,
    threads_text_publication,
)
from tests.fakes import FakeClock, FakeThreads

MIN_AGE = MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _created_at(db_path: Path) -> datetime:
    with sqlite3.connect(db_path) as connection:
        value = connection.execute(
            "SELECT container_created_at FROM threads_publish_runs"
        ).fetchone()[0]
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _publish(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    publication = threads_text_publication(client)["publication"]
    published = publish_and_wait(client, publication["id"])
    [attempt] = client.get(f"/api/publications/{publication['id']}/attempts").json()
    return published, attempt


def _advance_on_first_read(
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    seconds: float,
) -> None:
    """The first status read happens `seconds` after the container was created."""
    original = fake_threads._status
    reads: list[str] = []

    def status(container_id: str) -> Any:
        if not reads:
            fake_clock.advance(seconds)
        reads.append(container_id)
        return original(container_id)

    monkeypatch.setattr(fake_threads, "_status", status)


def _record_age_at_publish(
    fake_threads: FakeThreads, fake_clock: FakeClock, db_path: Path
) -> list[float]:
    ages: list[float] = []
    fake_threads.publish_hook = lambda: ages.append(
        (fake_clock.now() - _created_at(db_path)).total_seconds()
    )
    return ages


def test_minimum_age_is_thirty_seconds() -> None:
    assert MIN_AGE == 30


def test_finished_at_once_is_not_published_before_the_minimum_age(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
    db_path: Path,
) -> None:
    ages = _record_age_at_publish(fake_threads, fake_clock, db_path)

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert attempt["status"] == "succeeded"
    [age] = ages
    assert age >= MIN_AGE
    # Only the missing time, in slices; never a fixed wait added after FINISHED.
    assert recorded_sleeps == [1.0] * 30
    # FINISHED is confirmed again once the container is old enough.
    assert len(fake_threads.requests_for("status")) == 2
    [container_id] = fake_threads.containers
    assert fake_threads.publish_count(container_id) == 1


def test_finished_at_twenty_seconds_waits_only_ten(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _advance_on_first_read(fake_threads, fake_clock, monkeypatch, 20)
    ages = _record_age_at_publish(fake_threads, fake_clock, db_path)

    published, _ = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert recorded_sleeps == [1.0] * 10
    assert ages == [30.0]


def test_finished_after_the_minimum_age_publishes_at_once(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _advance_on_first_read(fake_threads, fake_clock, monkeypatch, 35)

    published, _ = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert recorded_sleeps == []
    assert len(fake_threads.requests_for("status")) == 1
    assert len(fake_threads.requests_for("publish")) == 1


def test_in_progress_keeps_the_normal_polling(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
    db_path: Path,
) -> None:
    fake_threads.status_script = ["IN_PROGRESS"] * 4 + ["FINISHED"]
    ages = _record_age_at_publish(fake_threads, fake_clock, db_path)

    published, _ = _publish(threads_publishing_client)

    assert published["status"] == "published"
    # Polling waits 2, 5, 10 and 15 s: FINISHED at 32 s is already old enough.
    assert recorded_sleeps == [1.0] * 32
    assert len(fake_threads.requests_for("status")) == 5
    assert ages == [32.0]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("ERROR:UNKNOWN", "threads_processing_failed"),
        ("EXPIRED", "threads_container_expired"),
    ],
)
def test_error_during_the_age_wait_never_publishes(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    recorded_sleeps: list[float],
    status: str,
    code: str,
) -> None:
    fake_threads.status_script = ["FINISHED", status]

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert recorded_sleeps == [1.0] * 30
    assert fake_threads.requests_for("publish") == []


def test_shutdown_during_the_age_wait_is_determined(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    app = _app(threads_publishing_client)
    publisher = app.state.publishers[Platform.THREADS]
    seen: list[tuple[str, str, Any]] = []

    def sleep(seconds: float) -> None:
        with sqlite3.connect(db_path) as connection:
            seen.append(
                connection.execute(
                    "SELECT a.stage, r.phase, r.publish_started_at FROM "
                    "publication_attempts a JOIN threads_publish_runs r "
                    "ON r.attempt_id = a.id"
                ).fetchone()
            )
        fake_clock.advance(seconds)
        app.state.publication_runner._stop_event.set()

    publisher.settings = dataclasses.replace(publisher.settings, sleep=sleep)

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is True
    assert fake_threads.requests_for("publish") == []
    # While waiting for the minimum age nothing irreversible has started.
    assert seen[0] == ("processing", "processing_container", None)
    assert threads_run_rows(db_path)[0]["phase"] == "failed"


def test_restart_before_the_minimum_age_is_determined(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    """A crash while waiting for the minimum age leaves the attempt in
    `processing`: the generic recovery closes it as determined, because
    `threads_publish` was never called."""
    fake_threads.status_script = ["FINISHED", "ERROR"]
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])
    # Rebuild the exact state a crash during the age wait leaves behind.
    run_sql(
        db_path,
        "UPDATE publications SET status = 'publishing' WHERE id = ?",
        publication["id"],
    )
    run_sql(
        db_path,
        "UPDATE publication_attempts SET status = 'running', stage = 'processing', "
        "finished_at = NULL, error_code = NULL, error_message = NULL, "
        "outcome_determined = NULL",
    )
    run_sql(db_path, "UPDATE threads_publish_runs SET phase = 'processing_container'")

    assert AttemptStage.PROCESSING not in UNCERTAIN_STAGES
    closed = recover_interrupted_attempts(
        _app(threads_publishing_client).state.session_factory
    )

    [attempt] = threads_publishing_client.get(
        f"/api/publications/{publication['id']}/attempts"
    ).json()
    assert closed == 1
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert fake_threads.requests_for("publish") == []
