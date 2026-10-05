"""Local media storage.

Uploads are streamed in fixed-size chunks into ``<root>/tmp`` while their SHA-256 and
size are computed, so a file is never held in memory as a whole. ``tmp`` lives inside
the same root as ``projects``, so moving a validated file to its final place is an
atomic ``os.replace`` on the same filesystem.
"""

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app import config


class FileTooLargeError(Exception):
    pass


@dataclass(frozen=True)
class ReceivedFile:
    path: Path
    checksum: str
    size: int


class MediaStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def tmp_dir(self) -> Path:
        return self.root / "tmp"

    def prepare(self) -> None:
        """Create the storage directories and remove leftovers of past imports."""
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        for entry in self.tmp_dir.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)

    def receive_upload(self, source: BinaryIO, max_size: int) -> ReceivedFile:
        """Stream ``source`` into a temporary file, computing its checksum and size."""
        temp_path = self.tmp_dir / f"{uuid4().hex}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with temp_path.open("xb") as target:
                while chunk := source.read(config.CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_size:
                        raise FileTooLargeError
                    digest.update(chunk)
                    target.write(chunk)
        except BaseException:
            self.discard(temp_path)
            raise
        return ReceivedFile(temp_path, digest.hexdigest(), size)

    def discard(self, path: Path) -> None:
        path.unlink(missing_ok=True)

    def final_relative_path(self, project_id: int, extension: str) -> str:
        return f"projects/{project_id}/{uuid4().hex}{extension}"

    def commit(self, temp_path: Path, relative_path: str) -> Path:
        """Move a validated temporary file to its final location."""
        final_path = self.resolve(relative_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_path, final_path)
        return final_path

    def resolve(self, relative_path: str) -> Path:
        """Return the absolute path of a stored file; refuse paths outside the root."""
        root = self.root.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Path is outside the media storage.")
        return path
