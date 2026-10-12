"""Instagram media rules without network: caption, image policy and Reel checks
(research.md §2-§5)."""

import hashlib
import io
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.instagram_media import (
    IMAGE_MAX_BYTES,
    ImageIncompatible,
    caption_problems,
    caption_stats,
    fingerprint,
    image_problems,
    prepare_image,
    reel_problems,
)
from app.media import StreamInfo, VideoStreams, moov_before_mdat, probe_video_streams
from app.publications import description_with_hashtags

# --- Caption -------------------------------------------------------------------------


def test_caption_is_description_blank_line_and_hashtags() -> None:
    assert description_with_hashtags("Summer drop.", ["cyber", "studio"]) == (
        "Summer drop.\n\n#cyber #studio"
    )
    assert description_with_hashtags(None, ["a"]) == "#a"
    assert description_with_hashtags("Only text", []) == "Only text"
    assert description_with_hashtags(None, []) == ""


def test_caption_within_limits_has_no_problems() -> None:
    caption = "x" * 2180 + "\n\n" + " ".join(f"#t{i}" for i in range(3))
    assert caption_problems(caption[:2200]) == []


@pytest.mark.parametrize(
    ("caption", "fragment"),
    [
        ("x" * 2201, "2201 characters"),
        (" ".join(f"#t{i}" for i in range(31)), "31 hashtags"),
        (" ".join(f"@user{i}" for i in range(21)), "21 accounts"),
    ],
)
def test_caption_over_a_limit_is_rejected(caption: str, fragment: str) -> None:
    problems = caption_problems(caption)

    assert [p.code for p in problems] == ["instagram_caption_invalid"]
    assert fragment in problems[0].message
    assert problems[0].field == "caption"


def test_caption_stats_ignore_symbols_inside_words() -> None:
    stats = caption_stats("mail me at a@b.com #ok C# @friend")

    assert stats.hashtags == 1
    assert stats.mentions == 1


# --- Images --------------------------------------------------------------------------


def _image(
    tmp_path: Path,
    name: str,
    size: tuple[int, int],
    image_format: str,
    mode: str = "RGB",
    color: Any = (200, 30, 30),
    **save: Any,
) -> Path:
    path = tmp_path / name
    Image.new(mode, size, color).save(path, image_format, **save)
    return path


def test_jpeg_is_sent_byte_for_byte(tmp_path: Path) -> None:
    path = _image(tmp_path, "a.jpg", (1080, 1080), "JPEG")
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    prepared = prepare_image(path, "jpeg")

    assert prepared.converted is False
    assert prepared.path == path
    assert prepared.data is None
    assert prepared.size == path.stat().st_size
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    ("image_format", "suffix", "mode", "color"),
    [
        ("PNG", "png", "RGB", (10, 20, 30)),
        ("PNG", "png", "RGBA", (10, 20, 30, 255)),
        ("PNG", "png", "L", 128),
        ("PNG", "png", "P", 3),
        ("WEBP", "webp", "RGB", (10, 20, 30)),
    ],
)
def test_opaque_png_and_webp_are_converted_in_memory(
    tmp_path: Path, image_format: str, suffix: str, mode: str, color: Any
) -> None:
    path = _image(tmp_path, f"a.{suffix}", (1080, 1350), image_format, mode, color)
    before = path.read_bytes()

    prepared = prepare_image(path, suffix)

    assert prepared.converted is True
    assert prepared.path is None
    assert prepared.data is not None and prepared.size == len(prepared.data)
    with Image.open(io.BytesIO(prepared.data)) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (1080, 1350)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]  # No derived file on disk.


def test_icc_profile_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    Image.new("RGB", (100, 100)).save(path, "PNG", icc_profile=b"fake-icc")

    prepared = prepare_image(path, "png")

    assert prepared.data is not None
    with Image.open(io.BytesIO(prepared.data)) as converted:
        assert converted.info.get("icc_profile") == b"fake-icc"


