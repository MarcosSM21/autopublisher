"""Validated restore (Feature 020 T027, research §22)."""

import getpass
import hashlib
import io
import json
import os
import sqlite3
import tarfile
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text

from app import auth, backup, cli, config, instance_lock
from app.backup import BackupError, create_backup, restore_backup
from app.deployment import DataLayout, HostConfig, config_path, write_host_config
from tests.conftest import (
    INSTALLATION_PASSWORD,
    create_account,
    create_project,
    import_one,
    installation_app,
    installation_client,
    installation_settings,
    make_image,
    sign_in,
)
from tests.fakes import InMemoryCredentialStore, client_config_json
from tests.test_migrations import _alembic_config

PLATFORM_JSON = b'{"client_key": "k", "client_secret": "s"}\n'


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@pytest.fixture(autouse=True)
def reset_installation_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_installation_data_dir", None)


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    """A backup of an installation with an image, a YouTube account (its token is
    only in that machine's keyring), a session and a platform JSON file."""
    source = tmp_path / "source"
    settings = installation_settings(source)
    app = installation_app(settings)
    assert settings.layout is not None
    with installation_client(app) as client:
        sign_in(client, app)
        project = create_project(client, "Cyber")
        import_one(client, project["id"], "photo.png", make_image())
        account = create_account(client, project["id"], "youtube", "cyber")
        with app.state.session_factory() as db:
            db.execute(
                text(
                    "INSERT INTO youtube_connections (account_id, project_id, "
                    "channel_id, channel_title, status, credential_ref, "
                    "connected_at, updated_at) VALUES (:account, :project, 'UC1', "
                    "'Channel', 'connected', 'ref-1', '2026-10-06 10:00:00', "
                    "'2026-10-06 10:00:00')"
                ),
                {"account": account["id"], "project": project["id"]},
            )
            db.commit()
        (settings.layout.data_dir / "tiktok-app.json").write_bytes(PLATFORM_JSON)
        result = create_backup(settings.layout, tmp_path / "backups")
    return result.path


def _layout(data_dir: Path) -> DataLayout:
    return DataLayout(
        data_dir=data_dir,
        db_path=data_dir / config.DB_FILE_NAME,
        media_dir=data_dir / config.MEDIA_DIR_NAME,
        platform_files={},
    )


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """An existing installation data directory that will be replaced."""
    data_dir = tmp_path / "target" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / config.DB_FILE_NAME).write_bytes(b"old database")
    (data_dir / "old-only.txt").write_text("previous data")
    return data_dir


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _staging_left(target: Path) -> list[Path]:
    return list(target.parent.glob(f".{target.name}.restore-*"))


