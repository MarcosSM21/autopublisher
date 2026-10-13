"""Publications without content (Feature 011, research.md §2): created for platforms
whose publisher accepts text-only posts, neutral everywhere else."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import Platform
from tests.conftest import (
    FUTURE,
    LATER,
    PAST,
    create_account,
    create_project,
    create_publications,
    create_text_publications,
    import_one,
    make_image,
    publish_and_wait,
    run_sql,
)
from tests.fakes import FakePublisher

TEXT = "Hello Threads https://example.com"


@pytest.fixture
def text_publisher() -> FakePublisher:
    return FakePublisher(accepts_text_only=True)


@pytest.fixture
def media_publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def text_client(
    client: TestClient, text_publisher: FakePublisher, media_publisher: FakePublisher
) -> Iterator[TestClient]:
    """Threads served by a text-capable fake; Instagram by one that needs media."""
    app = client.app
    assert isinstance(app, FastAPI)
    app.state.publishers[Platform.THREADS] = text_publisher
    app.state.publishers[Platform.INSTAGRAM] = media_publisher
    yield client


def _project_with(
    client: TestClient, *platforms: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    project = create_project(client, "Cyber")
    accounts = [
        create_account(client, project["id"], platform, f"cyber{index}")
        for index, platform in enumerate(platforms)
    ]
    return project, accounts


def _create(client: TestClient, project_id: int, **body: Any) -> Any:
    body.setdefault("account_ids", [])
    return client.post(f"/api/projects/{project_id}/text-publications", json=body)


def _queue(client: TestClient, project_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/publications")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items


# --- Creation ------------------------------------------------------------------------


def test_create_text_publication(text_client: TestClient) -> None:
    project, [account] = _project_with(text_client, "threads")

    response = create_text_publications(
        text_client,
        project["id"],
        [account["id"]],
        description=f"  {TEXT}  ",
        hashtags=["#cyber", "Cyber", "studio"],
    )

    assert response.status_code == 201, response.text
    [publication] = response.json()
    assert publication["content_id"] is None
    assert publication["content"] is None
    assert publication["status"] == "unscheduled"
    assert publication["title_override"] is None
    assert publication["description_override"] == TEXT
    assert publication["hashtags_override"] == ["cyber", "studio"]
    assert publication["title"] is None
    assert publication["description"] == TEXT
    assert publication["hashtags"] == ["cyber", "studio"]
    assert publication["account"]["platform"] == "threads"
    assert publication["auto_publish_enabled"] is False


def test_several_active_text_publications_per_account(text_client: TestClient) -> None:
    project, [account] = _project_with(text_client, "threads")

    first = create_text_publications(text_client, project["id"], [account["id"]])
    second = create_text_publications(text_client, project["id"], [account["id"]])

    assert first.status_code == second.status_code == 201
    assert first.json()[0]["id"] != second.json()[0]["id"]


def test_create_scheduled_and_armed_text_publication(text_client: TestClient) -> None:
    project, [account] = _project_with(text_client, "threads")

    response = create_text_publications(
        text_client,
        project["id"],
        [account["id"]],
        scheduled_at=FUTURE,
        auto_publish_enabled=True,
    )

    assert response.status_code == 201, response.text
    [publication] = response.json()
    assert publication["status"] == "scheduled"
    assert publication["scheduled_at"] == FUTURE
    assert publication["auto_publish_enabled"] is True


@pytest.mark.parametrize("platform", ["youtube", "instagram", "tiktok"])
def test_platforms_without_text_posts_are_rejected(
    text_client: TestClient, platform: str
) -> None:
    project, [threads, other] = _project_with(text_client, "threads", platform)

    response = create_text_publications(
        text_client, project["id"], [threads["id"], other["id"]]
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "text_publication_not_supported"
    assert [f["field"] for f in error["fields"]] == ["account_ids"]
    assert f"@{other['handle']}" in error["fields"][0]["message"]
    assert _queue(text_client, project["id"]) == []


def test_inactive_project_is_rejected(text_client: TestClient) -> None:
    project, [account] = _project_with(text_client, "threads")
    text_client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = create_text_publications(text_client, project["id"], [account["id"]])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_inactive"


def test_inactive_account_is_rejected(text_client: TestClient) -> None:
    project, [account] = _project_with(text_client, "threads")
    text_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})

    response = create_text_publications(text_client, project["id"], [account["id"]])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_inactive"


def test_account_of_another_project_is_rejected(text_client: TestClient) -> None:
    project, _ = _project_with(text_client, "threads")
    other = create_project(text_client, "Other")
    foreign = create_account(text_client, other["id"], "threads", "foreign")

    response = create_text_publications(text_client, project["id"], [foreign["id"]])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_project_is_not_found(text_client: TestClient) -> None:
    response = create_text_publications(text_client, 999, [1])

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"scheduled_at": PAST}, "scheduled_at"),
        ({"auto_publish_enabled": True}, "auto_publish_enabled"),
        ({"description": "x" * 5001}, "description"),
        ({"hashtags": ["two words"]}, "hashtags"),
        ({"unexpected": True}, "unexpected"),
    ],
)
def test_invalid_bodies_are_rejected(
    text_client: TestClient, body: dict[str, Any], field: str
) -> None:
    project, [account] = _project_with(text_client, "threads")

    response = _create(
        text_client,
        project["id"],
        **{"account_ids": [account["id"]], "description": "Hi", **body},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert field in {f["field"] for f in error["fields"]}


def test_account_ids_are_required(text_client: TestClient) -> None:
    project, _ = _project_with(text_client, "threads")

    response = _create(text_client, project["id"], description="Hi")

    assert response.status_code == 422


# --- Queue and lifecycle -------------------------------------------------------------


def test_queue_lists_text_publications_in_order(text_client: TestClient) -> None:
    project, [threads, instagram] = _project_with(text_client, "threads", "instagram")
    content = import_one(text_client, project["id"], "a.png", make_image())["content"]
    [with_media] = create_publications(text_client, content["id"], [instagram["id"]])
    [scheduled] = create_text_publications(
        text_client, project["id"], [threads["id"]], scheduled_at=FUTURE
    ).json()
    [unscheduled] = create_text_publications(
        text_client, project["id"], [threads["id"]]
    ).json()

    queue = _queue(text_client, project["id"])

    assert [item["id"] for item in queue] == [
        scheduled["id"],
        with_media["id"],
        unscheduled["id"],
    ]
    assert queue[0]["content"] is None
    assert queue[1]["content"]["id"] == content["id"]


def test_edit_schedule_and_arm_text_publication(text_client: TestClient) -> None:
    project, [account] = _project_with(text_client, "threads")
    [publication] = create_text_publications(
        text_client, project["id"], [account["id"]]
    ).json()
    url = f"/api/publications/{publication['id']}"

    edited = text_client.patch(
        url, json={"description_override": "New text", "hashtags_override": ["#new"]}
    )
    scheduled = text_client.patch(url, json={"scheduled_at": LATER})
    armed = text_client.patch(url, json={"auto_publish_enabled": True})

    assert edited.status_code == 200, edited.text
    assert edited.json()["description"] == "New text"
    assert edited.json()["hashtags"] == ["new"]
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["status"] == "scheduled"
    assert armed.status_code == 200, armed.text
    assert armed.json()["auto_publish_enabled"] is True


def test_cancel_and_reactivate_text_publication(text_client: TestClient) -> None:
    project, [account] = _project_with(text_client, "threads")
    [first, second] = [
        create_text_publications(text_client, project["id"], [account["id"]]).json()[0]
        for _ in range(2)
    ]

    cancelled = text_client.post(f"/api/publications/{first['id']}/cancel")
    reactivated = text_client.post(f"/api/publications/{first['id']}/reactivate")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # Another active text publication of the same account is not a duplicate.
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "unscheduled"
    assert second["status"] == "unscheduled"


def test_publish_text_publication_with_text_capable_publisher(
    text_client: TestClient, text_publisher: FakePublisher
) -> None:
    project, [account] = _project_with(text_client, "threads")
    [publication] = create_text_publications(
        text_client, project["id"], [account["id"]]
    ).json()

    published = publish_and_wait(text_client, publication["id"])

    assert published["status"] == "published"
    assert text_publisher.check_calls == [publication["id"]]
    assert text_publisher.upload_calls == [publication["id"]]


# --- Generic preflight ---------------------------------------------------------------


def _insert_text_publication(db_path: Path, project_id: int, account_id: int) -> int:
    run_sql(
        db_path,
        "INSERT INTO publications (project_id, content_id, account_id, status, "
        "description_override, created_at, updated_at) VALUES (?, NULL, ?, "
        "'unscheduled', 'Text only', '2026-10-13 10:00:00', '2026-10-13 10:00:00')",
        project_id,
        account_id,
    )
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT MAX(id) FROM publications").fetchone()
    publication_id: int = row[0]
    return publication_id


def test_publish_check_requires_media_for_other_platforms(
    text_client: TestClient, media_publisher: FakePublisher, db_path: Path
) -> None:
    project, [account] = _project_with(text_client, "instagram")
    publication_id = _insert_text_publication(db_path, project["id"], account["id"])

    check = text_client.get(f"/api/publications/{publication_id}/publish-check")
    publish = text_client.post(f"/api/publications/{publication_id}/publish", json={})

    assert check.status_code == 200, check.text
    assert check.json()["eligible"] is False
    assert [p["code"] for p in check.json()["problems"]] == [
        "publication_media_required"
    ]
    assert publish.status_code == 409
    assert publish.json()["error"]["code"] == "publication_media_required"
    assert media_publisher.check_calls == []
    assert media_publisher.prepare_calls == []


def _fail_uncertain(db_path: Path, publication_id: int) -> None:
    run_sql(
        db_path,
        "UPDATE publications SET status = 'failed' WHERE id = ?",
        publication_id,
    )
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (publication_id, platform, trigger, status, "
        "stage, started_at, finished_at, bytes_sent, total_bytes, error_code, "
        "error_message, outcome_determined, submitted, details, warnings) VALUES "
        "(?, 'threads', 'manual', 'failed', 'finalizing', '2026-10-13 10:00:00', "
        "'2026-10-13 10:01:00', 0, 0, 'internal_error', 'Uncertain', 0, '{}', '{}', "
        "'[]')",
        publication_id,
    )


def test_remote_check_uses_the_publication_own_attempts(
    text_client: TestClient, db_path: Path
) -> None:
    project, [account] = _project_with(text_client, "threads")
    [uncertain, other] = [
        create_text_publications(text_client, project["id"], [account["id"]]).json()[0]
        for _ in range(2)
    ]
    _fail_uncertain(db_path, uncertain["id"])

    uncertain_check = text_client.get(
        f"/api/publications/{uncertain['id']}/publish-check"
    )
    other_check = text_client.get(f"/api/publications/{other['id']}/publish-check")
    publish = text_client.post(f"/api/publications/{uncertain['id']}/publish", json={})

    assert uncertain_check.json()["requires_remote_check"] is True
    # Another text post of the same account is a different post.
    assert other_check.json()["requires_remote_check"] is False
    assert publish.status_code == 409
    assert publish.json()["error"]["code"] == "remote_check_required"
