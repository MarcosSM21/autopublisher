"""Snapshots, original values and engagement (Feature 027 T029, FR-005–FR-007,
FR-019). Each cycle runs against `FakeGoogle`; nothing else is contacted."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.analytics.adapters.youtube import YouTubeMetricsAdapter
from app.analytics.engagement import engagement_of
from app.analytics.refresh import (
    MAX_PER_CYCLE,
    CycleReport,
    request_manual_refresh,
    run_refresh_cycle,
)
from app.db import write_transaction
from app.models import Platform
from app.youtube_gateway import MAX_IDS_PER_VIDEOS_LIST
from tests import analytics_support as scene
from tests.analytics_support import NOW, YouTubeWorld, later

FORMULA = YouTubeMetricsAdapter.engagement


@pytest.fixture
def world(tmp_path: Path) -> Iterator[YouTubeWorld]:
    with scene.youtube_world(tmp_path) as world:
        yield world


def request(world: YouTubeWorld, *post_ids: int, now: Any = NOW) -> None:
    with write_transaction(world.session_factory) as session:
        for post_id in post_ids:
            request_manual_refresh(session, post_id, now)


def cycle(world: YouTubeWorld, now: Any = NOW) -> CycleReport:
    return run_refresh_cycle(
        world.session_factory, {Platform.YOUTUBE: world.adapter}, now
    )


def test_a_success_records_the_original_values_with_traceability(
    world: YouTubeWorld,
) -> None:
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1")
    world.google.statistics = {
        "VIDEO-1": {
            "viewCount": "1500",
            "likeCount": "0",
            "commentCount": "12",
            "dislikeCount": "3",
            "favoriteCount": "0",
        }
    }
    request(world, post_id)

    report = cycle(world)

    assert (report.attempted, report.succeeded) == (1, 1)
    [only] = scene.values(world.db_path, post_id)
    snapshot = only["snapshot"]
    assert snapshot["platform"] == "youtube"
    assert snapshot["remote_id"] == "VIDEO-1"
    assert snapshot["source"] == "youtube.videos.list:statistics"
    assert snapshot["trigger"] == "manual"
    assert snapshot["captured_at"] == scene.ts(NOW)
    assert {name: row["value"] for name, row in only["values"].items()} == {
        "viewCount": 1500,
        "likeCount": 0,  # a real 0 is stored
        "commentCount": 12,
        "dislikeCount": 3,
    }
    assert {row["origin"] for row in only["values"].values()} == {"public_counter"}
    # The deprecated field is never stored.
    assert "favoriteCount" not in only["values"]


def test_absent_fields_have_no_row(world: YouTubeWorld) -> None:
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1")
    # Likes hidden and comments disabled: YouTube omits the fields.
    world.google.statistics = {"VIDEO-1": {"viewCount": "10"}}
    request(world, post_id)

    cycle(world)

    [only] = scene.values(world.db_path, post_id)
    assert set(only["values"]) == {"viewCount"}


def test_a_failure_creates_no_snapshot(world: YouTubeWorld) -> None:
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1")
    world.google.statistics_outcomes = ["server_error"]
    request(world, post_id)

    cycle(world)

    assert scene.values(world.db_path, post_id) == []


def test_history_snapshots_are_never_overwritten(world: YouTubeWorld) -> None:
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1")
    for minutes, views in ((0, "10"), (20, "25")):
        world.google.statistics = {"VIDEO-1": {"viewCount": views}}
        request(world, post_id, now=later(minutes))
        cycle(world, later(minutes))

    history = scene.values(world.db_path, post_id)
    assert [s["values"]["viewCount"]["value"] for s in history] == [10, 25]
    assert [s["snapshot"]["captured_at"] for s in history] == [
        scene.ts(later(0)),
        scene.ts(later(20)),
    ]


def test_one_call_reads_a_batch_of_the_same_account(world: YouTubeWorld) -> None:
    owner = world.youtube_account()
    total = MAX_IDS_PER_VIDEOS_LIST + 3
    ids = [f"V{i}" for i in range(total)]
    posts = [scene.published(world.db_path, owner, video_id) for video_id in ids]
    other = world.youtube_account("other")
    other_post = scene.published(world.db_path, other, "OTHER-1")
    world.google.statistics = {v: {"viewCount": "1"} for v in [*ids, "OTHER-1"]}
    request(world, *posts, other_post)

    report = cycle(world)

    assert report.succeeded == total + 1
    batches = [
        parse_qs(urlsplit(r.url).query)["id"][0].split(",")
        for r in world.google.statistics_requests
    ]
    # One account per call, at most 50 ids per call.
    assert sorted(len(batch) for batch in batches) == [1, 3, 50]
    assert ["OTHER-1"] in batches


def test_a_cycle_handles_at_most_its_limit(world: YouTubeWorld) -> None:
    assert MAX_PER_CYCLE == 200
    owner = world.youtube_account()
    posts = [scene.published(world.db_path, owner, f"V{i}") for i in range(3)]
    world.google.statistics = {f"V{i}": {"viewCount": "1"} for i in range(3)}
    request(world, *posts)

    report = run_refresh_cycle(
        world.session_factory, {Platform.YOUTUBE: world.adapter}, NOW, limit=2
    )

    assert report.attempted == 2
    assert scene.state(world.db_path, posts[2])["status"] == "pending"  # type: ignore[index]


# --- Engagement (computed on read, never stored) ------------------------------------


def test_engagement_uses_the_fixed_formula() -> None:
    result = engagement_of(
        FORMULA, {"viewCount": 200, "likeCount": 30, "commentCount": 10}
    )

    assert result.available
    assert result.value == pytest.approx(0.2)
    assert result.formula == "(likeCount + commentCount) / viewCount"
    assert result.components == {"likeCount": 30, "commentCount": 10, "viewCount": 200}


def test_engagement_counts_real_zeros() -> None:
    result = engagement_of(FORMULA, {"viewCount": 5, "likeCount": 0, "commentCount": 0})

    assert result.available and result.value == 0


@pytest.mark.parametrize("missing", ["likeCount", "commentCount", "viewCount"])
def test_engagement_is_not_available_without_a_component(missing: str) -> None:
    values = {"viewCount": 100, "likeCount": 3, "commentCount": 1}
    del values[missing]

    result = engagement_of(FORMULA, values)

    assert not result.available
    assert result.value is None
    assert result.components[missing] is None


def test_engagement_is_not_available_without_views() -> None:
    result = engagement_of(FORMULA, {"viewCount": 0, "likeCount": 0, "commentCount": 0})

    assert not result.available and result.value is None


def test_engagement_is_never_stored(world: YouTubeWorld) -> None:
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1")
    world.google.statistics = {
        "VIDEO-1": {"viewCount": "10", "likeCount": "1", "commentCount": "1"}
    }
    request(world, post_id)

    cycle(world)

    [only] = scene.values(world.db_path, post_id)
    assert set(only["values"]) == {"viewCount", "likeCount", "commentCount"}
