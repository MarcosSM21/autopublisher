"""Online backup and validated restore (research §20-22, contracts/cli.md).

Backup: a consistent snapshot of portable state while the server keeps running —
the database at one instant (SQLite backup API, without browser sessions), exactly
the Media files that snapshot references, verified against the checksums it
records, and the platform JSON files present, archived from the bytes that were
hashed. A `.tar` only gets its final name after it has been re-read and verified.

Restore: everything is validated before the target is touched; the data is
extracted into a sibling staging directory, the target is swapped with two renames
while locks M, A and B are held, and the previous data is kept next to it. The
host configuration, the keyring and the locks live elsewhere and are never touched.
"""

import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import tarfile
import tomllib
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from app import config, instance_lock
from app.db import known_revision, utc_now
from app.deployment import (
    EXIT_CONFIG,
    PORTABLE_PLATFORM_FILES,
    SPECIFIC_PATH_OVERRIDE_ENVS,
    DataLayout,
    canonical,
    is_inside,
    make_private_dir,
    path_overrides,
)

FORMAT = "autopublisher-backup"
FORMAT_VERSION = 1
DB_MEMBER = "autopublisher.db"
MANIFEST_MEMBER = "manifest.json"
MEDIA_PREFIX = "media/"
CONFIG_PREFIX = "config/"
COMPONENTS = ["database", "media", "platform_config"]

MAX_CONFIG_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 100_000
SPACE_MARGIN = 1.05
CHUNK = 1024 * 1024
SNAPSHOT_RETRIES = 5

