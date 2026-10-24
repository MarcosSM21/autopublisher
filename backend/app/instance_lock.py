"""Stable instance locks (see specs/020-deployment-mobile-readiness/research.md §9).

Three `flock` locks live in one root per user, outside the data directory, so a
restore that swaps that directory can never move or replace them:

- M (`maint-`): maintenance operations (backup, restore, set-password).
- A (`data-`): the effective data directory (server, restore).
- B (`db-`): the effective SQLite database (server, restore).

Each file is named after the canonical path of the resource it protects. Locks are
always taken in the order M → A → B and released in reverse order. `flock` (never
`lockf`: POSIX record locks do not conflict inside one process) is released by the
kernel when the process dies, so there are no stale locks and no PID checks; the PID
and command written in the file are only shown in messages.

The root is always `<home>/.local/state/autopublisher/locks/`, where `<home>` comes
only from the password database for the effective user. It never depends on
environment variables (`HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR`, `TMPDIR`,
`AUTOPUBLISHER_*`) or the host configuration: two processes that share a resource
must always meet on the same lock file, so the root is deliberately not
configurable. A lock file left behind is harmless: only a held `flock` excludes.
"""

import fcntl
import hashlib
import json
import os
import pwd
import stat
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.deployment import APP_DIR_NAME, DataLayout, canonical, make_private_dir

# Exit code when a lock is held by another process (EX_TEMPFAIL).
EXIT_BUSY = 75
# The server waits this long for a lock, to absorb the `--reload` handover.
SERVER_RETRY_SECONDS = 5.0
RETRY_INTERVAL_SECONDS = 0.5
STOP_HINT = "Stop it first: `systemctl --user stop autopublisher`."


class LockKind(StrEnum):
    MAINTENANCE = "maint"
    DATA = "data"
    DB = "db"


ORDER = (LockKind.MAINTENANCE, LockKind.DATA, LockKind.DB)

LockRequest = tuple[LockKind, Path]


class LockBusy(Exception):
    """Another process holds the lock; the message names the resource and holder."""

    exit_code = EXIT_BUSY

    def __init__(self, kind: LockKind, resource: Path, pid: int | None) -> None:
        self.kind = kind
        self.resource = resource
        self.pid = pid
        holder = f" (process {pid})" if pid is not None else ""
        if kind is LockKind.MAINTENANCE:
            message = (
                "Another maintenance operation (backup, restore or set-password) "
                f"is running for the data directory {resource}{holder}. "
                "Wait for it to finish."
            )
        else:
            what = "data directory" if kind is LockKind.DATA else "database"
            message = (
                f"AutoPublisher is already running with the {what} "
                f"{resource}{holder}. {STOP_HINT}"
            )
        super().__init__(message)


@dataclass(frozen=True)
class LockObservation:
    held: bool
    pid: int | None = None
    command: str | None = None


class LockRootUnsafe(Exception):
    """The lock directory is not private to this user; nothing is locked."""

    exit_code = 1


def locks_dir() -> Path:
    """The single stable root for this user (see the module docstring)."""
    uid = os.geteuid()
    try:
        home = _passwd_home(uid)
    except KeyError:
        raise LockRootUnsafe(
            f"User {uid} has no home directory in the password database, so "
            "AutoPublisher cannot place its instance locks."
        ) from None
    if not home.is_absolute():
        raise LockRootUnsafe(f"The home directory {home} of user {uid} is not usable.")
    real_home = home.resolve()
    try:
        info = real_home.stat()
    except OSError as exc:
        raise LockRootUnsafe(
            f"The home directory {real_home} cannot be used ({exc})."
        ) from None
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != uid
        or stat.S_IMODE(info.st_mode) & 0o002
    ):
        raise LockRootUnsafe(
            f"The home directory {real_home} must be a directory owned by this user "
            "and not writable by others."
        )
    return real_home / ".local" / "state" / APP_DIR_NAME / "locks"


