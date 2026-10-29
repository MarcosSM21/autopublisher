"""Automatic refresh rules and the YouTube budget (Feature 027 T045, data-model
rules 2, 5, 8 and 9)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.analytics.adapters.base import FetchResult
from app.analytics.budget import YOUTUBE_DAILY_UNITS, DailyUnitBudget, quota_day
from app.analytics.refresh import (
    CycleReport,
    PlatformPauses,
    request_manual_refresh,
    run_refresh_cycle,
)
from app.db import write_transaction
from app.models import Platform
from tests import analytics_support as scene
from tests import readmodels
from tests.analytics_support import NOW, YouTubeWorld, later


@pytest.fixture
def world(tmp_path: Path) -> Iterator[YouTubeWorld]:
    with scene.youtube_world(tmp_path) as world:
        yield world


def cycle(
    world: YouTubeWorld, now: datetime = NOW, pauses: PlatformPauses | None = None
) -> CycleReport:
    return run_refresh_cycle(world.session_factory, world.adapters, now, pauses=pauses)


def video(world: YouTubeWorld, remote_id: str = "VIDEO-1", days_ago: float = 1) -> int:
    owner = world.youtube_account(remote_id.lower())
    world.google.statistics[remote_id] = {"viewCount": "5"}
    return scene.published(
        world.db_path,
        owner,
        remote_id,
        published_at=NOW - timedelta(days=days_ago),
    )


def calls(world: YouTubeWorld) -> int:
    return len(world.google.statistics_requests)


def sql(world: YouTubeWorld, statement: str, **params: object) -> None:
    with write_transaction(world.session_factory) as session:
        session.execute(text(statement), params)


def test_a_recent_post_is_read_automatically_at_most_once_a_day(
    world: YouTubeWorld,
) -> None:
    post = video(world)

    first = cycle(world)
    assert (first.succeeded, calls(world)) == (1, 1)
    [snapshot] = scene.values(world.db_path, post)
    assert snapshot["snapshot"]["trigger"] == "automatic"

    cycle(world, later(5))
    cycle(world, NOW + timedelta(hours=23, minutes=55))
    assert calls(world) == 1

    cycle(world, NOW + timedelta(hours=24))
    assert calls(world) == 2
    assert len(scene.values(world.db_path, post)) == 2


def test_an_older_post_is_only_refreshed_manually(world: YouTubeWorld) -> None:
    post = video(world, days_ago=91)

    cycle(world)
    assert calls(world) == 0
    assert scene.state(world.db_path, post) is None

    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post, NOW)
    cycle(world)

    assert calls(world) == 1
    state = scene.state(world.db_path, post)
    assert state is not None and state["status"] == "ok"
    [snapshot] = scene.values(world.db_path, post)
    assert snapshot["snapshot"]["trigger"] == "manual"


def test_manual_requests_go_first(world: YouTubeWorld) -> None:
    automatic = [video(world, f"AUTO-{i}") for i in range(2)]
    manual = video(world, "MANUAL", days_ago=200)
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, manual, NOW)

    report = run_refresh_cycle(world.session_factory, world.adapters, NOW, limit=1)

    assert report.attempted == 1
    assert scene.state(world.db_path, manual)["status"] == "ok"  # type: ignore[index]
    assert all(scene.state(world.db_path, p) is None for p in automatic)


@pytest.mark.parametrize("status", ["remote_deleted", "permission_required"])
def test_terminal_states_are_not_retried_automatically(
    world: YouTubeWorld, status: str
) -> None:
    post = video(world)
    readmodels.insert(
        world.db_path,
        "publication_metric_states",
        publication_id=post,
        status=status,
        last_attempt_at=NOW - timedelta(days=2),
        failure_count=1,
    )

    cycle(world)

    assert calls(world) == 0


def test_a_reconnected_account_is_read_again(world: YouTubeWorld) -> None:
    post = video(world)
    sql(world, "UPDATE youtube_connections SET status = 'reconnect_required'")
    cycle(world)
    assert calls(world) == 0

    sql(world, "UPDATE youtube_connections SET status = 'connected'")
    cycle(world, later(10))

    assert calls(world) == 1
    assert scene.state(world.db_path, post)["status"] == "ok"  # type: ignore[index]


def test_a_post_of_another_identity_is_never_read_automatically(
    world: YouTubeWorld,
) -> None:
    owner = world.youtube_account()
    scene.published(
        world.db_path, owner, "VIDEO-1", published_at=NOW, identity="UC-OLD"
    )

    report = cycle(world)

    assert calls(world) == 0
    assert report.attempted == 0


def test_the_automation_pause_does_not_stop_analytics(world: YouTubeWorld) -> None:
    video(world)
    sql(
        world,
        "INSERT OR REPLACE INTO automation_settings (id, automation_paused, "
        "updated_at) VALUES (1, 1, :now)",
        now=scene.ts(NOW),
    )

    cycle(world)

    assert calls(world) == 1


# --- YouTube budget -----------------------------------------------------------------


def test_the_budget_is_200_units_per_pacific_day() -> None:
    budget = DailyUnitBudget()
    assert budget.limit == YOUTUBE_DAILY_UNITS == 200
    assert all(budget.try_spend(NOW) for _ in range(200))
    assert not budget.try_spend(NOW)
    assert budget.remaining(NOW) == 0
    # 00:00 PDT is 07:00 UTC.
    reset = datetime(2026, 10, 30, 7, 0, tzinfo=UTC)
    assert quota_day(reset - timedelta(seconds=1)) == quota_day(NOW)
    assert budget.remaining(reset - timedelta(seconds=1)) == 0
    assert budget.remaining(reset) == 200


def test_each_call_spends_one_unit_and_the_cap_defers_youtube(
    world: YouTubeWorld,
) -> None:
    world.adapter.budget = budget = DailyUnitBudget(limit=2)
    posts = [video(world, f"V{i}") for i in range(3)]  # three accounts, three calls

    report = cycle(world)

    assert calls(world) == 2
    assert budget.remaining(NOW) == 0
    assert (report.succeeded, report.deferred) == (2, 1)
    waiting = [p for p in posts if scene.state(world.db_path, p) is None]
    assert len(waiting) == 1  # untouched, not failed

    cycle(world, later(30))
    assert calls(world) == 2

    reset = datetime(2026, 10, 30, 7, 0, tzinfo=UTC)
    # In the app the adapters share the refresher's clock.
    world.adapter.clock = lambda: reset
    cycle(world, reset)
    assert calls(world) == 3
    assert scene.state(world.db_path, waiting[0])["status"] == "ok"  # type: ignore[index]


def test_a_spent_budget_keeps_manual_requests_queued(world: YouTubeWorld) -> None:
    world.adapter.budget = DailyUnitBudget(limit=0)
    post = video(world, days_ago=300)
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post, NOW)

    cycle(world)

    state = scene.state(world.db_path, post)
    assert state is not None
    assert (state["status"], state["error_code"]) == ("pending", None)
    assert state["manual_requested_at"] is not None
    assert world.google.requests == []  # not even a token refresh


def test_the_youtube_budget_does_not_affect_instagram(world: YouTubeWorld) -> None:
    world.adapter.budget = DailyUnitBudget(limit=0)
    video(world)
    instagram = scene.published(
        world.db_path, world.instagram_account(), "IG-1", published_at=NOW
    )
    world.meta.counters = {"IG-1": {"comments_count": 2}}

    cycle(world)

    assert calls(world) == 0
    assert scene.state(world.db_path, instagram)["status"] == "ok"  # type: ignore[index]


def test_a_real_quota_exceeded_is_spent_and_keeps_its_meaning(
    world: YouTubeWorld,
) -> None:
    world.adapter.budget = budget = DailyUnitBudget()
    post = video(world)
    world.google.statistics_outcomes = ["quota"]
    pauses = PlatformPauses()

    cycle(world, NOW, pauses)

    assert budget.remaining(NOW) == 199
    state = scene.state(world.db_path, post)
    assert state is not None and state["status"] == "rate_limited"
    assert pauses.paused(Platform.YOUTUBE, later(60))


def test_an_instagram_rate_limit_does_not_affect_youtube(world: YouTubeWorld) -> None:
    youtube = video(world)
    instagram = scene.published(
        world.db_path, world.instagram_account(), "IG-1", published_at=NOW
    )
    world.meta.faults["counters"] = "rate_limited"
    pauses = PlatformPauses()

    cycle(world, NOW, pauses)
    cycle(world, later(10), pauses)

    assert scene.state(world.db_path, youtube)["status"] == "ok"  # type: ignore[index]
    assert scene.state(world.db_path, instagram)["status"] == "rate_limited"  # type: ignore[index]
    # The paused platform was not called again.
    assert len(world.meta.requests_for("counters")) == 1


# --- At most one automatic attempt per 24 h, whatever its outcome ----------------


def instagram_post(world: YouTubeWorld) -> int:
    world.meta.counters = {"IG-1": {"comments_count": 1}}
    return scene.published(
        world.db_path,
        world.instagram_account(),
        "IG-1",
        published_at=NOW - timedelta(days=1),
    )


def platform_calls(world: YouTubeWorld, platform: str) -> int:
    if platform == "youtube":
        return calls(world)
    return len(world.meta.requests_for("counters"))


def fail_next(world: YouTubeWorld, platform: str) -> None:
    if platform == "youtube":
        world.google.statistics_outcomes = ["server_error"]
    else:
        world.meta.fault_queue["counters"] = ["server_error"]


@pytest.mark.parametrize("platform", ["youtube", "instagram"])
def test_a_failed_automatic_attempt_waits_a_day(
    world: YouTubeWorld, platform: str
) -> None:
    post = video(world) if platform == "youtube" else instagram_post(world)
    fail_next(world, platform)

    cycle(world)
    state = scene.state(world.db_path, post)
    assert state is not None and state["status"] == "stale"
    assert platform_calls(world, platform) == 1

    # Not 5 minutes later, not after the 1 h backoff, not just before the day.
    for when in (later(5), later(60), NOW + timedelta(hours=23, minutes=55)):
        cycle(world, when)
    assert platform_calls(world, platform) == 1

    cycle(world, NOW + timedelta(hours=24))
    assert platform_calls(world, platform) == 2
    assert scene.state(world.db_path, post)["status"] == "ok"  # type: ignore[index]


@pytest.mark.parametrize("platform", ["youtube", "instagram"])
def test_a_manual_request_is_not_held_by_the_automatic_cadence(
    world: YouTubeWorld, platform: str
) -> None:
    post = video(world) if platform == "youtube" else instagram_post(world)
    fail_next(world, platform)
    cycle(world)

    # Only the 15-minute cooldown applies to a manual request.
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post, later(20))
    cycle(world, later(20))

    assert platform_calls(world, platform) == 2
    state = scene.state(world.db_path, post)
    assert state is not None and state["status"] == "ok"
    # The success restarts the automatic day from the manual read.
    assert state["next_attempt_at"] == scene.ts(later(20) + timedelta(hours=24))


def test_a_backoff_longer_than_a_day_is_kept(
    world: YouTubeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    post = video(world)
    retry_at = NOW + timedelta(hours=30)

    attempts: list[datetime] = []

    def fetch(session: object, account_id: int, remote_ids: list[str]) -> object:
        attempts.append(NOW)
        return {r: FetchResult.rate_limited(retry_at) for r in remote_ids}

    monkeypatch.setattr(world.adapter, "fetch", fetch)

    cycle(world)
    state = scene.state(world.db_path, post)
    assert state is not None and state["next_attempt_at"] == scene.ts(retry_at)

    cycle(world, NOW + timedelta(hours=24))
    assert len(attempts) == 1
    cycle(world, retry_at)
    assert len(attempts) == 2
