"""GET /api/projects/{id}/analytics/content-types (Feature 027 T071,
contracts/analytics-api.md §Content-type summary, FR-021).

Medians per content type within one platform: over the posts that have each
metric (a real 0 counts, a missing metric does not), withheld below 3 posts.
Rows are written straight to SQLite.
"""

import itertools
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

_videos = itertools.count()


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


def read(db_path: Path, post_id: int, platform: str, values: dict[str, int]) -> None:
    snapshot_id = readmodels.insert(
        db_path,
        "metric_snapshots",
        publication_id=post_id,
        platform=platform,
        remote_id="R",
        captured_at=scene.NOW,
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


class Posts:
    """Published posts of one kind of content, with their readings."""

    def __init__(
        self, client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
    ) -> None:
        self.client, self.db_path, self.project, self.now = (
            client,
            db_path,
            project,
            now,
        )

    def add(
        self,
        owner: dict[str, Any],
        kind: str,
        values: dict[str, int] | None,
        days: int = 1,
    ) -> int:
        published_at = self.now - timedelta(days=days)
        if kind == "text":
            post_id = scene.published(
                self.db_path, owner, None, published_at=published_at
            )
        else:
            # Each import must be a new file (contents are unique per checksum).
            data = (
                make_image()
                if kind == "image"
                else make_mp4(payload=f"video-{next(_videos)}".encode())
            )
            name = "a.png" if kind == "image" else "b.mp4"
            content = import_one(self.client, self.project["id"], name, data)["content"]
            post_id = media_post(
                self.db_path, owner, content["id"], published_at, status="published"
            )
        if values is not None:
            read(self.db_path, post_id, owner["platform"], values)
        return post_id


def summary(
    client: TestClient, project_id: int, **params: Any
) -> dict[str, dict[str, Any]]:
    response = client.get(
        f"/api/projects/{project_id}/analytics/content-types", params=params
    )
    assert response.status_code == 200, response.text
    return {item["content_type"]: item for item in response.json()}


def medians(item: dict[str, Any]) -> dict[str, tuple[int, bool, float | None]]:
    return {
        m["name"]: (m["count"], m["insufficient_sample"], m["value"])
        for m in item["medians"]
    }


def test_medians_per_type_within_one_platform(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    posts = Posts(client, db_path, project, now)
    # Videos: odd sample for views, even one for likes (one post lacks likes),
    # comments with a real 0.
    for days, values in (
        (1, {"viewCount": 10, "likeCount": 1, "commentCount": 0}),
        (3, {"viewCount": 30, "likeCount": 3, "commentCount": 0}),
        (5, {"viewCount": 200, "likeCount": 9, "commentCount": 4}),
        (7, {"viewCount": 0, "commentCount": 2}),
        (9, {"viewCount": 50, "likeCount": 5, "commentCount": 6}),
    ):
        posts.add(youtube, "video", values, days)
    posts.add(youtube, "video", None, 2)  # never read
    # Images: only two with data.
    posts.add(youtube, "image", {"viewCount": 5, "likeCount": 1, "commentCount": 1})
    posts.add(youtube, "image", {"viewCount": 7, "likeCount": 2, "commentCount": 1})
    # Instagram videos never take part in YouTube's summary.
    for _ in range(3):
        posts.add(instagram, "video", {"like_count": 10_000, "comments_count": 1})

    found = summary(client, project["id"], platform="youtube")

    assert list(found) == ["image", "video"]
    video = found["video"]
    assert (video["posts_total"], video["posts_with_data"]) == (6, 5)
    assert video["insufficient_sample"] is False
    assert video["median_age_days"] == 5
    assert medians(video) == {
        "viewCount": (5, False, 30),
        "likeCount": (4, False, 4),  # (3 + 5) / 2
        "commentCount": (5, False, 2),
    }
    # Engagement only where computable (views 0 or likes missing are left out):
    # 0.1, 0.1, 0.065, 0.22 → median (0.1 + 0.1) / 2.
    assert video["engagement_median"] == {
        "count": 4,
        "insufficient_sample": False,
        "value": pytest.approx(0.1),
    }
    image = found["image"]
    assert (image["posts_total"], image["posts_with_data"]) == (2, 2)
    assert image["insufficient_sample"] is True
    assert medians(image) == {
        "viewCount": (2, True, None),
        "likeCount": (2, True, None),
        "commentCount": (2, True, None),
    }
    assert image["engagement_median"] == {
        "count": 2,
        "insufficient_sample": True,
        "value": None,
    }


def test_text_posts_and_instagram_without_engagement(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    posts = Posts(client, db_path, project, now)
    posts.add(youtube, "text", {"viewCount": 1})
    for likes in (4, 0, 8):
        posts.add(instagram, "image", {"like_count": likes, "comments_count": 1})

    youtube_summary = summary(client, project["id"], platform="youtube")
    instagram_summary = summary(client, project["id"], platform="instagram")

    assert list(youtube_summary) == ["text"]
    assert medians(youtube_summary["text"])["viewCount"] == (1, True, None)
    [image] = instagram_summary.values()
    assert image["content_type"] == "image" and image["posts_with_data"] == 3
    assert medians(image) == {
        "like_count": (3, False, 4),
        "comments_count": (3, False, 1),
    }
    assert image["engagement_median"] is None


def test_an_account_and_a_period_narrow_the_summary(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    main = connected(client, db_path, project, "youtube", "main")
    second = connected(client, db_path, project, "youtube", "second")
    posts = Posts(client, db_path, project, now)
    for views in (1, 2, 3):
        posts.add(main, "text", {"viewCount": views}, days=2)
    posts.add(main, "text", {"viewCount": 100}, days=40)
    posts.add(second, "text", {"viewCount": 1000}, days=2)

    by_account = summary(
        client, project["id"], platform="youtube", account_id=main["id"]
    )
    recent = summary(
        client,
        project["id"],
        platform="youtube",
        account_id=main["id"],
        published_from=(now - timedelta(days=7)).date().isoformat(),
    )
    empty = summary(
        client,
        project["id"],
        platform="youtube",
        published_to=(now - timedelta(days=90)).date().isoformat(),
    )

    assert medians(by_account["text"])["viewCount"] == (4, False, 2.5)
    assert medians(recent["text"])["viewCount"] == (3, False, 2)
    assert empty == {}


def test_an_account_without_readings_has_no_medians(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    posts = Posts(client, db_path, project, now)
    for _ in range(3):
        posts.add(youtube, "text", None)

    [text] = summary(client, project["id"], platform="youtube").values()

    assert (text["posts_total"], text["posts_with_data"]) == (3, 0)
    assert text["insufficient_sample"] is True
    assert text["median_age_days"] is None
    assert all(m["count"] == 0 and m["value"] is None for m in text["medians"])


def test_the_summary_requires_one_platform(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    instagram = connected(client, db_path, project, "instagram")
    path = f"/api/projects/{project['id']}/analytics/content-types"

    missing = client.get(path)
    mismatched = client.get(
        path, params={"platform": "youtube", "account_id": instagram["id"]}
    )

    assert missing.status_code == 422
    assert mismatched.status_code == 422
    assert mismatched.json()["error"]["code"] == "ranking_requires_single_platform"
    assert (
        client.get(
            "/api/projects/999999/analytics/content-types",
            params={"platform": "youtube"},
        ).status_code
        == 404
    )