def test_round_trip_into_another_directory(
    archive: Path, target: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_config = HostConfig(path=config_path(), data_dir=target, lan_enabled=False)
    write_host_config(host_config)
    config_before = config_path().read_bytes()

    result = restore_backup(_layout(target), archive)

    assert result.target == target.resolve()
    assert result.password_set
    assert result.previous is not None
    assert _tree(result.previous) == {
        config.DB_FILE_NAME: b"old database",
        "old-only.txt": b"previous data",
    }
    assert (target / "tiktok-app.json").read_bytes() == PLATFORM_JSON
    assert ((target / "tiktok-app.json").stat().st_mode & 0o777) == 0o600
    assert not (target / "old-only.txt").exists()
    assert config_path().read_bytes() == config_before  # host config untouched
    assert _staging_left(target) == []
    with closing(sqlite3.connect(target / config.DB_FILE_NAME)) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone() == (0,)

    # The installation runs from the new place: same password, media readable,
    # and the account whose token stayed in the other keyring needs a reconnect.
    client_file = tmp_path / "google-oauth-client.json"
    client_file.write_text(client_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE", str(client_file))
    settings = installation_settings(tmp_path / "restored")
    restored = DataLayout(
        target,
        target / config.DB_FILE_NAME,
        target / config.MEDIA_DIR_NAME,
        {},
    )
    object.__setattr__(settings, "layout", restored)
    app = installation_app(settings, credential_store=InMemoryCredentialStore())
    with installation_client(app) as client:
        anonymous = client.get("/api/projects")
        assert anonymous.status_code == 401  # zero sessions
        response = client.post(
            "/api/auth/login", json={"password": INSTALLATION_PASSWORD}
        )
        assert response.status_code == 204
        [project] = client.get("/api/projects").json()
        [content] = client.get(f"/api/projects/{project['id']}/contents").json()
        assert client.get(f"/api/contents/{content['id']}/file").status_code == 200
        [account] = [
            a
            for a in client.get(f"/api/projects/{project['id']}/accounts").json()
            if a["platform"] == "youtube"
        ]
        verify = client.post(f"/api/accounts/{account['id']}/youtube-connection/verify")
        assert verify.status_code == 409
        connection = client.get(f"/api/accounts/{account['id']}/youtube-connection")
        assert connection.json()["status"] == "reconnect_required"


def test_restore_into_a_new_directory(archive: Path, tmp_path: Path) -> None:
    fresh = tmp_path / "fresh" / "data"
    result = restore_backup(_layout(fresh), archive)
    assert result.previous is None
    assert (fresh / config.DB_FILE_NAME).is_file()


def test_symlinked_target_is_restored_at_its_real_place(
    archive: Path, target: Path, tmp_path: Path
) -> None:
    link = tmp_path / "data-link"
    link.symlink_to(target)

    result = restore_backup(_layout(link), archive)

    assert result.target == target.resolve()
    assert link.is_symlink() and (link / config.DB_FILE_NAME).is_file()


def test_mount_point_target_is_rejected(archive: Path, target: Path) -> None:
    before = _tree(target)
    with pytest.raises(BackupError, match="subdirectory inside the mounted disk"):
        restore_backup(_layout(target), archive, is_mount=lambda path: True)
    assert _tree(target) == before


def test_cancelled_confirmation_changes_nothing(archive: Path, target: Path) -> None:
    before = _tree(target)
    with pytest.raises(backup.RestoreCancelled):
        restore_backup(_layout(target), archive, confirm=lambda manifest: False)
    assert _tree(target) == before
    assert _staging_left(target) == []


# --- Hostile and broken archives ------------------------------------------------------


def _rebuild(
    source: Path,
    destination: Path,
    *,
    edit_manifest: Callable[[dict[str, object]], None] | None = None,
    extra: list[tarfile.TarInfo] | None = None,
    drop_media: bool = False,
    corrupt_media: bool = False,
    corrupt_db: bool = False,
) -> Path:
    with tarfile.open(source) as tar:
        members = [
            (member, tar.extractfile(member).read())  # type: ignore[union-attr]
            for member in tar.getmembers()
        ]
    manifest = json.loads(dict((m.name, d) for m, d in members)["manifest.json"])
    out: list[tuple[tarfile.TarInfo, bytes]] = []
    for member, data in members:
        if member.name == "manifest.json":
            continue
        if member.name.startswith("media/") and drop_media:
            continue
        if member.name.startswith("media/") and corrupt_media:
            data = data[::-1]
        if member.name == "autopublisher.db" and corrupt_db:
            data = b"SQLite format 3\x00" + b"\x00" * (len(data) - 16)
            for entry in manifest["files"]:
                if entry["path"] == "autopublisher.db":
                    entry["sha256"] = hashlib.sha256(data).hexdigest()
        out.append((member, data))
    if edit_manifest is not None:
        edit_manifest(manifest)
    with tarfile.open(destination, "w") as tar:
        for member, data in out:
            tar.addfile(member, io.BytesIO(data))
        for member in extra or []:
            tar.addfile(
                member, io.BytesIO(b"x" * member.size) if member.isreg() else None
            )
        document = json.dumps(manifest).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(document)
        tar.addfile(info, io.BytesIO(document))
    return destination


def _member(name: str, kind: bytes = tarfile.REGTYPE, size: int = 1) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.size = size if kind == tarfile.REGTYPE else 0
    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
        info.linkname = "/etc/passwd"
    return info


def _set(key: str, value: object) -> Callable[[dict[str, object]], None]:
    def edit(manifest: dict[str, object]) -> None:
        manifest[key] = value

    return edit


def _resize(manifest: dict[str, object]) -> None:
    files = manifest["files"]
    assert isinstance(files, list)
    files[0]["size"] += 1


HOSTILE: dict[str, dict[str, object]] = {
    "parent-traversal": {"extra": [_member("../evil.txt")]},
    "nested-traversal": {"extra": [_member("media/projects/1/../../../evil")]},
    "absolute-path": {"extra": [_member("/tmp/evil.txt")]},
    "symlink": {"extra": [_member("media/projects/1/link", tarfile.SYMTYPE)]},
    "hard-link": {"extra": [_member("media/projects/1/link", tarfile.LNKTYPE)]},
    "device": {"extra": [_member("media/projects/1/dev", tarfile.CHRTYPE)]},
    "fifo": {"extra": [_member("media/projects/1/fifo", tarfile.FIFOTYPE)]},
    "extra-member": {"extra": [_member("media/projects/1/extra.png")]},
    "unknown-file": {"extra": [_member("config.toml")]},
    "duplicate-member": {"extra": [_member("autopublisher.db")]},
    "missing-member": {"drop_media": True},
    "checksum-mismatch": {"corrupt_media": True},
    "size-mismatch": {"edit_manifest": _resize},
    "unknown-format-version": {"edit_manifest": _set("format_version", 2)},
    "unknown-schema": {"edit_manifest": _set("schema_revision", "9999")},
    "failing-integrity-check": {"corrupt_db": True},
}


@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_hostile_or_broken_archive_leaves_the_target_untouched(
    archive: Path, target: Path, tmp_path: Path, case: str
) -> None:
    hostile = _rebuild(archive, tmp_path / f"{case}.tar", **HOSTILE[case])  # type: ignore[arg-type]
    before = _tree(target)

    with pytest.raises(BackupError):
        restore_backup(_layout(target), hostile)

    assert _tree(target) == before
    assert _staging_left(target) == []
    assert not list(target.parent.glob("*.before-restore-*"))
    assert not (tmp_path / "evil.txt").exists()


@pytest.mark.parametrize("damage", ["truncated", "garbage", "missing"])
def test_corrupt_archive(
    archive: Path, target: Path, tmp_path: Path, damage: str
) -> None:
    broken = tmp_path / "broken.tar"
    if damage == "truncated":
        broken.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    elif damage == "garbage":
        broken.write_bytes(os.urandom(4096))
    before = _tree(target)
    with pytest.raises(BackupError):
        restore_backup(_layout(target), broken)
    assert _tree(target) == before


# --- Locks and the swap ---------------------------------------------------------------


def test_a_running_server_blocks_the_restore(archive: Path, target: Path) -> None:
    layout = _layout(target)
    with instance_lock.hold(
        instance_lock.server_locks(layout.data_dir, layout.db_path)
    ):
        with pytest.raises(instance_lock.LockBusy) as busy:
            restore_backup(layout, archive)
    assert busy.value.exit_code == 75
    assert (target / "old-only.txt").exists()


def test_no_server_can_start_between_the_renames(archive: Path, target: Path) -> None:
    layout = _layout(target)
    attempts: list[str] = []

    def start_a_server() -> None:
        assert not target.exists()  # the rare window: original moved away
        assert list(target.parent.glob("data.before-restore-*"))
        try:
            with instance_lock.hold(
                instance_lock.server_locks(layout.data_dir, layout.db_path)
            ):
                attempts.append("started")
        except instance_lock.LockBusy:
            attempts.append("refused")

    restore_backup(layout, archive, between_renames=start_a_server)
    assert attempts == ["refused"]


def test_second_rename_failure_rolls_back(
    archive: Path, target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _tree(target)
    real_rename = os.rename

    def failing(source: object, destination: object) -> None:
        if ".restore-" in str(source):
            raise OSError(28, "No space left on device")
        real_rename(source, destination)  # type: ignore[arg-type]

    monkeypatch.setattr("app.backup.os.rename", failing)
    with pytest.raises(OSError):
        restore_backup(_layout(target), archive)
    assert _tree(target) == before
    assert _staging_left(target) == []
    assert not list(target.parent.glob("*.before-restore-*"))


def test_specific_overrides_are_refused(
    archive: Path, target: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOPUBLISHER_DB_PATH", str(target / "other.db"))
    with pytest.raises(backup.UnsupportedOverrides):
        restore_backup(_layout(target), archive)


# --- Pre-020 round trip (H1) ----------------------------------------------------------


@pytest.fixture
def pre_020_archive(tmp_path: Path) -> Iterator[Path]:
    data_dir = tmp_path / "old"
    data_dir.mkdir()
    db_path = data_dir / config.DB_FILE_NAME
    command.upgrade(_alembic_config(db_path), "0017")
    with closing(sqlite3.connect(db_path)) as db:
        db.execute(
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            "updated_at) VALUES (1, 'Old', 'old', 1, '2026-01-01', '2026-01-01')"
        )
        db.commit()
    yield create_backup(_layout(data_dir), tmp_path / "backups").path


def test_pre_020_round_trip_through_the_cli(
    pre_020_archive: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "installation"
    assert cli.main(["configure", "--data-dir", str(data_dir)]) == 0
    assert cli.main(["restore", str(pre_020_archive), "--yes"]) == 0
    monkeypatch.setattr(getpass, "getpass", lambda prompt: INSTALLATION_PASSWORD)

    assert cli.main(["set-password"]) == 0

    with closing(sqlite3.connect(data_dir / config.DB_FILE_NAME)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0018",
        )
        assert db.execute("SELECT name FROM projects").fetchall() == [("Old",)]
        [(stored,)] = db.execute("SELECT password_hash FROM installation_auth")
    assert auth.verify_password(INSTALLATION_PASSWORD, stored)


def test_restore_reports_a_missing_password(
    pre_020_archive: Path, tmp_path: Path
) -> None:
    result = restore_backup(_layout(tmp_path / "new"), pre_020_archive)
    assert result.password_set is False
