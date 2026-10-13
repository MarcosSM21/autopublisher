"""Threads publications go through the generic scheduler and executor only: one
execution with `trigger=scheduled`, pause, races and concurrency (US6)."""

import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scheduler import Scheduler
from tests.conftest import (
    arm,
    attempt_rows,
    get_publication,
    in_minutes,
    iso,
    make_threads_publishing_app,
    run_tick,
    threads_image_publication,
    threads_text_publication,
    threads_video_publication,
    wait_idle,
)
from tests.fakes import (
    FakeClock,
    FakeMediaDeliveryProvider,
    FakeThreads,
    InMemoryCredentialStore,
)


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _due(
    client: TestClient,
    db_path: Path,
    clock: FakeClock,
    create: Callable[..., dict[str, Any]] = threads_text_publication,
    **values: Any,
) -> int:
    at: datetime = in_minutes(clock, 5)
    created = create(client, scheduled_at=iso(at), **values)
    publication_id: int = created["publication"]["id"]
    arm(db_path, publication_id)
    clock.set(at)
    return publication_id


def _in_parallel(*calls: Callable[[], Any]) -> None:
    errors: list[BaseException] = []

    def run(call: Callable[[], Any]) -> None:
        try:
            call()
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert errors == []


@pytest.mark.parametrize("kind", ["text", "image", "video"])
def test_due_publication_runs_once_with_trigger_scheduled(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    creators: dict[str, Callable[..., dict[str, Any]]] = {
        "text": threads_text_publication,
        "image": threads_image_publication,
        "video": lambda client, **values: threads_video_publication(
            client, monkeypatch, **values
        ),
    }
    publication_id = _due(
        threads_publishing_client, db_path, fake_clock, creators[kind]
    )

    report = run_tick(threads_publishing_client)
    wait_idle(threads_publishing_client)
    for _ in range(3):
        fake_clock.advance(30)
        assert run_tick(threads_publishing_client).started == []
    wait_idle(threads_publishing_client)

    assert report.started == [publication_id]
    publication = get_publication(threads_publishing_client, publication_id)
    assert publication["status"] == "published"
    assert publication["latest_attempt"]["trigger"] == "scheduled"
    assert len(attempt_rows(db_path)) == 1
    assert len(fake_threads.containers) == 1
    assert len(fake_threads.published) == 1


def test_pause_blocks_automatic_but_not_manual_publishing(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(threads_publishing_client, db_path, fake_clock)
    threads_publishing_client.put("/api/automation", json={"paused": True})

    assert run_tick(threads_publishing_client).started == []
    assert fake_threads.containers == {}

    response = threads_publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )
    assert response.status_code == 202
    wait_idle(threads_publishing_client)
    publication = get_publication(threads_publishing_client, publication_id)
    assert publication["status"] == "published"
    assert publication["latest_attempt"]["trigger"] == "manual"


def test_resume_lets_the_scheduler_start_it(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(threads_publishing_client, db_path, fake_clock)
    threads_publishing_client.put("/api/automation", json={"paused": True})
    assert run_tick(threads_publishing_client).started == []

    threads_publishing_client.put("/api/automation", json={"paused": False})
    report = run_tick(threads_publishing_client)
    wait_idle(threads_publishing_client)

    assert report.started == [publication_id]
    assert len(fake_threads.published) == 1


def test_pause_does_not_cancel_a_running_execution(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(threads_publishing_client, db_path, fake_clock)
    gate = threading.Event()
    reached = threading.Event()

    def hold() -> None:
        reached.set()
        assert gate.wait(10)

    fake_threads.create_hook = hold
    run_tick(threads_publishing_client)
    assert reached.wait(10)
    threads_publishing_client.put("/api/automation", json={"paused": True})
    gate.set()
    wait_idle(threads_publishing_client)

    status = get_publication(threads_publishing_client, publication_id)["status"]
    assert status == "published"


def test_publish_now_racing_a_cycle_starts_one_execution(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(threads_publishing_client, db_path, fake_clock)

    _in_parallel(
        lambda: run_tick(threads_publishing_client),
        lambda: threads_publishing_client.post(
            f"/api/publications/{publication_id}/publish", json={}
        ),
    )
    wait_idle(threads_publishing_client)

    assert len(attempt_rows(db_path)) == 1
    assert len(fake_threads.containers) == 1
    assert len(fake_threads.published) == 1


def test_two_concurrent_cycles_start_one_execution(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(threads_publishing_client, db_path, fake_clock)
    state = _app(threads_publishing_client).state
    first: Scheduler = state.scheduler
    second = Scheduler(
        first.session_factory, first.ctx, first.runner, first.publishers, first.settings
    )

    _in_parallel(first.run_once, second.run_once)
    wait_idle(threads_publishing_client)

    assert len(attempt_rows(db_path)) == 1
    assert len(fake_threads.published) == 1
    status = get_publication(threads_publishing_client, publication_id)["status"]
    assert status == "published"


@pytest.fixture
def single_slot_client(
    db_path: Path,
    media_dir: Path,
    threads_app_file: Path,
    media_delivery_file: Path,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
) -> Iterator[TestClient]:
    app = make_threads_publishing_app(
        db_path,
        media_dir,
        threads_credential_store,
        fake_threads,
        fake_delivery,
        fake_clock,
        recorded_sleeps,
        max_concurrent=1,
    )
    with TestClient(app) as client:
        yield client


def test_maximum_automatic_concurrency_is_respected(
    single_slot_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    ids = [
        threads_text_publication(
            single_slot_client, scheduled_at=iso(at), project_name=name
        )["publication"]["id"]
        for name in ("One", "Two")
    ]
    for publication_id in ids:
        arm(db_path, publication_id)
    fake_clock.set(at)
    gate = threading.Event()

    def hold() -> None:
        gate.wait(10)

    fake_threads.create_hook = hold

    report = run_tick(single_slot_client)
    gate.set()
    wait_idle(single_slot_client)

    assert len(report.started) == 1
    assert report.skipped_capacity == [ids[1]]
    assert len(fake_threads.containers) == 1


def test_preflight_failure_at_due_time_follows_the_generic_rules(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(
        threads_publishing_client,
        db_path,
        fake_clock,
        description="x" * 501,
        hashtags=[],
    )

    report = run_tick(threads_publishing_client)

    assert report.failed == [publication_id]
    publication = get_publication(threads_publishing_client, publication_id)
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_error"]["code"] == "threads_text_invalid"
    assert attempt_rows(db_path) == []
    assert fake_threads.containers == {}
    assert fake_delivery.put_calls == []


def test_scheduler_never_retries_an_uncertain_publication(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    fake_threads.faults["publish"] = "server_error"
    publication_id = _due(threads_publishing_client, db_path, fake_clock)
    run_tick(threads_publishing_client)
    wait_idle(threads_publishing_client)
    attempt = get_publication(threads_publishing_client, publication_id)[
        "latest_attempt"
    ]
    assert attempt["error"]["code"] == "threads_publish_uncertain"

    for _ in range(3):
        fake_clock.advance(30)
        assert run_tick(threads_publishing_client).started == []
    wait_idle(threads_publishing_client)

    assert len(attempt_rows(db_path)) == 1
    assert len(fake_threads.requests_for("publish")) == 1
