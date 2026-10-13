"""Threads media rules without network (research.md §3, §4, §7, §8)."""

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageCms

from app import threads_media
from app.media import VideoStreams
from app.models import (
    Content,
    MediaFormat,
    MediaType,
    Publication,
    ThreadsMediaKind,
)
from app.threads_media import (
    ALT_TEXT_MAX_CHARACTERS,
    TEXT_MAX_CHARACTERS,
    TEXT_MAX_LINKS,
    ImageIncompatible,
    build_text,
    image_problems,
    prepare_threads_image,
    text_length,
    text_links,
    text_problems,
    threads_media_kind,
    video_problems,
)
from tests.conftest import probe_streams

# --- Kind and text -------------------------------------------------------------------


def _content(media_type: str, **values: Any) -> Content:
    return Content(media_type=media_type, **values)


def test_media_kind() -> None:
    assert threads_media_kind(None) == ThreadsMediaKind.TEXT
    assert threads_media_kind(_content(MediaType.IMAGE)) == ThreadsMediaKind.IMAGE
    assert threads_media_kind(_content(MediaType.VIDEO)) == ThreadsMediaKind.VIDEO
    assert threads_media_kind(_content("audio")) is None


def test_text_is_description_and_hashtags_without_title() -> None:
    content = _content(
        MediaType.IMAGE,
        title="Never sent",
        description="  Spaces kept\r\nand line breaks  ",
        hashtags=["cyber", "studio"],
    )
    publication = Publication(title_override="Not sent either")

    text = build_text(publication, content)

    assert text == "  Spaces kept\r\nand line breaks  \n\n#cyber #studio"


def test_text_of_a_publication_without_content() -> None:
    publication = Publication(
        description_override="Café ☕ 🚀", hashtags_override=["a"]
    )

    assert build_text(publication, None) == "Café ☕ 🚀\n\n#a"
    assert build_text(Publication(), None) == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hello", 5),
        ("café ñandú", 10),  # accents count as one character
        ("🚀", 4),  # U+1F680: 4 UTF-8 bytes
        ("a🚀b", 6),
        ("❤️", 6),  # U+2764 (So, 3 bytes) + VS16 (3 bytes)
        ("1️⃣", 7),  # digit + VS16 + keycap
        ("👩‍💻", 11),  # 4 + ZWJ (3) + 4
        ("☕", 3),  # So symbol in the BMP
    ],
)
def test_conservative_length(text: str, expected: int) -> None:
    assert text_length(text) == expected


def test_links_are_unique_urls() -> None:
    text = (
        "https://a.example/x http://b.example www.c.example "
        "https://a.example/x example.com"
    )

    assert text_links(text) == 3


def test_valid_text_has_no_problems() -> None:
    text = "x" * TEXT_MAX_CHARACTERS
    assert text_problems(text, ThreadsMediaKind.TEXT) == []


def test_long_text_is_invalid_and_never_truncated() -> None:
    text = "x" * (TEXT_MAX_CHARACTERS - 3) + "🚀"

    [problem] = text_problems(text, ThreadsMediaKind.TEXT)

    assert problem.code == "threads_text_invalid"
    assert problem.field == "text"
    assert f"{TEXT_MAX_CHARACTERS - 3 + 4}" in problem.message
    assert f"{TEXT_MAX_CHARACTERS}" in problem.message


def test_too_many_links() -> None:
    text = " ".join(f"https://site{n}.example" for n in range(TEXT_MAX_LINKS + 1))

    [problem] = text_problems(text, ThreadsMediaKind.TEXT)

    assert problem.code == "threads_text_invalid"
    assert f"{TEXT_MAX_LINKS + 1}" in problem.message
    assert f"{TEXT_MAX_LINKS}" in problem.message


@pytest.mark.parametrize("text", ["", "  \n "])
def test_empty_text_only_fails_for_text_posts(text: str) -> None:
    [problem] = text_problems(text, ThreadsMediaKind.TEXT)

    assert problem.code == "threads_text_invalid"
    assert text_problems(text, ThreadsMediaKind.IMAGE) == []
    assert text_problems(text, ThreadsMediaKind.VIDEO) == []


def test_alt_text_limit() -> None:
    assert ALT_TEXT_MAX_CHARACTERS == 1000


# --- Images --------------------------------------------------------------------------


