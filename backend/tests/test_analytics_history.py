"""History of one post: GET /api/publications/{id}/analytics `history` and
`series` (Feature 027 T088, contracts/analytics-api.md §One publication, FR-023).

Only real snapshots, oldest first; a reading without a metric adds no point
(never 0, never interpolated); engagement uses each reading's own components.
Rows are written straight to SQLite.
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
    client: TestClient, db_path: Path, project: dict[str, Any], platform: str
) -> dict[str, Any]:
    account = create_account(client, project["id"], platform, "cyber")
    readmodels.connect(db_path, account, scene.NOW)
    return account


def read(
    db_path: Path,
    post_id: int,
    platform: str,
    at: datetime,
    values: dict[str, int],
    trigger: str = "automatic",
) -> int:
    snapshot_id = readmodels.insert(
        db_path,
        "metric_snapshots",
        publication_id=post_id,
        platform=platform,
        remote_id="REMOTE-1",
        captured_at=at,
        source=f"{platform}.test",
        trigger=trigger,
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
    return snapshot_id


def analytics(client: TestClient, post_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{post_id}/analytics")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def series(body: dict[str, Any]) -> dict[str, list[tuple[int, float]]]:
    """Each series as (reading index, value)."""
    return {
        s["name"]: [(p["reading"], p["value"]) for p in s["points"]]
        for s in body["series"]
    }


def test_youtube_history_is_every_real_reading_oldest_first(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    post = scene.published(db_path, owner, published_at=now - timedelta(days=5))
    second_at = now - timedelta(days=2, seconds=7)
    # Written out of order; a tie on captured_at keeps the id order.
    third = read(
        db_path,
        post,
        "youtube",
        now - timedelta(days=1),
        {"viewCount": 300, "likeCount": 9, "commentCount": 1},
        trigger="manual",
    )
    first = read(
        db_path,
        post,
        "youtube",
        now - timedelta(days=4),
        {"viewCount": 0, "likeCount": 0, "commentCount": 0},
    )
    # Comments disabled in this reading only.
    second = read(
        db_path, post, "youtube", second_at, {"viewCount": 100, "likeCount": 4}
    )
    tie = read(
        db_path,
        post,
        "youtube",
        now - timedelta(days=1),
        {"viewCount": 310, "likeCount": 9, "commentCount": 1, "dislikeCount": 3},
    )

    body = analytics(client, post)

    history = body["history"]
    assert [h["snapshot_id"] for h in history] == [first, second, third, tie]
    # Exact timestamps, kept to the second.
    assert datetime.fromisoformat(history[1]["captured_at"]) == second_at
    assert history[2]["trigger"] == "manual"
    assert history[2]["source"] == "youtube.test"
    assert history[2]["remote_id"] == "REMOTE-1"
    assert {v["name"]: v["value"] for v in history[1]["values"]} == {
        "viewCount": 100,
        "likeCount": 4,
    }
    assert history[0]["values"][0]["concept"] in {"comments", "likes", "views"}
    assert series(body) == {
        # A real 0 is a point; a missing comment count is no point at all.
        "viewCount": [(0, 0), (1, 100), (2, 300), (3, 310)],
        "likeCount": [(0, 0), (1, 4), (2, 9), (3, 9)],
        "commentCount": [(0, 0), (2, 1), (3, 1)],
        # Only seen once: a single real point.
        "dislikeCount": [(3, 3)],
        # Per reading, from that reading only: views 0 and missing comments
        # leave no point; nothing is combined across readings.
        "engagement": [(2, pytest.approx(10 / 300)), (3, pytest.approx(10 / 310))],
    }
    views = body["series"][0]
    assert views["concept"] == "views" and "2026-08-24" in views["definition"]
    engagement = body["series"][-1]
    assert engagement["derived"] is True
    assert "(likeCount + commentCount) / viewCount" in engagement["definition"]
    assert history[0]["engagement"]["available"] is False
    assert history[1]["engagement"]["components"]["commentCount"] is None
    # Exactly one point per reading that has the metric: none generated.
    total_points = sum(len(s["points"]) for s in body["series"] if not s["derived"])
    assert total_points == sum(len(h["values"]) for h in history)


def test_instagram_history_without_engagement_and_with_hidden_likes(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "instagram")
    post = scene.published(db_path, owner, "IG-1", published_at=now - timedelta(days=3))
    read(db_path, post, "instagram", now - timedelta(days=2), {"comments_count": 2})
    read(
        db_path,
        post,
        "instagram",
        now - timedelta(days=1),
        {"like_count": 15, "comments_count": 2},
    )

    body = analytics(client, post)

    assert series(body) == {
        "like_count": [(1, 15)],
        "comments_count": [(0, 2), (1, 2)],
    }
    assert all(h["engagement"] is None for h in body["history"])


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("stale", {"error_code": "refresh_failed"}),
        ("remote_deleted", {"error_code": "remote_deleted"}),
    ],
)
def test_history_stays_whatever_the_current_refresh_state(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    now: datetime,
    status: str,
    extra: dict[str, Any],
) -> None:
    owner = connected(client, db_path, project, "youtube")
    post = scene.published(db_path, owner, published_at=now - timedelta(days=3))
    read(db_path, post, "youtube", now - timedelta(days=2), {"viewCount": 5})
    read(db_path, post, "youtube", now - timedelta(days=1), {"viewCount": 8})
    readmodels.insert(
        db_path,
        "publication_metric_states",
        publication_id=post,
        status=status,
        failure_count=2,
        last_attempt_at=now - timedelta(minutes=1),
        **extra,
    )

    body = analytics(client, post)

    assert body["refresh"]["status"] == status
    assert series(body)["viewCount"] == [(0, 5), (1, 8)]


def test_one_reading_and_no_reading(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    once = scene.published(db_path, owner, "V-1", published_at=now - timedelta(days=1))
    read(db_path, once, "youtube", now, {"viewCount": 3})
    never = scene.published(db_path, owner, "V-2", published_at=now)

    assert series(analytics(client, once)) == {"viewCount": [(0, 3)]}
    body = analytics(client, never)
    assert body["history"] == [] and body["series"] == []


def test_the_latest_reading_is_the_newest_capture_not_the_newest_row(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    post = scene.published(db_path, owner, published_at=now - timedelta(days=3))
    read(db_path, post, "youtube", now - timedelta(hours=1), {"viewCount": 50})
    # Stored later, but captured earlier.
    read(db_path, post, "youtube", now - timedelta(days=2), {"viewCount": 10})

    body = analytics(client, post)
    [row] = client.get(f"/api/projects/{project['id']}/analytics/posts").json()

    assert series(body)["viewCount"] == [(0, 10), (1, 50)]
    for latest in (body, row):
        assert datetime.fromisoformat(latest["captured_at"]) == now - timedelta(hours=1)
        assert latest["metrics"][0]["value"] == 50
