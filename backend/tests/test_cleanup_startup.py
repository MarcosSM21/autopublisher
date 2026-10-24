"""Deferred cleanup at start-up (Feature 021, research §16): media files are
retried before anything else runs; secrets only in the background and only when
the credential store is seen `available` (never a prompt, never an unlock)."""

import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.credential_store import CredentialStoreProbe, ProbeStatus
from app.db import run_migrations
from app.main import create_app
from app.scheduler import SchedulerSettings
from tests.fakes import InMemoryCredentialStore

NOW = "2026-10-24 10:00:00"


class RecordingStore(InMemoryCredentialStore):
    """Records every use: with the store not seen available it must stay empty."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def get(self, ref: str) -> str | None:
        self.calls.append("get")
        return super().get(ref)

    def set(self, ref: str, value: str) -> None:
        self.calls.append("set")
        super().set(ref, value)

    def delete(self, ref: str) -> None:
        self.calls.append("delete")
        super().delete(ref)


def _app(
    db_path: Path,
    media_dir: Path,
    youtube: InMemoryCredentialStore,
    tiktok: InMemoryCredentialStore,
    probe: CredentialStoreProbe,
) -> FastAPI:
    return create_app(
        db_path,
        media_dir,
        credential_store=youtube,
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        tiktok_credential_store=tiktok,
        telegram_credential_store=InMemoryCredentialStore(),
        scheduler_settings=SchedulerSettings(autostart=False),
        credential_probe=probe,
    )


def _queue_credentials(db_path: Path) -> None:
    run_migrations(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO pending_credential_deletions VALUES (?, ?, ?, ?)",
            [("yt-ref", "youtube", 1, NOW), ("tt-ref", "tiktok", None, NOW)],
        )


def _queued_credentials(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT credential_ref FROM pending_credential_deletions ORDER BY 1"
            )
        ]


def _probe(status: ProbeStatus) -> CredentialStoreProbe:
    return CredentialStoreProbe(check=lambda: status)


def test_queued_media_files_are_deleted_at_start_up(
    db_path: Path, media_dir: Path
) -> None:
    run_migrations(db_path)
    stale = media_dir / "projects" / "1" / "deleted.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"deleted media")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO pending_file_deletions VALUES (?, ?)",
            ("projects/1/deleted.png", NOW),
        )
    app = _app(
        db_path,
        media_dir,
        InMemoryCredentialStore(),
        InMemoryCredentialStore(),
        _probe("locked"),
    )

    with TestClient(app):
        assert not stale.exists()
        with sqlite3.connect(db_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM pending_file_deletions"
            ).fetchone() == (0,)


@pytest.mark.parametrize("status", ["locked", "unavailable", "unknown"])
def test_secrets_are_left_alone_unless_the_store_is_available(
    db_path: Path, media_dir: Path, status: ProbeStatus
) -> None:
    _queue_credentials(db_path)
    youtube, tiktok = RecordingStore(), RecordingStore()
    youtube.secrets["yt-ref"] = "secret"

    app = _app(db_path, media_dir, youtube, tiktok, _probe(status))
    with TestClient(app):
        app.state.credential_cleanup.join(timeout=10)

    assert youtube.calls == [] and tiktok.calls == []
    assert youtube.secrets == {"yt-ref": "secret"}
    assert _queued_credentials(db_path) == ["tt-ref", "yt-ref"]


def test_secrets_are_cleaned_up_when_the_store_is_available(
    db_path: Path, media_dir: Path
) -> None:
    _queue_credentials(db_path)
    youtube, tiktok = RecordingStore(), RecordingStore()
    youtube.secrets["yt-ref"] = "secret"
    tiktok.secrets["tt-ref"] = "secret"

    app = _app(db_path, media_dir, youtube, tiktok, _probe("available"))
    with TestClient(app):
        app.state.credential_cleanup.join(timeout=10)

    assert youtube.secrets == {} and tiktok.secrets == {}
    assert _queued_credentials(db_path) == []


def test_start_up_never_waits_for_the_probe(db_path: Path, media_dir: Path) -> None:
    _queue_credentials(db_path)
    probing = threading.Event()
    release = threading.Event()

    def slow_probe() -> ProbeStatus:
        probing.set()
        assert release.wait(timeout=10)
        return "available"

    app = _app(
        db_path,
        media_dir,
        InMemoryCredentialStore(),
        InMemoryCredentialStore(),
        CredentialStoreProbe(check=slow_probe),
    )
    with TestClient(app) as client:
        # The app already serves while the probe is still running.
        assert probing.wait(timeout=10)
        assert client.get("/health").status_code == 200
        release.set()
        app.state.credential_cleanup.join(timeout=10)
    assert _queued_credentials(db_path) == []
