"""Resumable upload protocol in isolation (research.md §3 and §5)."""

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

import httpx2 as httpx
import pytest

from app import youtube_upload
from app.publishing import PublishFailure
from app.youtube_upload import ResumableUpload, UploadRequest, YouTubeUploadSettings
from tests.fakes import FAKE_ACCESS_TOKEN, FAKE_VIDEO_ID, FakeGoogle, UploadFault

CHUNK = 256 * 1024
SLICE = 32 * 1024
SIZE = 3 * CHUNK + 1234


class RecordingReporter:
    def __init__(self, events: list[str], confirm_final: bool = True) -> None:
        self.events = events
        self.confirm_final = confirm_final
        self.sent: list[int] = []

    def report_bytes(self, sent: int, *, confirmed: bool = False) -> None:
        self.sent.append(sent)

    def enter_final_chunk(self) -> bool:
        self.events.append("enter_final_chunk")
        return self.confirm_final

    def leave_final_chunk(self) -> None:
        self.events.append("leave_final_chunk")

    def should_stop(self) -> bool:
        return False


class CountingFile(io.BufferedReader):
    reads: list[int] = []

    def read(self, size: int | None = -1, /) -> bytes:
        CountingFile.reads.append(-1 if size is None else size)
        return super().read(size)


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "video.mp4"
    path.write_bytes(bytes(range(256)) * (SIZE // 256) + b"x" * (SIZE % 256))
    return path


@pytest.fixture
def fake() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def client(fake: FakeGoogle) -> Iterator[httpx.Client]:
    with httpx.Client(transport=fake.transport()) as http_client:
        yield http_client


@pytest.fixture
def counting_open(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    CountingFile.reads = []

    def open_media(path: Path) -> BinaryIO:
        return CountingFile(io.FileIO(path, "rb"))

    monkeypatch.setattr(youtube_upload, "open_media", open_media)
    return CountingFile.reads


def _request(video: Path) -> UploadRequest:
    return UploadRequest(
        file_path=video,
        total_bytes=video.stat().st_size,
        mime_type="video/mp4",
        resource={"snippet": {"title": "T"}, "status": {"privacyStatus": "private"}},
        notify_subscribers=False,
    )


def _upload(client: httpx.Client) -> ResumableUpload:
    settings = YouTubeUploadSettings(
        chunk_size=CHUNK, slice_size=SLICE, sleep=lambda seconds: None
    )
    return ResumableUpload(client, settings)


def _token(force_refresh: bool) -> str:
    return FAKE_ACCESS_TOKEN


def _starts(fake: FakeGoogle) -> list[int]:
    return [
        int(r.headers["content-range"][len("bytes ") :].split("-")[0])
        for r in fake.upload_requests
        if r.method == "PUT" and not r.headers["content-range"].startswith("bytes */")
    ]


def test_streams_the_file_in_slices_and_returns_the_video(
    client: httpx.Client, fake: FakeGoogle, video: Path, counting_open: list[int]
) -> None:
    reporter = RecordingReporter([])

    resource: dict[str, Any] = _upload(client).run(_request(video), reporter, _token)

    assert resource["id"] == FAKE_VIDEO_ID
    assert fake.videos_created[0]["data"] == video.read_bytes()
    assert counting_open
    assert max(counting_open) <= SLICE
    assert all(size > 0 for size in counting_open)
    assert reporter.sent[-1] == SIZE
    assert _starts(fake) == [0, CHUNK, 2 * CHUNK, 3 * CHUNK]


def test_follows_the_confirmed_range(
    client: httpx.Client, fake: FakeGoogle, video: Path
) -> None:
    fake.upload_faults = [UploadFault(on="chunk", truncate_to=100_000)]

    resource = _upload(client).run(_request(video), RecordingReporter([]), _token)

    assert resource["id"] == FAKE_VIDEO_ID
    assert _starts(fake)[:2] == [0, 100_000]
    assert fake.videos_created[0]["data"] == video.read_bytes()


def test_308_without_range_restarts_from_zero(
    client: httpx.Client, fake: FakeGoogle, video: Path
) -> None:
    fake.upload_faults = [UploadFault(on="chunk", truncate_to=0)]

    _upload(client).run(_request(video), RecordingReporter([]), _token)

    assert _starts(fake)[:2] == [0, 0]
    assert fake.videos_created[0]["data"] == video.read_bytes()


def test_final_chunk_stage_is_entered_right_before_the_last_chunk(
    client: httpx.Client, fake: FakeGoogle, video: Path
) -> None:
    events: list[str] = []
    fake.upload_hook = lambda kind, request: events.append(kind)

    _upload(client).run(_request(video), RecordingReporter(events), _token)

    assert events == [
        "start",
        "chunk",
        "chunk",
        "chunk",
        "enter_final_chunk",
        "last_chunk",
    ]


def test_last_chunk_is_never_sent_if_the_stage_was_not_saved(
    client: httpx.Client, fake: FakeGoogle, video: Path
) -> None:
    events: list[str] = []
    fake.upload_hook = lambda kind, request: events.append(kind)

    with pytest.raises(PublishFailure) as failure:
        _upload(client).run(
            _request(video), RecordingReporter(events, confirm_final=False), _token
        )

    assert failure.value.code == "internal_error"
    assert failure.value.determined is True
    assert "last_chunk" not in events
    assert fake.videos_created == []


def test_backoff_is_capped(client: httpx.Client, fake: FakeGoogle, video: Path) -> None:
    sleeps: list[float] = []
    settings = YouTubeUploadSettings(
        chunk_size=CHUNK,
        slice_size=SLICE,
        max_consecutive_failures=8,
        sleep=sleeps.append,
    )
    fake.upload_faults = [UploadFault(on="put", status=503) for _ in range(7)]

    ResumableUpload(client, settings).run(
        _request(video), RecordingReporter([]), _token
    )

    assert len(sleeps) == 7
    for base, waited in zip([1, 2, 4, 8, 16, 32, 32], sleeps, strict=True):
        assert base <= waited <= min(base * 1.2, 32)
