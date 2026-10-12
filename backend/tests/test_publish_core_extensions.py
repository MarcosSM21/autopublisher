"""Platform-neutral additions to the execution core for Feature 009: cleanup after the
outcome is saved, outcomes without a remote identity, read-only reconciliation of an
uncertain attempt and the public progress rule."""

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.models import AttemptStage
from app.publishing import (
    PublishContext,
    PublishFailure,
    PublishingSettings,
    PublishOutcome,
    Reconciliation,
    _AttemptReporter,
)
from tests.conftest import (
    FUTURE,
    attempt_rows,
    get_publication,
    publish_and_wait,
    run_sql,
    scheduled_publication,
)
from tests.fakes import FakeClock, FakePublisher

STARTED = "2026-10-07 10:00:00"
CLEANUP_WARNING = {"code": "temporary_media_cleanup_failed", "message": "Pending."}


def _publication(client: TestClient, db_path: Path, clock: FakeClock) -> int:
    created = scheduled_publication(
        client, db_path, datetime.fromisoformat(FUTURE), armed=False
    )
    publication_id: int = created["publication"]["id"]
    return publication_id


def _leave_uncertain(db_path: Path, publication_id: int, **values: Any) -> None:
    """A failed publication whose last attempt may have published it."""
    run_sql(
        db_path,
        "UPDATE publications SET status = 'failed', scheduled_at = NULL WHERE id = ?",
        publication_id,
    )
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (publication_id, platform, status, stage, "
        "started_at, finished_at, bytes_sent, total_bytes, error_code, error_message, "
        "outcome_determined, submitted, details, warnings) VALUES (?, 'youtube', "
        "'failed', 'finalizing', ?, ?, ?, ?, 'interrupted', 'Check it.', 0, '{}', "
        "'{}', '[]')",
        publication_id,
        STARTED,
        STARTED,
        values.get("bytes_sent", 10),
        values.get("total_bytes", 10),
    )


# --- Release (cleanup after the outcome is saved) ------------------------------------


def test_release_runs_after_the_success_is_saved(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)

    publication = publish_and_wait(fake_scheduler_client, publication_id)

    assert publication["status"] == "published"
    attempt_id = publication["latest_attempt"]["id"]
    assert fake_publisher.release_calls == [(attempt_id, True, "published")]


def test_cleanup_failure_only_adds_a_warning(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    fake_publisher.release_warnings = [CLEANUP_WARNING]
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)

    publication = publish_and_wait(fake_scheduler_client, publication_id)

    attempt = get_publication(fake_scheduler_client, publication_id)["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["progress"] == 1
    assert [w["code"] for w in attempt["warnings"]] == [
        "temporary_media_cleanup_failed"
    ]


def test_an_exception_in_release_never_changes_the_outcome(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    fake_publisher.release_error = RuntimeError("provider down")
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)

    publication = publish_and_wait(fake_scheduler_client, publication_id)

    assert publication["status"] == "published"
    assert publication["latest_attempt"]["status"] == "succeeded"


def test_release_runs_after_a_saved_failure(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    fake_publisher.upload_failure = PublishFailure(
        "network_error", "The network failed.", determined=True
    )
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)

    publication = publish_and_wait(fake_scheduler_client, publication_id)

    assert publication["status"] == "failed"
    attempt_id = publication["latest_attempt"]["id"]
    assert fake_publisher.release_calls == [(attempt_id, False, "failed")]


def test_success_without_remote_identity_is_published(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)
    original_upload = fake_publisher.upload

    def upload(*args: Any) -> PublishOutcome:
        original_upload(*args)
        return PublishOutcome(None, None)

    fake_publisher.upload = upload  # type: ignore[method-assign,assignment]

    publication = publish_and_wait(fake_scheduler_client, publication_id)

    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None


# --- Reporter ------------------------------------------------------------------------


def _broken_context() -> PublishContext:
    def factory() -> Any:
        raise OperationalError("SELECT 1", {}, Exception("disk I/O error"))

    return PublishContext(factory, None, PublishingSettings())  # type: ignore[arg-type]


def test_enter_finalizing_is_false_when_the_stage_cannot_be_saved() -> None:
    reporter = _AttemptReporter(_broken_context(), 1, threading.Event())

    assert reporter.enter_finalizing() is False
    assert reporter.stage == AttemptStage.PREPARING
    assert reporter.attempt_id == 1


# --- Reconciliation ------------------------------------------------------------------


def test_publish_check_reconciles_a_confirmed_publication(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)
    _leave_uncertain(db_path, publication_id)
    published_at = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
    fake_publisher.reconciliations[publication_id] = Reconciliation(
        published_at,
        PublishOutcome(
            None,
            None,
            warnings=[{"code": "remote_identity_unavailable", "message": "Check."}],
        ),
    )

    check = fake_scheduler_client.get(
        f"/api/publications/{publication_id}/publish-check"
    ).json()

    assert check["requires_remote_check"] is False
    assert check["eligible"] is False
    assert check["problems"][0]["code"] == "publication_not_eligible"
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "published"
    assert publication["published_at"].startswith("2026-10-07T10:00:00")
    attempt = publication["latest_attempt"]
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["error"] is None
    assert attempt["stage"] == "done"
    assert attempt["external_id"] is None
    assert [w["code"] for w in attempt["warnings"]] == ["remote_identity_unavailable"]
    assert len(attempt_rows(db_path)) == 1

    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_eligible"
    assert fake_publisher.upload_calls == []


def test_publish_now_reconciles_before_requiring_a_remote_check(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)
    _leave_uncertain(db_path, publication_id)
    fake_publisher.reconciliations[publication_id] = Reconciliation(
        datetime(2026, 10, 7, 10, 0, tzinfo=UTC), PublishOutcome(None, None)
    )

    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_eligible"
    assert get_publication(fake_scheduler_client, publication_id)["status"] == (
        "published"
    )
    assert fake_publisher.upload_calls == []


def test_an_unconfirmed_reconciliation_changes_nothing(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)
    _leave_uncertain(db_path, publication_id)

    check = fake_scheduler_client.get(
        f"/api/publications/{publication_id}/publish-check"
    ).json()
    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert fake_publisher.reconcile_calls == [publication_id, publication_id]
    assert check["requires_remote_check"] is True
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"
    publication = get_publication(fake_scheduler_client, publication_id)
    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["requires_manual_review"] is True


def test_determined_failures_are_not_reconciled(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    fake_publisher.upload_failure = PublishFailure(
        "network_error", "The network failed.", determined=True
    )
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)
    publish_and_wait(fake_scheduler_client, publication_id)

    fake_scheduler_client.get(f"/api/publications/{publication_id}/publish-check")

    assert fake_publisher.reconcile_calls == []


# --- Progress ------------------------------------------------------------------------


def test_unfinished_attempts_never_expose_full_progress(
    fake_scheduler_client: TestClient,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    publication_id = _publication(fake_scheduler_client, db_path, fake_clock)
    _leave_uncertain(db_path, publication_id, bytes_sent=10, total_bytes=10)

    failed = get_publication(fake_scheduler_client, publication_id)["latest_attempt"]
    run_sql(
        db_path,
        "UPDATE publication_attempts SET status = 'running', finished_at = NULL, "
        "error_code = NULL, error_message = NULL, outcome_determined = NULL",
    )
    run_sql(db_path, "UPDATE publications SET status = 'publishing'")
    running = get_publication(fake_scheduler_client, publication_id)["latest_attempt"]

    assert failed["progress"] == 0.99
    assert running["progress"] == 0.99
