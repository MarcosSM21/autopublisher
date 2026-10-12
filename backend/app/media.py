"""Media format detection and technical metadata.

The format is decided only by the file content (see
specs/003-content-library/research.md, decisions 3-5). Everything here works on files
already on disk, never on whole files in memory.
"""

import json
import logging
import shutil
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.models import MediaFormat, MediaType

logger = logging.getLogger(__name__)

HEADER_SIZE = 4096
FFPROBE_TIMEOUT_SECONDS = 15

MP4_BRANDS = {
    b"isom",
    b"iso2",
    b"iso4",
    b"iso5",
    b"iso6",
    b"mp41",
    b"mp42",
    b"avc1",
    b"M4V ",
    b"mmp4",
    b"dash",
    b"MSNV",
}
MOV_BRAND = b"qt  "

EBML_MAGIC = b"\x1a\x45\xdf\xa3"
EBML_DOCTYPE_ID = b"\x42\x82"

EXTENSIONS: dict[MediaFormat, str] = {
    MediaFormat.JPEG: ".jpg",
    MediaFormat.PNG: ".png",
    MediaFormat.WEBP: ".webp",
    MediaFormat.MP4: ".mp4",
    MediaFormat.MOV: ".mov",
    MediaFormat.WEBM: ".webm",
}

MIME_TYPES: dict[MediaFormat, str] = {
    MediaFormat.JPEG: "image/jpeg",
    MediaFormat.PNG: "image/png",
    MediaFormat.WEBP: "image/webp",
    MediaFormat.MP4: "video/mp4",
    MediaFormat.MOV: "video/quicktime",
    MediaFormat.WEBM: "video/webm",
}

_PILLOW_FORMATS: dict[MediaFormat, str] = {
    MediaFormat.JPEG: "JPEG",
    MediaFormat.PNG: "PNG",
    MediaFormat.WEBP: "WEBP",
}


class InvalidMediaError(Exception):
    """The file claims a supported format but cannot be read as such."""


@dataclass(frozen=True)
class VideoInfo:
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


def _ebml_doctype(header: bytes) -> bytes | None:
    """Return the DocType value of an EBML header, if present."""
    index = header.find(EBML_DOCTYPE_ID, len(EBML_MAGIC))
    if index == -1 or index + 2 >= len(header):
        return None
    # The size is an EBML variable-length integer; its first byte encodes its length.
    first = header[index + 2]
    length = 1
    mask = 0x80
    while length <= 8 and not first & mask:
        length += 1
        mask >>= 1
    if length > 8:
        return None
    size = first & (mask - 1)
    for byte in header[index + 3 : index + 2 + length]:
        size = (size << 8) | byte
    start = index + 2 + length
    return header[start : start + size]


def detect_format(header: bytes) -> MediaFormat | None:
    """Detect a supported format from the first bytes of a file."""
    if header.startswith(b"\xff\xd8\xff"):
        return MediaFormat.JPEG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaFormat.PNG
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return MediaFormat.WEBP
    if header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand == MOV_BRAND:
            return MediaFormat.MOV
        if brand in MP4_BRANDS:
            return MediaFormat.MP4
        return None
    if header.startswith(EBML_MAGIC) and _ebml_doctype(header) == b"webm":
        return MediaFormat.WEBM
    return None


def media_type_of(media_format: MediaFormat) -> MediaType:
    if media_format in _PILLOW_FORMATS:
        return MediaType.IMAGE
    return MediaType.VIDEO


