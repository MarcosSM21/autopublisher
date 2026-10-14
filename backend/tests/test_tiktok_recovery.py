"""Interruptions and restarts (spec US6, research §18): the generic recovery decides
by stage and never resumes an upload; a later read-only reconciliation of the
original publish_id settles the uncertain cases."""

import sqlite3
import threading
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import AttemptTrigger, Platform, Publication
from app.publishing import (
    _AttemptReporter,
    create_running_attempt,
    persist_failure,
    recover_interrupted_attempts,
)
from tests.conftest import (
    get_publication,
    publish_tiktok,
    tiktok_attempts,
    tiktok_ready_publication,
    tiktok_run_rows,
)
from tests.fakes import FakeTikTok, UploadAction


@pytest.fixture
def client(tiktok_chunked_client: TestClient) -> TestClient:
    return tiktok_chunked_client


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _run_until_stopped(
    client: TestClient, publication_id: int, stop: threading.Event
) -> tuple[int, Any]:
    """Run the TikTok upload in this thread with a reporter whose shutdown flag is
    `stop`; return the attempt id and the failure raised."""
    app = _app(client)
    ctx = app.state.publish_context
    publisher = app.state.publishers[Platform.TIKTOK]
    with ctx.session_factory() as session:
        publication = session.get_one(Publication, publication_id)
        prepared = publisher.prepare(session, publication, ctx)
        attempt_id = create_running_attempt(
            session, publication, prepared, "tiktok", trigger=AttemptTrigger.MANUAL
        )
    reporter = _AttemptReporter(ctx, attempt_id, stop)
    try:
        publisher.upload(prepared, reporter, ctx)
    except Exception as failure:
        persist_failure(
            ctx,
            attempt_id,
            failure.code,  # type: ignore[attr-defined]
            failure.message,  # type: ignore[attr-defined]
            determined=failure.determined,  # type: ignore[attr-defined]
        )
        return attempt_id, failure
    raise AssertionError("the upload was expected to stop")


