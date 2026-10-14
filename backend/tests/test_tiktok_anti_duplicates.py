"""Never a duplicate TikTok post (spec US6, FR-034–FR-046, research §11–§14): one
`video/init/` per attempt at most, the `publish_id` committed before the first byte,
the write-ahead committed before the last chunk, the last chunk sent exactly once
and, whatever its answer, only the status of the original `publish_id` read."""

import sqlite3
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import publishing
from app.models import AttemptStage, Platform
from tests.conftest import (
    get_publication,
    publish_tiktok,
    stored_file,
    tiktok_attempts,
    tiktok_ready_publication,
    tiktok_run_rows,
)
from tests.fakes import (
    FakeTikTok,
    UploadAction,
)

ALLOWED_CALLS = {"creator_info", "init", "upload", "status", "refresh"}


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


@pytest.fixture
def chunked_client(tiktok_chunked_client: TestClient) -> TestClient:
    return tiktok_chunked_client


def _publisher(client: TestClient) -> Any:
    app = client.app
    assert isinstance(app, FastAPI)
    return app.state.publishers[Platform.TIKTOK]


def _assert_only_documented_calls(fake: FakeTikTok) -> None:
    assert set(fake.calls()) <= ALLOWED_CALLS
    assert fake.unexpected == []


@pytest.mark.parametrize(
    "fault", ["server_error", "timeout", "transport", "api_access_token_invalid"]
)
def test_init_is_never_repeated(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["init"] = fault

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.calls().count("init") == 1
    assert fake_tiktok.requests_to("upload") == []
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert attempt["error"]["code"] == "tiktok_unavailable"
    _assert_only_documented_calls(fake_tiktok)


def test_publish_id_is_committed_before_the_first_byte(
    chunked_client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(chunked_client, fake_tiktok, monkeypatch)
    seen: list[tuple[Any, ...]] = []

    def read_from_a_fresh_connection(request: httpx.Request) -> None:
        with sqlite3.connect(db_path) as connection:
            seen.append(
                connection.execute(
                    "SELECT r.publish_id, r.final_chunk_started_at, a.stage "
                    "FROM tiktok_publish_runs r JOIN publication_attempts a "
                    "ON a.id = r.attempt_id"
                ).fetchone()
            )

    fake_tiktok.hooks["upload"] = read_from_a_fresh_connection

    publish_tiktok(chunked_client, created["publication"]["id"])

    assert len(seen) == 8
    assert all(row[0] is not None for row in seen)
    # Intermediate chunks: no write-ahead yet; last chunk: write-ahead committed.
    assert all(row[1] is None and row[2] == "uploading" for row in seen[:-1])
    assert seen[-1][1] is not None
    assert seen[-1][2] == "final_chunk"
    assert get_publication(chunked_client, created["publication"]["id"])["status"] == (
        "published"
    )


def test_failed_publish_id_commit_sends_nothing(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publisher = _publisher(client)
    original = publisher._update_run

    def failing(ctx: Any, attempt_id: int, **values: Any) -> bool:
        if "publish_id" in values:
            return False
        return bool(original(ctx, attempt_id, **values))

    monkeypatch.setattr(publisher, "_update_run", failing)

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.requests_to("upload") == []
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is True
    assert attempt["status"] == "failed"


def test_failed_run_write_ahead_never_sends_the_last_chunk(
    chunked_client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(chunked_client, fake_tiktok, monkeypatch)
    publisher = _publisher(chunked_client)
    original = publisher._update_run

    def failing(ctx: Any, attempt_id: int, **values: Any) -> bool:
        if "final_chunk_started_at" in values:
            return False
        return bool(original(ctx, attempt_id, **values))

    monkeypatch.setattr(publisher, "_update_run", failing)

    publish_tiktok(chunked_client, created["publication"]["id"])

    assert len(fake_tiktok.requests_to("upload")) == 7
    [attempt] = tiktok_attempts(chunked_client, created["publication"]["id"])
    assert attempt["outcome_determined"] is True
    assert fake_tiktok.requests_to("status") == []


def test_failed_stage_write_ahead_never_sends_the_last_chunk(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    original = publishing.set_stage

    def failing(ctx: Any, attempt_id: int, stage: AttemptStage) -> bool:
        if stage == AttemptStage.FINAL_CHUNK:
            return False
        return original(ctx, attempt_id, stage)

    monkeypatch.setattr(publishing, "set_stage", failing)

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.requests_to("upload") == []
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is True


def test_last_put_201_polls_normally(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.calls().count("upload") == 1
    assert get_publication(client, created["publication"]["id"])["status"] == (
        "published"
    )


LAST_PUT_FAILURES = {
    "timeout": UploadAction(raise_="timeout"),
    "transport": UploadAction(raise_="transport"),
    "lost": UploadAction(raise_="lost"),
    "500": UploadAction(status=500),
    "503": UploadAction(status=503),
    "429": UploadAction(status=429),
    "400": UploadAction(status=400),
    "403": UploadAction(status=403),
    "404": UploadAction(status=404),
    "416": UploadAction(status=416),
    "unexpected": UploadAction(status=302),
}


def _fail_last_put(fake: FakeTikTok, action: UploadAction) -> None:
    fake.upload_actions = [action]


@pytest.mark.parametrize("action", LAST_PUT_FAILURES.values(), ids=LAST_PUT_FAILURES)
def test_non_201_last_put_then_publish_complete_is_a_success(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    action: UploadAction,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    _fail_last_put(fake_tiktok, action)
    fake_tiktok.statuses = [{"status": "PUBLISH_COMPLETE"}]

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.calls().count("upload") == 1
    assert fake_tiktok.calls().count("init") == 1
    assert get_publication(client, created["publication"]["id"])["status"] == (
        "published"
    )
    [run] = tiktok_run_rows(db_path)
    expected_status = action.status if action.raise_ is None else None
    assert run["final_chunk_http_status"] == expected_status
    _assert_only_documented_calls(fake_tiktok)


@pytest.mark.parametrize("action", LAST_PUT_FAILURES.values(), ids=LAST_PUT_FAILURES)
def test_non_201_last_put_then_failed_is_determined(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    action: UploadAction,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    _fail_last_put(fake_tiktok, action)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "internal"}]

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.calls().count("upload") == 1
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is True
    assert attempt["error"]["code"] == "tiktok_publish_failed"


@pytest.mark.parametrize("action", LAST_PUT_FAILURES.values(), ids=LAST_PUT_FAILURES)
def test_non_201_last_put_still_processing_is_uncertain(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    action: UploadAction,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    _fail_last_put(fake_tiktok, action)
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD", "uploaded_bytes": 0}]

    publish_tiktok(client, created["publication"]["id"])

    # Not even a 4xx nor `uploaded_bytes < total` allows sending it again.
    assert fake_tiktok.calls().count("upload") == 1
    assert fake_tiktok.calls().count("init") == 1
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    assert attempt["error"]["code"] in (
        "tiktok_processing_pending",
        "tiktok_result_uncertain",
    )
    _assert_only_documented_calls(fake_tiktok)


@pytest.mark.parametrize(
    "fault", ["server_error", "transport", "bad_json", "api_invalid_publish_id"]
)
def test_status_read_errors_after_the_last_chunk_are_uncertain(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["status"] = fault

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is False
    assert attempt["error"]["code"] == "tiktok_result_uncertain"
    assert fake_tiktok.calls().count("upload") == 1
    assert fake_tiktok.calls().count("init") == 1


@pytest.mark.parametrize("status", ["PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX", "NEW"])
def test_unexpected_statuses_are_never_a_success(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    status: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": status}]

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["outcome_determined"] is False
    assert attempt["error"]["code"] == "tiktok_result_uncertain"
    assert len(fake_tiktok.requests_to("status")) == 1
    assert tiktok_run_rows(db_path)[0]["last_remote_status"] == "UNEXPECTED"


def test_no_second_publish_id_is_ever_requested(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [UploadAction(raise_="timeout")]
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]

    publish_tiktok(client, created["publication"]["id"])

    assert fake_tiktok.published_ids == ["v_pub_file~v2-fake.1"]
    statuses = {r.content for r in fake_tiktok.requests_to("status")}
    assert statuses == {b'{"publish_id": "v_pub_file~v2-fake.1"}'}


def test_digest_mismatch_during_upload_never_sends_the_last_chunk(
    chunked_client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(chunked_client, fake_tiktok, monkeypatch)
    path = stored_file(media_dir, db_path, created["content"]["id"])

    def change_the_file(request: httpx.Request) -> None:
        data = bytearray(path.read_bytes())
        data[-1] ^= 0xFF
        path.write_bytes(bytes(data))

    # The file changes after the preflight digest, while chunks are uploaded.
    fake_tiktok.hooks["init"] = change_the_file

    publish_tiktok(chunked_client, created["publication"]["id"])

    assert len(fake_tiktok.requests_to("upload")) == 7
    [attempt] = tiktok_attempts(chunked_client, created["publication"]["id"])
    assert attempt["error"]["code"] == "tiktok_video_changed"
    assert attempt["outcome_determined"] is True
    [run] = tiktok_run_rows(db_path)
    assert run["final_chunk_started_at"] is None
    assert fake_tiktok.requests_to("status") == []


def test_the_upload_reads_the_file_once_in_chunk_buffers(
    chunked_client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tiktok_ready_publication(chunked_client, fake_tiktok, monkeypatch)
    size = len(created["data"])
    opened: list[list[int]] = []
    original_open = Path.open

    class Spy:
        def __init__(self, file: Any) -> None:
            self.file = file
            self.sizes: list[int] = []
            opened.append(self.sizes)

        def read(self, amount: int = -1) -> bytes:
            data = bytes(self.file.read(amount))
            self.sizes.append(len(data))
            return data

        def seek(self, *args: Any) -> int:
            return int(self.file.seek(*args))

        def __enter__(self) -> "Spy":
            return self

        def __exit__(self, *args: object) -> None:
            self.file.close()

    def spy_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".mp4":
            return Spy(original_open(self, *args, **kwargs))
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy_open)

    publish_tiktok(chunked_client, created["publication"]["id"])

    # Two reads of the whole file: the preflight digest and the upload itself.
    assert len(opened) == 2
    preflight, upload = opened
    assert sum(preflight) == size
    assert sum(upload) == size
    # Never more than one chunk buffer (the last chunk is below 2 × 512 B).
    assert max(upload) < 1024
    assert len([n for n in upload if n > 0]) == 8
