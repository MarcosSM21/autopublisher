"""TikTok Direct Post rules without network (specs/013-tiktok-direct-post research
§5–§9): caption and its count, chunk plan, video matrix, options and their mapping to
`post_info`, the declaration, the consent fingerprint and file digests.

The caption is the effective description and hashtags, never transformed nor
truncated. Videos are only inspected: never transcoded, copied or modified, and read
in bounded buffers. Nothing here talks to TikTok or imports an HTTP client.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import media
from app.media import VideoStreams
from app.models import (
    Content,
    MediaFormat,
    MediaType,
    Publication,
    TikTokPublicationOptions,
)
from app.publications import description_with_hashtags, effective_metadata
from app.publishing import PublishProblem

# --- Caption (research §7) ------------------------------------------------------------

# "2200 UTF-16 runes", read conservatively as UTF-16 code units.
TIKTOK_CAPTION_MAX = 2200


def build_caption(publication: Publication, content: Content | None) -> str:
    """Effective description, a blank line and the hashtags; the title is not sent."""
    _, description, hashtags = effective_metadata(publication, content)
    return description_with_hashtags(description, hashtags)


def tiktok_caption_length(caption: str) -> int:
    """UTF-16 code units: a character outside the BMP counts 2. Never `len()`."""
    return len(caption.encode("utf-16-le")) // 2


def caption_problems(caption: str) -> list[PublishProblem]:
    length = tiktok_caption_length(caption)
    if length <= TIKTOK_CAPTION_MAX:
        return []
    return [
        PublishProblem(
            "tiktok_caption_invalid",
            f"The caption has {length} characters as TikTok counts them (emoji count "
            f"as 2); TikTok accepts at most {TIKTOK_CAPTION_MAX}. It is never "
            "shortened: edit the description or hashtags.",
            "caption",
        )
    ]


# --- Chunks (research §9) -------------------------------------------------------------

# Valid whether TikTok's "MB" means 10^6 or 2^20 bytes.
SINGLE_CHUNK_MAX = 64_000_000
CHUNK_SIZE = 32 * 1024 * 1024
MAX_CHUNKS = 1000


@dataclass(frozen=True)
class ChunkPlan:
    """How a file is split for FILE_UPLOAD: `total_chunk_count` is
    `video_size // chunk_size` and the last chunk takes the remainder."""

    video_size: int
    chunk_size: int
    total_chunk_count: int

    def chunk_range(self, index: int) -> tuple[int, int]:
        """First and last byte (inclusive) of chunk `index`."""
        first = index * self.chunk_size
        if self.is_last(index):
            return first, self.video_size - 1
        return first, first + self.chunk_size - 1

    def is_last(self, index: int) -> bool:
        return index == self.total_chunk_count - 1

    def ranges(self) -> list[tuple[int, int]]:
        return [self.chunk_range(i) for i in range(self.total_chunk_count)]

    def content_range(self, index: int) -> str:
        first, last = self.chunk_range(index)
        return f"bytes {first}-{last}/{self.video_size}"


def plan_chunks(
    video_size: int,
    single_chunk_max: int = SINGLE_CHUNK_MAX,
    chunk_size: int = CHUNK_SIZE,
) -> ChunkPlan:
    """One chunk up to `single_chunk_max`; otherwise chunks of
    `min(chunk_size, size // 2)` and a last chunk below twice that size."""
    if video_size <= 0:
        raise ValueError("A video needs at least one byte.")
    if video_size <= single_chunk_max:
        plan = ChunkPlan(video_size, video_size, 1)
    else:
        size = min(chunk_size, video_size // 2)
        plan = ChunkPlan(video_size, size, video_size // size)
    first, last = plan.chunk_range(plan.total_chunk_count - 1)
    last_size = last - first + 1
    if not 1 <= plan.total_chunk_count <= MAX_CHUNKS or not (
        plan.total_chunk_count == 1
        or plan.chunk_size <= last_size < 2 * plan.chunk_size
    ):
        raise ValueError("Invalid chunk plan.")
    return plan


# --- Video (research §8) --------------------------------------------------------------

VIDEO_FORMATS = frozenset({MediaFormat.MP4, MediaFormat.MOV, MediaFormat.WEBM})
VIDEO_CODECS = frozenset({"h264", "hevc", "vp8", "vp9"})
VIDEO_MIN_DIMENSION = 360
VIDEO_MAX_DIMENSION = 4096
# Technical limit of the API (10 minutes); the creator's own maximum is checked with
# Creator Info right before publishing.
VIDEO_MAX_SECONDS = 600.0
# "4 GB", read as decimal bytes (the conservative value).
VIDEO_MAX_BYTES = 4_000_000_000
# 23–60 FPS, widened by 0.01 to absorb 23.976/59.94 representations, no more.
VIDEO_MIN_FPS = 22.99
VIDEO_MAX_FPS = 60.01

PHOTOS_UNSUPPORTED_MESSAGE = (
    "TikTok publishing supports a single video; photos are not supported."
)
MEDIA_UNAVAILABLE_MESSAGE = "The video file of this content is missing or has changed."
UNINSPECTABLE_MESSAGE = (
    "AutoPublisher cannot inspect this video (install ffprobe), so it cannot check "
    "TikTok's requirements. Nothing was sent to TikTok."
)


@dataclass(frozen=True)
class VideoSummary:
    """What the local inspection found (shown in the review)."""

    format: str
    size_bytes: int
    duration_seconds: float | None
    width: int | None
    height: int | None
    frame_rate: float | None


@dataclass(frozen=True)
class VideoCheck:
    problems: list[PublishProblem]
    summary: VideoSummary | None = None
    # Requirements not verified locally and left to TikTok (never shown as checked).
    delegated_checks: list[str] = field(default_factory=list)


def _incompatible(messages: list[str]) -> list[PublishProblem]:
    return [
        PublishProblem("tiktok_video_incompatible", message, "media")
        for message in messages
    ]


def _unknown(what: str) -> str:
    return f"AutoPublisher could not determine the {what} of the video."


def video_check(
    media_type: str,
    media_format: str,
    size_bytes: int,
    file_size: int | None,
    streams: VideoStreams | None,
) -> VideoCheck:
    """Every TikTok video rule the file does not meet. `file_size` is the size on
    disk (None when the file is missing). A mandatory value that cannot be read fails
    conservatively; a missing frame rate is delegated to TikTok."""
    if media_type != MediaType.VIDEO:
        return VideoCheck(
            [PublishProblem("tiktok_video_required", PHOTOS_UNSUPPORTED_MESSAGE)]
        )
    if file_size is None or file_size != size_bytes:
        return VideoCheck(
            [PublishProblem("media_unavailable", MEDIA_UNAVAILABLE_MESSAGE)]
        )
    if media_format not in VIDEO_FORMATS:
        return VideoCheck(_incompatible(["TikTok videos must be MP4, MOV or WebM."]))
    problems: list[str] = []
    if size_bytes > VIDEO_MAX_BYTES:
        problems.append("TikTok videos can be at most 4 GB.")
    if streams is None:
        if problems:
            return VideoCheck(_incompatible(problems))
        return VideoCheck(
            [PublishProblem("tiktok_video_uninspectable", UNINSPECTABLE_MESSAGE)]
        )
    delegated: list[str] = []
    video = streams.first("video")
    width = height = None
    frame_rate = None
    if video is None:
        problems.append("The file has no video stream.")
    else:
        width, height, frame_rate = video.width, video.height, video.frame_rate
        if video.codec_name is None:
            problems.append(_unknown("codec"))
        elif video.codec_name not in VIDEO_CODECS:
            problems.append("TikTok videos must use H.264, H.265, VP8 or VP9.")
        if width is None or height is None:
            problems.append(_unknown("resolution"))
        elif not (
            VIDEO_MIN_DIMENSION <= width <= VIDEO_MAX_DIMENSION
            and VIDEO_MIN_DIMENSION <= height <= VIDEO_MAX_DIMENSION
        ):
            problems.append(
                "TikTok videos must be between 360 and 4096 pixels wide and high."
            )
        if frame_rate is None:
            delegated.append("frame_rate")
        elif not VIDEO_MIN_FPS <= frame_rate <= VIDEO_MAX_FPS:
            problems.append("TikTok videos must have between 23 and 60 FPS.")
    duration = streams.duration_seconds
    if duration is None:
        problems.append(_unknown("duration"))
    elif not 0 < duration <= VIDEO_MAX_SECONDS:
        problems.append("TikTok videos must last more than 0 and at most 10 minutes.")
    summary = VideoSummary(
        format=media_format,
        size_bytes=size_bytes,
        duration_seconds=duration,
        width=width,
        height=height,
        frame_rate=frame_rate,
    )
    return VideoCheck(_incompatible(problems), summary, delegated)


def inspect_video(content: Content, path: Path) -> VideoCheck:
    """Stat and ffprobe the stored file, read-only."""
    try:
        file_size: int | None = path.stat().st_size
    except OSError:
        file_size = None
    streams = None
    if file_size is not None and content.media_type == MediaType.VIDEO:
        streams = media.probe_video_streams(path)
    return video_check(
        content.media_type, content.media_format, content.size_bytes, file_size, streams
    )


def duration_problems(
    duration: float | None, max_duration: int
) -> list[PublishProblem]:
    """The creator's own maximum, from the Creator Info read right before posting."""
    if duration is not None and duration <= max_duration:
        return []
    return [
        PublishProblem(
            "tiktok_video_too_long",
            f"This TikTok account can post videos of at most {max_duration} seconds; "
            "the video is longer. It is never trimmed.",
            "media",
        )
    ]


