"""Online backup (Feature 020 T026, research §20-21)."""

import errno
import hashlib
import io
import json
import sqlite3
import tarfile
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, backup, instance_lock
from app.backup import BackupError, create_backup, verify_archive
from app.deployment import DataLayout, DeploymentSettings
from tests.conftest import (
    create_project,
    import_one,
    installation_app,
    installation_client,
    installation_settings,
    make_image,
    sign_in,
)
from tests.fakes import InMemoryCredentialStore
from tests.test_migrations import _alembic_config

SECRET = "TIKTOK-REFRESH-TOKEN-never-in-a-backup"
PLATFORM_JSON = b'{"installed": {"client_id": "x", "client_secret": "s"}}\n'


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@dataclass
class Installation:
    settings: DeploymentSettings
    app: FastAPI
    client: TestClient
    content: dict[str, object]

    @property
    def layout(self) -> DataLayout:
        assert self.settings.layout is not None
        return self.settings.layout


@pytest.fixture
def running(tmp_path: Path) -> Iterator[Installation]:
    """A running installation with one imported image, a session and a secret."""
    settings = installation_settings(tmp_path)
    store = InMemoryCredentialStore()
    store.set("tiktok-ref", SECRET)
    app = installation_app(settings, tiktok_credential_store=store)
    with installation_client(app) as client:
        sign_in(client, app)
        project = create_project(client, "Cyber")
        content = import_one(client, project["id"], "photo.png", make_image())[
            "content"
        ]
        assert settings.layout is not None
        (settings.layout.data_dir / "google-oauth-client.json").write_bytes(
            PLATFORM_JSON
        )
        yield Installation(settings, app, client, content)


def _rows(db: Path, sql: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(db)) as connection:
        return connection.execute(sql).fetchall()


def _archived_db(archive: Path, tmp_path: Path) -> Path:
    with tarfile.open(archive) as tar:
        stream = tar.extractfile("autopublisher.db")
        assert stream is not None
        target = tmp_path / "archived.db"
        target.write_bytes(stream.read())
    return target


def _names(archive: Path) -> list[str]:
    with tarfile.open(archive) as tar:
        return tar.getnames()


def _leftovers(output: Path) -> list[str]:
    return sorted(path.name for path in output.iterdir()) if output.exists() else []


def test_online_backup_of_a_running_installation(
    running: Installation, tmp_path: Path
) -> None:
    output = tmp_path / "backups"
    layout = running.layout
    live_sessions = _rows(layout.db_path, "SELECT token_hash FROM auth_sessions")
    assert live_sessions

    result = create_backup(layout, output)

    media = [name for name in _names(result.path) if name.startswith("media/")]
    assert len(media) == 1 and media[0].startswith("media/projects/")
    assert _names(result.path) == [
        "autopublisher.db",
        media[0],
        "config/google-oauth-client.json",
        "manifest.json",
    ]
    assert result.path.name.startswith("autopublisher-backup-")
    assert result.path.suffix == ".tar"
    assert (result.path.stat().st_mode & 0o777) == 0o600
    assert _leftovers(output) == [result.path.name]  # no partial, no snapshot

    archived = _archived_db(result.path, tmp_path)
    assert _rows(archived, "SELECT COUNT(*) FROM auth_sessions") == [(0,)]
    assert _rows(archived, "SELECT password_hash FROM installation_auth") == _rows(
        layout.db_path, "SELECT password_hash FROM installation_auth"
    )
    # The live database keeps every browser signed in.
    assert (
        _rows(layout.db_path, "SELECT token_hash FROM auth_sessions") == live_sessions
    )
    assert running.client.get("/api/projects").status_code == 200


def test_manifest(running: Installation, tmp_path: Path) -> None:
    result = create_backup(running.layout, tmp_path / "backups")
    with tarfile.open(result.path) as tar:
        stream = tar.extractfile("manifest.json")
        assert stream is not None
        document = json.loads(stream.read())
        for entry in document["files"]:
            member = tar.extractfile(entry["path"])
            assert member is not None
            data = member.read()
            assert len(data) == entry["size"]
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert document["format"] == "autopublisher-backup"
    assert document["format_version"] == 1
    assert document["schema_revision"] == "0019"
    assert document["app_version"] == "0.1.0"
    assert document["components"] == ["database", "media", "platform_config"]
    assert set(document["source"]) == {"hostname", "development_data_dir"}
    config = next(f for f in document["files"] if f["path"].startswith("config/"))
    assert config["sha256"] == hashlib.sha256(PLATFORM_JSON).hexdigest()
    assert verify_archive(result.path) == result.manifest


def test_no_secret_in_the_archive(running: Installation, tmp_path: Path) -> None:
    token = running.client.cookies.get(auth.SESSION_COOKIE)
    assert token
    result = create_backup(running.layout, tmp_path / "backups")
    data = result.path.read_bytes()
    assert SECRET.encode() not in data
    assert token.encode() not in data
    assert auth.hash_token(token).encode() not in data
    assert b"correct horse battery" not in data
    for excluded in (b"tmp/", b"config.toml", b"autopublisher.log"):
        assert excluded not in b"\n".join(n.encode() for n in _names(result.path))


