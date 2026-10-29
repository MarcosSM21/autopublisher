"""Instagram basic counters in the common refresh engine (Feature 027 T036).

Only `like_count`/`comments_count` are read, one call per media; insights are never
called. Every cycle runs against `FakeMeta`/`FakeGoogle`.
"""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.analytics.adapters.registry import ADAPTERS
from app.analytics.refresh import (
    CycleReport,
    PlatformPauses,
    request_manual_refresh,
    request_project_refresh,
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
    owner = world.instagram_account()
    world.meta.counters = {"IG-1": {"like_count": 40, "comments_count": 3}}
    return scene.published(world.db_path, owner, "IG-1")


def request(world: YouTubeWorld, *post_ids: int, now: datetime = NOW) -> None:
    with write_transaction(world.session_factory) as session:
        for post_id in post_ids:
            request_manual_refresh(session, post_id, now)


def cycle(
    world: YouTubeWorld, now: datetime = NOW, pauses: PlatformPauses | None = None
) -> CycleReport:
    return run_refresh_cycle(world.session_factory, world.adapters, now, pauses=pauses)


def attempt(
    world: YouTubeWorld, post_id: int, now: datetime, fault: str | None = None
) -> dict[str, Any]:
    if fault is not None:
        world.meta.fault_queue["counters"] = [fault]
    request(world, post_id, now=now)
    cycle(world, now)
    found = scene.state(world.db_path, post_id)
    assert found is not None
    return found


def counters_calls(world: YouTubeWorld) -> int:
    return len(world.meta.requests_for("counters"))


def test_a_success_records_the_basic_counters(world: YouTubeWorld, post: int) -> None:
    result = attempt(world, post, NOW)

    assert result["status"] == "ok"
    [only] = scene.values(world.db_path, post)
    assert only["snapshot"]["source"] == "instagram.media:fields"
    assert only["snapshot"]["remote_id"] == "IG-1"
    assert only["snapshot"]["captured_at"] == scene.ts(NOW)
    assert {n: r["value"] for n, r in only["values"].items()} == {
        "like_count": 40,
        "comments_count": 3,
    }
    assert {r["origin"] for r in only["values"].values()} == {"public_counter"}


def test_zero_is_a_real_value(world: YouTubeWorld, post: int) -> None:
    world.meta.counters = {"IG-1": {"like_count": 0, "comments_count": 0}}

    attempt(world, post, NOW)

    [only] = scene.values(world.db_path, post)
    assert {n: r["value"] for n, r in only["values"].items()} == {
        "like_count": 0,
        "comments_count": 0,
    }


def test_a_hidden_like_count_has_no_row(world: YouTubeWorld, post: int) -> None:
    # The owner hid like counts: Instagram omits the field.
    world.meta.counters = {"IG-1": {"comments_count": 9}}

    result = attempt(world, post, NOW)

    assert result["status"] == "ok"
    [only] = scene.values(world.db_path, post)
    assert set(only["values"]) == {"comments_count"}


def test_no_insights_call_is_ever_made(world: YouTubeWorld, post: int) -> None:
    attempt(world, post, NOW)

    urls = [r.url for r in world.meta.requests]
    assert urls and not any("insights" in url for url in urls)
    # Every Meta call is the basic counters read.
    assert len(world.meta.requests_for("counters")) == len(urls) == 1


def test_instagram_declares_no_engagement() -> None:
    assert ADAPTERS[Platform.INSTAGRAM].engagement is None


def test_history_is_kept(world: YouTubeWorld, post: int) -> None:
    attempt(world, post, NOW)
    world.meta.counters = {"IG-1": {"like_count": 55, "comments_count": 3}}
    attempt(world, post, later(20))

    history = scene.values(world.db_path, post)
    assert [s["values"]["like_count"]["value"] for s in history] == [40, 55]


def test_a_project_refresh_is_processed_by_the_same_queue(
    world: YouTubeWorld,
) -> None:
    owner = world.instagram_account()
    posts = [scene.published(world.db_path, owner, f"IG-{i}") for i in range(3)]
    world.meta.counters = {f"IG-{i}": {"comments_count": i} for i in range(3)}
    with write_transaction(world.session_factory) as session:
        counts = request_project_refresh(session, owner["project_id"], NOW)
    assert counts.queued == 3

    report = cycle(world)

    # One call per media.
    assert (report.succeeded, counters_calls(world)) == (3, 3)
    assert {scene.state(world.db_path, p)["status"] for p in posts} == {"ok"}  # type: ignore[index]


def test_a_post_of_another_instagram_account_is_never_read(
    world: YouTubeWorld, post: int
) -> None:
    attempt(world, post, NOW)
    with write_transaction(world.session_factory) as session:
        session.execute(
            text("UPDATE instagram_connections SET instagram_user_id = 'IG-OTHER'")
        )

    with pytest.raises(AppError) as refused:
        request(world, post, now=later(90))
    cycle(world, later(90))

    assert refused.value.details == {"reason": "remote_identity_changed"}
    assert counters_calls(world) == 1
    result = scene.state(world.db_path, post)
    assert result is not None and result["status"] == "ok"
    assert len(scene.values(world.db_path, post)) == 1


def test_an_invalid_token_requires_reconnection(world: YouTubeWorld, post: int) -> None:
    result = attempt(world, post, NOW, "graph_190")

    assert result["status"] == "reconnect_required"
    [connection] = scene.rows(world.db_path, "SELECT status FROM instagram_connections")
    assert connection["status"] == "reconnect_required"


def test_missing_credentials_require_reconnection_without_a_call(
    world: YouTubeWorld, post: int
) -> None:
    world.ig_store.secrets.clear()

    result = attempt(world, post, NOW)

    assert result["status"] == "reconnect_required"
    assert counters_calls(world) == 0


def test_a_permission_error_is_permission_required(
    world: YouTubeWorld, post: int
) -> None:
    result = attempt(world, post, NOW, "graph_10")

    assert result["status"] == "permission_required"
    assert result["next_attempt_at"] is None


@pytest.mark.parametrize("fault", ["graph_4", "rate_limited"])
def test_a_rate_limit_pauses_and_waits_a_day_for_the_post(
    world: YouTubeWorld, post: int, fault: str
) -> None:
    result = attempt(world, post, NOW, fault)

    assert result["status"] == "rate_limited"
    assert result["next_attempt_at"] == scene.ts(later(24 * 60))


@pytest.mark.parametrize("fault", ["server_error", "transport", "graph_9999"])
def test_transient_failures_are_stale_keeping_the_data(
    world: YouTubeWorld, post: int, fault: str
) -> None:
    attempt(world, post, NOW)

    result = attempt(world, post, later(20), fault)

    assert result["status"] == "stale"
    assert result["last_success_at"] == scene.ts(NOW)
    assert len(scene.values(world.db_path, post)) == 1


def test_an_absence_is_confirmed_only_an_hour_later(
    world: YouTubeWorld, post: int
) -> None:
    attempt(world, post, NOW)
    world.meta.counters = {}

    assert attempt(world, post, later(20))["status"] == "remote_not_found"
    assert attempt(world, post, later(40))["status"] == "remote_not_found"
    deleted = attempt(world, post, later(100))
    assert deleted["status"] == "remote_deleted"
    assert len(scene.values(world.db_path, post)) == 1


@pytest.mark.parametrize("fault", ["graph_100", "graph_100_2207008"])
def test_an_ambiguous_error_is_never_an_absence(
    world: YouTubeWorld, post: int, fault: str
) -> None:
    world.meta.counters = {}
    first = attempt(world, post, NOW, fault)
    second = attempt(world, post, later(90), fault)

    assert first["status"] == second["status"] == "stale"


def test_youtube_and_instagram_share_a_cycle_without_interfering(
    world: YouTubeWorld, post: int
) -> None:
    youtube = world.youtube_account()
    video = scene.published(world.db_path, youtube, "VIDEO-1")
    world.google.statistics = {"VIDEO-1": {"viewCount": "7"}}
    second_ig = scene.published(world.db_path, world.instagram_account("b"), "IG-2")
    # Instagram limits requests on its first call.
    world.meta.fault_queue["counters"] = ["rate_limited"]
    request(world, post, second_ig, video)
    pauses = PlatformPauses()

    report = cycle(world, NOW, pauses)

    assert scene.state(world.db_path, video)["status"] == "ok"  # type: ignore[index]
    assert scene.state(world.db_path, post)["status"] == "rate_limited"  # type: ignore[index]
    # The rest of Instagram waits, still queued.
    waiting = scene.state(world.db_path, second_ig)
    assert waiting is not None
    assert (waiting["status"], waiting["manual_requested_at"] is not None) == (
        "pending",
        True,
    )
    assert pauses.paused(Platform.INSTAGRAM, NOW)
    assert not pauses.paused(Platform.YOUTUBE, NOW)
    assert (report.succeeded, report.failed, report.deferred) == (1, 1, 1)
