"""Restarts never resume or repeat an Instagram execution; the next attempt reads the
previous container before creating anything (US6, FR-050-FR-053, research.md §12)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import (
    get_publication,
    instagram_publication,
    make_instagram_publishing_app,
    publish_and_wait,
    run_sql,
    temporary_media_rows,
    wait_idle,
)
from tests.fakes import (
    FakeClock,
    FakeMediaDeliveryProvider,
    FakeMeta,
    InMemoryCredentialStore,
)

STARTED = "2026-10-09 10:00:00"
CONTAINER = "17900000000009999"


@pytest.fixture
def restart(
    db_path: Path,
    media_dir: Path,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
) -> Any:
    @contextmanager
    def start() -> Iterator[TestClient]:
        app = make_instagram_publishing_app(
            db_path,
            media_dir,
            instagram_credential_store,
            fake_meta,
            fake_delivery,
            fake_clock,
            recorded_sleeps,
        )
        with TestClient(app) as client:
            state: Any = client.app
            assert isinstance(state, FastAPI)
            state.state.media_sweeper.join(10)
            yield client

    return start


def _leave_running(
    db_path: Path,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    publication_id: int,
    stage: str,
    phase: str,
    *,
    container: bool = False,
    write_ahead: bool = False,
) -> str:
    """What a crash in the middle of an Instagram execution leaves behind."""
    run_sql(db_path, "UPDATE publications SET status = 'publishing'")
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (id, publication_id, platform, status, "
        "stage, started_at, bytes_sent, total_bytes, submitted, details, warnings) "
        "VALUES (50, ?, 'instagram', 'running', ?, ?, 0, 10, '{}', '{}', '[]')",
        publication_id,
        stage,
        STARTED,
    )
    run_sql(
        db_path,
        "INSERT INTO instagram_publish_runs (attempt_id, publication_id, media_kind, "
        "fingerprint, phase, container_id, container_created_at, publish_started_at, "
        "updated_at) VALUES (50, ?, 'image', 'f', ?, ?, ?, ?, ?)",
        publication_id,
        phase,
        CONTAINER if container else None,
        STARTED if container else None,
        STARTED if write_ahead else None,
        STARTED,
    )
    key = "autopublisher-tmp/abc/def.jpg"
    run_sql(
        db_path,
        "INSERT INTO temporary_media_objects (provider, object_key, attempt_id, "
        "content_type, size_bytes, created_at, uploaded_at) VALUES ('s3_compatible', "
        "?, 50, 'image/jpeg', 10, ?, ?)",
        key,
        STARTED,
        STARTED,
    )
    fake_delivery.objects[key] = b"0123456789"
    if container:
        fake_meta.containers[CONTAINER] = {}
        fake_meta.container_statuses[CONTAINER] = ["FINISHED"]
    return key


@pytest.mark.parametrize(
    ("stage", "phase"),
    [
        ("preparing", "preparing"),
        ("uploading", "delivering_media"),
        ("processing", "processing_container"),
    ],
)
def test_restart_before_the_final_step_is_determined_and_swept(
    ig_client: TestClient,
    restart: Any,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
    stage: str,
    phase: str,
) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]
    key = _leave_running(
        db_path,
        fake_meta,
        fake_delivery,
        publication_id,
        stage,
        phase,
        container=stage == "processing",
    )
    before = len(fake_meta.requests)

    with restart() as client:
        publication = get_publication(client, publication_id)

    attempt = publication["latest_attempt"]
    assert publication["status"] == "failed"
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is True
    assert len(fake_meta.requests) == before  # No Meta call at start-up.
    assert key not in fake_delivery.objects
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None


def test_restart_after_the_write_ahead_is_uncertain(
    ig_client: TestClient,
    restart: Any,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]
    _leave_running(
        db_path,
        fake_meta,
        fake_delivery,
        publication_id,
        "finalizing",
        "publishing",
        container=True,
        write_ahead=True,
    )
    before = len(fake_meta.requests)

    with restart() as client:
        publication = get_publication(client, publication_id)

    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["outcome_determined"] is False
    assert publication["latest_attempt"]["requires_manual_review"] is True
    assert len(fake_meta.requests) == before
    assert fake_meta.requests_for("publish") == []


def test_crash_between_reserve_and_upload_is_swept(
    ig_client: TestClient,
    restart: Any,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]
    key = _leave_running(
        db_path, fake_meta, fake_delivery, publication_id, "uploading", "preparing"
    )
    fake_delivery.objects.pop(key)  # The upload never happened.

    with restart():
        pass

    assert key in fake_delivery.delete_calls
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None


# --- Previous container on a new attempt -------------------------------------------


def _first_attempt_not_ready(client: TestClient, fake_meta: FakeMeta) -> int:
    """A determined failure that leaves a FINISHED container behind."""
    fake_meta.faults["publish"] = "graph_9007_2207027"
    publication_id: int = instagram_publication(client)["publication"]["id"]
    publication = publish_and_wait(client, publication_id)
    assert publication["latest_attempt"]["outcome_determined"] is True
    fake_meta.faults.pop("publish")
    return publication_id


def test_finished_container_with_same_content_is_reused(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    publication_id = _first_attempt_not_ready(ig_client, fake_meta)
    uploads = len(fake_delivery.put_calls)

    publication = publish_and_wait(ig_client, publication_id)

    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["submitted"]["container_reused"] is True
    assert attempt["stage"] == "done"
    assert len(fake_meta.containers) == 1
    assert len(fake_delivery.put_calls) == uploads
    assert len(fake_meta.requests_for("publish")) == 2
    assert len(fake_meta.published) == 1


def test_changed_caption_creates_a_new_container(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    publication_id = _first_attempt_not_ready(ig_client, fake_meta)
    response = ig_client.patch(
        f"/api/publications/{publication_id}",
        json={"description_override": "New caption"},
    )
    assert response.status_code == 200, response.text

    publication = publish_and_wait(ig_client, publication_id)

    assert publication["latest_attempt"]["submitted"]["container_reused"] is False
    assert len(fake_meta.containers) == 2


@pytest.mark.parametrize("status", ["ERROR", "EXPIRED", "IN_PROGRESS"])
def test_unusable_previous_container_is_not_reused(
    ig_client: TestClient, fake_meta: FakeMeta, status: str
) -> None:
    publication_id = _first_attempt_not_ready(ig_client, fake_meta)
    for container in fake_meta.containers:
        fake_meta.container_statuses[container] = [status]

    publication = publish_and_wait(ig_client, publication_id)

    assert publication["status"] == "published"
    assert len(fake_meta.containers) == 2


def test_old_containers_are_not_read(
    ig_client: TestClient, fake_meta: FakeMeta, fake_clock: FakeClock
) -> None:
    publication_id = _first_attempt_not_ready(ig_client, fake_meta)
    fake_clock.advance(timedelta(hours=24).total_seconds())
    status_reads = len(fake_meta.requests_for("status"))

    publication = publish_and_wait(ig_client, publication_id)

    assert publication["latest_attempt"]["submitted"]["container_reused"] is False
    # Only the new container is read.
    assert len(fake_meta.requests_for("status")) == status_reads + 1


def test_published_previous_container_blocks_a_new_attempt(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    publication_id = _first_attempt_not_ready(ig_client, fake_meta)
    for container in fake_meta.containers:
        fake_meta.container_statuses[container] = ["PUBLISHED"]
    uploads = len(fake_delivery.put_calls)

    response = ig_client.post(f"/api/publications/{publication_id}/publish", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "instagram_already_published"
    assert len(fake_meta.requests_for("publish")) == 1
    assert len(fake_delivery.put_calls) == uploads
    assert get_publication(ig_client, publication_id)["attempt_count"] == 1


def test_unreadable_previous_container_blocks_without_effects(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    publication_id = _first_attempt_not_ready(ig_client, fake_meta)
    fake_meta.faults["status"] = "server_error"

    response = ig_client.post(f"/api/publications/{publication_id}/publish", json={})
    wait_idle(ig_client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "instagram_unavailable"
    assert len(fake_meta.containers) == 1