def _write(
    tmp_path: Path, name: str, image: Image.Image, fmt: str, **opts: Any
) -> Path:
    path = tmp_path / name
    image.save(path, format=fmt, **opts)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("fmt", "media_format", "content_type"),
    [("JPEG", MediaFormat.JPEG, "image/jpeg"), ("PNG", MediaFormat.PNG, "image/png")],
)
def test_jpeg_and_png_are_sent_byte_for_byte(
    tmp_path: Path, fmt: str, media_format: str, content_type: str
) -> None:
    path = _write(tmp_path, f"a.{fmt.lower()}", Image.new("RGB", (100, 80)), fmt)
    before = _sha(path)

    image = prepare_threads_image(path, media_format)

    assert image.path == path
    assert image.data is None
    assert image.size == path.stat().st_size
    assert image.content_type == content_type
    assert image.converted is False
    assert _sha(path) == before


def test_static_webp_becomes_png(tmp_path: Path) -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # Rotated 90°: displayed as 20x40.
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    source = Image.new("RGBA", (40, 20), (255, 0, 0, 255))
    source.putpixel((0, 0), (0, 0, 0, 0))
    path = _write(
        tmp_path,
        "a.webp",
        source,
        "WEBP",
        lossless=True,
        exif=exif.tobytes(),
        icc_profile=icc,
    )
    before = _sha(path)

    image = prepare_threads_image(path, MediaFormat.WEBP)

    assert image.converted is True
    assert image.path is None
    assert image.content_type == "image/png"
    assert image.data is not None
    assert image.size == len(image.data)
    with Image.open(io.BytesIO(image.data)) as derived:
        assert derived.format == "PNG"
        assert derived.size == (20, 40)
        assert derived.mode == "RGBA"
        alpha = derived.getchannel("A").getextrema()
        assert alpha[0] == 0
        assert derived.info.get("icc_profile") == icc
    assert _sha(path) == before


def test_animated_webp_is_rejected(tmp_path: Path) -> None:
    frames = [Image.new("RGB", (40, 40), color) for color in ("red", "blue")]
    path = tmp_path / "a.webp"
    frames[0].save(path, "WEBP", save_all=True, append_images=frames[1:])

    with pytest.raises(ImageIncompatible, match="Animated"):
        prepare_threads_image(path, MediaFormat.WEBP)
    [problem] = image_problems(path, MediaFormat.WEBP)
    assert problem.code == "threads_image_incompatible"
    assert problem.field == "media"


def test_unreadable_image_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    path.write_bytes(b"not an image")

    [problem] = image_problems(path, MediaFormat.JPEG)

    assert problem.code == "threads_image_incompatible"


@pytest.mark.parametrize("size", [(1101, 100), (100, 1101)])
def test_aspect_ratio_over_ten_is_rejected(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    path = _write(tmp_path, "a.png", Image.new("RGB", size), "PNG")

    [problem] = image_problems(path, MediaFormat.PNG)

    assert "10:1" in problem.message


@pytest.mark.parametrize("size", [(1000, 100), (100, 1000), (200, 150), (2000, 300)])
def test_accepted_sizes(tmp_path: Path, size: tuple[int, int]) -> None:
    # Widths outside 320-1440 are accepted: Threads scales them.
    path = _write(tmp_path, "a.png", Image.new("RGB", size), "PNG")

    assert image_problems(path, MediaFormat.PNG) == []


def test_oversized_original_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "a.jpg", Image.new("RGB", (100, 100)), "JPEG")
    monkeypatch.setattr(threads_media, "IMAGE_MAX_BYTES", path.stat().st_size - 1)

    [problem] = image_problems(path, MediaFormat.JPEG)

    assert problem.code == "threads_image_incompatible"
    assert "8 MB" in problem.message


def test_oversized_derivative_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "a.webp", Image.new("RGB", (100, 100)), "WEBP")
    monkeypatch.setattr(threads_media, "IMAGE_MAX_BYTES", 10)

    with pytest.raises(ImageIncompatible, match="PNG"):
        prepare_threads_image(path, MediaFormat.WEBP)


# --- Videos --------------------------------------------------------------------------


def _check(
    streams: VideoStreams | None = None,
    *,
    media_format: str = MediaFormat.MP4,
    size: int = 1_000_000,
    moov_first: bool | None = True,
) -> threads_media.VideoCheck:
    return video_problems(
        media_format,
        size,
        probe_streams() if streams is None else streams,
        moov_first,
    )


def _messages(check: threads_media.VideoCheck) -> list[str]:
    assert {p.code for p in check.problems} <= {"threads_video_incompatible"}
    assert {p.field for p in check.problems} <= {"media"}
    return [p.message for p in check.problems]


def test_valid_video() -> None:
    check = _check()

    assert check.problems == []
    assert check.delegated_checks == ["closed_gop", "edit_lists"]


