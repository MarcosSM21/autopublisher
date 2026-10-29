"""Publishing priority over analytics (Feature 027 T044, data-model rule 6).

No analytics call starts while an attempt is running or an armed publication is
due within 10 minutes (or still inside its automatic window). Nothing is marked as
failed: the work stays queued and runs once publishing is done.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app import scheduler
from app.analytics.refresh import request_manual_refresh, run_refresh_cycle
from app.automation import publishing_imminent
from app.db import write_transaction
from tests import analytics_support as scene
from tests import readmodels
from tests.analytics_support import NOW, YouTubeWorld, later
from tests.test_delete_post import running_attempt


@pytest.fixture
def world(tmp_path: Path) -> Iterator[YouTubeWorld]:
    with scene.youtube_world(tmp_path) as world:
        yield world


@pytest.fixture
def video(world: YouTubeWorld) -> dict[str, Any]:
    owner = world.youtube_account()
    world.google.statistics = {"VIDEO-1": {"viewCount": "9"}}
    post_id = scene.published(world.db_path, owner, "VIDEO-1")
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, post_id, NOW)
    return {"post": post_id, "owner": owner}


def scheduled(
    world: YouTubeWorld, owner: dict[str, Any], minutes: float, armed: bool = True
) -> int:
    return readmodels.post(
        world.db_path,
        owner,
        NOW,
        status="scheduled",
        scheduled_at=NOW + timedelta(minutes=minutes),
        armed=armed,
    )


def imminent(world: YouTubeWorld) -> bool:
    with world.session_factory() as session:
        return publishing_imminent(session, NOW)


def assert_untouched(world: YouTubeWorld, post_id: int) -> None:
    assert world.google.statistics_requests == []
    state = scene.state(world.db_path, post_id)
    assert state is not None
    assert state["status"] == "pending"
    assert state["manual_requested_at"] is not None
    assert state["error_code"] is None


def test_no_read_while_an_attempt_is_running(
    world: YouTubeWorld, video: dict[str, Any]
) -> None:
    other = readmodels.post(world.db_path, video["owner"], NOW, status="publishing")
    running_attempt(world.db_path, other, NOW)

    report = run_refresh_cycle(world.session_factory, world.adapters, NOW)

    assert imminent(world)
    assert report.yielded_to_publishing
    assert_untouched(world, video["post"])


@pytest.mark.parametrize("minutes", [0, 5, 10, -5, -10])
def test_no_read_with_an_armed_publication_due_soon_or_in_its_window(
    world: YouTubeWorld, video: dict[str, Any], minutes: float
) -> None:
    scheduled(world, video["owner"], minutes)

    report = run_refresh_cycle(world.session_factory, world.adapters, NOW)

    assert report.yielded_to_publishing
    assert_untouched(world, video["post"])


@pytest.mark.parametrize(
    ("minutes", "armed"),
    [(30, True), (5, False), (-11, True)],  # later, not armed, window missed
)
def test_other_publications_do_not_block(
    world: YouTubeWorld, video: dict[str, Any], minutes: float, armed: bool
) -> None:
    scheduled(world, video["owner"], minutes, armed)

    report = run_refresh_cycle(world.session_factory, world.adapters, NOW)

    assert not imminent(world)
    assert not report.yielded_to_publishing
    assert scene.state(world.db_path, video["post"])["status"] == "ok"  # type: ignore[index]


def test_queued_work_runs_once_publishing_is_done(
    world: YouTubeWorld, video: dict[str, Any]
) -> None:
    due = scheduled(world, video["owner"], 5)
    run_refresh_cycle(world.session_factory, world.adapters, NOW)
    assert_untouched(world, video["post"])

    # The scheduled publication went out.
    with write_transaction(world.session_factory) as session:
        session.execute(
            text(
                "UPDATE publications SET status = 'published', published_at = :now, "
                "auto_publish_enabled = 0 WHERE id = :id"
            ),
            {"now": scene.ts(later(6)), "id": due},
        )
    report = run_refresh_cycle(world.session_factory, world.adapters, later(20))

    assert not report.yielded_to_publishing
    state = scene.state(world.db_path, video["post"])
    assert state is not None and state["status"] == "ok"
    assert len(world.google.statistics_requests) == 1


def test_publishing_that_becomes_imminent_stops_the_next_batches(
    world: YouTubeWorld, video: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    second = world.youtube_account("second")
    second_post = scene.published(world.db_path, second, "VIDEO-2")
    world.google.statistics["VIDEO-2"] = {"viewCount": "1"}
    with write_transaction(world.session_factory) as session:
        request_manual_refresh(session, second_post, NOW)
    original = world.adapter.fetch

    def fetch_then_schedule(*args: Any) -> Any:
        results = original(*args)
        scheduled(world, video["owner"], 3)  # arrives during the first batch
        return results

    monkeypatch.setattr(world.adapter, "fetch", fetch_then_schedule)

    report = run_refresh_cycle(world.session_factory, world.adapters, NOW)

    # The batch in flight finished; the next one did not start.
    assert (report.attempted, report.deferred) == (1, 1)
    assert report.yielded_to_publishing
    assert len(world.google.statistics_requests) == 1
    states = {
        p: scene.state(world.db_path, p)["status"]  # type: ignore[index]
        for p in (video["post"], second_post)
    }
    assert sorted(states.values()) == ["ok", "pending"]


def test_the_publishing_scheduler_never_consults_analytics() -> None:
    source = Path(scheduler.__file__).read_text()
    assert "analytics" not in source
    assert "publishing_imminent" not in source