def test_sixteen_bit_png_is_converted(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    Image.new("I;16", (100, 100), 40000).save(path, "PNG")

    prepared = prepare_image(path, "png")

    assert prepared.converted is True


@pytest.mark.parametrize(
    ("size", "fragment"),
    [((1000, 300), "3.33:1"), ((300, 1000), "0.30:1"), ((800, 1001), "0.80:1")],
)
def test_aspect_ratio_outside_the_range_is_rejected(
    tmp_path: Path, size: tuple[int, int], fragment: str
) -> None:
    path = _image(tmp_path, "a.jpg", size, "JPEG")

    problems = image_problems(path, "jpeg")

    assert [p.code for p in problems] == ["instagram_image_incompatible"]
    assert fragment in problems[0].message
    assert "never crops" in problems[0].message


@pytest.mark.parametrize("size", [(800, 1000), (1910, 1000), (1080, 1080)])
def test_aspect_ratio_limits_are_accepted(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    assert image_problems(_image(tmp_path, "a.jpg", size, "JPEG"), "jpeg") == []


def test_exif_orientation_is_used_for_the_aspect_ratio(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # Rotated 90°: displayed as 1000x1910 → 0.52:1.
    Image.new("RGB", (1910, 1000)).save(path, "JPEG", exif=exif)

    with pytest.raises(ImageIncompatible, match="0.52:1"):
        prepare_image(path, "jpeg")


def test_transparent_png_is_rejected(tmp_path: Path) -> None:
    path = _image(tmp_path, "a.png", (100, 100), "PNG", "RGBA", (0, 0, 0, 0))

    problems = image_problems(path, "png")

    assert "transparent" in problems[0].message


def test_animated_webp_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.webp"
    frames = [Image.new("RGB", (100, 100), (i * 40, 0, 0)) for i in range(3)]
    frames[0].save(path, "WEBP", save_all=True, append_images=frames[1:])

    assert "Animated" in image_problems(path, "webp")[0].message


def test_cmyk_jpeg_is_rejected(tmp_path: Path) -> None:
    path = _image(tmp_path, "a.jpg", (100, 100), "JPEG", "CMYK", (0, 0, 0, 0))

    assert "CMYK" in image_problems(path, "jpeg")[0].message


def test_large_jpeg_is_rejected(tmp_path: Path) -> None:
    path = _image(tmp_path, "a.jpg", (100, 100), "JPEG")
    with path.open("ab") as file:
        file.write(b"\0" * IMAGE_MAX_BYTES)

    assert "8 MB" in image_problems(path, "jpeg")[0].message


def test_png_too_large_after_conversion_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.instagram_media.IMAGE_MAX_BYTES", 10)
    path = _image(tmp_path, "a.png", (100, 100), "PNG")

    assert "Converted to JPEG" in image_problems(path, "png")[0].message


def test_unreadable_image_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nbroken")

    assert "cannot be read" in image_problems(path, "png")[0].message


# --- Reels ---------------------------------------------------------------------------

VIDEO = StreamInfo(
    codec_type="video",
    codec_name="h264",
    width=1080,
    height=1920,
    frame_rate=30.0,
    pix_fmt="yuv420p",
    field_order="progressive",
    bit_rate=8_000_000,
)
AUDIO = StreamInfo(codec_type="audio", codec_name="aac", sample_rate=48_000, channels=2)


def _streams(
    video: dict[str, Any] | None = None,
    audio: dict[str, Any] | None = None,
    *,
    with_audio: bool = True,
    duration: float | None = 10.0,
) -> VideoStreams:
    streams = [StreamInfo(**{**VIDEO.__dict__, **(video or {})})]
    if with_audio:
        streams.append(StreamInfo(**{**AUDIO.__dict__, **(audio or {})}))
    return VideoStreams(
        format_names=frozenset({"mov", "mp4"}),
        duration_seconds=duration,
        size_bytes=1000,
        bit_rate=8_100_000,
        streams=tuple(streams),
    )


def test_valid_reel_has_no_problems() -> None:
    assert reel_problems("mp4", 1000, _streams(), True) == []
    assert reel_problems("mov", 1000, _streams(with_audio=False), True) == []


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"video": {"codec_name": "vp9"}}, "H.264 or HEVC"),
        ({"video": {"field_order": "tt"}}, "progressive"),
        ({"video": {"pix_fmt": "yuv444p"}}, "4:2:0"),
        ({"video": {"frame_rate": 15.0}}, "23 and 60 FPS"),
        ({"video": {"frame_rate": 120.0}}, "23 and 60 FPS"),
        ({"video": {"width": 3840, "height": 2160}}, "1920 pixels"),
        ({"video": {"width": 1000, "height": 1}}, "aspect ratio"),
        ({"video": {"bit_rate": 30_000_000}}, "25 Mbps"),
        ({"duration": 2.0}, "3 seconds"),
        ({"duration": 901.0}, "15 minutes"),
        ({"audio": {"codec_name": "mp3"}}, "AAC"),
        ({"audio": {"sample_rate": 96_000}}, "48 kHz"),
        ({"audio": {"channels": 6}}, "mono or stereo"),
    ],
)
def test_reel_requirements(kwargs: dict[str, Any], fragment: str) -> None:
    problems = reel_problems("mp4", 1000, _streams(**kwargs), True)

    assert [p.code for p in problems] == ["instagram_video_incompatible"]
    assert fragment in problems[0].message


