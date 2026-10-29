"""Remote link of a publication (Feature 027 T028, FR-003, FR-004).

Only the `external_id` of the succeeded attempt counts; there is no matching by
title, date or search.
"""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.analytics.refresh import RemoteLink, eligibility, remote_link
from app.models import Publication
from tests import analytics_support as scene
from tests import readmodels
from tests.analytics_support import NOW, YouTubeWorld


@pytest.fixture
def world(tmp_path: Path) -> Iterator[YouTubeWorld]:
    with scene.youtube_world(tmp_path) as world:
        yield world


def link_of(world: YouTubeWorld, post_id: int) -> RemoteLink:
    with world.session_factory() as session:
        publication = session.get(Publication, post_id)
        assert publication is not None
        return remote_link(session, publication)


def test_a_published_post_with_an_id_is_linked(world: YouTubeWorld) -> None:
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1")

    assert link_of(world, post_id) == RemoteLink("VIDEO-1", None)
    with world.session_factory() as session:
        publication = session.get(Publication, post_id)
        assert publication is not None
        assert eligibility(session, publication).refreshable


@pytest.mark.parametrize(
    ("platform", "options", "reason"),
    [
        ("tiktok", {"details": {"tiktok_mode": "INBOX_UPLOAD"}}, "inbox_upload"),
        (
            "instagram",
            {"warnings": [{"code": "remote_identity_unavailable", "message": "m"}]},
            "remote_identity_unavailable",
        ),
        ("youtube", {}, "remote_id_missing"),
    ],
)
def test_a_published_post_without_id_is_not_linked_with_its_reason(
    world: YouTubeWorld, platform: str, options: dict[str, Any], reason: str
) -> None:
    owner = scene.account(world.db_path, scene.project(world.db_path), platform)
    post_id = scene.published(world.db_path, owner, None, **options)

    assert link_of(world, post_id) == RemoteLink(None, reason)


@pytest.mark.parametrize("status", ["failed", "awaiting_user_action", "cancelled"])
def test_a_post_that_is_not_published_is_not_linked(
    world: YouTubeWorld, status: str
) -> None:
    owner = world.youtube_account()
    post_id = readmodels.post(world.db_path, owner, NOW, status=status)
    scene.attempt(world.db_path, post_id, "youtube", external_id="VIDEO-1")

    assert link_of(world, post_id) == RemoteLink(None, "not_published")


def test_a_published_post_without_a_succeeded_attempt_is_not_linked(
    world: YouTubeWorld,
) -> None:
    owner = world.youtube_account()
    post_id = readmodels.post(world.db_path, owner, NOW, status="published")
    scene.attempt(world.db_path, post_id, "youtube", status="failed")

    assert link_of(world, post_id) == RemoteLink(None, "no_succeeded_attempt")


def test_a_post_of_another_remote_identity_is_not_accessible(
    world: YouTubeWorld,
) -> None:
    # The account was reconnected to another channel after publishing.
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1", identity="UC-OLD")

    assert link_of(world, post_id) == RemoteLink(None, "remote_identity_changed")
    with world.session_factory() as session:
        publication = session.get(Publication, post_id)
        assert publication is not None
        checked = eligibility(session, publication)
    assert not checked.refreshable
    assert checked.reason == "remote_identity_changed"


def test_an_unknown_publishing_identity_never_concludes_a_change(
    world: YouTubeWorld,
) -> None:
    owner = world.youtube_account()
    post_id = scene.published(world.db_path, owner, "VIDEO-1", identity=None)

    assert link_of(world, post_id) == RemoteLink("VIDEO-1", None)


def test_only_the_succeeded_attempt_id_counts(world: YouTubeWorld) -> None:
    owner = world.youtube_account()
    post_id = readmodels.post(world.db_path, owner, NOW, status="published")
    earlier = NOW - timedelta(hours=1)
    scene.attempt(
        world.db_path,
        post_id,
        "youtube",
        status="failed",
        external_id="ORPHAN",
        started_at=earlier,
    )
    scene.attempt(world.db_path, post_id, "youtube", external_id="VIDEO-OK")

    assert link_of(world, post_id) == RemoteLink("VIDEO-OK", None)


@pytest.mark.parametrize(
    ("platform", "reason"),
    [
        ("tiktok", "not_supported"),
        ("telegram", "not_supported"),
        ("threads", "permission_required"),
    ],
)
def test_a_linked_post_of_an_unreadable_platform_is_not_refreshable(
    world: YouTubeWorld, platform: str, reason: str
) -> None:
    owner = scene.account(world.db_path, scene.project(world.db_path), platform)
    post_id = scene.published(world.db_path, owner, "REMOTE-1")

    with world.session_factory() as session:
        publication = session.get(Publication, post_id)
        assert publication is not None
        checked = eligibility(session, publication)
    assert checked.link.linked
    assert not checked.refreshable
    assert checked.reason == reason
