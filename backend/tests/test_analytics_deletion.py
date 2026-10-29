"""Analytics rows go with their post (Feature 027 T014, FR-005, research D4).

Deleting a post, a media, an account or a project deletes the snapshots, values and
refresh states of its posts, and leaves every other post's analytics intact.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import readmodels
from tests.conftest import create_account, create_project, import_one, make_image
from tests.fakes import FakeClock
from tests.test_delete_media import media_post
from tests.test_delete_post import count

TABLES = ("metric_snapshots", "metric_values", "publication_metric_states")


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


def with_analytics(db_path: Path, post_id: int, now: datetime) -> None:
    """Two snapshots with values (one of them 0) and a refresh state."""
    for views in (0, 12):
        snapshot = readmodels.insert(
            db_path,
            "metric_snapshots",
            publication_id=post_id,
            platform="youtube",
            remote_id=f"VIDEO-{post_id}",
            captured_at=now,
            source="youtube.videos.list:statistics",
            trigger="automatic",
        )
        for name, value in (("viewCount", views), ("likeCount", 1)):
            readmodels.insert(
                db_path,
                "metric_values",
                snapshot_id=snapshot,
                metric_name=name,
                value=value,
                origin="public_counter",
            )
    readmodels.insert(
        db_path,
        "publication_metric_states",
        publication_id=post_id,
        status="ok",
        last_success_at=now,
        last_attempt_at=now,
        failure_count=0,
    )


def analytics_of(db_path: Path, post_id: int) -> tuple[int, int, int]:
    return (
        count(db_path, "metric_snapshots", "publication_id = ?", post_id),
        count(
            db_path,
            "metric_values",
            "snapshot_id IN (SELECT id FROM metric_snapshots WHERE publication_id = ?)",
            post_id,
        ),
        count(db_path, "publication_metric_states", "publication_id = ?", post_id),
    )


def confirmed_delete(client: TestClient, path: str) -> None:
    preview = client.get(f"{path}/deletion-preview")
    assert preview.status_code == 200, preview.text
    response = client.delete(
        path, params={"confirmation": preview.json()["confirmation"]}
    )
    assert response.status_code == 204, response.text


@pytest.fixture
def scene(client: TestClient, db_path: Path, fake_clock: FakeClock) -> dict[str, Any]:
    """Two projects; in the first, two accounts sharing one media, a published post
    of each plus a text post. Every published post has analytics."""
    now = fake_clock.now()
    project = create_project(client, "Cyber")
    other_project = create_project(client, "Other")
    main = create_account(client, project["id"], "youtube", "main")
    second = create_account(client, project["id"], "youtube", "second")
    elsewhere = create_account(client, other_project["id"], "youtube", "elsewhere")
    media = import_one(client, project["id"], "a.png", make_image())["content"]
    posts = {
        "main_media": media_post(db_path, main, media["id"], now, status="published"),
        "second_media": media_post(
            db_path, second, media["id"], now, status="published"
        ),
        "main_text": readmodels.post(db_path, main, now, status="published"),
        "second_text": readmodels.post(db_path, second, now, status="published"),
        "elsewhere": readmodels.post(db_path, elsewhere, now, status="published"),
    }
    for post_id in posts.values():
        with_analytics(db_path, post_id, now)
    return {
        "project": project,
        "accounts": {"main": main, "second": second},
        "media": media,
        "posts": posts,
    }


def assert_only_kept(db_path: Path, posts: dict[str, int], kept: set[str]) -> None:
    for name, post_id in posts.items():
        expected = (2, 4, 1) if name in kept else (0, 0, 0)
        assert analytics_of(db_path, post_id) == expected, name


def test_deleting_a_post_removes_its_analytics(
    client: TestClient, db_path: Path, scene: dict[str, Any]
) -> None:
    posts = scene["posts"]

    confirmed_delete(client, f"/api/publications/{posts['main_text']}")

    assert_only_kept(db_path, posts, set(posts) - {"main_text"})


def test_deleting_a_media_removes_the_analytics_of_its_published_posts(
    client: TestClient, db_path: Path, scene: dict[str, Any]
) -> None:
    posts = scene["posts"]

    confirmed_delete(client, f"/api/contents/{scene['media']['id']}")

    assert_only_kept(db_path, posts, {"main_text", "second_text", "elsewhere"})


def test_deleting_an_account_removes_the_analytics_of_its_posts(
    client: TestClient, db_path: Path, scene: dict[str, Any]
) -> None:
    posts = scene["posts"]

    confirmed_delete(client, f"/api/accounts/{scene['accounts']['main']['id']}")

    assert_only_kept(db_path, posts, {"second_media", "second_text", "elsewhere"})


def test_deleting_a_project_removes_the_analytics_of_its_posts(
    client: TestClient, db_path: Path, scene: dict[str, Any]
) -> None:
    posts = scene["posts"]

    confirmed_delete(client, f"/api/projects/{scene['project']['id']}")

    assert_only_kept(db_path, posts, {"elsewhere"})
    # Only the other project's post keeps rows: 2 snapshots, 4 values, 1 state.
    assert [count(db_path, table) for table in TABLES] == [2, 4, 1]