def test_webm_is_not_a_reel() -> None:
    problems = reel_problems("webm", 1000, None, None)

    assert problems[0].code == "instagram_video_incompatible"
    assert "MP4 or MOV" in problems[0].message


def test_reel_size_and_fast_start() -> None:
    messages = [p.message for p in reel_problems("mp4", 300_000_001, _streams(), False)]

    assert any("300 MB" in m for m in messages)
    assert any("moov" in m for m in messages)


def test_unverifiable_video_is_not_published_blindly() -> None:
    problems = reel_problems("mp4", 1000, None, True)

    assert [p.code for p in problems] == ["instagram_media_unverifiable"]


# --- ffprobe and file structure -----------------------------------------------------


def test_probe_video_streams_reads_ffprobe_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "12.5",
            "size": "1000",
            "bit_rate": "640",
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30000/1001",
                "pix_fmt": "yuv420p",
                "field_order": "progressive",
                "bit_rate": "600",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
    }
    monkeypatch.setattr("app.media.shutil.which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        "app.media.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(output), b""),
    )

    streams = probe_video_streams(tmp_path / "clip.mp4")

    assert streams is not None
    assert {"mov", "mp4"} <= streams.format_names
    assert streams.duration_seconds == 12.5
    video = streams.first("video")
    assert video is not None and round(video.frame_rate or 0, 2) == 29.97
    audio = streams.first("audio")
    assert audio is not None and audio.sample_rate == 48_000


def test_probe_video_streams_without_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.media.shutil.which", lambda name: None)

    assert probe_video_streams(tmp_path / "clip.mp4") is None


def _box(kind: bytes, payload: bytes = b"") -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def test_moov_position(tmp_path: Path) -> None:
    fast = tmp_path / "fast.mp4"
    fast.write_bytes(_box(b"ftyp", b"isom") + _box(b"moov", b"x") + _box(b"mdat"))
    slow = tmp_path / "slow.mp4"
    slow.write_bytes(_box(b"ftyp", b"isom") + _box(b"mdat", b"xx") + _box(b"moov"))
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"\0\0")

    assert moov_before_mdat(fast) is True
    assert moov_before_mdat(slow) is False
    assert moov_before_mdat(broken) is None


# --- Fingerprint ---------------------------------------------------------------------


def test_fingerprint_changes_with_what_is_published() -> None:
    base = fingerprint("c1", "image", "caption", {"is_ai_generated": False})

    assert base == fingerprint("c1", "image", "caption", {"is_ai_generated": False})
    assert base != fingerprint("c2", "image", "caption", {"is_ai_generated": False})
    assert base != fingerprint("c1", "image", "other", {"is_ai_generated": False})
    assert base != fingerprint("c1", "image", "caption", {"is_ai_generated": True})
