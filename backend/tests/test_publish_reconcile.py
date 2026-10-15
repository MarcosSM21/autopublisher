"""Neutral core extension (research §17): a read-only reconciliation may also report
that the platform confirms nothing was published (`ReconciledFailure`), which makes
an uncertain attempt determined without the manual acknowledgement."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.publishing import PublishOutcome, ReconciledFailure, Reconciliation
from tests.conftest import attempt_rows, get_publication, run_sql
from tests.fakes import FakeClock, FakePublisher
from tests.test_publish_core_extensions import _leave_uncertain, _publication

FAILURE = ReconciledFailure("platform_failed", "The platform did not publish it.")


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


def _uncertain(client: TestClient, db_path: Path, clock: FakeClock) -> int:
    publication_id = _publication(client, db_path, clock)
    _leave_uncertain(db_path, publication_id)
    return publication_id


def _check(client: TestClient, publication_id: int) -> dict[str, object]:
    response = client.get(f"/api/publications/{publication_id}/publish-check")
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


def test_confirmed_failure_makes_the_attempt_determined(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _uncertain(client, db_path, fake_clock)
    fake_publisher.reconciliations[publication_id] = FAILURE

    check = _check(client, publication_id)

    assert check["requires_remote_check"] is False
    publication = get_publication(client, publication_id)
    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert attempt["error"]["code"] == "platform_failed"
    assert attempt["error"]["message"] == "The platform did not publish it."
    assert len(attempt_rows(db_path)) == 1
    # Publishing again needs no remote acknowledgement any more.
    response = client.post(f"/api/publications/{publication_id}/publish", json={})
    assert response.status_code == 202


def test_confirmed_publication_still_works(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _uncertain(client, db_path, fake_clock)
    fake_publisher.reconciliations[publication_id] = Reconciliation(
        datetime(2026, 10, 7, 10, tzinfo=UTC), PublishOutcome(None, None)
    )

    _check(client, publication_id)

    assert get_publication(client, publication_id)["status"] == "published"


def test_confirmed_delivery_awaits_the_user(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _uncertain(client, db_path, fake_clock)
    fake_publisher.reconciliations[publication_id] = Reconciliation(
        None,
        PublishOutcome(
            None, None, details={"delivered": True}, awaiting_user_action=True
        ),
    )

    check = _check(client, publication_id)

    assert check["requires_remote_check"] is False
    publication = get_publication(client, publication_id)
    assert publication["status"] == "awaiting_user_action"
    assert publication["published_at"] is None
    attempt = publication["latest_attempt"]
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["external_id"] is None
    assert attempt["details"]["delivered"] is True
    assert len(attempt_rows(db_path)) == 1


def test_no_answer_or_an_error_keeps_it_uncertain(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _uncertain(client, db_path, fake_clock)

    assert _check(client, publication_id)["requires_remote_check"] is True
    fake_publisher.reconcile_errors[publication_id] = RuntimeError("network")
    assert _check(client, publication_id)["requires_remote_check"] is True

    attempt = get_publication(client, publication_id)["latest_attempt"]
    assert attempt["outcome_determined"] is False
    assert attempt["error"]["code"] == "interrupted"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE publications SET status = 'cancelled' WHERE id = ?",
        "UPDATE publication_attempts SET outcome_determined = 1 "
        "WHERE publication_id = ?",
    ],
    ids=["publication_changed", "attempt_changed"],
)
def test_nothing_changes_if_the_state_changed_meanwhile(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
    statement: str,
) -> None:
    publication_id = _uncertain(client, db_path, fake_clock)
    fake_publisher.reconciliations[publication_id] = FAILURE
    fake_publisher.reconcile_hook = lambda pid: run_sql(db_path, statement, pid)

    _check(client, publication_id)

    [row] = attempt_rows(db_path)
    assert row["error_code"] == "interrupted"
