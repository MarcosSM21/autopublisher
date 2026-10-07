"""Uncertain remote outcomes are never retried silently (research.md §5, §7, §13)."""

import logging
import sqlite3
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app import publishing
from app.models import AttemptStage
from tests.conftest import (
    attempt_rows,
    create_publications,
    get_publication,
    publish_and_wait,
    set_youtube_options,
    setup_publishable,
)
from tests.fakes import FAKE_VIDEO_ID, FakeGoogle, UploadFault

CHUNK = 256 * 1024


def _ready(client: TestClient, fake_google: FakeGoogle) -> dict[str, Any]:
    created = setup_publishable(client, fake_google)
    set_youtube_options(client, created["publication"]["id"])
    return created


def _assert_ambiguous(publication: dict[str, Any], code: str) -> None:
    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    assert "check YouTube Studio" in attempt["error"]["message"]


def _stage(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT stage FROM publication_attempts ORDER BY id DESC"
        ).fetchone()
    stage: str = row[0]
    return stage


def test_lost_last_chunk_with_unknown_status_is_ambiguous(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="last_chunk")] + [
        UploadFault(on="status") for _ in range(5)
    ]

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_ambiguous(publication, "network_error")
    assert publication["latest_attempt"]["stage"] == "final_chunk"
    assert len(fake_google.session_starts) == 1


def test_incomplete_answer_after_the_last_chunk_resumes_safely(
    publishing_client: TestClient, fake_google: FakeGoogle, db_path: Path
) -> None:
    created = _ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="last_chunk", truncate_to=CHUNK)]
    seen: list[tuple[str, str]] = []
    fake_google.upload_hook = lambda kind, request: seen.append((kind, _stage(db_path)))

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "published"
    assert len(fake_google.videos_created) == 1
    last_chunks = [
        index for index, (kind, _) in enumerate(seen) if kind == "last_chunk"
    ]
    assert len(last_chunks) == 2
    assert all(seen[index][1] == "final_chunk" for index in last_chunks)
    between = seen[last_chunks[0] + 1 : last_chunks[1]]
    assert between
    assert all(stage == "uploading" for kind, stage in between)


def test_expired_session_on_the_last_chunk_is_ambiguous(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="last_chunk", status=404)]

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_ambiguous(publication, "upload_session_expired")
    assert len(fake_google.session_starts) == 1


@pytest.mark.parametrize("video_id", ["", "not-a-valid-video-id"])
def test_final_answer_without_a_valid_id_is_ambiguous(
    publishing_client: TestClient, fake_google: FakeGoogle, video_id: str
) -> None:
    created = _ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="last_chunk", video_id=video_id)]

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_ambiguous(publication, "unexpected_response")
    assert publication["latest_attempt"]["external_id"] is None


def test_last_chunk_is_not_sent_if_the_stage_cannot_be_saved(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _ready(publishing_client, fake_google)
    original = publishing.set_stage

    def failing_set_stage(
        ctx: publishing.PublishContext, attempt_id: int, stage: AttemptStage
    ) -> bool:
        if stage == AttemptStage.FINAL_CHUNK:
            return False
        return original(ctx, attempt_id, stage)

    monkeypatch.setattr(publishing, "set_stage", failing_set_stage)

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"]["code"] == "internal_error"
    assert attempt["outcome_determined"] is True
    kinds = [
        r.headers["content-range"]
        for r in fake_google.upload_requests
        if r.method == "PUT"
    ]
    total = created["content"]["size_bytes"]
    assert not any(header.endswith(f"-{total - 1}/{total}") for header in kinds)
    assert fake_google.videos_created == []


def test_result_that_cannot_be_saved_is_ambiguous_and_never_logged(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    created = _ready(publishing_client, fake_google)
    monkeypatch.setattr(publishing, "persist_success", lambda *args: False)

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"]["code"] == "result_not_saved"
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    (row,) = attempt_rows(db_path)
    assert row["external_id"] is None
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
    assert FAKE_VIDEO_ID not in dump
    assert FAKE_VIDEO_ID not in caplog.text
    assert len(fake_google.session_starts) == 1


# --- Publishing again after an uncertain outcome (FR-041) ----------------------------


def _ambiguous_failure(client: TestClient, fake_google: FakeGoogle) -> dict[str, Any]:
    created = _ready(client, fake_google)
    fake_google.upload_faults = [UploadFault(on="last_chunk", status=404)]
    publish_and_wait(client, created["publication"]["id"])
    return created


def _publish(client: TestClient, publication_id: int, **body: Any) -> httpx.Response:
    return client.post(f"/api/publications/{publication_id}/publish", json=body)


def _requires_check(client: TestClient, publication_id: int) -> bool:
    check = client.get(f"/api/publications/{publication_id}/publish-check").json()
    value: bool = check["requires_remote_check"]
    return value


def test_publishing_again_requires_confirming_the_manual_check(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ambiguous_failure(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    uploads_before = len(fake_google.upload_requests)

    assert _requires_check(publishing_client, publication_id) is True
    response = _publish(publishing_client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"
    assert len(fake_google.upload_requests) == uploads_before

    publication = publish_and_wait(
        publishing_client, publication_id, confirm_remote_checked=True
    )
    assert publication["status"] == "published"
    assert publication["attempt_count"] == 2


def test_the_rule_survives_cancel_and_reactivate(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ambiguous_failure(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    publishing_client.post(f"/api/publications/{publication_id}/cancel")
    publishing_client.post(f"/api/publications/{publication_id}/reactivate")

    response = _publish(publishing_client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"


def test_the_rule_applies_to_a_new_publication_of_the_same_pair(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ambiguous_failure(publishing_client, fake_google)
    publishing_client.post(f"/api/publications/{created['publication']['id']}/cancel")
    new = create_publications(
        publishing_client, created["content"]["id"], [created["account"]["id"]]
    )[0]
    set_youtube_options(publishing_client, new["id"])

    assert _requires_check(publishing_client, new["id"]) is True
    response = _publish(publishing_client, new["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"


def test_a_determined_failure_needs_no_confirmation(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ready(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    fake_google.upload_faults = [UploadFault(on="chunk", status=404)]
    failed = publish_and_wait(publishing_client, publication_id)
    assert failed["latest_attempt"]["outcome_determined"] is True

    assert _requires_check(publishing_client, publication_id) is False
    publication = publish_and_wait(publishing_client, publication_id)

    assert get_publication(publishing_client, publication_id)["status"] == "published"
    assert publication["attempt_count"] == 2
