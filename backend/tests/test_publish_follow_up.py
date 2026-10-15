"""`POST /api/publications/{id}/check-status` (Feature 014): one read-only check of
a publication awaiting user action, through the publisher's `follow_up`. Core only,
with a `FakePublisher`: the delivery attempt is never changed nor added to."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.errors import AppError
from app.publishing import PublishOutcome, UserActionCompleted, UserActionFailed
from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    publish_and_wait,
    run_sql,
    scheduled_publication,
)
from tests.fakes import FakeClock, FakePublisher

AWAITING = PublishOutcome(
    external_id=None,
    external_url=None,
    details={"delivered": True},
    awaiting_user_action=True,
)
SEEN = datetime(2026, 10, 15, 18, 4, 12, tzinfo=UTC)


def _awaiting(
    client: TestClient, db_path: Path, publisher: FakePublisher, clock: FakeClock
) -> int:
    setup = scheduled_publication(client, db_path, in_minutes(clock, 60), armed=False)
    publication_id: int = setup["publication"]["id"]
    publisher.outcomes[publication_id] = AWAITING
    assert publish_and_wait(client, publication_id)["status"] == (
        "awaiting_user_action"
    )
    return publication_id


def _check(client: TestClient, publication_id: int) -> Any:
    return client.post(f"/api/publications/{publication_id}/check-status")


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


def test_completed_moves_to_published(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _awaiting(client, db_path, fake_publisher, fake_clock)
    before = attempt_rows(db_path)
    fake_publisher.follow_ups[publication_id] = UserActionCompleted(SEEN)

    response = _check(client, publication_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "published"
    assert body["message"]
    assert body["checked_at"]
    assert body["publication"]["status"] == "published"
    assert body["publication"]["published_at"] == "2026-10-15T18:04:12Z"
    assert get_publication(client, publication_id)["status"] == "published"
    # The delivery attempt is history: byte-identical, nothing added.
    assert attempt_rows(db_path) == before
    assert fake_publisher.follow_up_calls == [publication_id]


def test_failed_moves_to_failed(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _awaiting(client, db_path, fake_publisher, fake_clock)
    before = attempt_rows(db_path)
    fake_publisher.follow_ups[publication_id] = UserActionFailed(
        "fake_rejected", "The platform rejected the post."
    )

    response = _check(client, publication_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "failed"
    assert body["message"] == "The platform rejected the post."
    publication = get_publication(client, publication_id)
    assert publication["status"] == "failed"
    assert publication["published_at"] is None
    assert attempt_rows(db_path) == before


def test_still_waiting_changes_nothing(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _awaiting(client, db_path, fake_publisher, fake_clock)
    before = attempt_rows(db_path)

    response = _check(client, publication_id)

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "awaiting"
    assert response.json()["publication"]["status"] == "awaiting_user_action"
    assert attempt_rows(db_path) == before


def test_errors_change_nothing_and_are_returned(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _awaiting(client, db_path, fake_publisher, fake_clock)
    before = attempt_rows(db_path)
    fake_publisher.follow_up_errors[publication_id] = AppError(
        503, "fake_unavailable", "Could not reach the platform."
    )

    response = _check(client, publication_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "fake_unavailable"
    assert get_publication(client, publication_id)["status"] == ("awaiting_user_action")
    assert attempt_rows(db_path) == before


@pytest.mark.parametrize("status", ["unscheduled", "failed", "published"])
def test_only_awaiting_publications_can_be_checked(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
    status: str,
) -> None:
    publication_id = _awaiting(client, db_path, fake_publisher, fake_clock)
    run_sql(
        db_path,
        "UPDATE publications SET status = ?, published_at = ?, scheduled_at = NULL "
        "WHERE id = ?",
        status,
        "2026-10-15 10:00:00" if status == "published" else None,
        publication_id,
    )

    response = _check(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_awaiting"
    assert fake_publisher.follow_up_calls == []


def test_unknown_publication(client: TestClient) -> None:
    assert _check(client, 9999).status_code == 404


def test_a_concurrent_change_wins(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    """Another check settled it meanwhile: the conditional update changes nothing."""
    publication_id = _awaiting(client, db_path, fake_publisher, fake_clock)
    fake_publisher.follow_ups[publication_id] = UserActionCompleted(SEEN)

    def settled_meanwhile(_: int) -> None:
        run_sql(
            db_path,
            "UPDATE publications SET status = 'failed' WHERE id = ?",
            publication_id,
        )

    fake_publisher.follow_up_hook = settled_meanwhile

    response = _check(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_awaiting"
    assert get_publication(client, publication_id)["status"] == "failed"


def test_repeated_checks_are_idempotent(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _awaiting(client, db_path, fake_publisher, fake_clock)
    fake_publisher.follow_ups[publication_id] = UserActionCompleted(SEEN)

    first = _check(client, publication_id)
    second = _check(client, publication_id)

    assert first.status_code == 200
    assert second.status_code == 409
    assert fake_publisher.follow_up_calls == [publication_id]
    assert len(attempt_rows(db_path)) == 1
