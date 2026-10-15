"""Upload to Inbox through interruptions and restarts (Feature 014, US6): never a
new upload on its own, Ready in TikTok survives a restart without any TikTok
request, and an ambiguous attempt is only settled with its own `publish_id`."""

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
    attempt_rows,
    get_publication,
    publish_tiktok,
    tiktok_attempts,
    tiktok_inbox_publication,
    tiktok_run_rows,
)
from tests.fakes import FakeTikTok

PUBLISH_ID = "v_inbox_file~v2-fake.9"


@pytest.fixture
def client(tiktok_chunked_client: TestClient) -> TestClient:
    return tiktok_chunked_client


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _recover(client: TestClient) -> int:
    return recover_interrupted_attempts(_app(client).state.session_factory)


def _check(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/publish-check")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _run_until_stopped(
    client: TestClient, publication_id: int, stop: threading.Event
) -> Any:
    """Run the upload in this thread with a reporter whose shutdown flag is `stop`;
    return the failure raised (already persisted)."""
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
        return failure
    raise AssertionError("the upload was expected to stop")


# --- Interruptions while running ------------------------------------------------------


def test_shutdown_during_intermediate_chunks_is_determined(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    stop = threading.Event()
    sent: list[int] = []

    def stop_after_two(request: httpx.Request) -> None:
        sent.append(1)
        if len(sent) == 2:
            stop.set()

    fake_tiktok.hooks["upload"] = stop_after_two

    failure = _run_until_stopped(client, created["publication"]["id"], stop)

    assert failure.code == "interrupted"
    assert failure.determined is True
    assert len(fake_tiktok.requests_to("upload")) == 2
    assert len(fake_tiktok.requests_to("inbox_init")) == 1
    assert fake_tiktok.requests_to("status") == []


def test_shutdown_while_waiting_for_the_inbox_is_ambiguous(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    stop = threading.Event()
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]
    fake_tiktok.hooks["status"] = lambda request: stop.set()

    failure = _run_until_stopped(client, created["publication"]["id"], stop)

    assert failure.code == "tiktok_processing_pending"
    assert failure.determined is False
    assert len(fake_tiktok.requests_to("inbox_init")) == 1


# --- Restart --------------------------------------------------------------------------


def _left_running(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    *,
    stage: str,
    run: dict[str, Any] | None,
) -> int:
    """An Upload to Inbox attempt left `running` at `stage` by a process that
    stopped, with the run it had saved (None: no run)."""
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
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
            "'2026-10-15 10:00:00', 0, ?, '{}', '{}', '[]')",
            (publication_id, stage, size),
        )
        attempt_id = cursor.lastrowid
        if run is not None:
            values = {
                "attempt_id": attempt_id,
                "publication_id": publication_id,
                "mode": "INBOX_UPLOAD",
                "phase": "preparing",
                "video_size": size,
                "chunk_size": 512,
                "total_chunk_count": 8,
                "confirmed_bytes": 0,
                "created_at": "2026-10-15 10:00:00",
                "updated_at": "2026-10-15 10:00:00",
                **run,
            }
            columns = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            connection.execute(
                f"INSERT INTO tiktok_publish_runs ({columns}) VALUES ({marks})",
                tuple(values.values()),
            )
    fake_tiktok.requests.clear()
    return publication_id


AFTER_WRITE_AHEAD = {
    "phase": "processing",
    "publish_id": PUBLISH_ID,
    "final_chunk_started_at": "2026-10-15 10:00:05",
}


@pytest.mark.parametrize(
    ("stage", "run"),
    [
        ("preparing", None),
        ("preparing", {"phase": "initializing"}),
        ("uploading", {"phase": "uploading", "publish_id": PUBLISH_ID}),
    ],
    ids=["before_init", "no_publish_id", "mid_chunks"],
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
    check = _check(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is True
    assert check["requires_remote_check"] is False
    # Nothing is resumed and nothing is sent to TikTok again.
    assert fake_tiktok.requests == []


def test_restart_keeps_ready_in_tiktok_without_any_request(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    publish_tiktok(client, publication_id)
    runs = tiktok_run_rows(db_path)
    attempts = attempt_rows(db_path)
    fake_tiktok.requests.clear()

    closed = _recover(client)

    assert closed == 0
    assert get_publication(client, publication_id)["status"] == ("awaiting_user_action")
    assert tiktok_run_rows(db_path) == runs
    assert attempt_rows(db_path) == attempts
    assert fake_tiktok.requests == []


@pytest.mark.parametrize(
    ("status", "publication_status", "phase", "determined"),
    [
        ({"status": "SEND_TO_USER_INBOX"}, "awaiting_user_action", "delivered", True),
        ({"status": "PUBLISH_COMPLETE"}, "published", "succeeded", True),
        (
            {"status": "FAILED", "fail_reason": "spam_risk"},
            "failed",
            "failed",
            True,
        ),
        ({"status": "PROCESSING_UPLOAD"}, "failed", "processing", False),
        ({"status": "SOMETHING_NEW"}, "failed", "processing", False),
    ],
    ids=["inbox", "published", "failed", "processing", "unknown"],
)
def test_restart_after_the_write_ahead_is_reconciled_with_its_publish_id(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    status: dict[str, Any],
    publication_status: str,
    phase: str,
    determined: bool,
) -> None:
    publication_id = _left_running(
        client,
        fake_tiktok,
        monkeypatch,
        db_path,
        stage="finalizing",
        run=AFTER_WRITE_AHEAD,
    )
    fake_tiktok.published_ids.append(PUBLISH_ID)
    _recover(client)
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is False
    fake_tiktok.statuses = [status]

    _check(client, publication_id)

    assert fake_tiktok.calls() == ["status"]
    [body] = [r for r in fake_tiktok.requests_to("status")]
    assert PUBLISH_ID.encode() in body.content
    publication = get_publication(client, publication_id)
    assert publication["status"] == publication_status
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is determined
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == phase
    if publication_status == "awaiting_user_action":
        assert attempt["status"] == "succeeded"
        assert attempt["external_id"] is None
        assert publication["published_at"] is None
        assert run["delivered_to_inbox_at"] is not None
    if publication_status == "published":
        assert run["user_published_at"] is not None
        assert attempt["external_id"] is None
    assert "inbox_init" not in fake_tiktok.calls()


def test_an_ambiguous_attempt_needs_a_manual_check_before_sending_again(
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
        run=AFTER_WRITE_AHEAD,
    )
    fake_tiktok.published_ids.append(PUBLISH_ID)
    _recover(client)
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]

    response = client.post(f"/api/publications/{publication_id}/publish", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"
    assert "inbox_init" not in fake_tiktok.calls()
    assert len(attempt_rows(db_path)) == 1
