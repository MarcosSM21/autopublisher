import hashlib
import io
import subprocess
from pathlib import Path

import pytest

from app import config, media
from app.media import InvalidMediaError, detect_format, read_image_info
from app.models import MediaFormat
from app.storage import FileTooLargeError, MediaStorage
from tests.conftest import make_image, make_mov, make_mp4, make_webm

# Bound before the autouse stub replaces media.probe_video in each test.
real_probe_video = media.probe_video


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (make_image("JPEG"), MediaFormat.JPEG),
        (make_image("PNG"), MediaFormat.PNG),
        (make_image("WEBP"), MediaFormat.WEBP),
        (make_mp4(b"isom"), MediaFormat.MP4),
        (make_mp4(b"mp42"), MediaFormat.MP4),
        (make_mov(), MediaFormat.MOV),
        (make_webm(), MediaFormat.WEBM),
    ],
)
def test_detect_supported_formats(data: bytes, expected: MediaFormat) -> None:
    assert detect_format(data[: media.HEADER_SIZE]) == expected


@pytest.mark.parametrize(
    "data",
    [
        make_mp4(b"M4A "),
        make_mp4(b"heic"),
        make_mp4(b"mif1"),
        make_webm(doctype=b"matroska"),
        b"Just some plain text pretending to be a JPEG.",
        b"",
        b"GIF89a\x01\x00\x01\x00",
    ],
)
def test_detect_rejects_unsupported_content(data: bytes) -> None:
    assert detect_format(data) is None


@pytest.mark.parametrize(
    ("fmt", "media_format"),
    [("PNG", MediaFormat.PNG), ("JPEG", MediaFormat.JPEG), ("WEBP", MediaFormat.WEBP)],
)
def test_read_image_info_returns_size(
    tmp_path: Path, fmt: str, media_format: MediaFormat
) -> None:
    path = tmp_path / "image"
    path.write_bytes(make_image(fmt, size=(32, 20)))

    assert read_image_info(path, media_format) == (32, 20)


@pytest.mark.parametrize(
    "data",
    [b"\xff\xd8\xff" + b"garbage" * 20, make_image("JPEG")[:20]],
)
def test_read_image_info_rejects_broken_images(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "broken.jpg"
    path.write_bytes(data)

    with pytest.raises(InvalidMediaError):
        read_image_info(path, MediaFormat.JPEG)


def test_read_image_info_rejects_format_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "image"
    path.write_bytes(make_image("PNG"))

    with pytest.raises(InvalidMediaError):
        read_image_info(path, MediaFormat.JPEG)


def test_probe_video_without_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.media.shutil.which", lambda name: None)

    assert real_probe_video(tmp_path / "clip.mp4") == media.VideoInfo()


def test_probe_video_tolerates_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("ffprobe", 15)

    monkeypatch.setattr("app.media.shutil.which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr("app.media.subprocess.run", timeout)

    assert real_probe_video(tmp_path / "clip.mp4") == media.VideoInfo()


def test_probe_video_tolerates_invalid_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 0, stdout=b"not json", stderr=b"")

    monkeypatch.setattr("app.media.shutil.which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr("app.media.subprocess.run", invalid)

    assert real_probe_video(tmp_path / "clip.mp4") == media.VideoInfo()


def test_probe_video_reads_ffprobe_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = (
        b'{"streams": [{"codec_type": "audio"}, '
        b'{"codec_type": "video", "width": 1080, "height": 1920}], '
        b'"format": {"duration": "14.5"}}'
    )

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 0, stdout=output, stderr=b"")

    monkeypatch.setattr("app.media.shutil.which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr("app.media.subprocess.run", run)

    assert real_probe_video(tmp_path / "clip.mp4") == media.VideoInfo(1080, 1920, 14.5)


@pytest.fixture
def storage(tmp_path: Path) -> MediaStorage:
    storage = MediaStorage(tmp_path / "media")
    storage.prepare()
    return storage


def test_receive_upload_streams_in_chunks(
    storage: MediaStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "CHUNK_SIZE", 7)
    data = bytes(range(256)) * 5

    received = storage.receive_upload(io.BytesIO(data), max_size=10_000)

    assert received.checksum == hashlib.sha256(data).hexdigest()
    assert received.size == len(data)
    assert received.path.parent == storage.tmp_dir
    assert received.path.read_bytes() == data


def test_receive_upload_rejects_large_files_without_residue(
    storage: MediaStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "CHUNK_SIZE", 4)

    with pytest.raises(FileTooLargeError):
        storage.receive_upload(io.BytesIO(b"x" * 100), max_size=10)

    assert list(storage.tmp_dir.iterdir()) == []


def test_prepare_empties_tmp(storage: MediaStorage) -> None:
    (storage.tmp_dir / "leftover.part").write_bytes(b"x")

    storage.prepare()

    assert list(storage.tmp_dir.iterdir()) == []


def test_commit_moves_file_into_project_dir(storage: MediaStorage) -> None:
    received = storage.receive_upload(io.BytesIO(b"data"), max_size=100)
    relative = storage.final_relative_path(3, ".png")

    final = storage.commit(received.path, relative)

    assert final.read_bytes() == b"data"
    assert final.parent == (storage.projects_dir / "3").resolve()
    assert not received.path.exists()


@pytest.mark.parametrize("relative", ["../x", "/etc/passwd", "projects/../../x", ""])
def test_resolve_refuses_paths_outside_root(
    storage: MediaStorage, relative: str
) -> None:
    with pytest.raises(ValueError):
        storage.resolve(relative)
