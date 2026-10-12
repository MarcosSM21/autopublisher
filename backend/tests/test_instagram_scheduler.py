"""Instagram publications go through the generic scheduler and executor: one
execution, `trigger=scheduled`, pause and concurrency guards (US5, FR-059-FR-061)."""

import threading
from collections.abc import Callable
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
    instagram_publication,
    iso,
    run_sql,
    run_tick,
    wait_idle,
)
from tests.fakes import FakeClock, FakeMediaDeliveryProvider, FakeMeta


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _due(client: TestClient, db_path: Path, clock: FakeClock, **kwargs: Any) -> int:
    at: datetime = in_minutes(clock, 5)
    created = instagram_publication(client, scheduled_at=iso(at), **kwargs)
    publication_id: int = created["publication"]["id"]
    arm(db_path, publication_id)
    clock.set(at)
    return publication_id


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


# --- T048: edge cases ----------------------------------------------------------------


def test_preflight_failure_at_due_time_has_no_effects(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(ig_client, db_path, fake_clock, kind="wide")

    report = run_tick(ig_client)

    assert report.failed == [publication_id]
    publication = get_publication(ig_client, publication_id)
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_error"]["code"] == "instagram_image_incompatible"
    assert attempt_rows(db_path) == []
    assert fake_delivery.put_calls == []
    assert fake_meta.requests_for("create") == []


@pytest.mark.parametrize("status", ["failed", "published"])
def test_failed_and_published_are_never_started_again(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
    status: str,
) -> None:
    publication_id = _due(ig_client, db_path, fake_clock)
    published_at = "'2026-10-09 10:00:00'" if status == "published" else "NULL"
    run_sql(
        db_path,
        f"UPDATE publications SET status = ?, auto_publish_enabled = 0, "
        f"published_at = {published_at} WHERE id = ?",
        status,
        publication_id,
    )

    assert run_tick(ig_client).started == []
    assert fake_meta.requests_for("create") == []
    assert fake_meta.requests_for("publish") == []


# --- T049: functional scheduled execution --------------------------------------------


def test_due_publication_runs_once_through_the_generic_scheduler(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(ig_client, db_path, fake_clock)

    report = run_tick(ig_client)
    wait_idle(ig_client)
    for _ in range(3):
        fake_clock.advance(30)
        assert run_tick(ig_client).started == []
    wait_idle(ig_client)

    assert report.started == [publication_id]
    publication = get_publication(ig_client, publication_id)
    assert publication["status"] == "published"
    assert publication["latest_attempt"]["trigger"] == "scheduled"
    assert len(attempt_rows(db_path)) == 1
    assert len(fake_meta.containers) == 1
    assert len(fake_meta.published) == 1


def test_pause_blocks_automatic_but_not_manual_publishing(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(ig_client, db_path, fake_clock)
    ig_client.put("/api/automation", json={"paused": True})

    assert run_tick(ig_client).started == []
    assert fake_meta.requests_for("create") == []

    response = ig_client.post(f"/api/publications/{publication_id}/publish", json={})
    assert response.status_code == 202
    wait_idle(ig_client)
    publication = get_publication(ig_client, publication_id)
    assert publication["status"] == "published"
    assert publication["latest_attempt"]["trigger"] == "manual"


def test_pause_does_not_cancel_a_running_instagram_execution(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(ig_client, db_path, fake_clock)
    gate = threading.Event()
    reached = threading.Event()

    def hold() -> None:
        reached.set()
        assert gate.wait(10)

    fake_meta.create_hook = hold
    run_tick(ig_client)
    assert reached.wait(10)
    ig_client.put("/api/automation", json={"paused": True})
    gate.set()
    wait_idle(ig_client)

    assert get_publication(ig_client, publication_id)["status"] == "published"


def test_publish_now_racing_a_cycle_starts_one_execution(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(ig_client, db_path, fake_clock)

    def publish_now() -> int:
        response = ig_client.post(
            f"/api/publications/{publication_id}/publish", json={}
        )
        return response.status_code

    _in_parallel(lambda: run_tick(ig_client), publish_now)
    wait_idle(ig_client)

    assert len(attempt_rows(db_path)) == 1
    assert len(fake_meta.containers) == 1
    assert len(fake_meta.published) == 1


def test_two_concurrent_cycles_start_one_execution(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = _due(ig_client, db_path, fake_clock)
    state = _app(ig_client).state
    first: Scheduler = state.scheduler
    second = Scheduler(
        first.session_factory, first.ctx, first.runner, first.publishers, first.settings
    )

    _in_parallel(first.run_once, second.run_once)
    wait_idle(ig_client)

    assert len(attempt_rows(db_path)) == 1
    assert len(fake_meta.published) == 1
    assert get_publication(ig_client, publication_id)["status"] == "published"