@pytest.mark.parametrize("media_format", [MediaFormat.MP4, MediaFormat.MOV])
def test_mp4_and_mov_are_accepted(media_format: str) -> None:
    assert _check(media_format=media_format).problems == []


def test_unverifiable_without_ffprobe() -> None:
    check = video_problems(MediaFormat.MP4, 1_000, None, True)

    assert [p.code for p in check.problems] == ["threads_media_unverifiable"]


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"media_format": MediaFormat.WEBM}, "MP4 or MOV"),
        ({"size": 1_000_000_001}, "1 GB"),
        ({"moov_first": False}, "moov"),
        ({"moov_first": None}, "could not determine"),
        ({"streams": probe_streams(format_names=frozenset({"matroska"}))}, "MP4"),
        ({"streams": probe_streams(video={"codec_type": "data"})}, "no video"),
        ({"streams": probe_streams(video={"codec_name": "vp9"})}, "H.264"),
        ({"streams": probe_streams(video={"codec_name": None})}, "could not"),
        ({"streams": probe_streams(video={"width": 1921})}, "1920"),
        ({"streams": probe_streams(video={"width": None})}, "could not"),
        ({"streams": probe_streams(video={"height": None})}, "could not"),
        (
            {"streams": probe_streams(video={"width": 1100, "height": 100})},
            "aspect",
        ),
        ({"streams": probe_streams(duration_seconds=301.0)}, "300"),
        ({"streams": probe_streams(duration_seconds=0.0)}, "300"),
        ({"streams": probe_streams(duration_seconds=None)}, "could not"),
        ({"streams": probe_streams(video={"frame_rate": 22.0})}, "23"),
        ({"streams": probe_streams(video={"frame_rate": 61.0})}, "60"),
        ({"streams": probe_streams(video={"frame_rate": None})}, "could not"),
        ({"streams": probe_streams(video={"pix_fmt": "yuv444p"})}, "4:2:0"),
        ({"streams": probe_streams(video={"pix_fmt": None})}, "could not"),
        ({"streams": probe_streams(video={"bit_rate": 100_000_001})}, "100 Mbps"),
        ({"streams": probe_streams(video={"field_order": "tt"})}, "progressive"),
        ({"streams": probe_streams(audio={"codec_name": "mp3"})}, "AAC"),
        ({"streams": probe_streams(audio={"codec_name": None})}, "could not"),
        ({"streams": probe_streams(audio={"sample_rate": 96_000})}, "48 kHz"),
        ({"streams": probe_streams(audio={"sample_rate": None})}, "could not"),
        ({"streams": probe_streams(audio={"channels": 6})}, "mono or stereo"),
        ({"streams": probe_streams(audio={"channels": None})}, "could not"),
        ({"streams": probe_streams(audio={"bit_rate": 128_001})}, "128 kbps"),
    ],
)
def test_each_rule(kwargs: dict[str, Any], fragment: str) -> None:
    streams = kwargs.pop("streams", None)

    messages = _messages(_check(streams, **kwargs))

    assert messages
    assert any(fragment.lower() in message.lower() for message in messages), messages


def test_missing_values_say_what_could_not_be_determined() -> None:
    check = _check(probe_streams(video={"pix_fmt": None}))

    assert _messages(check) == [
        "AutoPublisher could not determine the chroma subsampling of the video."
    ]


def test_video_bitrate_falls_back_to_the_container() -> None:
    over = probe_streams(video={"bit_rate": None}, bit_rate=100_000_001)
    unknown = probe_streams(video={"bit_rate": None}, bit_rate=None)

    assert _messages(_check(over))
    check = _check(unknown)
    assert check.problems == []
    assert "video_bitrate" in check.delegated_checks


def test_audio_bitrate_is_delegated_when_unknown() -> None:
    check = _check(probe_streams(audio={"bit_rate": None}))

    assert check.problems == []
    assert check.delegated_checks == ["closed_gop", "edit_lists", "audio_bitrate"]


def test_audio_bitrate_limit_is_strict() -> None:
    assert _check(probe_streams(audio={"bit_rate": 128_000})).problems == []


@pytest.mark.parametrize("field_order", [None, "unknown"])
def test_unknown_scan_is_delegated(field_order: str | None) -> None:
    check = _check(probe_streams(video={"field_order": field_order}))

    assert check.problems == []
    assert "progressive_scan" in check.delegated_checks


def test_video_without_audio_is_accepted() -> None:
    assert _check(probe_streams(has_audio=False)).problems == []
