"""Deferred cleanup of media files and stored secrets (Feature 021, research §8, §15).

A deletion records what must disappear outside the database in its own transaction
(write-ahead): `pending_file_deletions` and `pending_credential_deletions`. The
runners below try right after the commit and again at start-up. They are idempotent,
never raise, never recreate anything and only ever delete a file or a secret nothing
uses any more. Logs carry counts only: never paths, refs or secrets.
"""

import logging
import threading
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from app.credential_store import CredentialStore, CredentialStoreUnavailable
from app.db import utc_now, write_transaction
from app.models import (
    Content,
    InstagramConnection,
    PendingCredentialDeletion,
    PendingFileDeletion,
    Platform,
    TelegramConnection,
    ThreadsConnection,
    TikTokConnection,
    YouTubeConnection,
)
from app.storage import MediaStorage

logger = logging.getLogger(__name__)

# Every table that may still use a credential reference.
CONNECTION_MODELS = (
    YouTubeConnection,
    InstagramConnection,
    ThreadsConnection,
    TikTokConnection,
    TelegramConnection,
)

# How long a cleanup waits for a platform's credential lock before leaving the row
# for a later run (a renewal or a Telegram client may be using the account).
CREDENTIAL_LOCK_TIMEOUT_SECONDS = 5.0


class CredentialLockTimeout(Exception):
    """The platform's credential lock was not obtained in time."""


CredentialLock = Callable[[int], AbstractContextManager[None]]


@dataclass(frozen=True)
class CredentialTarget:
    """Where a platform keeps its secrets, and the lock its credential changes use."""

    store: CredentialStore
    credential_lock: CredentialLock


@dataclass(frozen=True)
class PendingCredential:
    platform: Platform
    credential_ref: str
    account_id: int | None


class Lock(Protocol):
    def acquire(self, blocking: bool = ..., timeout: float = ...) -> bool: ...

    def release(self) -> None: ...