def video_mime(media_format: str) -> str:
    """`Content-Type` of the upload, from the container detected on import."""
    return media.MIME_TYPES[MediaFormat(media_format)]


# --- Options (research §5) ------------------------------------------------------------

SELF_ONLY = "SELF_ONLY"
PRIVACY_LEVELS = (
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    SELF_ONLY,
)

PRIVACY_REQUIRED_MESSAGE = "Choose who can view this video."
PRIVACY_NOT_ALLOWED_MESSAGE = (
    "This TikTok app is not audited: TikTok only allows private (Only me) posts."
)
AIGC_REQUIRED_MESSAGE = "Say whether this video is AI-generated."
DISCLOSURE_INCOMPLETE_MESSAGE = (
    "You need to indicate if your content promotes yourself, a third party, or both."
)
BRANDED_PRIVATE_MESSAGE = "Branded content visibility cannot be set to private."


def allowed_privacy_levels(*, client_audited: bool) -> tuple[str, ...]:
    """An unaudited client can only post privately (Content Sharing Guidelines)."""
    return PRIVACY_LEVELS if client_audited else (SELF_ONLY,)


def disclosure_complete(options: TikTokPublicationOptions) -> bool:
    return not options.commercial_disclosure_enabled or bool(
        options.brand_organic_toggle or options.brand_content_toggle
    )