def test_shutdown_during_intermediate_chunks_is_determined(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    stop = threading.Event()
    sent: list[int] = []

    def stop_after_two(request: httpx.Request) -> None:
        sent.append(1)
        if len(sent) == 2:
            stop.set()

    fake_tiktok.hooks["upload"] = stop_after_two

    _, failure = _run_until_stopped(client, created["publication"]["id"], stop)

    assert failure.code == "interrupted"
    assert failure.determined is True
    assert len(fake_tiktok.requests_to("upload")) == 2
    assert fake_tiktok.requests_to("status") == []


def test_shutdown_during_polling_is_uncertain(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    stop = threading.Event()
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]
    fake_tiktok.hooks["status"] = lambda request: stop.set()

    _, failure = _run_until_stopped(client, created["publication"]["id"], stop)

    assert failure.code == "tiktok_processing_pending"
    assert failure.determined is False
    assert len(fake_tiktok.requests_to("upload")) == 8


@pytest.mark.parametrize(
    ("statuses", "code"),
    [
        ([{"status": "PROCESSING_UPLOAD"}], "tiktok_processing_pending"),
        ([{"status": "PROCESSING_DOWNLOAD"}], "tiktok_result_uncertain"),
        ([{"status": "SEND_TO_USER_INBOX"}], "tiktok_result_uncertain"),
        ([{"status": "SOMETHING_NEW"}], "tiktok_result_uncertain"),
    ],
)
def test_unsettled_results_are_uncertain_and_reconciled_later(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[Any],
    code: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    fake_tiktok.statuses = statuses

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is False
    fake_tiktok.statuses = [{"status": "PUBLISH_COMPLETE"}]
    client.get(f"/api/publications/{publication_id}/publish-check")
    assert get_publication(client, publication_id)["status"] == "published"


# --- Restart: the generic recovery, by stage and without network -------------------


def _left_running(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    *,
    stage: str,
    run: dict[str, Any] | None,
) -> int:
    """A publication whose attempt was left `running` at `stage` by a process that
    stopped, with the TikTok run it had saved (None: no run)."""
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = int(created["publication"]["id"])
    size = len(created["data"])
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE publications SET status = 'publishing' WHERE id = ?",
            (publication_id,),
        )
        cursor = connection.execute(
            "INSERT INTO publication_attempts (publication_id, platform, trigger, "
            "status, stage, started_at, bytes_sent, total_bytes, submitted, "
            "details, warnings) VALUES (?, 'tiktok', 'manual', 'running', ?, "
            "'2026-10-14 10:00:00', 0, ?, '{}', '{}', '[]')",
            (publication_id, stage, size),
        )
        attempt_id = cursor.lastrowid
        if run is not None:
            values = {
                "attempt_id": attempt_id,
                "publication_id": publication_id,
                "phase": "preparing",
                "video_size": size,
                "chunk_size": 512,
                "total_chunk_count": 8,
                "confirmed_bytes": 0,
                "created_at": "2026-10-14 10:00:00",
                "updated_at": "2026-10-14 10:00:00",
                **run,
            }
            columns = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            connection.execute(
                f"INSERT INTO tiktok_publish_runs ({columns}) VALUES ({marks})",
                tuple(values.values()),
            )
    assert attempt_id is not None
    return publication_id


def _recover(client: TestClient) -> None:
    recover_interrupted_attempts(_app(client).state.session_factory)


@pytest.mark.parametrize(
    ("stage", "run"),
    [
        ("preparing", None),
        ("preparing", {"phase": "initializing"}),
        (
            "uploading",
            {"phase": "uploading", "publish_id": "v_pub_file~v2-fake.9"},
        ),
    ],
    ids=["no_run", "no_publish_id", "publish_id_without_write_ahead"],
)
def test_restart_before_the_write_ahead_is_determined(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    stage: str,
    run: dict[str, Any] | None,
) -> None:
    publication_id = _left_running(
        client, fake_tiktok, monkeypatch, db_path, stage=stage, run=run
    )

    _recover(client)
    check = client.get(f"/api/publications/{publication_id}/publish-check").json()

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is True
    assert check["requires_remote_check"] is False
    # Nothing is resumed and no new Direct Post is initialized.
    assert fake_tiktok.requests == []


@pytest.mark.parametrize("stage", ["final_chunk", "finalizing"])
def test_restart_after_the_write_ahead_is_uncertain_then_reconciled(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    stage: str,
) -> None:
    publication_id = _left_running(
        client,
        fake_tiktok,
        monkeypatch,
        db_path,
        stage=stage,
        run={
            "phase": stage if stage == "final_chunk" else "processing",
            "publish_id": "v_pub_file~v2-fake.9",
            "final_chunk_started_at": "2026-10-14 10:00:05",
        },
    )
    fake_tiktok.published_ids.append("v_pub_file~v2-fake.9")

    _recover(client)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is False
    assert fake_tiktok.requests == []
    fake_tiktok.statuses = [{"status": "PUBLISH_COMPLETE"}]
    client.get(f"/api/publications/{publication_id}/publish-check")
    assert fake_tiktok.calls() == ["status"]
    assert get_publication(client, publication_id)["status"] == "published"
    assert tiktok_run_rows(db_path)[0]["phase"] == "succeeded"


def test_restart_after_the_write_ahead_then_failed_is_determined(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _left_running(
        client,
        fake_tiktok,
        monkeypatch,
        db_path,
        stage="finalizing",
        run={
            "phase": "processing",
            "publish_id": "v_pub_file~v2-fake.9",
            "final_chunk_started_at": "2026-10-14 10:00:05",
        },
    )
    fake_tiktok.published_ids.append("v_pub_file~v2-fake.9")
    _recover(client)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "internal"}]

    client.get(f"/api/publications/{publication_id}/publish-check")

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is True
    assert attempt["error"]["code"] == "tiktok_publish_failed"


def test_intermediate_failure_after_retries_never_reaches_the_last_chunk(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [UploadAction(raise_="transport")] * 4

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
