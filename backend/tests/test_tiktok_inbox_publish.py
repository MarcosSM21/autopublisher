"""Send to TikTok with Upload to Inbox, single chunk (Feature 014, US2): one
`inbox/video/init/` with `source_info` only, the shared FILE_UPLOAD transfer and a
polling loop that stops at `SEND_TO_USER_INBOX`."""

import sqlite3
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    attempt_rows,
    get_publication,
    publish_tiktok,
    tiktok_attempts,
    tiktok_inbox_publication,
    tiktok_run_rows,
)
from tests.fakes import FAKE_TT_PUBLISH_ID_PREFIX, FakeTikTok

INBOX = {"status": "SEND_TO_USER_INBOX"}
PROCESSING = {"status": "PROCESSING_UPLOAD"}


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _send(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    if statuses is not None:
        fake_tiktok.statuses = statuses
    response = publish_tiktok(client, created["publication"]["id"])
    assert response.status_code == 202, response.text
    return created


def test_single_chunk_upload_to_inbox(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = _send(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    size = len(created["data"])

    # No Creator Info, one init, one PUT, then status reads until the inbox.
    assert fake_tiktok.calls() == ["inbox_init", "upload", "status", "status"]
    [body] = fake_tiktok.inbox_init_bodies()
    assert body == {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        }
    }
    assert fake_tiktok.requests_to("init") == []
    [put] = fake_tiktok.requests_to("upload")
    assert put.headers["content-range"] == f"bytes 0-{size - 1}/{size}"
    assert put.content == created["data"]

    publication = get_publication(client, publication_id)
    assert publication["status"] == "awaiting_user_action"
    assert publication["published_at"] is None
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert attempt["details"] == {
        "tiktok_mode": "INBOX_UPLOAD",
        "delivered_to_inbox": True,
    }
    assert attempt["warnings"] == []
    submitted = attempt["submitted"]
    assert submitted["mode"] == "INBOX_UPLOAD"
    assert submitted["source_info"] == body["source_info"]
    assert "post_info" not in submitted
    assert "caption" not in submitted
    assert submitted["video"]["size_bytes"] == size
    [run] = tiktok_run_rows(db_path)
    assert run["mode"] == "INBOX_UPLOAD"
    assert run["phase"] == "delivered"
    assert run["publish_id"] == f"{FAKE_TT_PUBLISH_ID_PREFIX}1"
    assert run["last_remote_status"] == "SEND_TO_USER_INBOX"
    assert run["delivered_to_inbox_at"] is not None
    assert run["user_published_at"] is None
    assert run["confirmed_bytes"] == size
    assert run["final_chunk_started_at"] is not None
    [row] = attempt_rows(db_path)
    assert row["stage"] == "done"
    assert row["bytes_sent"] == row["total_bytes"] == size


def test_inbox_needs_no_options_nor_consent(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)

    check = client.get(
        f"/api/publications/{created['publication']['id']}/publish-check"
    )

    assert check.json()["eligible"] is True, check.text
    assert fake_tiktok.requests == []


def test_publish_id_is_committed_before_the_first_byte(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    seen: list[tuple[Any, ...]] = []

    def read_from_a_fresh_connection(request: httpx.Request) -> None:
        with sqlite3.connect(db_path) as connection:
            seen.append(
                connection.execute(
                    "SELECT r.publish_id, r.final_chunk_started_at, r.phase, a.stage "
                    "FROM tiktok_publish_runs r JOIN publication_attempts a "
                    "ON a.id = r.attempt_id"
                ).fetchone()
            )

    fake_tiktok.hooks["upload"] = read_from_a_fresh_connection

    publish_tiktok(client, created["publication"]["id"])

    # The only chunk is the last one: publish_id and write-ahead are on record.
    [(publish_id, final_chunk_started_at, phase, stage)] = seen
    assert publish_id == f"{FAKE_TT_PUBLISH_ID_PREFIX}1"
    assert final_chunk_started_at is not None
    assert phase == "final_chunk"
    assert stage == "final_chunk"


def test_polling_stops_at_the_inbox(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # TikTok would keep answering: AutoPublisher must not read again.
    created = _send(
        client,
        fake_tiktok,
        monkeypatch,
        [INBOX, {"status": "PUBLISH_COMPLETE"}],
    )

    assert len(fake_tiktok.requests_to("status")) == 1
    publication = get_publication(client, created["publication"]["id"])
    assert publication["status"] == "awaiting_user_action"


def test_early_publish_complete_is_published(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = _send(
        client,
        fake_tiktok,
        monkeypatch,
        [
            PROCESSING,
            {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [1, 2]},
        ],
    )
    publication_id = created["publication"]["id"]

    publication = get_publication(client, publication_id)
    assert publication["status"] == "published"
    assert publication["published_at"] is not None
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["status"] == "succeeded"
    # Several posts may come from one publish_id: never an identity.
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "succeeded"
    assert run["user_published_at"] is not None
    assert run["delivered_to_inbox_at"] is None
    assert run["public_post_count"] == 2


def test_failed_status_is_a_determined_failure(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = _send(
        client,
        fake_tiktok,
        monkeypatch,
        [{"status": "FAILED", "fail_reason": "file_format_check_failed"}],
    )
    publication_id = created["publication"]["id"]

    assert get_publication(client, publication_id)["status"] == "failed"
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["status"] == "failed"
    assert attempt["outcome_determined"] is True
    assert attempt["error"]["code"] == "tiktok_video_rejected"
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "failed"
    assert run["fail_reason"] == "file_format_check_failed"


@pytest.mark.parametrize("status", ["PROCESSING_DOWNLOAD", "SOMETHING_NEW"])
def test_other_statuses_are_ambiguous(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    created = _send(client, fake_tiktok, monkeypatch, [{"status": status}])
    publication_id = created["publication"]["id"]

    assert get_publication(client, publication_id)["status"] == "failed"
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is False
    assert attempt["error"]["code"] == "tiktok_result_uncertain"
    assert len(fake_tiktok.requests_to("inbox_init")) == 1


def test_processing_window_expiry_is_reconcilable_never_a_success(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = _send(client, fake_tiktok, monkeypatch, [PROCESSING])
    publication_id = created["publication"]["id"]

    publication = get_publication(client, publication_id)
    assert publication["status"] == "failed"
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["status"] == "failed"
    assert attempt["outcome_determined"] is False
    assert attempt["error"]["code"] == "tiktok_processing_pending"
    [run] = tiktok_run_rows(db_path)
    # The same publish_id remains the only way to settle it.
    assert run["publish_id"] == f"{FAKE_TT_PUBLISH_ID_PREFIX}1"
    assert run["delivered_to_inbox_at"] is None
    assert len(fake_tiktok.requests_to("inbox_init")) == 1
    assert len(fake_tiktok.requests_to("status")) > 1


def test_inbox_init_is_never_repeated(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["inbox_init"] = "server_error"

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.calls() == ["inbox_init"]
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is True
    assert attempt["error"]["code"] == "tiktok_unavailable"