def test_sanitized_copies_are_included(running: Installation, tmp_path: Path) -> None:
    layout = running.layout
    clean = b"clean copy bytes"
    content_id = running.content["id"]
    project_id = running.content["project_id"]
    relative = f"projects/{project_id}/{'c' * 32}.png"
    (layout.media_dir / relative).write_bytes(clean)
    with closing(sqlite3.connect(layout.db_path)) as db:
        db.execute(
            "UPDATE contents SET metadata_status = 'sanitized', "
            "sanitized_storage_path = ?, sanitized_checksum = ?, "
            "sanitized_size_bytes = ?, sanitized_at = '2026-10-23 10:00:00' "
            "WHERE id = ?",
            (relative, hashlib.sha256(clean).hexdigest(), len(clean), content_id),
        )
        db.commit()

    result = create_backup(layout, tmp_path / "backups")

    assert f"media/{relative}" in _names(result.path)


def test_pre_020_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "autopublisher.db"
    command.upgrade(_alembic_config(db_path), "0017")
    with closing(sqlite3.connect(db_path)) as db:
        db.execute(
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            "updated_at) VALUES (1, 'Old', 'old', 1, '2026-01-01', '2026-01-01')"
        )
        db.commit()
    before = db_path.read_bytes()
    layout = DataLayout(data_dir, db_path, data_dir / "media", {})

    result = create_backup(layout, tmp_path / "backups")

    assert db_path.read_bytes() == before  # never migrated or modified
    assert result.manifest.schema_revision == "0017"
    archived = _archived_db(result.path, tmp_path)
    tables = {row[0] for row in _rows(archived, "SELECT name FROM sqlite_master")}
    assert "auth_sessions" not in tables and "installation_auth" not in tables
    assert _rows(archived, "SELECT name FROM projects") == [("Old",)]


@pytest.mark.parametrize("change", ["altered", "missing"])
def test_media_changed_during_the_backup_aborts(
    running: Installation, tmp_path: Path, change: str
) -> None:
    layout = running.layout
    [stored] = list((layout.media_dir / "projects").rglob("*.png"))

    def tamper() -> None:
        if change == "missing":
            stored.unlink()
        else:
            stored.write_bytes(stored.read_bytes()[::-1])

    output = tmp_path / "backups"
    with pytest.raises(BackupError, match="Media changed during the backup"):
        create_backup(layout, output, after_snapshot=tamper)
    assert _leftovers(output) == []


def test_a_concurrent_import_yields_a_valid_snapshot(
    running: Installation, tmp_path: Path
) -> None:
    project_id = running.content["project_id"]

    def import_another() -> None:
        import_one(running.client, int(str(project_id)), "late.png", make_image())

    result = create_backup(
        running.layout, tmp_path / "backups", after_snapshot=import_another
    )

    assert verify_archive(result.path) == result.manifest
    media = [n for n in _names(result.path) if n.startswith("media/")]
    assert len(media) == 1  # only what the snapshot references


def test_write_failure_leaves_nothing(
    running: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(path: Path) -> backup.Manifest:
        assert path.name.endswith(".tar.partial") and path.exists()
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(backup, "verify_archive", full)
    output = tmp_path / "backups"
    with pytest.raises(BackupError, match="No space left on device"):
        create_backup(running.layout, output)
    assert _leftovers(output) == []


def test_not_enough_free_space(
    running: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "_free_bytes", lambda path: 0)
    output = tmp_path / "backups"
    with pytest.raises(BackupError, match="Not enough free space"):
        create_backup(running.layout, output)
    assert _leftovers(output) == []


def test_stale_partials_are_removed(running: Installation, tmp_path: Path) -> None:
    output = tmp_path / "backups"
    output.mkdir()
    (output / ".autopublisher-backup-20000101T000000Z.tar.partial").write_bytes(b"x")
    (output / ".autopublisher-snapshot-20000101T000000Z.db").write_bytes(b"x")

    result = create_backup(running.layout, output)

    assert _leftovers(output) == [result.path.name]


@pytest.mark.parametrize("where", ["inside", "symlink-inside", "parent"])
def test_output_inside_the_data_dir_is_rejected(
    running: Installation, tmp_path: Path, where: str
) -> None:
    data_dir = running.layout.data_dir
    if where == "inside":
        output = data_dir / "backups"
    elif where == "symlink-inside":
        link = tmp_path / "looks-outside"
        link.symlink_to(data_dir)
        output = link / "backups"
    else:
        output = data_dir.parent
    with pytest.raises(BackupError, match="outside the data directory"):
        create_backup(running.layout, output)
    assert not (data_dir / "backups").exists()


def test_specific_override_outside_the_data_dir_is_rejected(
    running: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOPUBLISHER_TIKTOK_APP_FILE", str(tmp_path / "tt.json"))
    with pytest.raises(backup.UnsupportedOverrides):
        create_backup(running.layout, tmp_path / "backups")


def test_concurrent_backups(running: Installation, tmp_path: Path) -> None:
    with instance_lock.hold(instance_lock.maintenance_locks(running.layout)):
        with pytest.raises(instance_lock.LockBusy) as busy:
            create_backup(running.layout, tmp_path / "backups")
    assert busy.value.exit_code == 75


def test_archive_reads_back_through_tarfile(
    running: Installation, tmp_path: Path
) -> None:
    result = create_backup(running.layout, tmp_path / "backups")
    with tarfile.open(result.path) as tar:
        assert all(m.isreg() and m.mode == 0o600 for m in tar.getmembers())
        manifest = tar.extractfile("manifest.json")
        assert manifest is not None
        assert io.BytesIO(manifest.read()).getvalue().startswith(b"{")
