"""The background analytics refresher (Feature 027 T046) and its wiring in the app.

Thread tests synchronise with events, never `sleep`.
"""

import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics import refresher as refresher_module
from app.analytics.refresh import CycleReport
from app.analytics.refresher import AnalyticsRefresher, AnalyticsRefresherSettings
from app.main import create_app
from app.scheduler import SchedulerSettings
from tests import analytics_support as scene
from tests import readmodels
from tests.analytics_support import NOW, YouTubeWorld
from tests.conftest import create_account, create_project
from tests.fakes import (
    FAKE_ACCESS_TOKEN,
    FAKE_IG_LONG_TOKEN,
    FakeClock,
    FakeGoogle,
    InMemoryCredentialStore,
)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[YouTubeWorld]:
    with scene.youtube_world(tmp_path) as world:
        yield world


class Cycles:
    """Counts the cycles of a refresher and lets a test wait for them."""

    def __init__(self, fail_first: bool = False) -> None:
        self.count = 0
        self.fail_first = fail_first
        self.condition = threading.Condition()

    def __call__(self, *args: Any, **kwargs: Any) -> CycleReport:
        with self.condition:
            self.count += 1
            self.condition.notify_all()
            if self.fail_first and self.count == 1:
                raise RuntimeError(f"boom {FAKE_ACCESS_TOKEN}")
        return CycleReport()

    def wait_for(self, count: int) -> bool:
        with self.condition:
            return self.condition.wait_for(lambda: self.count >= count, timeout=5)


def refresher_for(world: YouTubeWorld, **settings: Any) -> AnalyticsRefresher:
    return AnalyticsRefresher(
        world.session_factory,
        world.adapters,
        AnalyticsRefresherSettings(clock=lambda: NOW, interval=3600, **settings),
    )


