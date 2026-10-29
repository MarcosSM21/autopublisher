"""GET /api/projects/{id}/analytics/posts and GET /api/publications/{id}/analytics
(Feature 027 T059, contracts/analytics-api.md §Posts list).

Rows are written straight to SQLite; nothing contacts a platform.
"""

import sqlite3
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

ROW_KEYS = {
    "publication_id",
    "content_id",
    "content_type",
    "title",
    "platform",
    "account_id",
    "account_label",
    "published_at",
    "age_days",
    "remote_url",
    "link_state",
    "not_linked_reason",
    "capability_state",
    "metrics",
    "engagement",
    "refresh",
    "captured_at",
    "ranked",
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
    status: str = "connected",
) -> dict[str, Any]:
    account = create_account(client, project["id"], platform, handle)
    readmodels.connect(db_path, account, scene.NOW, status=status)
    return account


def snapshot(
    db_path: Path,
    post_id: int,
    captured_at: datetime,
    values: dict[str, int],
    origin: str = "public_counter",
) -> None:
    snapshot_id = readmodels.insert(
        db_path,
        "metric_snapshots",
        publication_id=post_id,
        platform="youtube",
        remote_id="VIDEO-1",
        captured_at=captured_at,
        source="youtube.videos.list:statistics",
        trigger="automatic",
    )
    for name, value in values.items():
        readmodels.insert(
            db_path,
            "metric_values",
            snapshot_id=snapshot_id,
            metric_name=name,
            value=value,
            origin=origin,
        )


def state(db_path: Path, post_id: int, **values: Any) -> None:
    readmodels.insert(
        db_path,
        "publication_metric_states",
        publication_id=post_id,
        failure_count=values.pop("failure_count", 0),
        **values,
    )


def rows(client: TestClient, project_id: int, **params: Any) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/analytics/posts", params=params)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def by_id(rows_: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {row["publication_id"]: row for row in rows_}


def metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {m["name"]: (m["value"], m["available"]) for m in row["metrics"]}


