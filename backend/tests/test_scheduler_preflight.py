"""Automatic preflight failures (User Story 6): nothing external happens, the
publication stays scheduled, a safe reason is kept and re-checks are throttled."""

import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import ConflictError
from app.models import Platform
from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    iso,
    make_scheduler_app,
    run_sql,
    run_tick,
    scheduled_publication,
    set_youtube_options,
    stored_file,
    use_fake_publisher,
    wait_idle,
)
from tests.fakes import FakeClock, FakeGoogle, FakePublisher

INTERNAL_MESSAGE = "AutoPublisher could not start this publication automatically."


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


# --- Every preflight cause, with the YouTube simulator ------------------------------


def _deactivate_project(client: TestClient, setup: dict[str, Any], **_: Any) -> None:
    client.patch(f"/api/projects/{setup['project']['id']}", json={"is_active": False})


def _deactivate_account(client: TestClient, setup: dict[str, Any], **_: Any) -> None:
    client.patch(f"/api/accounts/{setup['account']['id']}", json={"is_active": False})


def _reconnect_required(db_path: Path, **_: Any) -> None:
    run_sql(db_path, "UPDATE youtube_connections SET status = 'reconnect_required'")


def _not_connected(db_path: Path, **_: Any) -> None:
    run_sql(db_path, "DELETE FROM youtube_connections")


def _missing_media(
    setup: dict[str, Any], db_path: Path, media_dir: Path, **_: Any
) -> None:
    stored_file(media_dir, db_path, setup["content"]["id"]).unlink()


def _invalid_title(client: TestClient, setup: dict[str, Any], **_: Any) -> None:
    client.patch(
        f"/api/publications/{setup['publication']['id']}",
        json={"title_override": "x" * 101},
    )


def _incomplete_options(client: TestClient, setup: dict[str, Any], **_: Any) -> None:
    set_youtube_options(client, setup["publication"]["id"], made_for_kids=None)


def _no_publisher(client: TestClient, **_: Any) -> None:
    _app(client).state.publishers.pop(Platform.YOUTUBE)


def _youtube_unreachable(fake_google: FakeGoogle, **_: Any) -> None:
    fake_google.channels_outcome = "server_error"


def _ambiguous_previous_attempt(setup: dict[str, Any], db_path: Path, **_: Any) -> None:
    run_sql(
        db_path,
        "INSERT INTO publications (project_id, content_id, account_id, status, "
        "created_at, updated_at) VALUES (?, ?, ?, 'cancelled', "
        "'2026-10-06 10:00:00', '2026-10-06 10:00:00')",
        setup["project"]["id"],
        setup["content"]["id"],
        setup["account"]["id"],
    )
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (publication_id, platform, status, stage, "
        "started_at, finished_at, bytes_sent, total_bytes, error_code, error_message, "
        "outcome_determined, submitted, details, warnings) VALUES ("
        "(SELECT max(id) FROM publications), 'youtube', 'failed', 'final_chunk', "
        "'2026-10-06 10:00:00', '2026-10-06 10:01:00', 10, 10, 'interrupted', "
        "'Interrupted.', 0, '{}', '{}', '[]')",
    )


CAUSES: dict[str, tuple[Callable[..., None], str]] = {
    "project_inactive": (_deactivate_project, "project_inactive"),
    "account_inactive": (_deactivate_account, "account_inactive"),
    "reconnect_required": (_reconnect_required, "reconnect_required"),
    "not_connected": (_not_connected, "not_connected"),
    "media_missing": (_missing_media, "media_unavailable"),
    "invalid_metadata": (_invalid_title, "invalid_metadata"),
    "options_incomplete": (_incomplete_options, "youtube_options_incomplete"),
    "publisher_missing": (_no_publisher, "platform_not_supported"),
    "network_error": (_youtube_unreachable, "youtube_unavailable"),
    "ambiguous_previous": (_ambiguous_previous_attempt, "remote_check_required"),
}


@pytest.mark.parametrize("cause", list(CAUSES))
def test_preflight_failure_keeps_it_scheduled_without_side_effects(
    scheduler_client: TestClient,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    cause: str,
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(
        scheduler_client, db_path, at, fake_google=fake_google
    )
    publication_id = setup["publication"]["id"]
    make_it_fail, code = CAUSES[cause]
    make_it_fail(
        client=scheduler_client,
        setup=setup,
        db_path=db_path,
        media_dir=media_dir,
        fake_google=fake_google,
    )
    fake_clock.set(at + timedelta(seconds=30))

    report = run_tick(scheduler_client)

    assert report.started == []
    assert report.failed == [publication_id]
    publication = get_publication(scheduler_client, publication_id)
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_enabled"] is True
    assert publication["attempt_count"] == 0
    assert fake_google.session_starts == []
    error = publication["auto_publish_error"]
    assert error["code"] == code
    assert error["failed_at"] == iso(fake_clock.now())
    # The same safe message "Publish now" gives for that problem.
    manual = scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )
    assert manual.json()["error"]["code"] == code
    assert error["message"] == manual.json()["error"]["message"]
    assert fake_google.session_starts == []


# --- With a fake publisher ----------------------------------------------------------


