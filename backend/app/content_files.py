"""The file a content publishes (original or clean copy), independent of platforms.

`Remove metadata` may give a content a clean copy (`metadata_status = sanitized`);
from then on that copy is the only file any publisher may send. Every publisher asks
`resolve_publish_file` instead of reading `storage_path`/`checksum`/`size_bytes`, so
there is a single place deciding the file and no path back to the original.
"""

import hashlib
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import ColumnElement, case, select
from sqlalchemy.orm import Session

from app import config
from app.errors import ConflictError
from app.models import Content, MetadataStatus
from app.storage import MediaStorage

UnavailableCode = Literal["media_unavailable", "media_corrupt"]

ORIGINAL_UNAVAILABLE_MESSAGE = "The media file is not available."
COPY_UNAVAILABLE_MESSAGE = (
    "The clean copy of this file (without metadata) is missing. Use Remove metadata "
    "on the asset to create it again; the original is never published instead."
)
REMOVAL_IN_PROGRESS_MESSAGE = (
    "Metadata is already being removed from this content. Wait until it finishes."
)
METADATA_BUSY_MESSAGE = (
    "Metadata is being removed from this content. Publish again when it finishes."
)
COPY_CORRUPT_MESSAGE = (
    "The clean copy of this file (without metadata) is damaged. Use Remove metadata "
    "on the asset to create it again; the original is never published instead."
)


@dataclass(frozen=True)
class EffectiveFile:
    path: Path
    checksum: str
    size: int
    clean_copy: bool


class ContentFileUnavailable(Exception):
    def __init__(self, code: UnavailableCode, message: str) -> None:
        super().__init__(message)
        self.code: UnavailableCode = code
        self.message = message


def file_sha256(path: Path) -> str:
    """Streaming SHA-256 in bounded reads; never loads the file whole."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(config.CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_publish_file(
    storage: MediaStorage, content: Content, *, verify: bool
) -> EffectiveFile:
    """The file to publish for `content`.

    `verify=False` checks existence and size only (cheap: listings, checks, dialogs).
    `verify=True` also hashes the clean copy against `sanitized_checksum`; it is meant
    for the last local step of `prepare()`, right before the claim and the upload.
    A `sanitized` content never falls back to its original.
    """
    if content.metadata_status == MetadataStatus.SANITIZED:
        assert content.sanitized_storage_path is not None
        assert content.sanitized_checksum is not None
        assert content.sanitized_size_bytes is not None
        relative = content.sanitized_storage_path
        checksum = content.sanitized_checksum
        size = content.sanitized_size_bytes
        clean_copy = True
        missing_message = COPY_UNAVAILABLE_MESSAGE
    else:
        relative = content.storage_path
        checksum = content.checksum
        size = content.size_bytes
        clean_copy = False
        missing_message = ORIGINAL_UNAVAILABLE_MESSAGE
    try:
        path = storage.resolve(relative)
        actual_size = path.stat().st_size if path.is_file() else None
    except (ValueError, OSError):
        actual_size = None
    if actual_size != size:
        raise ContentFileUnavailable("media_unavailable", missing_message)
    if verify and clean_copy:
        try:
            digest = file_sha256(path)
        except OSError:
            raise ContentFileUnavailable("media_unavailable", missing_message) from None
        if digest != checksum:
            raise ContentFileUnavailable("media_corrupt", COPY_CORRUPT_MESSAGE)
    return EffectiveFile(path, checksum, size, clean_copy)


def effective_checksum(content: Content) -> str:
    """Checksum of the file publications send, from the database only."""
    if content.metadata_status == MetadataStatus.SANITIZED:
        assert content.sanitized_checksum is not None
        return content.sanitized_checksum
    return content.checksum


def effective_size(content: Content) -> int:
    """Size of the file publications send, from the database only (labels)."""
    if content.metadata_status == MetadataStatus.SANITIZED:
        assert content.sanitized_size_bytes is not None
        return content.sanitized_size_bytes
    return content.size_bytes


def effective_checksum_sql() -> ColumnElement[str]:
    """SQL equivalent of the effective checksum, for conditional updates."""
    return case(
        (
            Content.metadata_status == MetadataStatus.SANITIZED.value,
            Content.sanitized_checksum,
        ),
        else_=Content.checksum,
    )


class ContentFileGuard:
    """Keeps `Remove metadata` and the start of a publication of the same content
    apart (research §4). In memory only: the app is a single process, and a
    sanitization never survives a restart.

    `sanitizing` registers a content under the lock after running `check` (e.g. "no
    publication is publishing"); the work itself runs outside the lock. `claiming`
    holds the lock while a publication is moved to `publishing`, so a claim never
    happens while the content is being sanitized.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sanitizing: set[int] = set()

    @contextmanager
    def sanitizing(self, content_id: int, check: Callable[[], None]) -> Iterator[None]:
        with self._lock:
            if content_id in self._sanitizing:
                raise ConflictError(
                    "metadata_removal_in_progress", REMOVAL_IN_PROGRESS_MESSAGE
                )
            check()
            self._sanitizing.add(content_id)
        try:
            yield
        finally:
            with self._lock:
                self._sanitizing.discard(content_id)

    @contextmanager
    def claiming(self, content_id: int) -> Iterator[None]:
        with self._lock:
            if content_id in self._sanitizing:
                raise ConflictError("content_metadata_busy", METADATA_BUSY_MESSAGE)
            yield


# Clean copies are named `{uuid}.clean{ext}`; originals never contain `.clean.`.
CLEAN_COPY_MARKER = ".clean."


def clean_copy_relative_path(project_id: int, extension: str) -> str:
    return f"projects/{project_id}/{uuid4().hex}.clean{extension}"


def sweep_orphan_clean_copies(session: Session, storage: MediaStorage) -> int:
    """Delete clean copies no content references (left by a crash between the
    move and the commit). Only `.clean.` files are ever considered; originals
    are never touched. Returns how many files were deleted."""
    referenced = set(
        session.scalars(
            select(Content.sanitized_storage_path).where(
                Content.sanitized_storage_path.is_not(None)
            )
        )
    )
    deleted = 0
    for path in storage.projects_dir.glob("*/*"):
        if CLEAN_COPY_MARKER not in path.name or not path.is_file():
            continue
        if path.relative_to(storage.root).as_posix() in referenced:
            continue
        path.unlink(missing_ok=True)
        deleted += 1
    return deleted
