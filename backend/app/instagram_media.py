"""Instagram media rules without network: caption, image policy and Reel checks
(specs/009 research.md §2-§5).

Images: JPEG files are sent byte for byte; static PNG/WebP are converted to JPEG in
memory without cropping, padding or resizing. Videos are only checked, never
transcoded. The original file is only ever opened for reading.
"""

import hashlib
import io
import json
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from app.media import VideoStreams
from app.models import Content, InstagramMediaKind, MediaFormat, MediaType, Publication
from app.publications import description_with_hashtags, effective_metadata
from app.publishing import PublishProblem

# Caption (IG User Media: "Maximum 2200 characters, 30 hashtags, and 20 @ tags").
CAPTION_MAX_CHARACTERS = 2200
CAPTION_MAX_HASHTAGS = 30
CAPTION_MAX_MENTIONS = 20
ALT_TEXT_MAX_CHARACTERS = 1000

# Images: JPEG, at most 8 MiB, aspect ratio from 4:5 to 1.91:1.
IMAGE_MAX_BYTES = 8 * 1024 * 1024
ASPECT_MIN = 4 / 5
ASPECT_MAX = 1.91
ASPECT_TOLERANCE = 1e-6

# Reels.
REEL_FORMATS = frozenset({MediaFormat.MP4, MediaFormat.MOV})
REEL_VIDEO_CODECS = frozenset({"h264", "hevc"})
REEL_PIXEL_FORMATS = frozenset({"yuv420p", "yuvj420p", "yuv420p10le"})
REEL_INTERLACED = frozenset({"tt", "bb", "tb", "bt"})
REEL_MIN_FPS = 23.0
REEL_MAX_FPS = 60.0
REEL_MAX_WIDTH = 1920
REEL_MIN_ASPECT = 0.01
REEL_MAX_ASPECT = 10.0
REEL_MIN_SECONDS = 3.0
REEL_MAX_SECONDS = 15 * 60.0
REEL_MAX_BYTES = 300 * 1000 * 1000
REEL_MAX_VIDEO_BITRATE = 25_000_000
REEL_MAX_SAMPLE_RATE = 48_000

CONTENT_TYPES = {
    MediaFormat.JPEG: "image/jpeg",
    MediaFormat.MP4: "video/mp4",
    MediaFormat.MOV: "video/quicktime",
}

_HASHTAG = re.compile(r"(?<!\w)#\w")
_MENTION = re.compile(r"(?<!\w)@[\w.]")
# EXIF orientations that swap width and height.
_TRANSPOSED_ORIENTATIONS = frozenset({5, 6, 7, 8})
_EXIF_ORIENTATION = 0x0112


# --- Caption -----------------------------------------------------------------------


def media_kind_of(content: Content) -> InstagramMediaKind | None:
    if content.media_type == MediaType.IMAGE:
        return InstagramMediaKind.IMAGE
    if content.media_type == MediaType.VIDEO:
        return InstagramMediaKind.REEL
    return None


def build_caption(publication: Publication, content: Content) -> str:
    """Effective description, a blank line and the hashtags; the title is not sent."""
    _, description, hashtags = effective_metadata(publication, content)
    return description_with_hashtags(description, hashtags)


@dataclass(frozen=True)
class CaptionStats:
    length: int
    hashtags: int
    mentions: int


def caption_stats(caption: str) -> CaptionStats:
    return CaptionStats(
        length=len(caption),
        hashtags=len(_HASHTAG.findall(caption)),
        mentions=len(_MENTION.findall(caption)),
    )


def caption_problems(caption: str) -> list[PublishProblem]:
    """Limits Instagram enforces; the caption is never truncated."""
    stats = caption_stats(caption)
    problems: list[PublishProblem] = []

    def problem(message: str) -> None:
        problems.append(PublishProblem("instagram_caption_invalid", message, "caption"))

    if stats.length > CAPTION_MAX_CHARACTERS:
        problem(
            f"The caption has {stats.length} characters; Instagram accepts at most "
            f"{CAPTION_MAX_CHARACTERS}."
        )
    if stats.hashtags > CAPTION_MAX_HASHTAGS:
        problem(
            f"The caption has {stats.hashtags} hashtags; Instagram accepts at most "
            f"{CAPTION_MAX_HASHTAGS}."
        )
    if stats.mentions > CAPTION_MAX_MENTIONS:
        problem(
            f"The caption mentions {stats.mentions} accounts; Instagram accepts at "
            f"most {CAPTION_MAX_MENTIONS}."
        )
    return problems


