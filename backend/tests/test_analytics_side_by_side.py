"""GET /api/contents/{id}/analytics (Feature 027 T080, contracts/analytics-api.md
§Side by side, FR-009, FR-022).

Publications of one media line up likes and comments with their original names;
every other metric stays with its own publication. Nothing is summed, averaged,
ordered or marked as best. Rows are written straight to SQLite.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import analytics_support as scene
from tests import readmodels
from tests.conftest import (
    create_account,
    create_project,
    import_one,
    make_image,
    make_mp4,
)
from tests.fakes import FakeClock
from tests.test_delete_media import media_post

FORBIDDEN_KEYS = {
    "winner",
    "best",
    "best_platform",
    "difference",
    "percentage_difference",
    "total",
    "totals",
    "total_views",
    "total_engagement",
    "average",
    "rank",
    "ranked",
    "score",
}


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


@pytest.fixture
def now(fake_clock: FakeClock) -> datetime:
    return fake_clock.now()


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


def connected(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    platform: str,
    handle: str = "cyber",
) -> dict[str, Any]:
    account = create_account(client, project["id"], platform, handle)
    readmodels.connect(db_path, account, scene.NOW)
    return account


def published(
    db_path: Path,
    owner: dict[str, Any],
    content_id: int,
    published_at: datetime,
    *,
    external_id: str | None = "REMOTE",
    identity: str = scene.CONNECTED,
) -> int:
    """A published post of the media whose succeeded attempt has `external_id`."""
    post_id = media_post(db_path, owner, content_id, published_at, status="published")
    submitted = {}
    if owner["platform"] in scene.IDENTITY_KEYS:
        key, connected_identity = scene.IDENTITY_KEYS[owner["platform"]]
        submitted[key] = (
            connected_identity.format(owner["id"])
            if identity == scene.CONNECTED
            else identity
        )
    scene.attempt(
        db_path,
        post_id,
        owner["platform"],
        external_id=external_id,
        started_at=published_at,
        submitted=submitted,
    )
    return post_id


def read(
    db_path: Path, post_id: int, platform: str, at: datetime, values: dict[str, int]
) -> None:
    snapshot_id = readmodels.insert(
        db_path,
        "metric_snapshots",
        publication_id=post_id,
        platform=platform,
        remote_id="REMOTE",
        captured_at=at,
        source="test",
        trigger="automatic",
    )
    for name, value in values.items():
        readmodels.insert(
            db_path,
            "metric_values",
            snapshot_id=snapshot_id,
            metric_name=name,
            value=value,
            origin="public_counter",
        )


def side_by_side(client: TestClient, content_id: int) -> dict[str, Any]:
    response = client.get(f"/api/contents/{content_id}/analytics")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def keys(value: Any) -> set[str]:
    """Every key anywhere in the response."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def cells(body: dict[str, Any], concept: str) -> list[tuple[Any, ...]]:
    [row] = [row for row in body["aligned"] if row["concept"] == concept]
    return [
        (cell["platform"], cell["metric_name"], cell["value"], cell["available"])
        for cell in row["cells"]
    ]


def own_metrics(body: dict[str, Any], platform: str) -> dict[str, Any]:
    [publication] = [p for p in body["per_platform"] if p["platform"] == platform]
    return {m["name"]: (m["value"], m["available"]) for m in publication["metrics"]}


