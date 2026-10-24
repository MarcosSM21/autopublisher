"""Deferred credential cleanup (Feature 021, research §15): under the platform's
credential lock, never a secret still in use, unavailable store keeps the rows."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.cleanup import (
    CredentialTarget,
    PendingCredential,
    bounded,
    enqueue_credentials,
    run_credential_cleanup,
)
from app.db import create_db_engine, run_migrations, write_transaction
from app.models import Platform
from tests.fakes import InMemoryCredentialStore

NOW = "2026-10-24 10:00:00"
_locks: dict[int, threading.Lock] = {}


def _lock(account_id: int) -> AbstractContextManager[None]:
    return bounded(_locks.setdefault(account_id, threading.Lock()), timeout=0.01)


@pytest.fixture(autouse=True)
def fresh_locks() -> None:
    _locks.clear()


@pytest.fixture
def factory(db_path: Path) -> Iterator[sessionmaker[Session]]:
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def stores() -> dict[Platform, InMemoryCredentialStore]:
    return {
        Platform.YOUTUBE: InMemoryCredentialStore(),
        Platform.TIKTOK: InMemoryCredentialStore(),
    }


def _targets(
    stores: dict[Platform, InMemoryCredentialStore],
) -> dict[Platform, CredentialTarget]:
    return {
        platform: CredentialTarget(store, _lock) for platform, store in stores.items()
    }


def _queue(factory: sessionmaker[Session], *items: PendingCredential) -> None:
    with write_transaction(factory) as session:
        enqueue_credentials(session, items)


def _queued(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT credential_ref FROM pending_credential_deletions ORDER BY 1"
            )
        ]


def test_queued_secrets_are_deleted_from_their_platform_store(
    factory: sessionmaker[Session],
    stores: dict[Platform, InMemoryCredentialStore],
    db_path: Path,
) -> None:
    stores[Platform.YOUTUBE].secrets.update({"yt-1": "s", "shared-name": "keep"})
    stores[Platform.TIKTOK].secrets.update({"tt-1": "s", "shared-name": "s"})
    _queue(
        factory,
        PendingCredential(Platform.YOUTUBE, "yt-1", 1),
        PendingCredential(Platform.TIKTOK, "tt-1", 2),
        PendingCredential(Platform.TIKTOK, "shared-name", None),
    )
    _queue(factory, PendingCredential(Platform.TIKTOK, "tt-1", 2))  # INSERT OR IGNORE

    run_credential_cleanup(factory, _targets(stores))

    assert stores[Platform.YOUTUBE].secrets == {"shared-name": "keep"}
    assert stores[Platform.TIKTOK].secrets == {}
    assert _queued(db_path) == []
    run_credential_cleanup(factory, _targets(stores))  # idempotent
    assert _queued(db_path) == []


def test_a_missing_secret_counts_as_deleted(
    factory: sessionmaker[Session],
    stores: dict[Platform, InMemoryCredentialStore],
    db_path: Path,
) -> None:
    _queue(factory, PendingCredential(Platform.YOUTUBE, "gone", 1))

    run_credential_cleanup(factory, _targets(stores))

    assert _queued(db_path) == []


def test_an_unavailable_store_keeps_every_remaining_row(
    factory: sessionmaker[Session],
    stores: dict[Platform, InMemoryCredentialStore],
    db_path: Path,
) -> None:
    stores[Platform.YOUTUBE].secrets.update({"yt-1": "s", "yt-2": "s"})
    stores[Platform.YOUTUBE].unavailable = True
    _queue(
        factory,
        PendingCredential(Platform.YOUTUBE, "yt-1", 1),
        PendingCredential(Platform.YOUTUBE, "yt-2", 1),
    )

    run_credential_cleanup(factory, _targets(stores))

    assert _queued(db_path) == ["yt-1", "yt-2"]
    stores[Platform.YOUTUBE].unavailable = False
    run_credential_cleanup(factory, _targets(stores), refs=["yt-2"])
    assert _queued(db_path) == ["yt-1"]
    assert set(stores[Platform.YOUTUBE].secrets) == {"yt-1"}


def test_a_reference_still_in_use_only_drops_the_row(
    factory: sessionmaker[Session],
    stores: dict[Platform, InMemoryCredentialStore],
    db_path: Path,
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            "updated_at) VALUES (1, 'P', 'p', 1, ?, ?)",
            (NOW, NOW),
        )
        connection.execute(
            "INSERT INTO accounts (id, project_id, platform, handle, handle_key, "
            "is_active, created_at, updated_at) VALUES (1, 1, 'youtube', 'a', 'a', "
            "1, ?, ?)",
            (NOW, NOW),
        )
        connection.execute(
            "INSERT INTO youtube_connections (account_id, project_id, channel_id, "
            "channel_title, status, credential_ref, connected_at, updated_at) VALUES "
            "(1, 1, 'UC1', 'C', 'connected', 'in-use', ?, ?)",
            (NOW, NOW),
        )
    stores[Platform.YOUTUBE].secrets["in-use"] = "active secret"
    _queue(factory, PendingCredential(Platform.YOUTUBE, "in-use", 1))

    run_credential_cleanup(factory, _targets(stores))

    assert stores[Platform.YOUTUBE].secrets == {"in-use": "active secret"}
    assert _queued(db_path) == []


def test_a_busy_credential_lock_keeps_the_row(
    factory: sessionmaker[Session],
    stores: dict[Platform, InMemoryCredentialStore],
    db_path: Path,
) -> None:
    stores[Platform.YOUTUBE].secrets["yt-1"] = "s"
    _queue(factory, PendingCredential(Platform.YOUTUBE, "yt-1", 7))
    held = _locks.setdefault(7, threading.Lock())
    held.acquire()  # e.g. a token renewal of account 7 in progress
    try:
        run_credential_cleanup(factory, _targets(stores))
    finally:
        held.release()

    assert stores[Platform.YOUTUBE].secrets == {"yt-1": "s"}
    assert _queued(db_path) == ["yt-1"]
    run_credential_cleanup(factory, _targets(stores))
    assert _queued(db_path) == []


def test_rows_of_a_platform_without_target_wait(
    factory: sessionmaker[Session],
    stores: dict[Platform, InMemoryCredentialStore],
    db_path: Path,
) -> None:
    _queue(factory, PendingCredential(Platform.TELEGRAM, "tg-1", 1))

    run_credential_cleanup(factory, _targets(stores))

    assert _queued(db_path) == ["tg-1"]


def test_logs_never_carry_references(
    factory: sessionmaker[Session],
    stores: dict[Platform, InMemoryCredentialStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    stores[Platform.YOUTUBE].unavailable = True
    _queue(factory, PendingCredential(Platform.YOUTUBE, "secret-ref-123", 1))

    run_credential_cleanup(factory, _targets(stores))

    assert "secret-ref-123" not in caplog.text
