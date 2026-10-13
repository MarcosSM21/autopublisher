"""Recovery after a crash in each phase of a Threads attempt (US7): the generic
recovery closes the attempt, determined before the write-ahead and uncertain after
it; temporary media is swept; nothing is resumed or republished."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.publishing import recover_interrupted_attempts
from tests.conftest import (
    attempt_rows,
    get_publication,
    publish_and_wait,
    run_sql,
    run_tick,
    temporary_media_rows,
    threads_image_publication,
    threads_text_publication,
    wait_idle,
)
from tests.fakes import FakeMediaDeliveryProvider, FakeThreads


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _crash(
    db_path: Path,
    publication_id: int,
    *,
    stage: str,
    phase: str,
    container: bool,
    write_ahead: bool,
) -> None:
    """Rebuild the exact state a process killed in this phase leaves behind."""
    run_sql(
        db_path,
        "UPDATE publications SET status = 'publishing', published_at = NULL "
        "WHERE id = ?",
        publication_id,
    )
    run_sql(
        db_path,
        "UPDATE publication_attempts SET status = 'running', stage = ?, "
        "finished_at = NULL, error_code = NULL, error_message = NULL, "
        "outcome_determined = NULL, external_id = NULL, external_url = NULL, "
        "bytes_sent = 0, warnings = '[]', details = '{}'",
        stage,
    )
    run_sql(
        db_path,
        "UPDATE threads_publish_runs SET phase = ?, "
        f"container_id = {'container_id' if container else 'NULL'}, "
        f"container_created_at = {'container_created_at' if container else 'NULL'}, "
        f"publish_started_at = {'publish_started_at' if write_ahead else 'NULL'}",
        phase,
    )


PHASES = [
    # (stage, phase, container stored, write-ahead committed, determined)
    ("preparing", "preparing", False, False, True),
    ("processing", "creating_container", False, False, True),
    ("processing", "processing_container", True, False, True),
    ("finalizing", "publishing", True, True, False),
    ("finalizing", "verifying_result", True, True, False),
]


@pytest.mark.parametrize(
    ("stage", "phase", "container", "write_ahead", "determined"), PHASES
)
@pytest.mark.parametrize("remote", ["FINISHED", "PUBLISHED"])
def test_restart_in_each_phase(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
    stage: str,
    phase: str,
    container: bool,
    write_ahead: bool,
    determined: bool,
    remote: str,
) -> None:
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])
    [container_id] = fake_threads.containers
    publishes = len(fake_threads.requests_for("publish"))
    _crash(
        db_path,
        publication["id"],
        stage=stage,
        phase=phase,
        container=container,
        write_ahead=write_ahead,
    )
    # What Threads reports about the original container after the restart.
    fake_threads.container_statuses[container_id] = [remote]

    closed = recover_interrupted_attempts(
        _app(threads_publishing_client).state.session_factory
    )
    after = get_publication(threads_publishing_client, publication["id"])

    assert closed == 1
    [row] = attempt_rows(db_path)
    attempt = after["latest_attempt"]
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is determined
    assert after["status"] == "failed"
    # Nothing is resumed and no request was made while recovering.
    assert len(fake_threads.requests_for("publish")) == publishes
    assert len(fake_threads.containers) == 1
    assert run_tick(threads_publishing_client).started == []

    # Only an uncertain attempt that reached the write-ahead is reconciled, and only
    # a PUBLISHED container settles it.
    threads_publishing_client.get(
        f"/api/publications/{publication['id']}/publish-check"
    )
    final = get_publication(threads_publishing_client, publication["id"])
    settled = not determined and remote == "PUBLISHED"
    assert final["status"] == ("published" if settled else "failed")
    assert len(fake_threads.requests_for("publish")) == publishes
    assert fake_threads.post_list_requests == 0
    assert row["id"] == attempt["id"]


def test_restart_while_delivering_media_sweeps_the_object(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    fake_delivery.delete_failures = 2  # Keep the object pending after the run.
    created = threads_image_publication(threads_publishing_client)
    publish_and_wait(threads_publishing_client, created["publication"]["id"])
    assert temporary_media_rows(db_path)[0]["deleted_at"] is None
    _crash(
        db_path,
        created["publication"]["id"],
        stage="uploading",
        phase="delivering_media",
        container=False,
        write_ahead=False,
    )

    app = _app(threads_publishing_client)
    recover_interrupted_attempts(app.state.session_factory)
    failures = app.state.temporary_media.sweep()

    attempt = get_publication(threads_publishing_client, created["publication"]["id"])[
        "latest_attempt"
    ]
    assert attempt["outcome_determined"] is True
    assert failures == 0
    assert fake_delivery.objects == {}
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None


def test_published_is_never_republished_after_a_restart(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])

    recover_interrupted_attempts(_app(threads_publishing_client).state.session_factory)
    response = threads_publishing_client.post(
        f"/api/publications/{publication['id']}/publish", json={}
    )
    wait_idle(threads_publishing_client)

    assert response.status_code == 409
    assert get_publication(threads_publishing_client, publication["id"])["status"] == (
        "published"
    )
    assert len(attempt_rows(db_path)) == 1
    assert len(fake_threads.requests_for("publish")) == 1
