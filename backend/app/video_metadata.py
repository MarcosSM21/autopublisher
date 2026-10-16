"""Metadata removal for MP4, MOV and WebM videos with ffmpeg stream copy.

Only the video streams (without attached pictures) and the audio streams are
kept, copied without re-encoding; global and per-stream tags, chapters and data,
subtitle, attachment and timecode tracks are dropped (research §8). The rotation
is stream side data and survives the copy. ffmpeg is only needed for this action.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.image_metadata import FileMetadataReport, FindingCollector
from app.models import MediaFormat

logger = logging.getLogger(__name__)

SANITIZE_TIMEOUT_SECONDS = 600
MUXERS = {MediaFormat.MP4: "mp4", MediaFormat.MOV: "mov", MediaFormat.WEBM: "webm"}

FFMPEG_MISSING_MESSAGE = (
    "Removing metadata from videos needs ffmpeg. Install it and try again."
)
SANITIZE_FAILED_MESSAGE = "The metadata could not be removed from this video."


class FfmpegMissing(Exception):
    def __init__(self) -> None:
        super().__init__(FFMPEG_MISSING_MESSAGE)
        self.message = FFMPEG_MISSING_MESSAGE


class SanitizeFailed(Exception):
    def __init__(self) -> None:
        super().__init__(SANITIZE_FAILED_MESSAGE)
        self.message = SANITIZE_FAILED_MESSAGE


def sanitize_video(src: Path, dst: Path, fmt: MediaFormat | str) -> None:
    """Write to `dst` the video of `src` without metadata. `dst` may hold a
    partial file after a failure; the caller discards it."""
    media_format = MediaFormat(fmt)
    muxer = MUXERS[media_format]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FfmpegMissing
    command = [
        ffmpeg,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:V",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-map_metadata",
        "-1",
        "-map_metadata:s",
        "-1",
        "-map_chapters",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
    ]
    if media_format in {MediaFormat.MP4, MediaFormat.MOV}:
        command += ["-movflags", "+faststart"]
    command += ["-f", muxer, str(dst)]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=SANITIZE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("ffmpeg could not sanitize a video", exc_info=True)
        raise SanitizeFailed from None
    if completed.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
        # stderr may contain paths and tag values: never beyond debug logs.
        logger.debug("ffmpeg failed: %s", completed.stderr[-2000:])
        raise SanitizeFailed


# --- Inspection (research §9): categories and key names, never values ---------------

PROBE_TIMEOUT_SECONDS = 30
# Technical tags every remux writes; they say nothing about the user.
TECHNICAL_TAGS = frozenset(
    {"major_brand", "minor_version", "compatible_brands", "language", "vendor_id"}
)
GENERIC_HANDLERS = frozenset({"VideoHandler", "SoundHandler", "Core Media Video"})
COMFYUI_MARKERS = ("workflow", "prompt", "class_type")


def _classify_tag(key: str, value: str, found: FindingCollector) -> None:
    lower = key.lower()
    if lower in TECHNICAL_TAGS or lower == "duration":
        return
    if lower in {"handler_name", "handler"} and value in GENERIC_HANDLERS:
        return
    if lower == "encoder" and value == "Lavf":
        # Muxer name without version (bitexact): accepted residue (research §8).
        return
    if lower in {"workflow", "prompt"} or any(m in value for m in COMFYUI_MARKERS):
        found.add("comfyui", key)
    elif "location" in lower or "gps" in lower or "iso6709" in lower:
        found.add("location", key)
    elif "creation_time" in lower or lower in {"date", "creationdate"}:
        found.add("dates", key)
    elif lower in {"encoder", "software"} or lower.endswith(".software"):
        found.add("software", key)
    elif lower in {"make", "model"} or lower.endswith((".make", ".model")):
        found.add("device", key)
    else:
        found.add("container", key)


def inspect_video_metadata(path: Path) -> FileMetadataReport:
    """Categories of metadata found by ffprobe in a video (never the values)."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return FileMetadataReport(inspected=False, reason="ffprobe is not available.")
    try:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format"]
            + ["-show_streams", "-show_chapters", str(path)],
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=True,
        )
        probe: dict[str, Any] = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        logger.debug("ffprobe could not inspect a video", exc_info=True)
        return FileMetadataReport(
            inspected=False, reason="The video could not be inspected."
        )
    found = FindingCollector()
    for key, value in (probe.get("format", {}).get("tags") or {}).items():
        _classify_tag(key, str(value), found)
    for stream in probe.get("streams", []):
        kind = stream.get("codec_type")
        if kind not in {"video", "audio"}:
            found.add("other", f"{kind} stream")
        elif (stream.get("disposition") or {}).get("attached_pic"):
            found.add("other", "attached picture")
        for key, value in (stream.get("tags") or {}).items():
            _classify_tag(key, str(value), found)
    if probe.get("chapters"):
        found.add("container", "chapters")
    return found.report()
