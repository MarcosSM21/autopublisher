"""The effective-file contract: which file a content publishes (research §3)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.content_files import ContentFileUnavailable, resolve_publish_file
from app.models import Content
from app.storage import MediaStorage

ORIGINAL = b"original bytes with metadata"
COPY = b"clean bytes"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def storage(tmp_path: Path) -> MediaStorage:
    storage = MediaStorage(tmp_path / "media")
    storage.prepare()
    (storage.projects_dir / "1").mkdir()
    (storage.projects_dir / "1" / "a.png").write_bytes(ORIGINAL)
    (storage.projects_dir / "1" / "a.clean.png").write_bytes(COPY)
    return storage


def _content(status: str) -> Content:
    content = Content(
        id=1,
        project_id=1,
        storage_path="projects/1/a.png",
        checksum=_sha(ORIGINAL),
        size_bytes=len(ORIGINAL),
        metadata_status=status,
    )
    if status == "sanitized":
        content.sanitized_storage_path = "projects/1/a.clean.png"
        content.sanitized_checksum = _sha(COPY)
        content.sanitized_size_bytes = len(COPY)
        content.sanitized_at = datetime.now(UTC)
    return content


@pytest.mark.parametrize(
    ("status", "name", "data", "clean_copy"),
    [
        ("unknown", "a.png", ORIGINAL, False),
        ("clean", "a.png", ORIGINAL, False),
        ("sanitized", "a.clean.png", COPY, True),
    ],
)
@pytest.mark.parametrize("verify", [False, True])
def test_effective_file_by_status(
    storage: MediaStorage,
    status: str,
    name: str,
    data: bytes,
    clean_copy: bool,
    verify: bool,
) -> None:
    effective = resolve_publish_file(storage, _content(status), verify=verify)
    assert effective.path == storage.projects_dir / "1" / name
    assert effective.checksum == _sha(data)
    assert effective.size == len(data)
    assert effective.clean_copy is clean_copy


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("missing", "media_unavailable"),
        ("wrong_size", "media_unavailable"),
        ("wrong_sha", "media_corrupt"),
    ],
)
def test_broken_clean_copy_never_falls_back_to_the_original(
    storage: MediaStorage, damage: str, code: str
) -> None:
    copy = storage.projects_dir / "1" / "a.clean.png"
    if damage == "missing":
        copy.unlink()
    elif damage == "wrong_size":
        copy.write_bytes(COPY + b"x")
    else:
        copy.write_bytes(b"X" * len(COPY))

    with pytest.raises(ContentFileUnavailable) as error:
        resolve_publish_file(storage, _content("sanitized"), verify=True)

    assert error.value.code == code
    assert "a.png" not in error.value.message


def test_cheap_resolution_does_not_hash(storage: MediaStorage) -> None:
    # Same size, different bytes: only `verify=True` (prepare) may detect it.
    (storage.projects_dir / "1" / "a.clean.png").write_bytes(b"X" * len(COPY))

    effective = resolve_publish_file(storage, _content("sanitized"), verify=False)

    assert effective.clean_copy is True
