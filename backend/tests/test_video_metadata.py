"""Video metadata removal (Feature 016, research §8). Tiny synthetic videos are
made with ffmpeg here; only our contract is checked: sentinels gone, streams
copied as they were (no re-encoding), duration and rotation kept."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.video_metadata import FfmpegMissing, inspect_video_metadata, sanitize_video

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
SENTINELS = [
    b"SENTINEL_WORKFLOW",
    b"KSampler",
    b"seed_987654321",
    b"lora_secret_style",
    b"SENTINEL_TITLE",
    b"SENTINEL_CHAPTER",
    b"+40.4168-003.7038",
    b"2026-01-02T03:04:05",
]
COMMENT = json.dumps(
    {
        "prompt": {"3": {"class_type": "KSampler", "seed": "seed_987654321"}},
        "workflow": {"id": "SENTINEL_WORKFLOW", "lora": "lora_secret_style"},
    }
)
CODECS = {
    "mp4": ["-c:v", "mpeg4", "-c:a", "aac"],
    "mov": ["-c:v", "mpeg4", "-c:a", "aac"],
    "webm": ["-c:v", "libvpx", "-c:a", "libopus"],
}


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _probe(path: Path) -> dict[str, Any]:
    output = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ],
        capture_output=True,
        check=True,
    ).stdout
    result: dict[str, Any] = json.loads(output)
    return result


def _stream_hashes(path: Path) -> str:
    """MD5 of the video and audio packets: equal only when nothing was
    re-encoded."""
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-map", "0:a"]
        + ["-c", "copy"]
        + ["-f", "streamhash", "-hash", "md5", "-"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout


def _rotation(probe: dict[str, Any]) -> float | None:
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    for data in video.get("side_data_list", []):
        if "rotation" in data:
            return float(data["rotation"])
    return None


def dirty_video(tmp_path: Path, fmt: str) -> Path:
    """Video + audio with a ComfyUI-like JSON comment, title, location, creation
    time and a chapter; MP4/MOV are also rotated 90°."""
    chapters = tmp_path / "chapters.txt"
    chapters.write_text(
        ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=500\n"
        "title=SENTINEL_CHAPTER\n"
    )
    plain = tmp_path / f"plain.{fmt}"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=64x48:rate=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-i",
        str(chapters),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-map_chapters",
        "2",
        "-t",
        "1",
        *CODECS[fmt],
        "-metadata",
        f"comment={COMMENT}",
        "-metadata",
        "title=SENTINEL_TITLE",
        "-metadata",
        "location=+40.4168-003.7038/",
        "-metadata",
        "creation_time=2026-01-02T03:04:05Z",
        "-metadata:s:v",
        "handler_name=SENTINEL_TITLE",
        str(plain),
    )
    if fmt == "webm":
        return plain
    rotated = tmp_path / f"dirty.{fmt}"
    _ffmpeg(
        "-display_rotation",
        "90",
        "-i",
        str(plain),
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
        str(rotated),
    )
    return rotated


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
@pytest.mark.parametrize("fmt", ["mp4", "mov", "webm"])
def test_dirty_video_is_sanitized(tmp_path: Path, fmt: str) -> None:
    dirty = dirty_video(tmp_path, fmt)
    assert all(sentinel in dirty.read_bytes() for sentinel in SENTINELS[:2])
    before = _probe(dirty)
    clean = tmp_path / f"clean.{fmt}"

    sanitize_video(dirty, clean, fmt)

    data = clean.read_bytes()
    for sentinel in SENTINELS:
        assert sentinel not in data, sentinel
    after = _probe(clean)
    assert after["chapters"] == []
    assert not {
        key for key in after["format"].get("tags", {}) if key.lower() != "encoder"
    } - {"major_brand", "minor_version", "compatible_brands"}
    # Same streams, copied packet for packet (no re-encoding).
    assert [s["codec_type"] for s in after["streams"]] == ["video", "audio"]
    assert _stream_hashes(clean) == _stream_hashes(dirty)
    assert float(after["format"]["duration"]) == pytest.approx(
        float(before["format"]["duration"]), abs=0.05
    )
    if fmt != "webm":
        assert _rotation(before) is not None
        assert _rotation(after) == _rotation(before)
    # Inspection: ComfyUI and location before, nothing after.
    found = {f.category for f in inspect_video_metadata(dirty).findings}
    assert {"comfyui", "location", "dates"} <= found
    assert inspect_video_metadata(clean).findings == []


def test_missing_ffmpeg_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(FfmpegMissing):
        sanitize_video(tmp_path / "in.mp4", tmp_path / "out.mp4", "mp4")