def test_start_waits_for_the_interval_and_stop_ends_the_thread(
    world: YouTubeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycles = Cycles()
    monkeypatch.setattr(refresher_module, "run_refresh_cycle", cycles)
    waited = threading.Event()

    def wait(seconds: float) -> None:
        assert seconds == 3600
        waited.set()
        stop.wait(5)

    stop = threading.Event()
    refresher = refresher_for(world, wait=wait)

    refresher.start()
    assert waited.wait(5)
    # Starting never runs a cycle by itself.
    assert cycles.count == 0
    assert refresher.running

    stop.set()
    refresher.stop()
    assert not refresher.running
    assert cycles.count <= 1


def test_wake_runs_the_next_cycle_now(
    world: YouTubeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycles = Cycles()
    monkeypatch.setattr(refresher_module, "run_refresh_cycle", cycles)
    refresher = refresher_for(world)
    refresher.start()

    refresher.wake()
    assert cycles.wait_for(1)
    refresher.wake()

    assert cycles.wait_for(2)
    refresher.stop()


def test_a_failed_cycle_never_stops_the_thread_nor_logs_secrets(
    world: YouTubeWorld,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cycles = Cycles(fail_first=True)
    monkeypatch.setattr(refresher_module, "run_refresh_cycle", cycles)
    refresher = refresher_for(world)
    caplog.set_level(logging.ERROR)

    refresher.start()
    refresher.wake()
    assert cycles.wait_for(1)
    refresher.wake()
    assert cycles.wait_for(2)
    refresher.stop()

    assert "RuntimeError" in caplog.text
    assert FAKE_ACCESS_TOKEN not in caplog.text
    assert "boom" not in caplog.text


def test_start_twice_keeps_a_single_worker(
    world: YouTubeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycles = Cycles()
    monkeypatch.setattr(refresher_module, "run_refresh_cycle", cycles)
    refresher = refresher_for(world)

    refresher.start()
    refresher.start()
    refresher.wake()
    assert cycles.wait_for(1)

    workers = [t for t in threading.enumerate() if t.name == "analytics-refresher"]
    assert len(workers) == 1
    refresher.stop()
    assert not any(t.name == "analytics-refresher" for t in threading.enumerate())


def test_pauses_survive_between_cycles(world: YouTubeWorld) -> None:
    post = scene.published(world.db_path, world.instagram_account(), "IG-1")
    world.meta.faults["counters"] = "rate_limited"
    refresher = refresher_for(world)

    refresher.run_once()
    refresher.run_once()

    assert len(world.meta.requests_for("counters")) == 1
    assert scene.state(world.db_path, post)["status"] == "rate_limited"  # type: ignore[index]


# --- In the application -------------------------------------------------------------


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def stores() -> dict[str, InMemoryCredentialStore]:
    return {
        "youtube": InMemoryCredentialStore(),
        "instagram": InMemoryCredentialStore(),
    }


def make_app(
    db_path: Path,
    media_dir: Path,
    google: FakeGoogle,
    stores: dict[str, InMemoryCredentialStore],
    clock: FakeClock,
    **analytics: Any,
) -> FastAPI:
    return create_app(
        db_path,
        media_dir,
        credential_store=stores["youtube"],
        google_transport=google.transport(),
        instagram_credential_store=stores["instagram"],
        threads_credential_store=InMemoryCredentialStore(),
        tiktok_credential_store=InMemoryCredentialStore(),
        scheduler_settings=SchedulerSettings(clock=clock.now, autostart=False),
        analytics_settings=AnalyticsRefresherSettings(clock=clock.now, **analytics),
        clock=clock.now,
    )


def connected_video(
    client: TestClient,
    db_path: Path,
    stores: dict[str, InMemoryCredentialStore],
    google: FakeGoogle,
) -> int:
    project = create_project(client, "Cyber")
    owner = create_account(client, project["id"], "youtube", "cyber")
    readmodels.connect(db_path, owner, NOW)
    scene.youtube_tokens(stores["youtube"], owner)
    google.statistics = {"VIDEO-1": {"viewCount": "42", "likeCount": "0"}}
    return scene.published(db_path, owner, "VIDEO-1")


def test_the_app_refreshes_without_calling_the_cycle_directly(
    db_path: Path,
    media_dir: Path,
    google: FakeGoogle,
    stores: dict[str, InMemoryCredentialStore],
) -> None:
    clock = FakeClock(NOW)
    app = make_app(db_path, media_dir, google, stores, clock, autostart=False)
    with TestClient(app) as client:
        refresher: AnalyticsRefresher = app.state.analytics_refresher
        assert not refresher.running
        post = connected_video(client, db_path, stores, google)
        assert (
            client.post(f"/api/publications/{post}/analytics/refresh").status_code
            == 202
        )

        report = refresher.run_once()

    assert report.succeeded == 1
    [snapshot] = scene.values(db_path, post)
    assert snapshot["snapshot"]["trigger"] == "manual"
    assert snapshot["values"]["likeCount"]["value"] == 0
    assert FAKE_IG_LONG_TOKEN not in str(report)


def test_a_manual_request_wakes_the_running_refresher(
    db_path: Path,
    media_dir: Path,
    google: FakeGoogle,
    stores: dict[str, InMemoryCredentialStore],
) -> None:
    clock = FakeClock(NOW)
    app = make_app(db_path, media_dir, google, stores, clock, interval=3600)
    with TestClient(app) as client:
        refresher: AnalyticsRefresher = app.state.analytics_refresher
        assert refresher.running
        done = threading.Event()
        original = refresher.run_once

        def run_once() -> CycleReport:
            report = original()
            if report.succeeded:
                done.set()
            return report

        # Before any data, so whichever cycle reads the post is observed.
        refresher.run_once = run_once  # type: ignore[method-assign]
        post = connected_video(client, db_path, stores, google)
        client.post(f"/api/publications/{post}/analytics/refresh")

        assert done.wait(10)
    state = scene.state(db_path, post)
    assert state is not None and state["status"] == "ok"
    # Shutdown stopped the worker.
    assert not refresher.running