def option_problems(
    options: TikTokPublicationOptions, *, client_audited: bool
) -> list[PublishProblem]:
    """What keeps the saved options from being published; interactions never do."""
    problems: list[PublishProblem] = []
    if options.privacy_level is None:
        problems.append(
            PublishProblem(
                "tiktok_privacy_required", PRIVACY_REQUIRED_MESSAGE, "privacy_level"
            )
        )
    elif options.privacy_level not in allowed_privacy_levels(
        client_audited=client_audited
    ):
        problems.append(
            PublishProblem(
                "tiktok_privacy_not_allowed",
                PRIVACY_NOT_ALLOWED_MESSAGE,
                "privacy_level",
            )
        )
    if not disclosure_complete(options):
        problems.append(
            PublishProblem(
                "tiktok_disclosure_incomplete",
                DISCLOSURE_INCOMPLETE_MESSAGE,
                "commercial_disclosure_enabled",
            )
        )
    if options.brand_content_toggle and options.privacy_level == SELF_ONLY:
        problems.append(
            PublishProblem(
                "tiktok_branded_content_private",
                BRANDED_PRIVATE_MESSAGE,
                "brand_content_toggle",
            )
        )
    if options.is_aigc is None:
        problems.append(
            PublishProblem("tiktok_aigc_required", AIGC_REQUIRED_MESSAGE, "is_aigc")
        )
    return problems


