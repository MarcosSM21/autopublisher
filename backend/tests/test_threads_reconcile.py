"""Read-only reconciliation of uncertain Threads attempts (US7, research.md §12):
one read of the original container; only PUBLISHED settles it."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import (
    attempt_rows,
    get_publication,
    publish_and_wait,
    run_sql,
    threads_run_rows,
    threads_text_publication,
    wait_idle,
)
from tests.fakes import FakeThreads


def _uncertain(client: TestClient, fake_threads: FakeThreads) -> tuple[int, str]:
    fake_threads.fault_queue["publish"] = ["server_error"]
    publication = threads_text_publication(client)["publication"]
    published = publish_and_wait(client, publication["id"])
    assert published["latest_attempt"]["error"]["code"] == "threads_publish_uncertain"
    [container_id] = fake_threads.containers
    return publication["id"], container_id


def _check(client: TestClient, publication_id: int) -> dict[str, object]:
    response = client.get(f"/api/publications/{publication_id}/publish-check")
    assert response.status_code == 200, response.text
    check: dict[str, object] = response.json()
    return check


def test_published_container_settles_the_attempt(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    publication_id, container_id = _uncertain(threads_publishing_client, fake_threads)
    fake_threads.container_statuses[container_id] = ["PUBLISHED"]
    reads = len(fake_threads.requests_for("status"))

    check = _check(threads_publishing_client, publication_id)

    assert len(fake_threads.requests_for("status")) == reads + 1
    publication = get_publication(threads_publishing_client, publication_id)
    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert [w["code"] for w in attempt["warnings"]] == ["remote_identity_unavailable"]
    assert check["eligible"] is False
    assert threads_run_rows(db_path)[0]["phase"] == "succeeded"
    assert len(attempt_rows(db_path)) == 1
    assert len(fake_threads.containers) == 1
    assert len(fake_threads.requests_for("publish")) == 1
    assert fake_threads.post_list_requests == 0


def test_publish_now_reconciles_before_anything_else(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    publication_id, container_id = _uncertain(threads_publishing_client, fake_threads)
    fake_threads.container_statuses[container_id] = ["PUBLISHED"]

    response = threads_publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )
    wait_idle(threads_publishing_client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_eligible"
    assert get_publication(threads_publishing_client, publication_id)["status"] == (
        "published"
    )
    assert len(attempt_rows(db_path)) == 1
    assert len(fake_threads.containers) == 1
    assert len(fake_threads.requests_for("publish")) == 1


def test_any_other_status_keeps_it_uncertain(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
) -> None:
    publication_id, container_id = _uncertain(threads_publishing_client, fake_threads)
    for status in ("FINISHED", "EXPIRED", "ERROR", "IN_PROGRESS"):
        fake_threads.container_statuses[container_id] = [status]

        check = _check(threads_publishing_client, publication_id)

        assert check["requires_remote_check"] is True
    response = threads_publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"
    assert get_publication(threads_publishing_client, publication_id)["status"] == (
        "failed"
    )


def test_failing_read_keeps_it_uncertain(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
) -> None:
    publication_id, _ = _uncertain(threads_publishing_client, fake_threads)
    fake_threads.faults["status"] = "server_error"

    check = _check(threads_publishing_client, publication_id)

    assert check["requires_remote_check"] is True
    assert get_publication(threads_publishing_client, publication_id)["status"] == (
        "failed"
    )


def test_confirmed_retry_reads_the_previous_container_then_creates_a_new_one(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
) -> None:
    publication_id, container_id = _uncertain(threads_publishing_client, fake_threads)
    status_reads: list[str] = []
    original = fake_threads._status

    def status(cid: str) -> Any:
        status_reads.append(cid)
        return original(cid)

    fake_threads._status = status  # type: ignore[method-assign,assignment]

    published = publish_and_wait(
        threads_publishing_client, publication_id, confirm_remote_checked=True
    )

    assert published["status"] == "published"
    first, second = fake_threads.containers
    assert first == container_id
    # Reconciliation and the research §11 read happen before the new container.
    assert status_reads[:2] == [container_id, container_id]
    assert fake_threads.publish_count(first) == 1
    assert fake_threads.publish_count(second) == 1


def test_runs_without_write_ahead_are_never_reconciled(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    fake_threads.status_script = ["ERROR"]
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])
    # An uncertain attempt whose run never reached the write-ahead.
    run_sql(db_path, "UPDATE publication_attempts SET outcome_determined = 0")
    [container_id] = fake_threads.containers
    fake_threads.container_statuses[container_id] = ["PUBLISHED"]
    reads = len(fake_threads.requests_for("status"))

    check = _check(threads_publishing_client, publication["id"])

    assert check["requires_remote_check"] is True
    assert len(fake_threads.requests_for("status")) == reads
    assert get_publication(threads_publishing_client, publication["id"])["status"] == (
        "failed"
    )