def test_youtube_and_instagram_align_only_likes_and_comments(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    video = import_one(client, project["id"], "a.mp4", make_mp4())["content"]
    on_youtube = published(db_path, youtube, video["id"], now - timedelta(days=3))
    on_instagram = published(db_path, instagram, video["id"], now - timedelta(days=2))
    read(
        db_path,
        on_youtube,
        "youtube",
        now - timedelta(hours=1),
        {"viewCount": 500, "likeCount": 0, "commentCount": 7, "dislikeCount": 2},
    )
    # Instagram hides likes on this post: like_count absent, never 0.
    read(
        db_path,
        on_instagram,
        "instagram",
        now - timedelta(hours=2),
        {"comments_count": 3},
    )
    # The same caption on another media is not "the same content".
    other = import_one(client, project["id"], "b.png", make_image())["content"]
    published(db_path, instagram, other["id"], now - timedelta(days=2))

    body = side_by_side(client, video["id"])

    assert body["content_id"] == video["id"]
    assert "Not quantitatively equivalent" in body["note"]
    assert [row["concept"] for row in body["aligned"]] == ["likes", "comments"]
    likes = body["aligned"][0]
    assert likes["label"] == "Likes" and likes["definition"]
    # Account order, original names, a real 0 next to "not available".
    assert cells(body, "likes") == [
        ("youtube", "likeCount", 0, True),
        ("instagram", "like_count", None, False),
    ]
    assert cells(body, "comments") == [
        ("youtube", "commentCount", 7, True),
        ("instagram", "comments_count", 3, True),
    ]
    assert all(cell["definition"] for cell in likes["cells"])
    # Views and platform-only metrics stay with their own publication.
    assert own_metrics(body, "youtube") == {
        "viewCount": (500, True),
        "dislikeCount": (2, True),
    }
    assert own_metrics(body, "instagram") == {}
    [yt, ig] = body["per_platform"]
    assert [yt["publication_id"], ig["publication_id"]] == [on_youtube, on_instagram]
    # Engagement only inside YouTube, with its own formula; never aligned.
    assert yt["engagement"]["available"] is True
    assert yt["engagement"]["value"] == pytest.approx(7 / 500)
    assert ig["engagement"] is None
    assert yt["account_label"] == "YouTube @cyber" and yt["age_days"] == 3
    assert datetime.fromisoformat(ig["captured_at"]) == now - timedelta(hours=2)
    assert not keys(body) & FORBIDDEN_KEYS


def test_publications_without_data_or_link_are_not_available(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    tiktok = connected(client, db_path, project, "tiktok", "cyber.tt")
    video = import_one(client, project["id"], "a.mp4", make_mp4())["content"]
    stale = published(db_path, youtube, video["id"], now - timedelta(days=5))
    read(db_path, stale, "youtube", now - timedelta(days=1), {"likeCount": 4})
    readmodels.insert(
        db_path,
        "publication_metric_states",
        publication_id=stale,
        status="stale",
        failure_count=1,
        last_success_at=now - timedelta(days=1),
        last_attempt_at=now - timedelta(minutes=1),
        error_code="refresh_failed",
    )
    # Published by another Instagram account than the one connected now.
    changed = published(
        db_path, instagram, video["id"], now - timedelta(days=4), identity="IG-OTHER"
    )
    published(db_path, tiktok, video["id"], now - timedelta(days=4), external_id=None)
    # Not published yet: not part of the view.
    media_post(db_path, youtube, video["id"], now, status="unscheduled")

    body = side_by_side(client, video["id"])

    assert cells(body, "likes") == [
        ("youtube", "likeCount", 4, True),
        ("instagram", "like_count", None, False),
        # TikTok metrics are not supported: no metric to line up, never 0.
        ("tiktok", None, None, False),
    ]
    [yt, ig, tt] = body["per_platform"]
    assert yt["refresh"]["status"] == "stale"
    assert datetime.fromisoformat(yt["captured_at"]) == now - timedelta(days=1)
    assert ig["publication_id"] == changed
    assert ig["link_state"] == "not_linked"
    assert ig["not_linked_reason"] == "remote_identity_changed"
    assert ig["captured_at"] is None
    assert tt["capability_state"] == "not_supported"
    assert tt["metrics"] == [] and tt["engagement"] is None


def test_a_single_publication_is_still_a_view(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    instagram = connected(client, db_path, project, "instagram")
    image = import_one(client, project["id"], "a.png", make_image())["content"]
    post = published(db_path, instagram, image["id"], now - timedelta(days=1))
    read(db_path, post, "instagram", now, {"like_count": 9, "comments_count": 0})

    body = side_by_side(client, image["id"])

    assert [p["publication_id"] for p in body["per_platform"]] == [post]
    assert cells(body, "likes") == [("instagram", "like_count", 9, True)]
    assert cells(body, "comments") == [("instagram", "comments_count", 0, True)]


def test_an_unpublished_media_has_an_empty_view_and_a_missing_one_is_404(
    client: TestClient, project: dict[str, Any]
) -> None:
    image = import_one(client, project["id"], "a.png", make_image())["content"]

    body = side_by_side(client, image["id"])

    assert body["aligned"] == [] and body["per_platform"] == []
    response = client.get("/api/contents/999999/analytics")
    assert response.status_code == 404