def post_info(options: TikTokPublicationOptions, caption: str) -> dict[str, Any]:
    """`post_info` of `video/init/`: positive controls inverted, both commercial
    toggles always present, `is_aigc` explicit, no cover; `title` only with a
    caption."""
    info: dict[str, Any] = {}
    if caption:
        info["title"] = caption
    info.update(
        {
            "privacy_level": options.privacy_level,
            "disable_comment": not options.allow_comment,
            "disable_duet": not options.allow_duet,
            "disable_stitch": not options.allow_stitch,
            "brand_content_toggle": bool(options.brand_content_toggle),
            "brand_organic_toggle": bool(options.brand_organic_toggle),
            "is_aigc": bool(options.is_aigc),
        }
    )
    return info


def source_info(plan: ChunkPlan) -> dict[str, Any]:
    return {
        "source": "FILE_UPLOAD",
        "video_size": plan.video_size,
        "chunk_size": plan.chunk_size,
        "total_chunk_count": plan.total_chunk_count,
    }


# --- Declaration and labels ----------------------------------------------------------

# Changing a text requires a new version: it invalidates every previous consent.
MUSIC_DECLARATION_VERSION = "music-usage-2026-10-14"
BRANDED_DECLARATION_VERSION = "branded-music-usage-2026-10-14"
MUSIC_USAGE_URL = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en"
BRANDED_CONTENT_URL = "https://www.tiktok.com/legal/page/global/bc-policy/en"

PROMOTIONAL_LABEL = "Your video will be labeled as 'Promotional content'"
PAID_PARTNERSHIP_LABEL = "Your video will be labeled as 'Paid partnership'"


@dataclass(frozen=True)
class DeclarationLink:
    label: str
    url: str


@dataclass(frozen=True)
class Declaration:
    version: str
    text: str
    links: tuple[DeclarationLink, ...]


MUSIC_DECLARATION = Declaration(
    MUSIC_DECLARATION_VERSION,
    "By posting, you agree to TikTok's Music Usage Confirmation.",
    (DeclarationLink("Music Usage Confirmation", MUSIC_USAGE_URL),),
)
BRANDED_DECLARATION = Declaration(
    BRANDED_DECLARATION_VERSION,
    "By posting, you agree to TikTok's Branded Content Policy and Music Usage "
    "Confirmation.",
    (
        DeclarationLink("Branded Content Policy", BRANDED_CONTENT_URL),
        DeclarationLink("Music Usage Confirmation", MUSIC_USAGE_URL),
    ),
)


def declaration_for(options: TikTokPublicationOptions) -> Declaration:
    if options.commercial_disclosure_enabled and options.brand_content_toggle:
        return BRANDED_DECLARATION
    return MUSIC_DECLARATION


def disclosure_labels(options: TikTokPublicationOptions) -> list[str]:
    if not options.commercial_disclosure_enabled:
        return []
    if options.brand_content_toggle:
        return [PAID_PARTNERSHIP_LABEL]
    if options.brand_organic_toggle:
        return [PROMOTIONAL_LABEL]
    return []


# --- Consent fingerprint and digests (research §6) ------------------------------------

FILE_READ_SIZE = 1024 * 1024


def consent_fingerprint(
    *,
    open_id: str,
    video_sha256: str,
    caption: str,
    options: TikTokPublicationOptions,
) -> str | None:
    """SHA-256 of exactly what the user consents to, or None while the options are
    incomplete. `video_sha256` is `Content.checksum`, the digest of the file bytes."""
    if (
        options.privacy_level is None
        or options.is_aigc is None
        or not disclosure_complete(options)
    ):
        return None
    payload = {
        "v": 1,
        "open_id": open_id,
        "video_sha256": video_sha256,
        "caption": caption,
        "privacy_level": options.privacy_level,
        "allow_comment": bool(options.allow_comment),
        "allow_duet": bool(options.allow_duet),
        "allow_stitch": bool(options.allow_stitch),
        "commercial_disclosure": bool(options.commercial_disclosure_enabled),
        "brand_organic_toggle": bool(options.brand_organic_toggle),
        "brand_content_toggle": bool(options.brand_content_toggle),
        "is_aigc": bool(options.is_aigc),
        "declaration": declaration_for(options).version,
    }
    canonical = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """Streaming SHA-256 of a file in bounded reads; never loads it whole."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(FILE_READ_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


class UploadDigest:
    """SHA-256 fed with the very buffers that are uploaded, in order."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    def update(self, data: bytes) -> None:
        self._digest.update(data)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()
