"""Threads media rules without network (specs/011 research.md §3, §4, §7, §8).

Text is the effective description and hashtags, never transformed nor truncated.
Images: JPEG and PNG files are sent byte for byte; a static WebP becomes a lossless PNG
in memory. Videos are only checked, never transcoded. The original file is only ever
opened for reading. Nothing here imports the Instagram rules: Threads is independent.
"""

import io
import re
import unicodedata
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from app.media import VideoStreams
from app.models import Content, MediaFormat, MediaType, Publication, ThreadsMediaKind
from app.publications import description_with_hashtags, effective_metadata
from app.publishing import PublishProblem

# Text ("Text posts are limited to 500 characters"; at most 5 links).
TEXT_MAX_CHARACTERS = 500
TEXT_MAX_LINKS = 5
ALT_TEXT_MAX_CHARACTERS = 1000

# Images: JPEG or PNG, at most 8 MiB (prudent reading of "8 MB"), aspect ≤ 10:1.
IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGE_MAX_ASPECT = 10.0

# Videos (Threads "Video Specifications").
VIDEO_FORMATS = frozenset({MediaFormat.MP4, MediaFormat.MOV})
VIDEO_FORMAT_NAMES = frozenset({"mov", "mp4"})
VIDEO_CODECS = frozenset({"h264", "hevc"})
VIDEO_PIXEL_FORMATS = frozenset({"yuv420p", "yuvj420p", "yuv420p10le"})
VIDEO_INTERLACED = frozenset({"tt", "bb", "tb", "bt"})
VIDEO_MIN_FPS = 23.0
VIDEO_MAX_FPS = 60.0
VIDEO_MAX_WIDTH = 1920
VIDEO_MIN_ASPECT = 0.01
VIDEO_MAX_ASPECT = 10.0
VIDEO_MAX_SECONDS = 300.0
VIDEO_MAX_BYTES = 1_000_000_000
VIDEO_MAX_BITRATE = 100_000_000
AUDIO_MAX_SAMPLE_RATE = 48_000
AUDIO_MAX_CHANNELS = 2
AUDIO_MAX_BITRATE = 128_000
# Requirements that cannot be checked robustly without analysing the bitstream.
ALWAYS_DELEGATED = ("closed_gop", "edit_lists")

CONTENT_TYPES = {
    MediaFormat.JPEG: "image/jpeg",
    MediaFormat.PNG: "image/png",
    MediaFormat.MP4: "video/mp4",
    MediaFormat.MOV: "video/quicktime",
}

_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# Code points that only appear inside emoji: zero width joiner, variation selectors
# and the combining keycap.
_EMOJI_JOINERS = frozenset({"‍", "️", "︎", "⃣"})
_EXIF_ORIENTATION = 0x0112
_TRANSPOSED_ORIENTATIONS = frozenset({5, 6, 7, 8})


# --- Kind and text -------------------------------------------------------------------


def threads_media_kind(content: Content | None) -> ThreadsMediaKind | None:
    """Derived, never stored: no content is a text post."""
    if content is None:
        return ThreadsMediaKind.TEXT
    if content.media_type == MediaType.IMAGE:
        return ThreadsMediaKind.IMAGE
    if content.media_type == MediaType.VIDEO:
        return ThreadsMediaKind.VIDEO
    return None


def build_text(publication: Publication, content: Content | None) -> str:
    """Effective description, a blank line and the hashtags; the title is not sent."""
    _, description, hashtags = effective_metadata(publication, content)
    return description_with_hashtags(description, hashtags)


def text_length(text: str) -> int:
    """Conservative count: one per code point, except emoji parts, which count their
    UTF-8 bytes as Threads does. Overcounting a symbol is accepted."""
    total = 0
    for char in text:
        if (
            ord(char) >= 0x10000
            or char in _EMOJI_JOINERS
            or unicodedata.category(char) == "So"
        ):
            total += len(char.encode("utf-8"))
        else:
            total += 1
    return total


def text_links(text: str) -> int:
    """Unique URLs starting with http://, https:// or www."""
    return len(set(_LINK.findall(text)))


def text_problems(text: str, kind: ThreadsMediaKind) -> list[PublishProblem]:
    """Limits Threads enforces on the final text; it is never truncated."""
    problems: list[PublishProblem] = []

    def problem(message: str) -> None:
        problems.append(PublishProblem("threads_text_invalid", message, "text"))

    if kind == ThreadsMediaKind.TEXT and not text.strip():
        problem("A text post needs a text: write a description or hashtags.")
    length = text_length(text)
    if length > TEXT_MAX_CHARACTERS:
        problem(
            f"The text has {length} characters (emoji count as several); Threads "
            f"accepts at most {TEXT_MAX_CHARACTERS}."
        )
    links = text_links(text)
    if links > TEXT_MAX_LINKS:
        problem(
            f"The text has {links} links; Threads accepts at most {TEXT_MAX_LINKS}."
        )
    return problems