# --- Images ------------------------------------------------------------------------


class ImageIncompatible(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class PreparedImage:
    """What is sent: the original JPEG file, or a JPEG converted in memory."""

    path: Path | None
    data: bytes | None
    size: int
    converted: bool

    @property
    def content_type(self) -> str:
        return "image/jpeg"


def _displayed_size(image: Image.Image) -> tuple[int, int]:
    width, height = image.size
    orientation = image.getexif().get(_EXIF_ORIENTATION)
    if orientation in _TRANSPOSED_ORIENTATIONS:
        return height, width
    return width, height


def _check_aspect(width: int, height: int) -> None:
    ratio = width / height
    if ratio < ASPECT_MIN - ASPECT_TOLERANCE or ratio > ASPECT_MAX + ASPECT_TOLERANCE:
        raise ImageIncompatible(
            f"Instagram accepts aspect ratios from 4:5 (0.80:1) to 1.91:1; this image "
            f"is {ratio:.2f}:1. AutoPublisher never crops or pads images: adjust the "
            "file and import it again."
        )


def _has_transparency(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        alpha = image.convert("RGBA").getchannel("A")
        lowest = alpha.getextrema()[0]
        return isinstance(lowest, (int, float)) and lowest < 255
    return False


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("I;16", "I;16B", "I;16L", "I"):
        # 16-bit grayscale: scale to 8 bits before converting.
        image = image.convert("I").point(lambda value: value / 256).convert("L")
    return image.convert("RGB")


def _encode_jpeg(image: Image.Image, icc: Any) -> bytes:
    for quality, subsampling in ((95, 0), (90, 2)):
        buffer = io.BytesIO()
        options: dict[str, Any] = {"quality": quality, "subsampling": subsampling}
        if icc:
            options["icc_profile"] = icc
        image.save(buffer, "JPEG", **options)
        data = buffer.getvalue()
        if len(data) <= IMAGE_MAX_BYTES:
            return data
    raise ImageIncompatible(
        "Converted to JPEG, this image is larger than the 8 MB Instagram accepts. "
        "AutoPublisher never resizes images: reduce the file and import it again."
    )


def prepare_image(path: Path, media_format: str) -> PreparedImage:
    """The bytes Instagram will receive; raises `ImageIncompatible` with the reason."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if getattr(image, "n_frames", 1) > 1:
                    raise ImageIncompatible(
                        "Animated images cannot be published on Instagram."
                    )
                _check_aspect(*_displayed_size(image))
                if media_format == MediaFormat.JPEG:
                    if image.mode == "CMYK":
                        raise ImageIncompatible(
                            "CMYK JPEG images cannot be converted safely; export the "
                            "image as RGB (sRGB) and import it again."
                        )
                    size = path.stat().st_size
                    if size > IMAGE_MAX_BYTES:
                        raise ImageIncompatible(
                            "The image is larger than the 8 MB Instagram accepts. "
                            "AutoPublisher never recompresses JPEG files: reduce it "
                            "and import it again."
                        )
                    return PreparedImage(
                        path=path, data=None, size=size, converted=False
                    )
                oriented = ImageOps.exif_transpose(image)
                if _has_transparency(oriented):
                    raise ImageIncompatible(
                        "The image has transparent areas. Instagram needs an opaque "
                        "image and AutoPublisher never adds a background: flatten it "
                        "and import it again."
                    )
                data = _encode_jpeg(_to_rgb(oriented), image.info.get("icc_profile"))
    except ImageIncompatible:
        raise
    except Exception:  # Pillow raises many error types for broken files.
        raise ImageIncompatible("The image cannot be read.") from None
    return PreparedImage(path=None, data=data, size=len(data), converted=True)


def image_problems(path: Path, media_format: str) -> list[PublishProblem]:
    try:
        prepare_image(path, media_format)
    except ImageIncompatible as error:
        return [PublishProblem("instagram_image_incompatible", error.message, "media")]
    return []


# --- Reels -------------------------------------------------------------------------

UNVERIFIABLE_MESSAGE = (
    "AutoPublisher cannot inspect this video (install ffprobe), so it cannot check "
    "the Reel requirements. Nothing was published."
)


def reel_problems(
    media_format: str,
    size: int,
    streams: VideoStreams | None,
    moov_first: bool | None,
) -> list[PublishProblem]:
    """Every Reel requirement the file does not meet; no transcoding is ever done."""
    problems: list[str] = []
    if media_format not in REEL_FORMATS:
        return [
            PublishProblem(
                "instagram_video_incompatible",
                "Instagram Reels must be MP4 or MOV files.",
                "media",
            )
        ]
    if size > REEL_MAX_BYTES:
        problems.append("Reels can be at most 300 MB.")
    if streams is None or moov_first is None:
        if problems:
            return [
                PublishProblem("instagram_video_incompatible", message, "media")
                for message in problems
            ]
        return [PublishProblem("instagram_media_unverifiable", UNVERIFIABLE_MESSAGE)]
    if not moov_first:
        problems.append(
            "The video index (moov atom) must be at the start of the file "
            '("fast start").'
        )
    video = streams.first("video")
    if video is None:
        problems.append("The file has no video stream.")
    else:
        if video.codec_name not in REEL_VIDEO_CODECS:
            problems.append("Reels must use the H.264 or HEVC video codec.")
        if video.field_order in REEL_INTERLACED:
            problems.append("Reels must use progressive (not interlaced) video.")
        if video.pix_fmt is not None and video.pix_fmt not in REEL_PIXEL_FORMATS:
            problems.append("Reels must use 4:2:0 chroma subsampling.")
        if video.frame_rate is None or not (
            REEL_MIN_FPS <= video.frame_rate <= REEL_MAX_FPS
        ):
            problems.append("Reels must have a frame rate between 23 and 60 FPS.")
        if video.width is not None and video.width > REEL_MAX_WIDTH:
            problems.append("Reels can be at most 1920 pixels wide.")
        if video.width and video.height:
            ratio = video.width / video.height
            if not REEL_MIN_ASPECT <= ratio <= REEL_MAX_ASPECT:
                problems.append("Reels need an aspect ratio between 0.01:1 and 10:1.")
        bit_rate = video.bit_rate or streams.bit_rate
        if bit_rate is not None and bit_rate > REEL_MAX_VIDEO_BITRATE:
            problems.append("Reels can have a video bitrate of at most 25 Mbps.")
    duration = streams.duration_seconds
    if duration is None or not REEL_MIN_SECONDS <= duration <= REEL_MAX_SECONDS:
        problems.append("Reels must last between 3 seconds and 15 minutes.")
    audio = streams.first("audio")
    if audio is not None:
        if audio.codec_name != "aac":
            problems.append("Reel audio must use the AAC codec.")
        if audio.sample_rate is not None and audio.sample_rate > REEL_MAX_SAMPLE_RATE:
            problems.append("Reel audio can have a sample rate of at most 48 kHz.")
        if audio.channels is not None and audio.channels > 2:
            problems.append("Reel audio must be mono or stereo.")
    return [
        PublishProblem("instagram_video_incompatible", message, "media")
        for message in problems
    ]


# --- Fingerprint -------------------------------------------------------------------


def fingerprint(
    checksum: str, media_kind: str, caption: str, options: dict[str, Any]
) -> str:
    """Identifies exactly what a container publishes, to decide whether it is reused."""
    payload = json.dumps(
        {
            "checksum": checksum,
            "media_kind": media_kind,
            "caption": caption,
            "options": options,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
