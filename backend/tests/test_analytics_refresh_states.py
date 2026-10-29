"""Refresh state transitions (Feature 027 T030, data-model rule 7).

Every failure keeps the last valid snapshot and never creates one; publications and
attempts are never modified.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.analytics.adapters.youtube import next_quota_reset
from app.analytics.refresh import (
    PlatformPauses,
    backoff,
    request_manual_refresh,
    run_refresh_cycle,
)
from app.db import write_transaction
from app.errors import AppError
from app.models import Platform
from tests import analytics_support as scene
from tests.analytics_support import NOW, YouTubeWorld, later


@pytest.fixture
def world(tmp_path: Path) -> Iterator[YouTubeWorld]:
    with scene.youtube_world(tmp_path) as world:
        yield world


@pytest.fixture
def post(world: YouTubeWorld) -> int:
    owner = world.youtube_account()
    world.google.statistics = {
        "VIDEO-1": {"viewCount": "100", "likeCount": "4", "commentCount": "1"}
    }
    return scene.published(world.db_path, owner, "VIDEO-1")


def attempt(
    world: YouTubeWorld,
    post_id: int,
    now: datetime,
    outcome: str = "ok",
    pauses: PlatformPauses | None = None,
) -> dict[str, Any]:
    """A manual request, then one cycle with the given FakeGoogle outcome."""
    world.google.statistics_outcomes = [outcome]
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post_id, now)
    run_refresh_cycle(
        world.session_factory, {Platform.YOUTUBE: world.adapter}, now, pauses=pauses
    )
    found = scene.state(world.db_path, post_id)
    assert found is not None
    return found


def publishing_rows(world: YouTubeWorld) -> list[list[dict[str, Any]]]:
    return [
        scene.rows(world.db_path, f"SELECT * FROM {table} ORDER BY id")
        for table in ("publications", "publication_attempts")
    ]


def test_success_is_ok_until_the_next_day(world: YouTubeWorld, post: int) -> None:
    result = attempt(world, post, NOW)

    assert result["status"] == "ok"
    assert result["last_success_at"] == scene.ts(NOW)
    assert result["next_attempt_at"] == scene.ts(NOW + timedelta(hours=24))
    assert result["manual_requested_at"] is None
    assert result["failure_count"] == 0
    assert result["error_code"] is None


def test_transient_failures_are_stale_keeping_the_data_and_wait_a_day(
    world: YouTubeWorld, post: int
) -> None:
    attempt(world, post, NOW)
    for failures, minutes in enumerate((20, 40, 60), start=1):
        now = later(minutes)
        result = attempt(world, post, now, "server_error")
        assert result["status"] == "stale"
        assert result["failure_count"] == failures
        # The backoff (1 h, 2 h, 4 h) never brings the next automatic attempt
        # closer than a day.
        assert result["next_attempt_at"] == scene.ts(now + timedelta(hours=24))
        assert result["last_success_at"] == scene.ts(NOW)
        assert result["error_code"] == "refresh_failed"
    # The valid reading is kept.
    assert len(scene.values(world.db_path, post)) == 1


def test_backoff_is_capped_at_a_day() -> None:
    assert [backoff(n) for n in (1, 2, 3, 5, 6, 40)] == [
        timedelta(hours=h) for h in (1, 2, 4, 16, 24, 24)
    ]


def test_success_after_failures_resets_the_count(
    world: YouTubeWorld, post: int
) -> None:
    attempt(world, post, NOW, "timeout")

    result = attempt(world, post, later(20))

    assert (result["status"], result["failure_count"]) == ("ok", 0)
    assert result["error_code"] is None


def test_daily_quota_is_rate_limited_until_the_pacific_reset(
    world: YouTubeWorld, post: int
) -> None:
    pauses = PlatformPauses()

    result = attempt(world, post, NOW, "quota", pauses)

    reset = next_quota_reset(NOW)
    assert reset == datetime(2026, 10, 30, 7, 0, tzinfo=UTC)  # 00:00 PDT
    assert result["status"] == "rate_limited"
    # The platform waits for the reset; this post's next automatic attempt is
    # still a day away.
    assert result["next_attempt_at"] == scene.ts(NOW + timedelta(hours=24))
    assert pauses.paused(Platform.YOUTUBE, later(60))
    assert not pauses.paused(Platform.YOUTUBE, reset)


def test_a_rate_limit_skips_the_rest_of_the_platform(world: YouTubeWorld) -> None:
    first, second = world.youtube_account("first"), world.youtube_account("second")
    posts = [
        scene.published(world.db_path, first, "A"),
        scene.published(world.db_path, second, "B"),
    ]
    with write_transaction(world.session_factory) as session:
        for post_id in posts:
            request_manual_refresh(session, post_id, NOW)
    world.google.statistics_outcomes = ["rate_limit"]

    report = run_refresh_cycle(
        world.session_factory, {Platform.YOUTUBE: world.adapter}, NOW
    )

    assert (report.attempted, report.deferred) == (1, 1)
    assert len(world.google.statistics_requests) == 1
    states = [scene.state(world.db_path, p) for p in posts]
    assert [s["status"] for s in states if s] == ["rate_limited", "pending"]
    # The blocked manual request stays queued.
    assert states[1] is not None and states[1]["manual_requested_at"] is not None


def test_a_paused_platform_leaves_other_platforms_alone(
    world: YouTubeWorld, post: int
) -> None:
    pauses = PlatformPauses()
    pauses.pause(Platform.INSTAGRAM, NOW, later(60))

    result = attempt(world, post, NOW, "ok", pauses)

    assert result["status"] == "ok"


def test_an_unauthorized_token_requires_reconnection(
    world: YouTubeWorld,
    post: int,
    oauth_client_file: Path,
) -> None:
    # 401 even after one forced refresh.
    world.google.statistics_outcomes = ["unauthorized", "unauthorized"]
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post, NOW)

    run_refresh_cycle(world.session_factory, {Platform.YOUTUBE: world.adapter}, NOW)

    result = scene.state(world.db_path, post)
    assert result is not None
    assert result["status"] == "reconnect_required"
    assert result["next_attempt_at"] == scene.ts(NOW + timedelta(hours=24))
    assert len(world.google.statistics_requests) == 2
    [connection] = scene.rows(world.db_path, "SELECT status FROM youtube_connections")
    assert connection["status"] == "reconnect_required"


def test_one_unauthorized_answer_is_retried_with_a_fresh_token(
    world: YouTubeWorld,
    post: int,
    oauth_client_file: Path,
) -> None:
    world.google.statistics_outcomes = ["unauthorized"]
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post, NOW)

    run_refresh_cycle(world.session_factory, {Platform.YOUTUBE: world.adapter}, NOW)

    result = scene.state(world.db_path, post)
    assert result is not None and result["status"] == "ok"


def test_missing_stored_credentials_require_reconnection(
    world: YouTubeWorld, post: int
) -> None:
    world.store.secrets.clear()

    result = attempt(world, post, NOW)

    assert result["status"] == "reconnect_required"
    assert world.google.statistics_requests == []


def test_a_missing_scope_requires_the_permission(
    world: YouTubeWorld, post: int
) -> None:
    result = attempt(world, post, NOW, "forbidden")

    assert result["status"] == "permission_required"
    assert result["error_code"] == "permission_required"
    assert result["next_attempt_at"] is None


def test_an_unavailable_credential_store_is_transient(
    world: YouTubeWorld, post: int
) -> None:
    world.store.unavailable = True

    result = attempt(world, post, NOW)

    assert result["status"] == "stale"


def test_an_absence_needs_a_second_one_an_hour_later(
    world: YouTubeWorld, post: int
) -> None:
    attempt(world, post, NOW)
    world.google.statistics = {}

    first = attempt(world, post, later(20))
    assert first["status"] == "remote_not_found"
    assert first["error_code"] == "remote_not_found"
    # A manual check may confirm it an hour later; automatically, a day later.
    assert first["next_attempt_at"] == scene.ts(later(20) + timedelta(hours=24))

    # Too soon: still not confirmed.
    early = attempt(world, post, later(40))
    assert early["status"] == "remote_not_found"

    confirmed = attempt(world, post, later(100))
    assert confirmed["status"] == "remote_deleted"
    assert confirmed["error_code"] == "remote_deleted"
    assert confirmed["next_attempt_at"] is None
    # The last valid reading is kept.
    assert len(scene.values(world.db_path, post)) == 1
    assert confirmed["last_success_at"] == scene.ts(NOW)


def test_a_reappearance_between_absences_returns_to_ok(
    world: YouTubeWorld, post: int
) -> None:
    statistics = dict(world.google.statistics)
    world.google.statistics = {}
    attempt(world, post, NOW)

    world.google.statistics = statistics
    assert attempt(world, post, later(20))["status"] == "ok"

    world.google.statistics = {}
    assert attempt(world, post, later(90))["status"] == "remote_not_found"


def test_another_failure_between_absences_restarts_the_confirmation(
    world: YouTubeWorld, post: int
) -> None:
    world.google.statistics = {}
    attempt(world, post, NOW)
    attempt(world, post, later(20), "server_error")

    assert attempt(world, post, later(90))["status"] == "remote_not_found"


def test_an_ambiguous_answer_is_never_an_absence(
    world: YouTubeWorld, post: int
) -> None:
    world.google.statistics = {}

    result = attempt(world, post, NOW, "paged")

    assert result["status"] == "stale"


def test_a_deleted_post_can_still_be_refreshed_manually(
    world: YouTubeWorld, post: int
) -> None:
    statistics = dict(world.google.statistics)
    world.google.statistics = {}
    attempt(world, post, NOW)
    attempt(world, post, later(70))
    world.google.statistics = statistics

    assert attempt(world, post, later(90))["status"] == "ok"


def test_publications_and_attempts_are_never_modified(
    world: YouTubeWorld, post: int
) -> None:
    before = publishing_rows(world)
    for minutes, outcome in ((0, "ok"), (20, "server_error"), (40, "quota")):
        attempt(world, post, later(minutes), outcome, PlatformPauses())

    assert publishing_rows(world) == before


def test_a_crashing_adapter_does_not_stop_the_cycle(
    world: YouTubeWorld, post: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(world.adapter, "fetch", boom)

    result = attempt(world, post, NOW)

    assert result["status"] == "stale"


def test_an_identity_change_never_leads_to_remote_deleted(
    world: YouTubeWorld, post: int
) -> None:
    # A first real absence, then the account is reconnected to another channel.
    world.google.statistics = {}
    attempt(world, post, NOW)
    with write_transaction(world.session_factory) as session:
        session.execute(
            text("UPDATE youtube_connections SET channel_id = 'UC-NEW-CHANNEL'")
        )
    calls = len(world.google.statistics_requests)

    with write_transaction(world.session_factory) as session:
        with pytest.raises(AppError) as refused:
            request_manual_refresh(session, post, later(90))
    run_refresh_cycle(
        world.session_factory, {Platform.YOUTUBE: world.adapter}, later(90)
    )

    assert refused.value.details == {"reason": "remote_identity_changed"}
    assert len(world.google.statistics_requests) == calls
    result = scene.state(world.db_path, post)
    assert result is not None and result["status"] == "remote_not_found"


def test_a_queued_request_is_dropped_without_a_call_after_an_identity_change(
    world: YouTubeWorld, post: int
) -> None:
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post, NOW)
        session.execute(
            text("UPDATE youtube_connections SET channel_id = 'UC-NEW-CHANNEL'")
        )

    report = run_refresh_cycle(
        world.session_factory, {Platform.YOUTUBE: world.adapter}, NOW
    )

    assert (report.attempted, report.not_refreshable) == (0, 1)
    assert world.google.statistics_requests == []
    result = scene.state(world.db_path, post)
    assert result is not None
    assert result["manual_requested_at"] is None
    assert result["status"] not in ("remote_not_found", "remote_deleted")