def read_image_info(path: Path, media_format: MediaFormat) -> tuple[int, int]:
    """Return (width, height) reading only the image header."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != _PILLOW_FORMATS.get(media_format):
                    raise InvalidMediaError("Image format does not match its content.")
                width, height = image.size
    except InvalidMediaError:
        raise
    except Exception as exc:  # Pillow raises many error types for broken files.
        raise InvalidMediaError(str(exc)) from exc
    if width <= 0 or height <= 0:
        raise InvalidMediaError("Image has no size.")
    return width, height


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def probe_video(path: Path) -> VideoInfo:
    """Read video dimensions and duration with ffprobe when it is available.

    ffprobe is optional: any problem returns empty or partial information.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return VideoInfo()
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            return VideoInfo()
        data = json.loads(completed.stdout)
        streams = data.get("streams") or []
        video = next(
            (
                stream
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "video"
            ),
            {},
        )
        duration: float | None = None
        raw_duration = (data.get("format") or {}).get("duration")
        if raw_duration is not None:
            duration = float(raw_duration)
            if duration <= 0:
                duration = None
        return VideoInfo(
            width=_positive_int(video.get("width")),
            height=_positive_int(video.get("height")),
            duration_seconds=duration,
        )
    except Exception:
        logger.debug("ffprobe could not read the video", exc_info=True)
        return VideoInfo()


@dataclass(frozen=True)
class StreamInfo:
    codec_type: str | None = None
    codec_name: str | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    pix_fmt: str | None = None
    field_order: str | None = None
    bit_rate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class VideoStreams:
    """What ffprobe reports about a video file (Feature 009 Reel checks)."""

    format_names: frozenset[str]
    duration_seconds: float | None
    size_bytes: int | None
    bit_rate: int | None
    streams: tuple[StreamInfo, ...]

    def first(self, codec_type: str) -> StreamInfo | None:
        return next((s for s in self.streams if s.codec_type == codec_type), None)


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _whole(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return _number(value)
    numerator, _, denominator = value.partition("/")
    top, bottom = _number(numerator), _number(denominator)
    if top is None or bottom is None:
        return None
    return top / bottom


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def probe_video_streams(path: Path) -> VideoStreams | None:
    """Detailed ffprobe report, or None when ffprobe is missing or fails."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            return None
        data = json.loads(completed.stdout)
        container = data.get("format") or {}
        streams = tuple(
            StreamInfo(
                codec_type=_text(stream.get("codec_type")),
                codec_name=_text(stream.get("codec_name")),
                width=_positive_int(stream.get("width")),
                height=_positive_int(stream.get("height")),
                frame_rate=_frame_rate(stream.get("avg_frame_rate"))
                or _frame_rate(stream.get("r_frame_rate")),
                pix_fmt=_text(stream.get("pix_fmt")),
                field_order=_text(stream.get("field_order")),
                bit_rate=_whole(stream.get("bit_rate")),
                sample_rate=_whole(stream.get("sample_rate")),
                channels=_positive_int(stream.get("channels")),
            )
            for stream in data.get("streams") or []
            if isinstance(stream, dict)
        )
        names = container.get("format_name")
        return VideoStreams(
            format_names=frozenset(names.split(","))
            if isinstance(names, str)
            else (frozenset()),
            duration_seconds=_number(container.get("duration")),
            size_bytes=_whole(container.get("size")),
            bit_rate=_whole(container.get("bit_rate")),
            streams=streams,
        )
    except Exception:
        logger.debug("ffprobe could not read the video", exc_info=True)
        return None


def moov_before_mdat(path: Path) -> bool | None:
    """Whether the `moov` box comes before `mdat` (fast start), reading only the
    top-level box headers. None when the file cannot be parsed."""
    try:
        with path.open("rb") as file:
            while True:
                header = file.read(8)
                if len(header) < 8:
                    return None
                size = int.from_bytes(header[:4], "big")
                kind = header[4:8]
                if kind == b"moov":
                    return True
                if kind == b"mdat":
                    return False
                if size == 1:
                    extended = file.read(8)
                    if len(extended) < 8:
                        return None
                    size = int.from_bytes(extended, "big")
                    skip = size - 16
                elif size == 0:
                    return None
                else:
                    skip = size - 8
                if skip < 0:
                    return None
                file.seek(skip, 1)
    except OSError:
        return None