# --- Images --------------------------------------------------------------------------


class ImageIncompatible(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class PreparedImage:
    """What is sent: the original JPEG/PNG file, or a PNG converted in memory."""

    path: Path | None
    data: bytes | None
    size: int
    content_type: str
    converted: bool

    @property
    def delivered_format(self) -> str:
        return "jpeg" if self.content_type == "image/jpeg" else "png"


def _displayed_size(image: Image.Image) -> tuple[int, int]:
    width, height = image.size
    if image.getexif().get(_EXIF_ORIENTATION) in _TRANSPOSED_ORIENTATIONS:
        return height, width
    return width, height


def _check_aspect(width: int, height: int) -> None:
    ratio = max(width, height) / min(width, height)
    if ratio > IMAGE_MAX_ASPECT:
        raise ImageIncompatible(
            f"Threads accepts aspect ratios up to 10:1; this image is {ratio:.2f}:1. "
            "AutoPublisher never crops or pads images: adjust the file and import it "
            "again."
        )


def _check_size(size: int, converted: bool) -> None:
    if size <= IMAGE_MAX_BYTES:
        return
    if converted:
        raise ImageIncompatible(
            "Converted to PNG, this image is larger than the 8 MB Threads accepts. "
            "AutoPublisher never resizes images: reduce the file and import it again."
        )
    raise ImageIncompatible(
        "The image is larger than the 8 MB Threads accepts. AutoPublisher never "
        "recompresses or resizes images: reduce it and import it again."
    )


def _to_png(image: Image.Image) -> bytes:
    """Lossless PNG with the EXIF orientation applied, transparency and ICC kept."""
    icc = image.info.get("icc_profile")
    oriented = ImageOps.exif_transpose(image)
    if oriented.mode not in ("RGB", "RGBA", "L", "LA"):
        has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
        oriented = oriented.convert("RGBA" if has_alpha else "RGB")
    buffer = io.BytesIO()
    options = {"icc_profile": icc} if icc else {}
    oriented.save(buffer, "PNG", **options)
    return buffer.getvalue()


def _validate_png(data: bytes) -> None:
    """Rules checked on the derivative that will really be sent."""
    with Image.open(io.BytesIO(data)) as derived:
        if derived.format != "PNG":
            raise ImageIncompatible("The converted image is not a valid PNG file.")
        _check_aspect(*derived.size)
    _check_size(len(data), converted=True)


def prepare_threads_image(path: Path, media_format: str) -> PreparedImage:
    """The bytes Threads will receive; raises `ImageIncompatible` with the reason."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if getattr(image, "n_frames", 1) > 1:
                    raise ImageIncompatible(
                        "Animated images cannot be published on Threads; AutoPublisher "
                        "never picks a single frame."
                    )
                _check_aspect(*_displayed_size(image))
                if media_format in (MediaFormat.JPEG, MediaFormat.PNG):
                    if image.format != ("JPEG" if media_format == "jpeg" else "PNG"):
                        raise ImageIncompatible("The image cannot be read.")
                    size = path.stat().st_size
                    _check_size(size, converted=False)
                    return PreparedImage(
                        path=path,
                        data=None,
                        size=size,
                        content_type=CONTENT_TYPES[MediaFormat(media_format)],
                        converted=False,
                    )
                if media_format != MediaFormat.WEBP:
                    raise ImageIncompatible("Threads only accepts JPEG and PNG images.")
                data = _to_png(image)
            _validate_png(data)
    except ImageIncompatible:
        raise
    except Exception:  # Pillow raises many error types for broken files.
        raise ImageIncompatible("The image cannot be read.") from None
    return PreparedImage(
        path=None, data=data, size=len(data), content_type="image/png", converted=True
    )


def image_problems(path: Path, media_format: str) -> list[PublishProblem]:
    try:
        prepare_threads_image(path, media_format)
    except ImageIncompatible as error:
        return [PublishProblem("threads_image_incompatible", error.message, "media")]
    return []


# --- Videos --------------------------------------------------------------------------

UNVERIFIABLE_MESSAGE = (
    "AutoPublisher cannot inspect this video (install ffprobe), so it cannot check "
    "the Threads requirements. Nothing was published."
)


@dataclass(frozen=True)
class VideoCheck:
    problems: list[PublishProblem]
    # Requirements not verified locally and left to Threads (recorded per attempt).
    delegated_checks: list[str] = field(default_factory=list)


def _unknown(what: str) -> str:
    return f"AutoPublisher could not determine the {what} of the video."


def video_problems(
    media_format: str,
    size: int,
    streams: VideoStreams | None,
    moov_first: bool | None,
) -> VideoCheck:
    """Every Threads video rule the file does not meet. A mandatory value that
    cannot be read fails conservatively; nothing is ever transcoded."""
    problems: list[str] = []
    delegated = list(ALWAYS_DELEGATED)
    if media_format not in VIDEO_FORMATS:
        return VideoCheck(
            [
                PublishProblem(
                    "threads_video_incompatible",
                    "Threads videos must be MP4 or MOV files.",
                    "media",
                )
            ],
            delegated,
        )
    if size > VIDEO_MAX_BYTES:
        problems.append("Threads videos can be at most 1 GB.")
    if streams is None:
        if problems:
            return VideoCheck(_video_problems(problems), delegated)
        return VideoCheck(
            [PublishProblem("threads_media_unverifiable", UNVERIFIABLE_MESSAGE)],
            delegated,
        )
    if streams.format_names and not streams.format_names & VIDEO_FORMAT_NAMES:
        problems.append("Threads videos must be MP4 or MOV files.")
    if moov_first is None:
        problems.append(_unknown("position of the index (moov atom)"))
    elif not moov_first:
        problems.append(
            "The video index (moov atom) must be at the start of the file "
            '("fast start").'
        )

    video = streams.first("video")
    if video is None:
        problems.append("The file has no video stream.")
    else:
        if video.codec_name is None:
            problems.append(_unknown("codec"))
        elif video.codec_name not in VIDEO_CODECS:
            problems.append("Threads videos must use the H.264 or HEVC codec.")
        if video.width is None or video.height is None:
            problems.append(_unknown("resolution"))
        else:
            if video.width > VIDEO_MAX_WIDTH:
                problems.append("Threads videos can be at most 1920 pixels wide.")
            ratio = video.width / video.height
            if not VIDEO_MIN_ASPECT <= ratio <= VIDEO_MAX_ASPECT:
                problems.append(
                    "Threads videos need an aspect ratio between 0.01:1 and 10:1."
                )
        if video.frame_rate is None:
            problems.append(_unknown("frame rate"))
        elif not VIDEO_MIN_FPS <= video.frame_rate <= VIDEO_MAX_FPS:
            problems.append("Threads videos must have between 23 and 60 FPS.")
        if video.pix_fmt is None:
            problems.append(_unknown("chroma subsampling"))
        elif video.pix_fmt not in VIDEO_PIXEL_FORMATS:
            problems.append("Threads videos must use 4:2:0 chroma subsampling.")
        bit_rate = video.bit_rate or streams.bit_rate
        if bit_rate is None:
            delegated.append("video_bitrate")
        elif bit_rate > VIDEO_MAX_BITRATE:
            problems.append("Threads videos can have a bitrate of at most 100 Mbps.")
        if video.field_order in VIDEO_INTERLACED:
            problems.append("Threads videos must be progressive (not interlaced).")
        elif video.field_order != "progressive":
            delegated.append("progressive_scan")

    duration = streams.duration_seconds
    if duration is None:
        problems.append(_unknown("duration"))
    elif not 0 < duration <= VIDEO_MAX_SECONDS:
        problems.append("Threads videos must last more than 0 and at most 300 seconds.")

    audio = streams.first("audio")
    if audio is not None:
        if audio.codec_name is None:
            problems.append(_unknown("audio codec"))
        elif audio.codec_name != "aac":
            problems.append("Threads video audio must use the AAC codec.")
        if audio.sample_rate is None:
            problems.append(_unknown("audio sample rate"))
        elif audio.sample_rate > AUDIO_MAX_SAMPLE_RATE:
            problems.append("Threads video audio can be at most 48 kHz.")
        if audio.channels is None:
            problems.append(_unknown("audio channels"))
        elif not 1 <= audio.channels <= AUDIO_MAX_CHANNELS:
            problems.append("Threads video audio must be mono or stereo.")
        if audio.bit_rate is None:
            delegated.append("audio_bitrate")
        elif audio.bit_rate > AUDIO_MAX_BITRATE:
            problems.append("Threads video audio can be at most 128 kbps.")
    return VideoCheck(_video_problems(problems), delegated)


def _video_problems(messages: list[str]) -> list[PublishProblem]:
    return [
        PublishProblem("threads_video_incompatible", message, "media")
        for message in messages
    ]