def _passwd_home(uid: int) -> Path:
    """The home directory from the password database, never from `$HOME`. Tests
    replace it to isolate the filesystem; it is not configuration."""
    return Path(pwd.getpwuid(uid).pw_dir)


def _owned_dir(path: Path, uid: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and info.st_uid == uid


def _private_root() -> Path:
    """Create the root (0700) and refuse one another user could replace or read."""
    root = locks_dir()
    make_private_dir(root)
    try:
        info = root.lstat()
    except OSError as exc:
        raise LockRootUnsafe(
            f"The lock directory {root} cannot be used ({exc})."
        ) from None
    if not _owned_dir(root, os.geteuid()) or stat.S_IMODE(info.st_mode) & 0o077:
        raise LockRootUnsafe(
            f"The lock directory {root} must be a directory owned by this user with "
            f"mode 700. Fix it with: chmod 700 {root}"
        )
    return root


def lock_file(kind: LockKind, resource: Path, root: Path | None = None) -> Path:
    """`<kind>-<first 16 hex of SHA-256 of the canonical path>.lock`."""
    digest = hashlib.sha256(str(canonical(resource)).encode()).hexdigest()[:16]
    return (root or locks_dir()) / f"{kind}-{digest}.lock"


# What each operation takes; always in the order M → A → B.
def server_locks(data_dir: Path, db_path: Path) -> list[LockRequest]:
    return [(LockKind.DATA, data_dir), (LockKind.DB, db_path)]


def maintenance_locks(layout: DataLayout) -> list[LockRequest]:
    """backup and set-password."""
    return [(LockKind.MAINTENANCE, layout.data_dir)]


def restore_locks(layout: DataLayout) -> list[LockRequest]:
    return [
        (LockKind.MAINTENANCE, layout.data_dir),
        *server_locks(layout.data_dir, layout.db_path),
    ]


@contextmanager
def hold(
    requests: Sequence[LockRequest],
    *,
    retry_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[None]:
    """Hold every requested lock; on a busy one, release what was taken and raise
    `LockBusy`. Requests must follow the order M → A → B, each kind once."""
    positions = [ORDER.index(kind) for kind, _ in requests]
    if positions != sorted(set(positions)):
        raise ValueError("Locks must be requested once each, in the order M → A → B.")
    root = _private_root()
    held: list[int] = []
    try:
        for kind, resource in requests:
            held.append(_acquire(kind, canonical(resource), root, retry_seconds, sleep))
        yield
    finally:
        for fd in reversed(held):
            _release(fd)


def observe(kind: LockKind, resource: Path) -> LockObservation:
    """A momentary, read-only look (for `status`): never waits, never creates."""
    path = lock_file(kind, resource)
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return LockObservation(held=False)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pid, command = _read_holder(fd)
            return LockObservation(held=True, pid=pid, command=command)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return LockObservation(held=False)
    finally:
        os.close(fd)


def _acquire(
    kind: LockKind,
    resource: Path,
    root: Path,
    retry_seconds: float,
    sleep: Callable[[float], None],
) -> int:
    fd = os.open(lock_file(kind, resource, root), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                pid, _ = _read_holder(fd)
                os.close(fd)
                raise LockBusy(kind, resource, pid) from None
            sleep(RETRY_INTERVAL_SECONDS)
        except BaseException:
            os.close(fd)
            raise
    # Informative only: who holds it and what it protects.
    info = {"pid": os.getpid(), "command": " ".join(sys.argv), "path": str(resource)}
    os.ftruncate(fd, 0)
    os.pwrite(fd, json.dumps(info).encode(), 0)
    return fd


def _release(fd: int) -> None:
    try:
        os.ftruncate(fd, 0)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_holder(fd: int) -> tuple[int | None, str | None]:
    try:
        info = json.loads(os.pread(fd, 4096, 0) or b"{}")
    except (OSError, ValueError):
        return None, None
    if not isinstance(info, dict):
        return None, None
    pid = info.get("pid")
    command = info.get("command")
    return (
        pid if isinstance(pid, int) else None,
        command if isinstance(command, str) else None,
    )
