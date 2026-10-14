"""Multi-chunk FILE_UPLOAD (spec US7, research §9–§12): bounded retries of
intermediate chunks on the same buffer, the conservative `416` policy, the upload
deadline and, for the last chunk, the semantics fixed before V1 (sent once; any
non-201 only leads to the status of the original publish_id)."""

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app.tiktok_gateway import UploadProgress
from app.tiktok_publishing import _confirms_chunk
from tests.conftest import (
    attempt_rows,
    get_publication,
    publish_tiktok,
    tiktok_attempts,
    tiktok_ready_publication,
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
    created = tiktok_ready_publication(client, fake, monkeypatch)
    return int(created["publication"]["id"]), len(created["data"])


def test_multi_chunk_happy_path(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    confirmed: list[int] = []

    def record(request: httpx.Request) -> None:
        confirmed.append(tiktok_run_rows(db_path)[0]["confirmed_bytes"])

    fake_tiktok.hooks["upload"] = record

    publish_tiktok(client, publication_id)

    ranges = _ranges(fake_tiktok)
    assert len(ranges) == 8
    assert ranges[0] == f"bytes 0-511/{size}"
    assert ranges[6] == f"bytes 3072-3583/{size}"
    assert ranges[-1] == f"bytes 3584-{size - 1}/{size}"
    # Progress only advances with bytes TikTok confirmed.
    assert confirmed == [0, 512, 1024, 1536, 2048, 2560, 3072, 3584]
    [body] = fake_tiktok.init_bodies()
    assert body["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": size,
        "chunk_size": 512,
        "total_chunk_count": 8,
    }
    assert get_publication(client, publication_id)["status"] == "published"
    [run] = tiktok_run_rows(db_path)
    assert run["confirmed_bytes"] == size
    assert attempt_rows(db_path)[0]["bytes_sent"] == size


@pytest.mark.parametrize(
    "failure",
    [
        UploadAction(status=500, store=False),
        UploadAction(status=503, store=False),
        UploadAction(status=429, store=False),
        UploadAction(raise_="transport"),
        UploadAction(raise_="timeout"),
    ],
    ids=["500", "503", "429", "transport", "timeout"],
)
def test_intermediate_temporary_failures_are_retried_on_the_same_buffer(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    failure: UploadAction,
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    # Chunk 1 fails three times, then succeeds.
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
    assert fake_tiktok.calls().count("init") == 1
    # A retried buffer never enters the digest twice: the upload completes.
    assert get_publication(client, publication_id)["status"] == "published"


def test_exhausted_retries_are_determined_and_the_last_chunk_is_never_sent(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [UploadAction(status=503, store=False)] * 4

    publish_tiktok(client, publication_id)

    assert len(fake_tiktok.requests_to("upload")) == 4
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_upload_failed"
    assert attempt["outcome_determined"] is True
    assert tiktok_run_rows(db_path)[0]["final_chunk_started_at"] is None
    assert fake_tiktok.requests_to("status") == []


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "tiktok_upload_failed"),
        (404, "tiktok_upload_failed"),
        (403, "tiktok_upload_expired"),
    ],
)
def test_intermediate_rejections_are_not_retried(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [
        UploadAction(),
        UploadAction(status=status, store=False),
    ]

    publish_tiktok(client, publication_id)

    assert len(fake_tiktok.requests_to("upload")) == 2
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True


V2_TOTAL = 67_686_392


@pytest.mark.parametrize(
    ("progress", "last", "confirmed"),
    [
        # Request `bytes 0-33554431/…` answered `bytes 0-33554432/…` (V2 real).
        (UploadProgress(33_554_432, V2_TOTAL), 33_554_431, True),
        # A second intermediate chunk `bytes 33554432-67108863/…`.
        (UploadProgress(67_108_864, V2_TOTAL), 67_108_863, True),
        (UploadProgress(33_554_431, V2_TOTAL), 33_554_431, False),
        (UploadProgress(33_554_000, V2_TOTAL), 33_554_431, False),
        (UploadProgress(33_554_433, V2_TOTAL), 33_554_431, False),
        (UploadProgress(67_108_864, V2_TOTAL), 33_554_431, False),
        (UploadProgress(33_554_432, V2_TOTAL + 1), 33_554_431, False),
        (UploadProgress(33_554_432, None), 33_554_431, False),
        (None, 33_554_431, False),
    ],
    ids=[
        "accepted",
        "second_chunk_accepted",
        "equals_last_byte",
        "behind",
        "one_ahead",
        "next_chunk",
        "other_total",
        "unknown_total",
        "missing",
    ],
)
def test_416_confirms_a_chunk_only_with_last_plus_one_accepted_bytes(
    progress: UploadProgress | None, last: int, confirmed: bool
) -> None:
    assert _confirms_chunk(progress, last, V2_TOTAL) is confirmed


@pytest.mark.parametrize("index", [0, 1], ids=["first_chunk", "second_chunk"])
def test_416_confirming_the_retried_chunk_continues(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    index: int,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    # TikTok kept the chunk but its answer was lost: the retry gets a 416 whose
    # Content-Range counts exactly the bytes up to the end of that chunk
    # (`bytes 0-{last + 1}/{size}`).
    fake_tiktok.upload_actions = [UploadAction()] * index + [
        UploadAction(raise_="lost")
    ]

    publish_tiktok(client, publication_id)

    first, last = 512 * index, 512 * index + 511
    ranges = _ranges(fake_tiktok)
    assert ranges[index : index + 3] == [
        f"bytes {first}-{last}/{size}",
        f"bytes {first}-{last}/{size}",
        f"bytes {last + 1}-{last + 512}/{size}",
    ]
    assert len(ranges) == 9
    assert get_publication(client, publication_id)["status"] == "published"


def test_explicit_416_with_the_chunk_accepted_continues(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [
        UploadAction(status=416, content_range=f"bytes 0-512/{size}")
    ]

    publish_tiktok(client, publication_id)

    ranges = _ranges(fake_tiktok)
    assert ranges[:2] == [f"bytes 0-511/{size}", f"bytes 512-1023/{size}"]
    assert len(ranges) == 8
    assert get_publication(client, publication_id)["status"] == "published"


# `{last}` is the inclusive last byte of the chunk sent; only `0-{last + 1}/{size}`
# would confirm it.
OTHER_416 = {
    "missing": None,
    "equals_last_byte": "bytes 0-{last}/{size}",
    "behind": "bytes 0-{behind}/{size}",
    "ahead": "bytes 0-{ahead}/{size}",
    "next_chunk": "bytes 0-{next_end}/{size}",
    "other_total": "bytes 0-{end}/{other_total}",
    "unknown_total": "bytes 0-{end}/*",
    "not_from_zero": "bytes 1-{end}/{size}",
    "unreadable": "garbage",
}


@pytest.mark.parametrize("index", [0, 1], ids=["first_chunk", "second_chunk"])
@pytest.mark.parametrize("content_range", OTHER_416.values(), ids=OTHER_416)
def test_other_416_answers_are_determined_before_the_write_ahead(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    content_range: str | None,
    index: int,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    last = 512 * index + 511
    header = (
        content_range.format(
            size=size,
            last=last,
            behind=last - 100,
            ahead=last + 2,
            next_end=last + 513,
            end=last + 1,
            other_total=size + 1,
        )
        if content_range
        else None
    )
    fake_tiktok.upload_actions = [UploadAction()] * index + [
        UploadAction(status=416, content_range=header, store=False)
    ]

    publish_tiktok(client, publication_id)

    assert len(fake_tiktok.requests_to("upload")) == index + 1
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_upload_failed"
    assert attempt["outcome_determined"] is True
    [run] = tiktok_run_rows(db_path)
    assert run["final_chunk_started_at"] is None
    assert run["confirmed_bytes"] == 512 * index
    assert len(fake_tiktok.published_ids) == 1


def test_upload_deadline_before_the_write_ahead(
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


def test_unexpected_201_before_the_last_chunk_is_uncertain(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.upload_actions = [UploadAction(status=201)]

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is False
    assert len(fake_tiktok.requests_to("upload")) == 1


LAST_FAILURES: dict[str, UploadAction] = {
    "500": UploadAction(status=500),
    "timeout": UploadAction(raise_="timeout"),
    "400": UploadAction(status=400),
    "404": UploadAction(status=404),
    "416": UploadAction(status=416),
}


def _fail_last(fake: FakeTikTok, action: UploadAction) -> None:
    fake.upload_actions = [UploadAction()] * 7 + [action]


@pytest.mark.parametrize("action", LAST_FAILURES.values(), ids=LAST_FAILURES)
def test_last_chunk_is_never_retried_and_processing_stays_uncertain(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    action: UploadAction,
) -> None:
    publication_id, size = _ready(client, fake_tiktok, monkeypatch)
    _fail_last(fake_tiktok, action)
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]

    publish_tiktok(client, publication_id)

    ranges = _ranges(fake_tiktok)
    assert ranges.count(f"bytes 3584-{size - 1}/{size}") == 1
    assert len(ranges) == 8
    [attempt] = tiktok_attempts(client, publication_id)
    # Not even a 4xx makes PROCESSING_UPLOAD a determined failure.
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    [run] = tiktok_run_rows(db_path)
    assert run["final_chunk_http_status"] == action.status


@pytest.mark.parametrize("action", LAST_FAILURES.values(), ids=LAST_FAILURES)
def test_last_chunk_failure_then_status_decides(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    action: UploadAction,
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    _fail_last(fake_tiktok, action)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "internal"}]

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is True
    assert attempt["error"]["code"] == "tiktok_publish_failed"
    assert len(fake_tiktok.requests_to("upload")) == 8


def test_uncertain_message_keeps_the_last_answer_as_diagnosis(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id, _ = _ready(client, fake_tiktok, monkeypatch)
    _fail_last(fake_tiktok, UploadAction(status=400))
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    message: Any = attempt["error"]["message"]
    assert "HTTP 400" in message
    assert "TikTok profile" in message
