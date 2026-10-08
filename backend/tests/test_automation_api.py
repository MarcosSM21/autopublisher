"""Global pause of automatic publishing (User Story 4): GET/PUT /api/automation."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import make_scheduler_app, run_sql, run_tick
from tests.fakes import FakeClock


def _status(client: TestClient) -> dict[str, object]:
    response = client.get("/api/automation")
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def test_automation_starts_running_and_not_paused(
    fake_scheduler_client: TestClient,
) -> None:
    status = _status(fake_scheduler_client)

    assert status == {
        "paused": False,
        "running": False,  # autostart=False in this fixture
        "last_check_at": None,
        "check_interval_seconds": 30.0,
        "window_minutes": 10,
    }


def test_last_check_is_reported_after_a_cycle(
    fake_scheduler_client: TestClient, fake_clock: FakeClock
) -> None:
    run_tick(fake_scheduler_client)

    last = _status(fake_scheduler_client)["last_check_at"]

    assert last == fake_clock.now().isoformat().replace("+00:00", "Z")


def test_pause_persists_across_restarts(
    db_path: Path, media_dir: Path, fake_clock: FakeClock
) -> None:
    with TestClient(make_scheduler_app(db_path, media_dir, fake_clock)) as client:
        response = client.put("/api/automation", json={"paused": True})
        assert response.status_code == 200, response.text
        assert response.json()["paused"] is True
        again = client.put("/api/automation", json={"paused": True})
        assert again.json()["paused"] is True

    with TestClient(make_scheduler_app(db_path, media_dir, fake_clock)) as client:
        assert _status(client)["paused"] is True
        client.put("/api/automation", json={"paused": False})

    with TestClient(make_scheduler_app(db_path, media_dir, fake_clock)) as client:
        assert _status(client)["paused"] is False


def test_invalid_bodies_are_rejected(fake_scheduler_client: TestClient) -> None:
    for body in ({}, {"paused": "maybe"}, {"paused": True, "other": 1}):
        response = fake_scheduler_client.put("/api/automation", json=body)
        assert response.status_code == 422, body


def test_missing_settings_row_means_paused(
    fake_scheduler_client: TestClient, db_path: Path
) -> None:
    run_sql(db_path, "DELETE FROM automation_settings")

    assert _status(fake_scheduler_client)["paused"] is True

    response = fake_scheduler_client.put("/api/automation", json={"paused": False})
    assert response.json()["paused"] is False
    assert _status(fake_scheduler_client)["paused"] is False


def test_resuming_wakes_the_scheduler(fake_scheduler_client: TestClient) -> None:
    app = fake_scheduler_client.app
    assert isinstance(app, FastAPI)
    woken: list[bool] = []
    app.state.scheduler.wake = lambda: woken.append(True)

    fake_scheduler_client.put("/api/automation", json={"paused": True})
    assert woken == []
    fake_scheduler_client.put("/api/automation", json={"paused": False})

    assert woken == [True]
