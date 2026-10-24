"""Deferred media file cleanup (Feature 021, research §8, §15): relative paths,
idempotent, never a file a media item still uses, failures stay queued."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.cleanup import enqueue_files, run_file_cleanup
from app.db import create_db_engine, run_migrations, write_transaction
from app.storage import MediaStorage

NOW = "2026-10-24 10:00:00"


@pytest.fixture
def factory(db_path: Path) -> Iterator[sessionmaker[Session]]:
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def storage(media_dir: Path) -> MediaStorage:
    storage = MediaStorage(media_dir)
    storage.prepare()
    return storage


def _file(storage: MediaStorage, relative: str) -> Path:
    path = storage.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"media")
    return path


def _queue(factory: sessionmaker[Session], *paths: str) -> None:
    with write_transaction(factory) as session:
        enqueue_files(session, paths)


def _queued(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT storage_path FROM pending_file_deletions ORDER BY 1"
            )
        ]


def test_queued_files_are_deleted_and_dequeued(
    factory: sessionmaker[Session], storage: MediaStorage, db_path: Path
) -> None:
    original = _file(storage, "projects/1/a.png")
    copy = _file(storage, "projects/1/a.clean.png")
    _queue(factory, "projects/1/a.png", "projects/1/a.clean.png")
    _queue(factory, "projects/1/a.png")  # queued twice: still one row

    run_file_cleanup(factory, storage)

    assert not original.exists() and not copy.exists()
    assert _queued(db_path) == []
    run_file_cleanup(factory, storage)  # idempotent
    assert _queued(db_path) == []


def test_only_the_given_paths_are_cleaned(
    factory: sessionmaker[Session], storage: MediaStorage, db_path: Path
) -> None:
    kept = _file(storage, "projects/1/b.png")
    _file(storage, "projects/1/a.png")
    _queue(factory, "projects/1/a.png", "projects/1/b.png")

    run_file_cleanup(factory, storage, ["projects/1/a.png"])

    assert kept.exists()
    assert _queued(db_path) == ["projects/1/b.png"]


def test_a_missing_file_counts_as_deleted(
    factory: sessionmaker[Session], storage: MediaStorage, db_path: Path
) -> None:
    _queue(factory, "projects/1/gone.png")

    run_file_cleanup(factory, storage)

    assert _queued(db_path) == []


def test_a_failed_unlink_stays_queued_for_the_next_run(
    factory: sessionmaker[Session],
    storage: MediaStorage,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _file(storage, "projects/1/a.png")
    _queue(factory, "projects/1/a.png")
    original_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    run_file_cleanup(factory, storage)

    assert path.exists()
    assert _queued(db_path) == ["projects/1/a.png"]
    # Logs never carry the path.
    assert "a.png" not in caplog.text and str(storage.root) not in caplog.text

    monkeypatch.setattr(Path, "unlink", original_unlink)
    run_file_cleanup(factory, storage)
    assert not path.exists()
    assert _queued(db_path) == []


def test_a_path_still_referenced_by_a_media_item_is_never_deleted(
    factory: sessionmaker[Session], storage: MediaStorage, db_path: Path
) -> None:
    original = _file(storage, "projects/1/a.png")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            "updated_at) VALUES (1, 'P', 'p', 1, ?, ?)",
            (NOW, NOW),
        )
        connection.execute(
            "INSERT INTO contents (project_id, media_type, media_format, "
            "storage_path, original_filename, checksum, size_bytes, hashtags, "
            "created_at, updated_at) VALUES (1, 'image', 'png', 'projects/1/a.png', "
            "'a.png', 'abc', 5, '[]', ?, ?)",
            (NOW, NOW),
        )
    _queue(factory, "projects/1/a.png")

    run_file_cleanup(factory, storage)

    assert original.exists()
    assert _queued(db_path) == []


@pytest.mark.parametrize("path", ["../outside.png", "/etc/hostname", "."])
def test_a_path_outside_the_media_root_is_refused(
    factory: sessionmaker[Session],
    storage: MediaStorage,
    db_path: Path,
    tmp_path: Path,
    path: str,
) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not media")
    _queue(factory, path)

    run_file_cleanup(factory, storage)

    assert outside.exists()
    assert _queued(db_path) == [path]
