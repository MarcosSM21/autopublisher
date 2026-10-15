"""Multi-chunk Upload to Inbox (Feature 014, US8): the shared FILE_UPLOAD transfer
with an injected chunk size (8 chunks of 512 B): sequential ranges, progress by
confirmed bytes, retries of intermediate chunks, the `416` policy, an expired
upload URL and a last chunk that is never resent."""

from datetime import datetime
from pathlib import Path

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
from tests.fakes import FakeClock, FakeTikTok, UploadAction


@pytest.fixture
def client(tiktok_chunked_client: TestClient) -> TestClient:
    return tiktok_chunked_client


def _ranges(fake: FakeTikTok) -> list[str]:
    return [r.headers["content-range"] for r in fake.requests_to("upload")]


def _ready(
    client: TestClient, fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> tuple[int, int]:
    created = tiktok_inbox_publication(client, fake, monkeypatch)
    return int(created["publication"]["id"]), len(created["data"])


def test_multi_chunk_upload_to_inbox(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    confirmed: list[int] = []
    fake_tiktok.hooks["upload"] = lambda request: confirmed.append(
        tiktok_run_rows(db_path)[0]["confirmed_bytes"]
    )

    publish_tiktok(client, publication_id)

    ranges = _ranges(fake_tiktok)
    assert len(ranges) == 8
    assert ranges[0] == f"bytes 0-511/{size}"
    assert ranges[-1] == f"bytes 3584-{size - 1}/{size}"
    assert confirmed == [0, 512, 1024, 1536, 2048, 2560, 3072, 3584]
    [body] = fake_tiktok.inbox_init_bodies()
    assert body == {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": 512,
            "total_chunk_count": 8,
        }
    }
    assert get_publication(client, publication_id)["status"] == ("awaiting_user_action")
    [run] = tiktok_run_rows(db_path)
    assert run["mode"] == "INBOX_UPLOAD"
    assert run["confirmed_bytes"] == size
    assert attempt_rows(db_path)[0]["bytes_sent"] == size


@pytest.mark.parametrize(
    "failure",
    [
        UploadAction(status=500, store=False),
        UploadAction(status=503, store=False),
        UploadAction(raise_="transport"),
    ],
    ids=["500", "503", "transport"],
)
def test_intermediate_failures_are_retried_on_the_same_buffer(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    failure: UploadAction,
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [UploadAction(), failure, failure, failure]
    times: list[datetime] = []
    fake_tiktok.hooks["upload"] = lambda request: times.append(fake_clock.now())

    publish_tiktok(client, publication_id)

    requests = fake_tiktok.requests_to("upload")
    assert len(requests) == 8 + 3
    retried = requests[1:5]
    assert {r.headers["content-range"] for r in retried} == {
        requests[1].headers["content-range"]
    }
    assert {r.content for r in retried} == {requests[1].content}
    waits = [
        round((b - a).total_seconds())
        for a, b in zip(times[1:4], times[2:5], strict=True)
    ]
    assert waits == [2, 5, 10]
    assert fake_tiktok.calls().count("inbox_init") == 1
    assert get_publication(client, publication_id)["status"] == ("awaiting_user_action")


def test_416_is_accepted_only_when_tiktok_holds_exactly_the_chunk(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [
        UploadAction(status=416, content_range=f"bytes 0-512/{size}")
    ]

    publish_tiktok(client, publication_id)

    assert len(_ranges(fake_tiktok)) == 8
    assert get_publication(client, publication_id)["status"] == ("awaiting_user_action")


def test_other_416_answers_are_determined(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [
        UploadAction(status=416, content_range=f"bytes 0-511/{size}", store=False)
    ]

    publish_tiktok(client, publication_id)

    assert len(fake_tiktok.requests_to("upload")) == 1
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_upload_failed"
    assert attempt["outcome_determined"] is True
    assert "Nothing was sent to TikTok." in attempt["error"]["message"]
    assert tiktok_run_rows(db_path)[0]["final_chunk_started_at"] is None


def test_expired_upload_url(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [
        UploadAction(),
        UploadAction(status=403, store=False),
    ]

    publish_tiktok(client, publication_id)

    assert len(fake_tiktok.requests_to("upload")) == 2
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_upload_expired"
    assert attempt["outcome_determined"] is True
    assert fake_tiktok.requests_to("status") == []


@pytest.mark.parametrize(
    "action",
    [
        UploadAction(status=500),
        UploadAction(raise_="timeout"),
        UploadAction(status=400),
        UploadAction(status=416),
    ],
    ids=["500", "timeout", "400", "416"],
)
def test_last_chunk_is_never_resent_and_only_the_status_decides(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    action: UploadAction,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [UploadAction()] * 7 + [action]
    fake_tiktok.statuses = [{"status": "SEND_TO_USER_INBOX"}]

    publish_tiktok(client, publication_id)

    ranges = _ranges(fake_tiktok)
    assert ranges.count(f"bytes 3584-{size - 1}/{size}") == 1
    assert len(ranges) == 8
    # TikTok's status of the same publish_id is what counts.
    assert get_publication(client, publication_id)["status"] == ("awaiting_user_action")
    [run] = tiktok_run_rows(db_path)
    assert run["final_chunk_http_status"] == action.status


def test_deadline_before_the_write_ahead_is_determined(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    calls: list[int] = []

    def slow(request: httpx.Request) -> None:
        calls.append(1)
        if len(calls) == 3:
            fake_clock.advance(51 * 60)

    fake_tiktok.hooks["upload"] = slow

    publish_tiktok(client, publication_id)

    assert len(fake_tiktok.requests_to("upload")) == 3
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_upload_expired"
    assert attempt["outcome_determined"] is True
    assert fake_tiktok.requests_to("status") == []