def test_a_row_carries_the_latest_valid_reading(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    post = scene.published(
        db_path, owner, "VIDEO-1", published_at=now - timedelta(days=3)
    )
    snapshot(db_path, post, now - timedelta(days=2), {"viewCount": 1})
    snapshot(
        db_path,
        post,
        now - timedelta(hours=5),
        {"viewCount": 200, "likeCount": 0, "commentCount": 10},
    )
    # A later failure keeps the reading.
    state(
        db_path,
        post,
        status="stale",
        last_success_at=now - timedelta(hours=5),
        last_attempt_at=now - timedelta(minutes=5),
        error_code="refresh_failed",
        error_message="Could not read the metrics.",
        failure_count=1,
    )

    [row] = rows(client, project["id"])

    assert set(row) == ROW_KEYS
    assert row["platform"] == "youtube"
    assert row["account_label"] == "YouTube @cyber"
    assert row["content_type"] == "text"
    assert row["age_days"] == 3
    assert row["link_state"] == "linked" and row["not_linked_reason"] is None
    assert row["capability_state"] == "supported"
    assert datetime.fromisoformat(row["captured_at"]) == now - timedelta(hours=5)
    # Every read metric is listed; a real 0 is a value; dislikes only if returned.
    assert metrics(row) == {
        "viewCount": (200, True),
        "likeCount": (0, True),
        "commentCount": (10, True),
    }
    viewcount = row["metrics"][0]
    assert viewcount["concept"] == "views" and viewcount["origin"] == "public_counter"
    assert "2026-08-24" in viewcount["definition"]
    assert row["engagement"] == {
        "available": True,
        "value": pytest.approx(0.05),
        "formula": "(likeCount + commentCount) / viewCount",
        "components": {"likeCount": 0, "commentCount": 10, "viewCount": 200},
    }
    refresh = row["refresh"]
    assert refresh["status"] == "stale"
    assert refresh["error_code"] == "refresh_failed"
    assert refresh["manual_pending"] is False
    assert datetime.fromisoformat(refresh["cooldown_until"]) == now + timedelta(
        minutes=10
    )


def test_an_absent_metric_is_not_available_never_zero(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    post = scene.published(db_path, owner, "VIDEO-1", published_at=now)
    snapshot(db_path, post, now, {"viewCount": 0, "dislikeCount": 2})

    [row] = rows(client, project["id"])

    assert metrics(row) == {
        "viewCount": (0, True),
        "likeCount": (None, False),
        "commentCount": (None, False),
        "dislikeCount": (2, True),
    }
    assert row["engagement"]["available"] is False
    assert row["engagement"]["value"] is None


def test_engagement_needs_views(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    post = scene.published(db_path, owner, "VIDEO-1", published_at=now)
    snapshot(db_path, post, now, {"viewCount": 0, "likeCount": 0, "commentCount": 0})

    [row] = rows(client, project["id"])

    assert row["engagement"]["available"] is False
    assert row["engagement"]["components"]["viewCount"] == 0


def test_instagram_lists_its_counters_without_engagement(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "instagram")
    post = scene.published(db_path, owner, "IG-1", published_at=now)
    # Likes hidden by the owner.
    snapshot(db_path, post, now, {"comments_count": 4})

    [row] = rows(client, project["id"])

    assert metrics(row) == {
        "like_count": (None, False),
        "comments_count": (4, True),
    }
    assert row["engagement"] is None
    assert row["capability_state"] == "supported"


def test_a_never_read_post_is_pending_or_has_no_state(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    recent = scene.published(db_path, owner, "V1", published_at=now)
    old = scene.published(db_path, owner, "V2", published_at=now - timedelta(days=200))

    found = by_id(rows(client, project["id"]))

    assert found[recent]["refresh"]["status"] == "pending"
    assert found[recent]["captured_at"] is None
    assert metrics(found[recent]) == {
        "viewCount": (None, False),
        "likeCount": (None, False),
        "commentCount": (None, False),
    }
    # Older than 90 days and never asked for: no refresh state.
    assert found[old]["refresh"] is None


@pytest.mark.parametrize(
    ("platform", "external_id", "options", "capability", "reason"),
    [
        ("youtube", None, {}, "supported", "remote_id_missing"),
        (
            "youtube",
            "V1",
            {"identity": "UC-OLD"},
            "supported",
            "remote_identity_changed",
        ),
        (
            "instagram",
            None,
            {"warnings": [{"code": "remote_identity_unavailable", "message": "m"}]},
            "supported",
            "remote_identity_unavailable",
        ),
        ("threads", "TH-1", {}, "permission_required", None),
        ("tiktok", "TT-1", {}, "not_supported", None),
        ("telegram", "42", {}, "not_supported", None),
    ],
)
def test_posts_without_metrics_explain_why(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    now: datetime,
    platform: str,
    external_id: str | None,
    options: dict[str, Any],
    capability: str,
    reason: str | None,
) -> None:
    owner = connected(client, db_path, project, platform)
    scene.published(db_path, owner, external_id, published_at=now, **options)

    [row] = rows(client, project["id"])

    assert row["capability_state"] == capability
    assert row["not_linked_reason"] == reason
    assert row["link_state"] == ("not_linked" if reason else "linked")
    assert row["refresh"] is None
    assert all(not m["available"] for m in row["metrics"])
    if platform in ("threads", "tiktok", "telegram"):
        assert row["metrics"] == []


def test_a_disconnected_account_keeps_its_last_reading(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube", status="reconnect_required")
    post = scene.published(db_path, owner, "VIDEO-1", published_at=now)
    snapshot(db_path, post, now - timedelta(hours=1), {"viewCount": 7})
    state(
        db_path,
        post,
        status="reconnect_required",
        last_success_at=now - timedelta(hours=1),
        last_attempt_at=now - timedelta(hours=1),
        error_code="reconnect_required",
        error_message="Reconnect the account.",
    )

    [row] = rows(client, project["id"])

    assert row["capability_state"] == "reconnect_required"
    assert row["refresh"]["status"] == "reconnect_required"
    assert metrics(row)["viewCount"] == (7, True)


def test_rows_have_content_types_and_remote_links(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    image = import_one(client, project["id"], "a.png", make_image())["content"]
    video = import_one(client, project["id"], "b.mp4", make_mp4())["content"]
    posts = {}
    for name, content in (("image", image), ("video", video)):
        post = media_post(db_path, owner, content["id"], now, status="published")
        scene.attempt(db_path, post, "youtube", external_id=f"V-{name}")
        posts[name] = post
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE publication_attempts SET external_url = 'https://youtu.be/x' "
            "WHERE publication_id = ?",
            (posts["video"],),
        )

    found = by_id(rows(client, project["id"]))

    assert found[posts["image"]]["content_type"] == "image"
    assert found[posts["video"]]["content_type"] == "video"
    assert found[posts["video"]]["remote_url"] == "https://youtu.be/x"
    assert found[posts["image"]]["remote_url"] is None
    assert found[posts["image"]]["title"] == "a.png"


def test_only_published_posts_newest_first_and_filters(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    older = scene.published(
        db_path, youtube, "V1", published_at=now - timedelta(days=5)
    )
    newer = scene.published(
        db_path, instagram, "IG", published_at=now - timedelta(days=1)
    )
    readmodels.post(db_path, youtube, now, status="unscheduled")
    other = create_project(client, "Other")
    scene.published(db_path, connected(client, db_path, other, "youtube", "o"), "V9")

    assert [r["publication_id"] for r in rows(client, project["id"])] == [newer, older]
    assert [
        r["publication_id"] for r in rows(client, project["id"], platform="youtube")
    ] == [older]
    assert [
        r["publication_id"]
        for r in rows(client, project["id"], account_id=instagram["id"])
    ] == [newer]
    day = (now - timedelta(days=5)).date().isoformat()
    assert [
        r["publication_id"]
        for r in rows(client, project["id"], published_from=day, published_to=day)
    ] == [older]


def test_there_are_no_aggregates(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    instagram = connected(client, db_path, project, "instagram", "cyber.ig")
    for owner, remote in ((youtube, "V1"), (instagram, "IG")):
        post = scene.published(db_path, owner, remote, published_at=now)
        snapshot(db_path, post, now, {"likeCount": 3, "like_count": 4})

    response = client.get(f"/api/projects/{project['id']}/analytics/posts")

    # A plain list of rows: no wrapper with totals, averages or rankings, and no
    # row field mixes posts or platforms.
    body = response.json()
    assert isinstance(body, list) and len(body) == 2
    assert all(set(row) == ROW_KEYS for row in body)
    assert [len(row["metrics"]) for row in body] == [2, 3]


def test_unknown_project_and_bad_filters(client: TestClient) -> None:
    assert client.get("/api/projects/999/analytics/posts").status_code == 404
    project = create_project(client, "Cyber")
    response = client.get(
        f"/api/projects/{project['id']}/analytics/posts", params={"platform": "myspace"}
    )
    assert response.status_code == 422


def test_one_publication(
    client: TestClient, db_path: Path, project: dict[str, Any], now: datetime
) -> None:
    owner = connected(client, db_path, project, "youtube")
    post = scene.published(db_path, owner, "VIDEO-1", published_at=now)
    snapshot(db_path, post, now, {"viewCount": 5})
    draft = readmodels.post(db_path, owner, now, status="unscheduled")

    response = client.get(f"/api/publications/{post}/analytics")
    assert response.status_code == 200
    assert set(response.json()) == ROW_KEYS
    assert metrics(response.json())["viewCount"] == (5, True)
    assert client.get(f"/api/publications/{draft}/analytics").status_code == 404
    assert client.get("/api/publications/999/analytics").status_code == 404
