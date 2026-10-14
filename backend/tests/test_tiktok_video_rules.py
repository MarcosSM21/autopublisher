"""Local video matrix for TikTok Direct Post (research §8). Nothing is transcoded,
copied or modified; ffprobe answers are simulated."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app import media
from app.media import StreamInfo, VideoStreams
from app.models import Content
from app.tiktok_media import (
    VIDEO_MAX_BYTES,
    duration_problems,
    inspect_video,
    video_check,
    video_mime,
)
from tests.conftest import tiktok_probe_streams


def _check(
    *,
    media_type: str = "video",
    media_format: str = "mp4",
    size: int = 1000,
    file_size: int | None = 1000,
    streams: VideoStreams | None = None,
    **video: Any,
) -> list[str]:
    probed = streams if streams is not None else tiktok_probe_streams(video=video)
    result = video_check(media_type, media_format, size, file_size, probed)
    return [problem.code for problem in result.problems]


def test_valid_video_has_no_problems_and_a_summary() -> None:
    result = video_check("video", "mp4", 1000, 1000, tiktok_probe_streams())

    assert result.problems == []
    assert result.delegated_checks == []
    assert result.summary is not None
    assert result.summary.format == "mp4"
    assert result.summary.size_bytes == 1000
    assert (result.summary.width, result.summary.height) == (1080, 1920)
    assert result.summary.duration_seconds == 12.4
    assert result.summary.frame_rate == 30.0


@pytest.mark.parametrize("media_format", ["mp4", "mov", "webm"])
def test_supported_containers(media_format: str) -> None:
    assert _check(media_format=media_format) == []


@pytest.mark.parametrize("media_format", ["jpeg", "png", "webp", "avi"])
def test_other_containers_are_rejected(media_format: str) -> None:
    assert "tiktok_video_incompatible" in _check(media_format=media_format)


def test_image_content_is_rejected() -> None:
    assert _check(media_type="image", media_format="png") == ["tiktok_video_required"]


def test_missing_file() -> None:
    assert _check(file_size=None) == ["media_unavailable"]


def test_size_mismatch_with_the_content() -> None:
    assert _check(size=1000, file_size=999) == ["media_unavailable"]


@pytest.mark.parametrize(
    ("size", "valid"), [(VIDEO_MAX_BYTES, True), (VIDEO_MAX_BYTES + 1, False)]
)
def test_size_limit(size: int, valid: bool) -> None:
    assert VIDEO_MAX_BYTES == 4_000_000_000
    codes = _check(size=size, file_size=size)

    assert (codes == []) is valid
    if not valid:
        assert codes == ["tiktok_video_incompatible"]


def test_ffprobe_unavailable_or_unreadable() -> None:
    result = video_check("video", "mp4", 1000, 1000, None)

    assert [p.code for p in result.problems] == ["tiktok_video_uninspectable"]
    assert result.summary is None


def test_no_video_stream() -> None:
    streams = tiktok_probe_streams(
        streams=(StreamInfo(codec_type="audio", codec_name="aac"),)
    )

    assert _check(streams=streams) == ["tiktok_video_incompatible"]


@pytest.mark.parametrize(
    ("codec", "valid"),
    [
        ("h264", True),
        ("hevc", True),
        ("vp8", True),
        ("vp9", True),
        ("av1", False),
        ("mpeg4", False),
        (None, False),
    ],
)
def test_codecs(codec: str | None, valid: bool) -> None:
    assert (_check(codec_name=codec) == []) is valid


@pytest.mark.parametrize(
    ("width", "height", "valid"),
    [
        (359, 1920, False),
        (360, 1920, True),
        (4096, 1920, True),
        (4097, 1920, False),
        (1080, 359, False),
        (1080, 360, True),
        (1080, 4096, True),
        (1080, 4097, False),
        (None, 1920, False),
    ],
)
def test_dimensions(width: int | None, height: int, valid: bool) -> None:
    assert (_check(width=width, height=height) == []) is valid


@pytest.mark.parametrize(
    ("duration", "valid"),
    [(0.0, False), (None, False), (0.5, True), (600.0, True), (601.0, False)],
)
def test_technical_duration(duration: float | None, valid: bool) -> None:
    streams = tiktok_probe_streams(duration_seconds=duration)

    assert (_check(streams=streams) == []) is valid


@pytest.mark.parametrize(
    ("duration", "max_duration", "valid"),
    [(180.0, 180, True), (180.5, 180, False), (12.4, 600, True), (301.0, 300, False)],
)
def test_duration_against_the_creator_maximum(
    duration: float, max_duration: int, valid: bool
) -> None:
    problems = duration_problems(duration, max_duration)

    assert (problems == []) is valid
    if not valid:
        assert [p.code for p in problems] == ["tiktok_video_too_long"]
        assert str(max_duration) in problems[0].message


@pytest.mark.parametrize(
    ("fps", "valid"),
    [
        (22.98, False),
        (22.99, True),
        (23.0, True),
        (23.976, True),
        (59.94, True),
        (60.0, True),
        (60.01, True),
        (60.02, False),
    ],
)
def test_frame_rate_bounds(fps: float, valid: bool) -> None:
    assert (_check(frame_rate=fps) == []) is valid


def test_missing_frame_rate_is_delegated_never_validated() -> None:
    result = video_check(
        "video", "webm", 1000, 1000, tiktok_probe_streams(video={"frame_rate": None})
    )

    assert result.problems == []
    assert result.delegated_checks == ["frame_rate"]
    assert result.summary is not None
    assert result.summary.frame_rate is None


@pytest.mark.parametrize(
    ("media_format", "mime"),
    [("mp4", "video/mp4"), ("mov", "video/quicktime"), ("webm", "video/webm")],
)
def test_mime_per_container(media_format: str, mime: str) -> None:
    assert video_mime(media_format) == mime


def test_inspection_never_changes_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "clip.mp4"
    data = bytes(range(256)) * 16
    path.write_bytes(data)
    probed: list[Path] = []

    def probe(file: Path) -> VideoStreams:
        probed.append(file)
        return tiktok_probe_streams()

    monkeypatch.setattr(media, "probe_video_streams", probe)
    content = Content(
        media_type="video",
        media_format="mp4",
        size_bytes=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
    )

    result = inspect_video(content, path)

    assert result.problems == []
    assert probed == [path]
    assert path.read_bytes() == data
    assert list(tmp_path.iterdir()) == [path]


def test_inspection_of_a_missing_file(tmp_path: Path) -> None:
    content = Content(media_type="video", media_format="mp4", size_bytes=10)

    result = inspect_video(content, tmp_path / "missing.mp4")

    assert [p.code for p in result.problems] == ["media_unavailable"]