_PRIVATE_FILE = 0o600
_STORAGE_PATH = re.compile(r"^projects/[0-9]+/[A-Za-z0-9_-][A-Za-z0-9._-]*$")
_MEDIA_MEMBER = re.compile(r"^media/projects/[0-9]+/[A-Za-z0-9_-][A-Za-z0-9._-]*$")
_ALLOWED_DIRS = re.compile(r"^(media|media/projects|media/projects/[0-9]+|config)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BackupError(Exception):
    """A backup or restore that cannot go on; the message says what to do."""

    exit_code = 1


class UnsupportedOverrides(BackupError):
    exit_code = EXIT_CONFIG


class RestoreCancelled(BackupError):
    exit_code = 1


def _app_version() -> str:
    try:
        data = tomllib.loads((config.BACKEND_DIR / "pyproject.toml").read_text())
        return str(data["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _ensure_space(directory: Path, needed: int) -> None:
    required = int(needed * SPACE_MARGIN)
    if _free_bytes(directory) < required:
        raise BackupError(
            f"Not enough free space in {directory}: about {required} bytes are "
            "needed. Free some space or choose another place."
        )


def is_development_data_dir(data_dir: Path) -> bool:
    return canonical(data_dir) == canonical(config.DEFAULT_DATA_DIR)


# --- Manifest -------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    created_at: str
    app_version: str
    schema_revision: str
    files: tuple[ManifestFile, ...]
    source: dict[str, Any]

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.files)

    @property
    def from_development(self) -> bool:
        return self.source.get("development_data_dir") is True

    def to_json(self) -> bytes:
        document = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "created_at": self.created_at,
            "app_version": self.app_version,
            "schema_revision": self.schema_revision,
            "components": COMPONENTS,
            "files": [
                {"path": item.path, "size": item.size, "sha256": item.sha256}
                for item in self.files
            ],
            "source": self.source,
        }
        return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def _allowed_file(path: str) -> bool:
    if path == DB_MEMBER:
        return True
    if _MEDIA_MEMBER.match(path):
        return True
    if path.startswith(CONFIG_PREFIX):
        return path.removeprefix(CONFIG_PREFIX) in PORTABLE_PLATFORM_FILES
    return False


def _parse_manifest(data: bytes) -> Manifest:
    def invalid(detail: str) -> BackupError:
        return BackupError(f"This file is not a valid AutoPublisher backup ({detail}).")

    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise invalid("unreadable manifest") from None
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise invalid("unknown format")
    if document.get("format_version") != FORMAT_VERSION:
        raise BackupError(
            "This backup uses a format this AutoPublisher does not know. "
            "Update AutoPublisher first."
        )
    files = document.get("files")
    fields = (
        document.get("created_at"),
        document.get("app_version"),
        document.get("schema_revision"),
    )
    if not all(isinstance(value, str) and value for value in fields):
        raise invalid("missing fields")
    if not isinstance(files, list) or not files or len(files) > MAX_MEMBERS:
        raise invalid("no file list")
    parsed: list[ManifestFile] = []
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise invalid("bad file entry")
        path, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
        if (
            not isinstance(path, str)
            or not _allowed_file(path)
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or not _SHA256.match(digest)
            or path in seen
        ):
            raise invalid("bad file entry")
        seen.add(path)
        parsed.append(ManifestFile(path, size, digest))
    if DB_MEMBER not in seen:
        raise invalid("no database")
    source = document.get("source")
    return Manifest(
        created_at=str(fields[0]),
        app_version=str(fields[1]),
        schema_revision=str(fields[2]),
        files=tuple(parsed),
        source=source if isinstance(source, dict) else {},
    )


# --- Archive validation (backup re-read and restore) ----------------------------------


def _hash_stream(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while chunk := stream.read(CHUNK):
        digest.update(chunk)
        total += len(chunk)
    return digest.hexdigest(), total


def _regular(member: tarfile.TarInfo) -> bool:
    # `isreg()` also accepts contiguous and sparse members: only plain files.
    return member.type in (tarfile.REGTYPE, tarfile.AREGTYPE)


def _validated_members(
    tar: tarfile.TarFile,
) -> tuple[Manifest, dict[str, tarfile.TarInfo]]:
    """Every member checked against the manifest before anything is written."""
    members = tar.getmembers()
    if len(members) > MAX_MEMBERS + 10:
        raise BackupError("This backup has too many files.")
    files: dict[str, tarfile.TarInfo] = {}
    for member in members:
        # The effective name (PAX headers included) is the one validated.
        name = member.name
        if name in files or (member.isdir() and name in files):
            raise BackupError(f"This backup repeats the member {name!r}.")
        if member.isdir():
            if not _ALLOWED_DIRS.match(name):
                raise BackupError(f"Unexpected directory in the backup: {name!r}.")
            continue
        if not _regular(member):
            raise BackupError(
                f"Unexpected member type in the backup: {name!r} "
                "(only regular files are allowed)."
            )
        if name != MANIFEST_MEMBER and not _allowed_file(name):
            raise BackupError(f"Unexpected file in the backup: {name!r}.")
        files[name] = member
    manifest_member = files.pop(MANIFEST_MEMBER, None)
    if manifest_member is None or manifest_member.size > MAX_MANIFEST_BYTES:
        raise BackupError(
            "This file is not a valid AutoPublisher backup (no manifest)."
        )
    stream = tar.extractfile(manifest_member)
    if stream is None:
        raise BackupError("This file is not a valid AutoPublisher backup.")
    manifest = _parse_manifest(stream.read())
    declared = {item.path: item for item in manifest.files}
    if set(declared) != set(files):
        extra = sorted(set(files) - set(declared))
        missing = sorted(set(declared) - set(files))
        raise BackupError(
            "The backup does not match its manifest "
            f"(unexpected: {extra or 'none'}; missing: {missing or 'none'})."
        )
    for path, item in declared.items():
        if files[path].size != item.size:
            raise BackupError(f"The size of {path!r} does not match the manifest.")
    return manifest, files


def verify_archive(path: Path) -> Manifest:
    """Open, validate every member and recompute every checksum (read-only)."""
    try:
        with tarfile.open(path, mode="r:") as tar:
            manifest, files = _validated_members(tar)
            for item in manifest.files:
                stream = tar.extractfile(files[item.path])
                if stream is None:
                    raise BackupError(f"Cannot read {item.path!r} from the backup.")
                digest, size = _hash_stream(stream)
                if digest != item.sha256 or size != item.size:
                    raise BackupError(
                        f"The backup is damaged: {item.path!r} does not match its "
                        "checksum."
                    )
    except (tarfile.TarError, EOFError) as exc:
        raise BackupError(
            f"The backup file is damaged or not a backup ({exc})."
        ) from None
    except FileNotFoundError:
        raise BackupError(f"The backup file {path} does not exist.") from None
    return manifest


# --- Backup ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupResult:
    path: Path
    manifest: Manifest


class _HashingReader(io.RawIOBase):
    """Feeds tarfile and hashes exactly the bytes it reads."""

    def __init__(self, source: IO[bytes]) -> None:
        self._source = source
        self.digest = hashlib.sha256()
        self.size = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data


def _check_backup_overrides(layout: DataLayout) -> None:
    for name, value in path_overrides(SPECIFIC_PATH_OVERRIDE_ENVS).items():
        if not is_inside(Path(value), layout.data_dir):
            raise UnsupportedOverrides(
                f"{name} points outside the data directory ({value}). A backup "
                "only covers the data directory: remove the override first."
            )


def _snapshot(db_path: Path, target: Path) -> None:
    """SQLite backup API into `target`; then, on that copy only, drop the
    sessions and VACUUM so no token hash survives in free pages."""
    if not db_path.is_file():
        raise BackupError(f"There is no database at {db_path}.")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _PRIVATE_FILE)
    os.close(fd)
    # Read-only: the database in use is never modified (nor migrated).
    source_uri = f"{db_path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source:
        with closing(sqlite3.connect(target)) as copy:
            for attempt in range(SNAPSHOT_RETRIES):
                try:
                    source.backup(copy)
                    break
                except sqlite3.OperationalError:
                    if attempt == SNAPSHOT_RETRIES - 1:
                        raise
            tables = {
                row[0]
                for row in copy.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "auth_sessions" in tables:  # absent in a database from before 020
                copy.execute("DELETE FROM auth_sessions")
                copy.commit()
            copy.execute("VACUUM")


@dataclass(frozen=True)
class _MediaEntry:
    storage_path: str
    checksum: str


def _snapshot_contents(snapshot: Path) -> tuple[str, list[_MediaEntry]]:
    with closing(sqlite3.connect(snapshot)) as copy:
        try:
            revision = copy.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
            rows = copy.execute(
                "SELECT storage_path, checksum FROM contents "
                "UNION SELECT sanitized_storage_path, sanitized_checksum FROM contents "
                "WHERE sanitized_storage_path IS NOT NULL ORDER BY 1"
            ).fetchall()
        except sqlite3.DatabaseError:
            raise BackupError(
                "The database is not an AutoPublisher database."
            ) from None
    if not revision:
        raise BackupError("The database is not an AutoPublisher database.")
    entries = []
    for storage_path, checksum in rows:
        if not isinstance(storage_path, str) or not _STORAGE_PATH.match(storage_path):
            raise BackupError(
                f"Unexpected media path in the database: {storage_path!r}."
            )
        entries.append(_MediaEntry(storage_path, str(checksum)))
    return str(revision[0]), entries


def _read_platform_files(layout: DataLayout) -> list[tuple[str, bytes]]:
    """Each present file read once; the same bytes are hashed and archived."""
    found = []
    for name in PORTABLE_PLATFORM_FILES:
        path = layout.platform_files.get(name, layout.data_dir / name)
        try:
            with open(path, "rb") as handle:
                data = handle.read(MAX_CONFIG_BYTES + 1)
        except FileNotFoundError:
            continue
        if len(data) > MAX_CONFIG_BYTES:
            raise BackupError(f"{path} is larger than {MAX_CONFIG_BYTES} bytes.")
        found.append((name, data))
    return found


def _tar_info(name: str, size: int, mtime: float) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = _PRIVATE_FILE
    info.mtime = int(mtime)
    return info


def _write_archive(
    partial: Path,
    snapshot: Path,
    media_dir: Path,
    media: list[_MediaEntry],
    platform_files: list[tuple[str, bytes]],
    manifest_for: Callable[[list[ManifestFile]], Manifest],
) -> Manifest:
    files: list[ManifestFile] = []
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _PRIVATE_FILE)
    with os.fdopen(fd, "wb") as raw:
        with tarfile.open(fileobj=raw, mode="w:", format=tarfile.PAX_FORMAT) as tar:
            with open(snapshot, "rb") as source:
                size = os.fstat(source.fileno()).st_size
                reader = _HashingReader(source)
                tar.addfile(_tar_info(DB_MEMBER, size, utc_now().timestamp()), reader)
                files.append(ManifestFile(DB_MEMBER, size, reader.digest.hexdigest()))
            for entry in media:
                name = f"{MEDIA_PREFIX}{entry.storage_path}"
                try:
                    with open(media_dir / entry.storage_path, "rb") as source:
                        stat = os.fstat(source.fileno())
                        reader = _HashingReader(source)
                        tar.addfile(
                            _tar_info(name, stat.st_size, stat.st_mtime), reader
                        )
                except (FileNotFoundError, OSError) as exc:
                    raise BackupError(
                        f"Media changed during the backup ({entry.storage_path}: "
                        f"{type(exc).__name__}). Run the backup again."
                    ) from None
                digest = reader.digest.hexdigest()
                if reader.size != stat.st_size or digest != entry.checksum:
                    raise BackupError(
                        f"Media changed during the backup ({entry.storage_path} "
                        "does not match the database). Run the backup again."
                    )
                files.append(ManifestFile(name, stat.st_size, digest))
            for file_name, data in platform_files:
                name = f"{CONFIG_PREFIX}{file_name}"
                tar.addfile(
                    _tar_info(name, len(data), utc_now().timestamp()), io.BytesIO(data)
                )
                files.append(
                    ManifestFile(name, len(data), hashlib.sha256(data).hexdigest())
                )
            manifest = manifest_for(files)
            document = manifest.to_json()
            tar.addfile(
                _tar_info(MANIFEST_MEMBER, len(document), utc_now().timestamp()),
                io.BytesIO(document),
            )
        raw.flush()
        os.fsync(raw.fileno())
    return manifest


def create_backup(
    layout: DataLayout,
    output_dir: Path,
    *,
    now: Callable[[], datetime] = utc_now,
    after_snapshot: Callable[[], None] | None = None,
) -> BackupResult:
    """Online backup under lock M (the server keeps A and B)."""
    _check_backup_overrides(layout)
    output = canonical(output_dir)
    data_dir = canonical(layout.data_dir)
    if is_inside(output, data_dir) or is_inside(data_dir, output):
        raise BackupError(
            f"Choose a backup folder outside the data directory {data_dir} "
            "(and not one that contains it)."
        )
    with instance_lock.hold(instance_lock.maintenance_locks(layout)):
        make_private_dir(output)
        for stale in (
            *output.glob(".autopublisher-backup-*.tar.partial"),
            *output.glob(".autopublisher-snapshot-*.db"),
        ):
            stale.unlink(missing_ok=True)
        moment = now()
        stamp = _timestamp(moment)
        final = output / f"autopublisher-backup-{stamp}.tar"
        if final.exists():
            raise BackupError(f"{final} already exists. Try again in a second.")
        snapshot = output / f".autopublisher-snapshot-{stamp}.db"
        partial = output / f".autopublisher-backup-{stamp}.tar.partial"
        try:
            _snapshot(layout.db_path, snapshot)
            revision, media = _snapshot_contents(snapshot)
            if after_snapshot is not None:
                after_snapshot()
            platform_files = _read_platform_files(layout)
            estimate = snapshot.stat().st_size + sum(
                len(data) for _, data in platform_files
            )
            for entry in media:
                try:
                    estimate += (layout.media_dir / entry.storage_path).stat().st_size
                except OSError:
                    pass  # reported precisely while archiving
            _ensure_space(output, estimate)

            def manifest_for(files: list[ManifestFile]) -> Manifest:
                return Manifest(
                    created_at=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    app_version=_app_version(),
                    schema_revision=revision,
                    files=tuple(files),
                    source={
                        # Informative only: never applied by a restore.
                        "hostname": socket.gethostname(),
                        "development_data_dir": is_development_data_dir(data_dir),
                    },
                )

            manifest = _write_archive(
                partial, snapshot, layout.media_dir, media, platform_files, manifest_for
            )
            verified = verify_archive(partial)
            if verified != manifest:
                raise BackupError("The backup could not be verified. Run it again.")
            os.replace(partial, final)
            _fsync_dir(output)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise BackupError(
                f"The backup failed ({exc.strerror or type(exc).__name__}); "
                "nothing was written."
            ) from None
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        finally:
            snapshot.unlink(missing_ok=True)
    return BackupResult(final, manifest)


# --- Restore --------------------------------------------------------------------------


@dataclass(frozen=True)
class RestoreResult:
    target: Path
    previous: Path | None
    manifest: Manifest
    password_set: bool


def _check_restore_overrides() -> None:
    overrides = path_overrides(SPECIFIC_PATH_OVERRIDE_ENVS)
    if overrides:
        raise UnsupportedOverrides(
            "A restore only supports the standard data directory layout. Unset "
            f"{', '.join(sorted(overrides))} first."
        )


def _extract(archive: Path, manifest: Manifest, staging: Path) -> None:
    """Exclusive writes inside the staging directory, hashed while streaming."""
    with tarfile.open(archive, mode="r:") as tar:
        _, members = _validated_members(tar)
        for item in manifest.files:
            if item.path == DB_MEMBER:
                target = staging / config.DB_FILE_NAME
            elif item.path.startswith(MEDIA_PREFIX):
                target = (
                    staging
                    / config.MEDIA_DIR_NAME
                    / item.path.removeprefix(MEDIA_PREFIX)
                )
            else:
                target = staging / item.path.removeprefix(CONFIG_PREFIX)
            if not is_inside(target, staging):
                raise BackupError(f"Refusing to write {item.path!r} outside staging.")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            stream = tar.extractfile(members[item.path])
            if stream is None:
                raise BackupError(f"Cannot read {item.path!r} from the backup.")
            digest = hashlib.sha256()
            size = 0
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _PRIVATE_FILE)
            with os.fdopen(fd, "wb") as out:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if digest.hexdigest() != item.sha256 or size != item.size:
                raise BackupError(
                    f"The backup is damaged: {item.path!r} does not match its checksum."
                )


