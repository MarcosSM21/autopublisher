"""One scheduler cycle: armed publications start by themselves through the generic
publishing service when their time comes (Feature 007)."""

import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import publishing
from app.models import AttemptTrigger
from app.publishing import PublishFailure
from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    iso,
    run_tick,
    scheduled_publication,
    wait_idle,
)
from tests.fakes import FakeClock, FakeGoogle, FakePublisher


def test_future_publication_is_not_started(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    scheduled_publication(fake_scheduler_client, db_path, in_minutes(fake_clock, 5))

    report = run_tick(fake_scheduler_client)

    assert report.started == []
    assert fake_publisher.check_calls == []
    assert fake_publisher.prepare_calls == []
    assert attempt_rows(db_path) == []


def test_armed_publication_starts_at_its_time_and_is_published(
    scheduler_client: TestClient,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(
        scheduler_client, db_path, at, fake_google=fake_google
    )
    publication_id = setup["publication"]["id"]
    calls: list[dict[str, Any]] = []
    original = publishing.start_publication

    def spy(*args: Any, **kwargs: Any) -> int:
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(publishing, "start_publication", spy)
    fake_clock.set(at)

    report = run_tick(scheduler_client)

    assert report.started == [publication_id]
    assert len(calls) == 1
    assert calls[0]["trigger"] == AttemptTrigger.SCHEDULED
    assert calls[0]["confirm_remote_checked"] is False
    wait_idle(scheduler_client)
    publication = get_publication(scheduler_client, publication_id)
    assert publication["status"] == "published"
    assert publication["auto_publish_enabled"] is False
    assert publication["attempt_count"] == 1
    assert publication["latest_attempt"]["trigger"] == "scheduled"
    assert len(fake_google.videos_created) == 1


def test_started_publication_is_never_started_again(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    scheduled_publication(fake_scheduler_client, db_path, at)
    fake_clock.set(at)

    run_tick(fake_scheduler_client)
    wait_idle(fake_scheduler_client)
    for _ in range(3):
        fake_clock.advance(30)
        assert run_tick(fake_scheduler_client).started == []

    assert len(attempt_rows(db_path)) == 1
    assert len(fake_publisher.upload_calls) == 1


def test_failed_execution_is_not_retried(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    fake_publisher.upload_failure = PublishFailure(
        "youtube_permanent_error", "Rejected.", determined=True
    )
    fake_clock.set(at)

    run_tick(fake_scheduler_client)
    wait_idle(fake_scheduler_client)
    for _ in range(4):
        fake_clock.advance(60)
        run_tick(fake_scheduler_client)

    publication = get_publication(fake_scheduler_client, setup["publication"]["id"])
    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["trigger"] == "scheduled"
    assert len(attempt_rows(db_path)) == 1


def test_publish_now_attempts_stay_manual(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 60)
    )
    publication_id = setup["publication"]["id"]

    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 202, response.text
    wait_idle(fake_scheduler_client)
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["latest_attempt"]["trigger"] == "manual"
    assert [row["trigger"] for row in attempt_rows(db_path)] == ["manual"]


# --- Automatic window (User Story 3) ------------------------------------------------


@pytest.mark.parametrize(
    ("delay", "starts"),
    [
        (timedelta(0), True),
        (timedelta(minutes=5), True),
        (timedelta(minutes=10), True),
        (timedelta(minutes=10, microseconds=1), False),
        (timedelta(minutes=11), False),
        (timedelta(seconds=-1), False),
    ],
)
def test_window_bounds(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    delay: timedelta,
    starts: bool,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    fake_clock.set(at + delay)

    report = run_tick(fake_scheduler_client)

    assert (report.started == [setup["publication"]["id"]]) is starts
    if not starts:
        assert fake_publisher.prepare_calls == []
        publication = get_publication(fake_scheduler_client, setup["publication"]["id"])
        assert publication["status"] == "scheduled"


def test_window_is_checked_again_after_the_preflight(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    publication_id = setup["publication"]["id"]
    fake_clock.set(at + timedelta(minutes=9, seconds=59))
    # The preflight takes long enough for the window to end.
    fake_publisher.prepare_hook = lambda _: fake_clock.advance(2)

    report = run_tick(fake_scheduler_client)

    assert report.started == []
    assert fake_publisher.prepare_calls == [publication_id]
    assert attempt_rows(db_path) == []
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_state"] == "overdue"
    assert publication["auto_publish_error"] is None


def test_overdue_is_derived_and_cleared_by_disarming_or_rescheduling(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    publication_id = setup["publication"]["id"]
    fake_clock.set(at + timedelta(minutes=11))

    overdue = get_publication(fake_scheduler_client, publication_id)
    assert overdue["status"] == "scheduled"
    assert overdue["auto_publish_state"] == "overdue"
    assert overdue["auto_publish_window_ends_at"] == iso(at + timedelta(minutes=10))

    disarmed = fake_scheduler_client.patch(
        f"/api/publications/{publication_id}", json={"auto_publish_enabled": False}
    ).json()
    assert disarmed["status"] == "scheduled"
    assert disarmed["auto_publish_state"] == "disabled"

    new_at = in_minutes(FakeClock(), 120)
    moved = fake_scheduler_client.patch(
        f"/api/publications/{publication_id}",
        json={"scheduled_at": iso(new_at), "auto_publish_enabled": True},
    ).json()
    assert moved["auto_publish_window_ends_at"] == iso(new_at + timedelta(minutes=10))
    fake_clock.set(new_at - timedelta(minutes=1))
    assert (
        get_publication(fake_scheduler_client, publication_id)["auto_publish_state"]
        == "waiting"
    )
    fake_clock.set(new_at)
    assert run_tick(fake_scheduler_client).started == [publication_id]


def test_disarmed_past_publication_is_never_overdue(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at, armed=False)
    fake_clock.set(at + timedelta(hours=3))

    publication = get_publication(fake_scheduler_client, setup["publication"]["id"])

    assert publication["status"] == "scheduled"
    assert publication["auto_publish_state"] == "disabled"
    assert run_tick(fake_scheduler_client).started == []


# --- Pause (User Story 4) -----------------------------------------------------------


def _pause(client: TestClient, paused: bool = True) -> None:
    response = client.put("/api/automation", json={"paused": paused})
    assert response.status_code == 200, response.text


def test_paused_automation_does_nothing_not_even_a_preflight(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    _pause(fake_scheduler_client)
    fake_clock.set(at + timedelta(minutes=1))

    assert run_tick(fake_scheduler_client).started == []

    assert fake_publisher.check_calls == []
    assert fake_publisher.prepare_calls == []
    publication = get_publication(fake_scheduler_client, setup["publication"]["id"])
    assert publication["auto_publish_state"] == "paused"
    assert publication["auto_publish_error"] is None


def test_pause_during_the_preflight_prevents_the_start(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    fake_clock.set(at)
    fake_publisher.prepare_hook = lambda _: _pause(fake_scheduler_client)

    assert run_tick(fake_scheduler_client).started == []

    assert attempt_rows(db_path) == []
    publication = get_publication(fake_scheduler_client, setup["publication"]["id"])
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_error"] is None


def test_pausing_does_not_stop_a_running_upload(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    gate = threading.Event()
    fake_publisher.upload_gate = gate
    fake_clock.set(at)
    run_tick(fake_scheduler_client)

    _pause(fake_scheduler_client)
    gate.set()
    wait_idle(fake_scheduler_client)

    publication = get_publication(fake_scheduler_client, setup["publication"]["id"])
    assert publication["status"] == "published"


def test_publish_now_works_while_paused(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 60)
    )
    _pause(fake_scheduler_client)

    response = fake_scheduler_client.post(
        f"/api/publications/{setup['publication']['id']}/publish", json={}
    )

    assert response.status_code == 202, response.text
    wait_idle(fake_scheduler_client)
    assert [row["trigger"] for row in attempt_rows(db_path)] == ["manual"]


def test_resume_within_the_window_starts_it(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at)
    _pause(fake_scheduler_client)
    fake_clock.set(at + timedelta(minutes=2))
    run_tick(fake_scheduler_client)

    _pause(fake_scheduler_client, False)
    fake_clock.advance(60)

    assert run_tick(fake_scheduler_client).started == [setup["publication"]["id"]]


def test_resume_after_the_window_never_dumps_old_publications(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    old = [
        scheduled_publication(fake_scheduler_client, db_path, at, project_name=f"P{i}")[
            "publication"
        ]["id"]
        for i in range(3)
    ]
    _pause(fake_scheduler_client)
    fake_clock.set(at + timedelta(minutes=30))

    _pause(fake_scheduler_client, False)

    assert run_tick(fake_scheduler_client).started == []
    assert fake_publisher.prepare_calls == []
    for publication_id in old:
        publication = get_publication(fake_scheduler_client, publication_id)
        assert publication["status"] == "scheduled"
        assert publication["auto_publish_state"] == "overdue"
