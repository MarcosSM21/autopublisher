"""Restarts and shutdowns never resume or repeat an upload (FR-044, FR-045, US5)."""

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import (
    FUTURE,
    PAST,
    get_publication,
    publish_and_wait,
    run_sql,
    set_youtube_options,
    setup_publishable,
)
from tests.fakes import FakeGoogle, InMemoryCredentialStore

STARTED = "2026-10-07 10:00:00"


def _ready(
    client: TestClient, fake_google: FakeGoogle, **kwargs: Any
) -> dict[str, Any]:
    created = setup_publishable(client, fake_google, **kwargs)
    set_youtube_options(client, created["publication"]["id"])
    return created


def _leave_running(db_path: Path, publication_id: int, stage: str) -> None:
    """What a crash in the middle of an upload leaves in the database."""
    run_sql(
        db_path,
        "UPDATE publications SET status = 'publishing' WHERE id = ?",
        publication_id,
    )
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (publication_id, platform, status, stage, "
        "started_at, bytes_sent, total_bytes, submitted, details, warnings) VALUES "
        "(?, 'youtube', 'running', ?, ?, 5, 10, '{}', '{}', '[]')",
        publication_id,
        stage,
        STARTED,
    )


def _restart(
    db_path: Path,
    media_dir: Path,
    credential_store: InMemoryCredentialStore,
    fake_google: FakeGoogle,
) -> TestClient:
    app = create_app(
        db_path,
        media_dir,
        credential_store=credential_store,
        google_transport=fake_google.transport(),
    )
    return TestClient(app)


@pytest.mark.parametrize(
    ("stage", "determined"),
    [("preparing", True), ("uploading", True), ("final_chunk", False)],
)
def test_restart_closes_running_attempts(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    media_dir: Path,
    credential_store: InMemoryCredentialStore,
    stage: str,
    determined: bool,
) -> None:
    created = _ready(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    _leave_running(db_path, publication_id, stage)
    requests_before = len(fake_google.requests)

    with _restart(db_path, media_dir, credential_store, fake_google) as restarted:
        publication = get_publication(restarted, publication_id)

    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["finished_at"] is not None
    assert attempt["outcome_determined"] is determined
    assert attempt["requires_manual_review"] is (not determined)
    assert len(fake_google.requests) == requests_before


def test_restart_keeps_published_and_scheduled_publications(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    media_dir: Path,
    credential_store: InMemoryCredentialStore,
) -> None:
    published = _ready(publishing_client, fake_google)
    before = publish_and_wait(publishing_client, published["publication"]["id"])
    scheduled = _ready(
        publishing_client, fake_google, scheduled_at=FUTURE, project_name="Two"
    )
    run_sql(
        db_path,
        "UPDATE publications SET scheduled_at = ? WHERE id = ?",
        PAST,
        scheduled["publication"]["id"],
    )
    requests_before = len(fake_google.requests)

    with _restart(db_path, media_dir, credential_store, fake_google) as restarted:
        after = get_publication(restarted, published["publication"]["id"])
        overdue = get_publication(restarted, scheduled["publication"]["id"])

    assert after == before
    assert overdue["status"] == "scheduled"
    assert overdue["latest_attempt"] is None
    assert len(fake_google.requests) == requests_before


def test_graceful_shutdown_closes_the_attempt_deterministically(
    publishing_client: TestClient, publishing_app: FastAPI, fake_google: FakeGoogle
) -> None:
    created = _ready(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    runner = publishing_app.state.publication_runner
    fake_google.block_uploads(at="chunk")
    response = publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )
    assert response.status_code == 202
    attempt_id = response.json()["latest_attempt"]["id"]
    assert fake_google.wait_until_blocked()

    # stop() sets the stop event and waits; the upload thread is still held by the
    # simulator, which the test releases explicitly.
    stopper = threading.Thread(target=runner.stop)
    stopper.start()
    deadline = time.monotonic() + 5
    while not runner.stopping and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runner.stopping
    uploads_before_release = len(fake_google.upload_requests)
    fake_google.release()
    stopper.join(10)

    assert not stopper.is_alive()
    assert not runner.is_live(attempt_id)
    publication = get_publication(publishing_client, publication_id)
    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["stage"] == "uploading"
    assert attempt["outcome_determined"] is True
    assert len(fake_google.upload_requests) == uploads_before_release
    assert fake_google.videos_created == []