@contextmanager
def bounded(
    lock: Lock,
    timeout: float = CREDENTIAL_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Hold `lock`, waiting at most `timeout` (`CredentialLockTimeout` otherwise)."""
    if not lock.acquire(timeout=timeout):
        raise CredentialLockTimeout()
    try:
        yield
    finally:
        lock.release()


# --- Enqueueing (in the caller's transaction) ---------------------------------------


def enqueue_files(
    session: Session, paths: Iterable[str], now: datetime | None = None
) -> None:
    """Record media files (relative to the media root) that must be deleted."""
    created_at = now or utc_now()
    rows = [{"storage_path": path, "created_at": created_at} for path in paths]
    if rows:
        session.execute(insert(PendingFileDeletion).on_conflict_do_nothing(), rows)


def enqueue_credentials(
    session: Session, items: Iterable[PendingCredential], now: datetime | None = None
) -> None:
    """Record secrets that must be deleted; a reference already queued stays."""
    created_at = now or utc_now()
    rows = [
        {
            "credential_ref": item.credential_ref,
            "platform": item.platform.value,
            "account_id": item.account_id,
            "created_at": created_at,
        }
        for item in items
    ]
    if rows:
        session.execute(
            insert(PendingCredentialDeletion).on_conflict_do_nothing(), rows
        )


def queue_credential(
    session_factory: sessionmaker[Session], pending: PendingCredential
) -> None:
    """Queue one secret whose deletion failed, in its own short transaction.

    For connection flows that already wrote a secret nothing will use; the caller
    must not hold uncommitted writes (see `write_transaction`). Never raises.
    """
    try:
        with write_transaction(session_factory) as session:
            enqueue_credentials(session, [pending])
    except Exception as error:
        logger.warning(
            "Could not queue a credential cleanup (%s).", type(error).__name__
        )


# --- Runners ------------------------------------------------------------------------


def run_file_cleanup(
    session_factory: sessionmaker[Session],
    storage: MediaStorage,
    paths: Collection[str] | None = None,
) -> None:
    """Delete the queued files (all, or only `paths`).

    A path still referenced by a content is never deleted (only its row goes); a
    missing file counts as deleted; a failure keeps the row for the next run.
    """
    remaining = 0
    try:
        with session_factory() as session:
            query = select(PendingFileDeletion.storage_path)
            if paths is not None:
                query = query.where(PendingFileDeletion.storage_path.in_(list(paths)))
            queued = list(session.scalars(query))
            for path in queued:
                referenced = session.scalars(
                    select(Content.id).where(
                        or_(
                            Content.storage_path == path,
                            Content.sanitized_storage_path == path,
                        )
                    )
                ).first()
                if referenced is None:
                    try:
                        storage.resolve(path).unlink(missing_ok=True)
                    except (OSError, ValueError) as error:
                        logger.warning(
                            "Could not delete a media file (%s); it stays queued.",
                            type(error).__name__,
                        )
                        remaining += 1
                        continue
                session.execute(
                    delete(PendingFileDeletion).where(
                        PendingFileDeletion.storage_path == path
                    )
                )
                session.commit()
    except Exception as error:
        logger.warning("Media file cleanup failed (%s).", type(error).__name__)
        return
    if queued:
        logger.info(
            "Cleaned up %s media file(s); %s still queued.",
            len(queued) - remaining,
            remaining,
        )


def _in_use(session: Session, credential_ref: str) -> bool:
    return any(
        session.scalars(
            select(model.id).where(model.credential_ref == credential_ref)
        ).first()
        is not None
        for model in CONNECTION_MODELS
    )


def run_credential_cleanup(
    session_factory: sessionmaker[Session],
    targets: Mapping[Platform, CredentialTarget],
    refs: Collection[str] | None = None,
) -> None:
    """Delete the queued secrets (all, or only `refs`).

    Each secret is deleted under its platform's credential lock (bounded wait). A
    reference still used by a connection is never deleted (only its row goes); a
    missing secret counts as deleted. An unavailable store is not tried again in
    this run: every remaining row of that platform stays, the other platforms go
    on. Any other failure keeps that row.
    """
    remaining = 0
    unavailable: set[Platform] = set()
    try:
        with session_factory() as session:
            query = select(PendingCredentialDeletion)
            if refs is not None:
                query = query.where(
                    PendingCredentialDeletion.credential_ref.in_(list(refs))
                )
            queued = list(session.scalars(query))
            session.rollback()
            for row in queued:
                platform = Platform(row.platform)
                target = targets.get(platform)
                if target is None or platform in unavailable:
                    remaining += 1
                    continue
                try:
                    with _credential_lock(target, row.account_id):
                        if not _in_use(session, row.credential_ref):
                            target.store.delete(row.credential_ref)
                        session.execute(
                            delete(PendingCredentialDeletion).where(
                                PendingCredentialDeletion.credential_ref
                                == row.credential_ref
                            )
                        )
                        session.commit()
                except CredentialStoreUnavailable:
                    session.rollback()
                    remaining += 1
                    unavailable.add(platform)
                    logger.warning(
                        "Could not clean up credentials (secure storage unavailable); "
                        "they stay queued."
                    )
                except Exception as error:
                    session.rollback()
                    remaining += 1
                    logger.warning(
                        "Could not clean up a credential (%s); it stays queued.",
                        type(error).__name__,
                    )
    except Exception as error:
        logger.warning("Credential cleanup failed (%s).", type(error).__name__)
        return
    if queued and remaining < len(queued):
        logger.info(
            "Cleaned up %s credential(s); %s still queued.",
            len(queued) - remaining,
            remaining,
        )


def _credential_lock(
    target: CredentialTarget, account_id: int | None
) -> AbstractContextManager[None]:
    # Rows without an account (older TikTok orphans) have no lock to take: their
    # reference was already replaced, so nothing renews it any more.
    if account_id is None:
        return nullcontext()
    return target.credential_lock(account_id)


# --- Start-up (research §16) --------------------------------------------------------


def start_credential_cleanup(
    probe_status: Callable[[], str],
    session_factory: sessionmaker[Session],
    targets: Mapping[Platform, CredentialTarget],
) -> threading.Thread:
    """Retry the queued secrets in the background, only if the credential store is
    seen `available` without any interaction: `locked`, `unavailable` and
    `unknown` never touch it (no prompt, no unlock). Start-up never waits."""

    def run() -> None:
        try:
            status = probe_status()
        except Exception as error:
            logger.warning(
                "Credential cleanup skipped (probe failed: %s).", type(error).__name__
            )
            return
        if status != "available":
            logger.info("Credential cleanup skipped (secure storage %s).", status)
            return
        run_credential_cleanup(session_factory, targets)

    thread = threading.Thread(target=run, name="credential-cleanup", daemon=True)
    thread.start()
    return thread
