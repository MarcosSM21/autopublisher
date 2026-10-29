"""Rankings: GET /api/projects/{id}/analytics/posts with `sort` (Feature 027 T070,
contracts/analytics-api.md §Posts list, FR-020).

A ranking always stays within one platform, sorts by one of its metrics only, and
never turns a missing metric into 0. Rows are written straight to SQLite.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import analytics_support as scene
from tests import readmodels
from tests.conftest import create_account, create_project
from tests.fakes import FakeClock


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


def post(
    db_path: Path,
    owner: dict[str, Any],
    published_at: datetime,
    values: dict[str, int] | None,
) -> int:
    """A published post with one reading (`None`: never read)."""
    post_id = scene.published(
        db_path, owner, f"R-{published_at.isoformat()}", published_at=published_at
    )
    if values is not None:
        snapshot_id = readmodels.insert(
            db_path,
            "metric_snapshots",
            publication_id=post_id,
            platform=owner["platform"],
            remote_id="R",
            captured_at=published_at + timedelta(hours=1),
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
    return post_id


def ranking(
    client: TestClient, project_id: int, **params: Any
) -> list[tuple[int, bool | None]]:
    response = client.get(f"/api/projects/{project_id}/analytics/posts", params=params)
    assert response.status_code == 200, response.text
    return [(row["publication_id"], row["ranked"]) for row in response.json()]


def error(client: TestClient, project_id: int, **params: Any) -> tuple[int, str]:
    response = client.get(f"/api/projects/{project_id}/analytics/posts", params=params)
    return response.status_code, response.json()["error"]["code"]


@pytest.mark.parametrize(
    ("sort", "order", "expected"),
    [
        # A real 0 is ranked; ties keep the newest publication first.
        ("viewCount", "desc", ["big", "tie_new", "tie_old", "zero"]),
        ("viewCount", "asc", ["zero", "tie_new", "tie_old", "big"]),
        ("likeCount", "desc", ["tie_new", "big", "zero"]),
        ("commentCount", "desc", ["big", "tie_new", "tie_old", "zero"]),
    ],
)
def test_youtube_ranking_by_one_metric(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    now: datetime,
    sort: str,
    order: str,
    expected: list[str],
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")

    def days(n: int) -> datetime:
        return now - timedelta(days=n)

    posts = {
        "big": post(
            db_path,
            youtube,
            days(9),
            {"viewCount": 900, "likeCount": 5, "commentCount": 9},
        ),
        "tie_old": post(
            db_path, youtube, days(5), {"viewCount": 50, "commentCount": 3}
        ),
        "tie_new": post(
            db_path,
            youtube,
            days(2),
            {"viewCount": 50, "likeCount": 7, "commentCount": 3},
        ),
        "zero": post(
            db_path,
            youtube,
            days(1),
            {"viewCount": 0, "likeCount": 0, "commentCount": 0},
        ),
        "unread": post(db_path, youtube, days(3), None),
    }
    # Another platform is never part of a YouTube ranking.
    post(db_path, instagram, days(1), {"like_count": 10_000})
    names = {post_id: name for name, post_id in posts.items()}

    result = ranking(client, project["id"], platform="youtube", sort=sort, order=order)

    ranked = [names[pid] for pid, flag in result if flag]
    unranked = [names[pid] for pid, flag in result if flag is False]
    assert ranked == expected
    # Without the metric: listed after the ranked ones, newest first, never as 0.
    newest_first = ["zero", "tie_new", "unread", "tie_old", "big"]
    assert unranked == [name for name in newest_first if name not in expected]
    assert len(result) == len(posts)


def test_engagement_ranks_only_posts_where_it_can_be_computed(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    high = post(
        db_path,
        youtube,
        now - timedelta(days=4),
        {"viewCount": 100, "likeCount": 8, "commentCount": 2},
    )
    low = post(
        db_path,
        youtube,
        now - timedelta(days=3),
        {"viewCount": 1000, "likeCount": 10, "commentCount": 0},
    )
    no_comments = post(
        db_path, youtube, now - timedelta(days=2), {"viewCount": 10, "likeCount": 9}
    )
    no_views = post(
        db_path,
        youtube,
        now - timedelta(days=1),
        {"viewCount": 0, "likeCount": 1, "commentCount": 1},
    )

    result = ranking(client, project["id"], platform="youtube", sort="engagement")

    assert result == [
        (high, True),
        (low, True),
        (no_views, False),
        (no_comments, False),
    ]


def test_instagram_ranking_by_its_counters(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    instagram = connected(client, db_path, project, "instagram")
    first = post(
        db_path,
        instagram,
        now - timedelta(days=2),
        {"like_count": 3, "comments_count": 40},
    )
    second = post(
        db_path,
        instagram,
        now - timedelta(days=1),
        {"like_count": 30, "comments_count": 4},
    )

    assert ranking(client, project["id"], platform="instagram", sort="like_count") == [
        (second, True),
        (first, True),
    ]
    assert ranking(
        client, project["id"], platform="instagram", sort="comments_count"
    ) == [(first, True), (second, True)]
    # Instagram has no views without insights and no engagement formula.
    for sort in ("engagement", "viewCount", "views"):
        status, code = error(client, project["id"], platform="instagram", sort=sort)
        assert (status, code) == (422, "validation_error")


def test_a_ranking_requires_one_platform_and_its_own_account(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    other_project = create_project(client, "Other")
    foreign = connected(client, db_path, other_project, "youtube", "other")

    for params in (
        {"sort": "viewCount"},
        {"sort": "viewCount", "account_id": youtube["id"]},
        {"sort": "viewCount", "platform": "youtube", "account_id": instagram["id"]},
        {"sort": "viewCount", "platform": "youtube", "account_id": foreign["id"]},
        {"sort": "viewCount", "platform": "youtube", "account_id": 999_999},
    ):
        assert error(client, project["id"], **params) == (
            422,
            "ranking_requires_single_platform",
        ), params


def test_a_ranking_by_account_and_publication_period(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    main = connected(client, db_path, project, "youtube", "main")
    second = connected(client, db_path, project, "youtube", "second")
    old = post(db_path, main, now - timedelta(days=40), {"viewCount": 999})
    recent = post(db_path, main, now - timedelta(days=2), {"viewCount": 5})
    post(db_path, second, now - timedelta(days=2), {"viewCount": 500})

    assert ranking(
        client,
        project["id"],
        platform="youtube",
        account_id=main["id"],
        sort="viewCount",
    ) == [(old, True), (recent, True)]
    # The period is about publication dates (inclusive UTC days).
    since = (now - timedelta(days=7)).date().isoformat()
    assert ranking(
        client,
        project["id"],
        platform="youtube",
        account_id=main["id"],
        sort="viewCount",
        published_from=since,
    ) == [(recent, True)]
    assert (
        ranking(
            client,
            project["id"],
            platform="youtube",
            sort="viewCount",
            published_to=(now - timedelta(days=60)).date().isoformat(),
        )
        == []
    )


def test_a_ranking_uses_the_last_valid_reading_after_a_failure(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    kept = post(db_path, youtube, now - timedelta(days=3), {"viewCount": 70})
    fresh = post(db_path, youtube, now - timedelta(days=2), {"viewCount": 20})
    readmodels.insert(
        db_path,
        "publication_metric_states",
        publication_id=kept,
        status="stale",
        failure_count=1,
        last_attempt_at=now - timedelta(minutes=1),
        error_code="refresh_failed",
    )

    assert ranking(client, project["id"], platform="youtube", sort="viewCount") == [
        (kept, True),
        (fresh, True),
    ]


def test_without_sort_rows_are_not_a_ranking(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    post(db_path, youtube, now - timedelta(days=1), {"viewCount": 1})
    post(db_path, instagram, now, {"like_count": 1})

    result = ranking(client, project["id"])

    assert [flag for _, flag in result] == [None, None]