def _prepare_database(db_path: Path) -> bool:
    """Integrity check, then zero sessions; returns whether a password is set."""
    with closing(sqlite3.connect(db_path)) as db:
        try:
            result = db.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError:
            result = None
        if not result or result[0] != "ok":
            raise BackupError("The database in the backup is damaged.")
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "auth_sessions" in tables:
            db.execute("DELETE FROM auth_sessions")
            db.commit()
        if "installation_auth" not in tables:
            return False
        count = db.execute("SELECT COUNT(*) FROM installation_auth").fetchone()[0]
        return bool(count)


def restore_backup(
    layout: DataLayout,
    archive: Path,
    *,
    confirm: Callable[[Manifest], bool] = lambda manifest: True,
    now: Callable[[], datetime] = utc_now,
    is_mount: Callable[[Path], bool] = os.path.ismount,
    between_renames: Callable[[], None] | None = None,
) -> RestoreResult:
    _check_restore_overrides()
    target = canonical(layout.data_dir)  # a symlinked data_dir is followed
    if is_mount(target):
        raise BackupError(
            f"{target} is a mount point. Use a subdirectory inside the mounted disk "
            "as the data directory."
        )
    archive = archive.resolve()
    if is_inside(archive, target):
        raise BackupError("Move the backup file out of the data directory first.")
    # M → A → B for the whole operation: no server can start during the swap.
    with instance_lock.hold(instance_lock.restore_locks(layout)):
        manifest = verify_archive(archive)
        if not known_revision(manifest.schema_revision):
            raise BackupError(
                "This backup was created by a newer AutoPublisher. Update first."
            )
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        _ensure_space(parent, manifest.total_size)
        stamp = _timestamp(now())
        staging = parent / f".{target.name}.restore-{stamp}"
        previous = parent / f"{target.name}.before-restore-{stamp}"
        staging.mkdir(mode=0o700)
        moved = False
        try:
            _extract(archive, manifest, staging)
            password_set = _prepare_database(staging / config.DB_FILE_NAME)
            if not confirm(manifest):
                raise RestoreCancelled("Restore cancelled; nothing was changed.")
            if target.exists():
                os.rename(target, previous)
                moved = True
            if between_renames is not None:
                between_renames()
            try:
                os.rename(staging, target)
            except BaseException:
                if moved:
                    os.rename(previous, target)
                raise
            _fsync_dir(parent)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return RestoreResult(target, previous if moved else None, manifest, password_set)


def iter_summary(manifest: Manifest) -> Iterator[str]:
    media = sum(1 for item in manifest.files if item.path.startswith(MEDIA_PREFIX))
    configs = sum(1 for item in manifest.files if item.path.startswith(CONFIG_PREFIX))
    yield f"Created: {manifest.created_at} (AutoPublisher {manifest.app_version})"
    yield f"Media files: {media}; platform configuration files: {configs}"
    hostname = manifest.source.get("hostname")
    if isinstance(hostname, str):
        yield f"Created on: {hostname} (informative)"
