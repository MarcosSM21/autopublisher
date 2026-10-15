"""The generic `awaiting_user_action` status (Feature 014): the execution finished
and the platform now waits for the user. Core only, with a `FakePublisher`: no
platform-specific code is involved."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.publishing import PublishOutcome, recover_interrupted_attempts
from tests.conftest import (
    FUTURE,
    attempt_rows,
    create_publications,
    get_publication,
    in_minutes,
    publish_and_wait,
    run_sql,
    run_tick,
    scheduled_publication,
    setup_project,
)
from tests.fakes import FakeClock, FakePublisher

AWAITING = PublishOutcome(
    external_id=None,
    external_url=None,
    details={"delivered": True},
    awaiting_user_action=True,
)


def _awaiting_publication(
    client: TestClient, db_path: Path, publisher: FakePublisher, clock: FakeClock
) -> dict[str, Any]:
    """A publication whose execution ended waiting for the user."""
    setup = scheduled_publication(client, db_path, in_minutes(clock, 60), armed=False)
    publication_id = setup["publication"]["id"]
    publisher.outcomes[publication_id] = AWAITING
    publication = publish_and_wait(client, publication_id)
    assert publication["status"] == "awaiting_user_action"
    return setup


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def test_outcome_awaiting_user_action_closes_the_execution(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    setup = _awaiting_publication(
        fake_scheduler_client, db_path, fake_publisher, fake_clock
    )
    publication_id = setup["publication"]["id"]

    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "awaiting_user_action"
    assert publication["published_at"] is None
    [attempt] = attempt_rows(db_path)
    assert attempt["status"] == "succeeded"
    assert attempt["stage"] == "done"
    assert attempt["outcome_determined"] == 1
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert attempt["finished_at"] is not None
    # Cleanup ran after the outcome was saved, as for any success.
    [(_, succeeded, status)] = fake_publisher.release_calls
    assert succeeded is True
    assert status == "awaiting_user_action"


def test_awaiting_publication_cannot_be_published_again(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    setup = _awaiting_publication(
        fake_scheduler_client, db_path, fake_publisher, fake_clock
    )
    publication_id = setup["publication"]["id"]

    check = fake_scheduler_client.get(
        f"/api/publications/{publication_id}/publish-check"
    )
    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert check.status_code == 200, check.text
    assert check.json()["eligible"] is False
    assert "publication_not_eligible" in [p["code"] for p in check.json()["problems"]]
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_eligible"
    assert fake_publisher.upload_calls == [publication_id]
    assert len(attempt_rows(db_path)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"scheduled_at": FUTURE},
        {"title_override": "New"},
        {"description_override": "New"},
        {"hashtags_override": []},
    ],
)
def test_awaiting_publication_cannot_be_edited(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
    body: dict[str, Any],
) -> None:
    setup = _awaiting_publication(
        fake_scheduler_client, db_path, fake_publisher, fake_clock
    )
    publication_id = setup["publication"]["id"]

    response = fake_scheduler_client.patch(
        f"/api/publications/{publication_id}", json=body
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "awaiting_user_action"


def test_awaiting_publication_cannot_be_cancelled(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    setup = _awaiting_publication(
        fake_scheduler_client, db_path, fake_publisher, fake_clock
    )
    publication_id = setup["publication"]["id"]

    response = fake_scheduler_client.post(f"/api/publications/{publication_id}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "awaiting_user_action"


def test_awaiting_publication_blocks_a_duplicate(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    setup = _awaiting_publication(
        fake_scheduler_client, db_path, fake_publisher, fake_clock
    )

    response = fake_scheduler_client.post(
        f"/api/contents/{setup['content']['id']}/publications",
        json={"account_ids": [setup["account"]["id"]]},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "duplicate"


def test_scheduler_and_recovery_ignore_awaiting_publications(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 5)
    )
    publication_id = setup["publication"]["id"]
    fake_publisher.outcomes[publication_id] = AWAITING
    fake_clock.advance(6 * 60)

    run_tick(fake_scheduler_client)
    _app(fake_scheduler_client).state.publication_runner.wait_idle(timeout=10)
    assert (
        get_publication(fake_scheduler_client, publication_id)["status"]
        == "awaiting_user_action"
    )
    before = attempt_rows(db_path)
    assert [row["trigger"] for row in before] == ["scheduled"]

    for _ in range(2):
        run_tick(fake_scheduler_client)
        fake_clock.advance(60)
    closed = recover_interrupted_attempts(
        _app(fake_scheduler_client).state.session_factory
    )

    assert closed == 0
    assert fake_publisher.prepare_calls == [publication_id]
    assert fake_publisher.upload_calls == [publication_id]
    assert attempt_rows(db_path) == before
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "awaiting_user_action"
    assert publication["auto_publish_enabled"] is False


def test_queue_places_awaiting_between_publishing_and_failed(
    client: TestClient, db_path: Path
) -> None:
    project, content, accounts = setup_project(
        client, ("instagram", "tiktok", "x", "youtube")
    )
    ids = [a["id"] for a in accounts]
    failed, awaiting, publishing, unscheduled = create_publications(
        client, content["id"], ids
    )
    for publication, status in (
        (failed, "failed"),
        (awaiting, "awaiting_user_action"),
        (publishing, "publishing"),
    ):
        run_sql(
            db_path,
            "UPDATE publications SET status = ? WHERE id = ?",
            status,
            publication["id"],
        )

    response = client.get(f"/api/projects/{project['id']}/publications")

    assert response.status_code == 200, response.text
    assert [p["id"] for p in response.json()] == [
        publishing["id"],
        awaiting["id"],
        failed["id"],
        unscheduled["id"],
    ]


def test_a_normal_success_is_published_never_awaiting(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 60), armed=False
    )

    publication = publish_and_wait(fake_scheduler_client, setup["publication"]["id"])

    assert PublishOutcome(None, None).awaiting_user_action is False
    assert publication["status"] == "published"
    assert publication["published_at"] is not None


@pytest.mark.parametrize(
    "module",
    [
        "youtube_publishing",
        "instagram_publishing",
        "threads_publishing",
        "tiktok_publishing",
        "tiktok_transfer",
    ],
)
def test_only_upload_to_inbox_produces_awaiting_user_action(module: str) -> None:
    """Direct Post, YouTube, Instagram and Threads successes are always published:
    the only outcomes awaiting the user are built by Upload to Inbox."""
    from app.config import BACKEND_DIR

    source = (BACKEND_DIR / "app" / f"{module}.py").read_text()

    assert "awaiting_user_action=True" not in source
    assert "AWAITING_USER_ACTION" not in source