@pytest.fixture
def failing(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> tuple[int, Any]:
    at = in_minutes(fake_clock, 5)
    publication_id: int = scheduled_publication(fake_scheduler_client, db_path, at)[
        "publication"
    ]["id"]
    fake_publisher.prepare_error[None] = ConflictError(
        "reconnect_required", "Reconnect the channel; nothing was uploaded."
    )
    fake_clock.set(at)
    return publication_id, at


def test_unexpected_errors_are_stored_safely(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    failing: tuple[int, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    publication_id, _ = failing
    fake_publisher.prepare_error[None] = RuntimeError("secret ya29.token")
    caplog.set_level(logging.DEBUG)

    report = run_tick(fake_scheduler_client)

    assert report.failed == [publication_id]
    error = get_publication(fake_scheduler_client, publication_id)["auto_publish_error"]
    assert error["code"] == "internal_error"
    assert error["message"] == INTERNAL_MESSAGE
    assert "RuntimeError" in caplog.text
    assert "ya29" not in caplog.text


def test_one_failure_does_not_stop_the_other_candidates(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    failing: tuple[int, Any],
    db_path: Path,
) -> None:
    publication_id, at = failing
    other = scheduled_publication(
        fake_scheduler_client, db_path, at, project_name="Other"
    )["publication"]["id"]
    del fake_publisher.prepare_error[None]
    fake_publisher.prepare_error[publication_id] = RuntimeError("boom")

    report = run_tick(fake_scheduler_client)

    assert report.failed == [publication_id]
    assert report.started == [other]


def test_rechecks_are_throttled(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    failing: tuple[int, Any],
) -> None:
    publication_id, at = failing
    run_tick(fake_scheduler_client)
    assert fake_publisher.prepare_calls == [publication_id]

    for seconds in (30, 60, 119):
        fake_clock.set(at + timedelta(seconds=seconds))
        report = run_tick(fake_scheduler_client)
        assert report.skipped_retry == [publication_id]
    assert fake_publisher.prepare_calls == [publication_id]

    fake_clock.set(at + timedelta(seconds=120))
    run_tick(fake_scheduler_client)
    assert fake_publisher.prepare_calls == [publication_id] * 2


def test_throttle_survives_a_restart(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    failing: tuple[int, Any],
    db_path: Path,
    media_dir: Path,
) -> None:
    publication_id, at = failing
    run_tick(fake_scheduler_client)
    fake_clock.set(at + timedelta(seconds=30))

    restarted_app = make_scheduler_app(db_path, media_dir, fake_clock)
    with TestClient(restarted_app) as restarted:
        use_fake_publisher(restarted, fake_publisher)
        assert run_tick(restarted).skipped_retry == [publication_id]
        assert fake_publisher.prepare_calls == [publication_id]
        fake_clock.set(at + timedelta(seconds=120))
        run_tick(restarted)

    assert fake_publisher.prepare_calls == [publication_id] * 2


def test_checks_stop_when_the_window_ends(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    failing: tuple[int, Any],
) -> None:
    publication_id, at = failing
    minute = 0
    while minute <= 10:
        fake_clock.set(at + timedelta(minutes=minute))
        run_tick(fake_scheduler_client)
        minute += 1
    checks = len(fake_publisher.prepare_calls)
    assert 1 < checks <= 6

    for minutes in (11, 20, 60):
        fake_clock.set(at + timedelta(minutes=minutes))
        run_tick(fake_scheduler_client)

    assert len(fake_publisher.prepare_calls) == checks
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_state"] == "overdue"
    assert publication["auto_publish_error"]["code"] == "reconnect_required"


def test_fixed_problem_starts_on_the_next_allowed_check(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    failing: tuple[int, Any],
) -> None:
    publication_id, at = failing
    run_tick(fake_scheduler_client)
    fake_publisher.prepare_error.clear()
    fake_clock.set(at + timedelta(minutes=2))

    assert run_tick(fake_scheduler_client).started == [publication_id]

    wait_idle(fake_scheduler_client)
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "published"
    assert publication["auto_publish_error"] is None


@pytest.mark.parametrize("action", ["reschedule", "disarm", "publish_now"])
def test_error_is_cleared(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    failing: tuple[int, Any],
    action: str,
) -> None:
    publication_id, _ = failing
    run_tick(fake_scheduler_client)
    url = f"/api/publications/{publication_id}"
    if action == "reschedule":
        response = fake_scheduler_client.patch(
            url,
            json={"scheduled_at": "2100-01-01T10:00:00Z", "auto_publish_enabled": True},
        )
    elif action == "disarm":
        response = fake_scheduler_client.patch(
            url, json={"auto_publish_enabled": False}
        )
    else:
        fake_publisher.prepare_error.clear()
        response = fake_scheduler_client.post(f"{url}/publish", json={})
        wait_idle(fake_scheduler_client)

    assert response.status_code in (200, 202), response.text
    assert (
        get_publication(fake_scheduler_client, publication_id)["auto_publish_error"]
        is None
    )


def test_stale_error_is_not_written_after_a_reschedule(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    failing: tuple[int, Any],
    db_path: Path,
) -> None:
    publication_id, _ = failing

    def reschedule(_: int) -> None:
        fake_scheduler_client.patch(
            f"/api/publications/{publication_id}",
            json={"scheduled_at": "2100-01-01T10:00:00Z", "auto_publish_enabled": True},
        )

    fake_publisher.prepare_hook = reschedule

    run_tick(fake_scheduler_client)

    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["scheduled_at"] == "2100-01-01T10:00:00Z"
    assert publication["auto_publish_error"] is None
    assert attempt_rows(db_path) == []
