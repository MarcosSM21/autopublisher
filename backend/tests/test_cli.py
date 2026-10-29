"""`set-password` (Feature 020 T014, contracts/cli.md).

`getpass` is replaced by a scripted prompt; host configuration, data and locks live
under `tmp_path` (conftest isolation).
"""

import getpass
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app import auth, cli, config, instance_lock
from app.config import BACKEND_DIR
from app.db import create_db_engine, run_migrations, utc_now
from app.deployment import (
    DataLayout,
    HostConfig,
    config_path,
    load_host_config,
    write_host_config,
)
from app.models import AuthSession
from tests.test_migrations import _alembic_config

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@pytest.fixture(autouse=True)
def reset_installation_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    # `resolve_layout` injects the configured data directory process-wide.
    monkeypatch.setattr(config, "_installation_data_dir", None)


@pytest.fixture
def layout(tmp_path: Path) -> DataLayout:
    """An installation configured with `data_dir` under `tmp_path`."""
    data_dir = tmp_path / "installation-data"
    write_host_config(HostConfig(path=config_path(), data_dir=data_dir))
    resolved = cli.resolve_layout()
    assert resolved.data_dir == data_dir
    return resolved


def _answers(monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    prompts: list[str] = []
    replies = iter(answers)

    def prompt(text: str) -> str:
        prompts.append(text)
        return next(replies)

    monkeypatch.setattr(getpass, "getpass", prompt)
    return prompts


def _run(monkeypatch: pytest.MonkeyPatch, *answers: str) -> int:
    _answers(monkeypatch, *answers)
    return cli.main(["set-password"])


def _stored_hash(db_path: Path) -> str | None:
    engine = create_db_engine(db_path)
    try:
        with sessionmaker(engine)() as db:
            return auth.current_password_hash(db)
    finally:
        engine.dispose()


def _version(db_path: Path) -> str:
    engine = create_db_engine(db_path)
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            )
    finally:
        engine.dispose()


@pytest.fixture
def sessions(layout: DataLayout) -> Iterator[int]:
    """Seed a password and two sessions; yields their count."""
    run_migrations(layout.db_path)
    engine = create_db_engine(layout.db_path)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        auth.set_password(db, "the old password", utc_now())
        stored = auth.current_password_hash(db)
        assert stored is not None
        for _ in range(2):
            assert auth.create_session(db, stored, utc_now())
    engine.dispose()
    yield 2


def _session_count(db_path: Path) -> int:
    engine = create_db_engine(db_path)
    try:
        with sessionmaker(engine)() as db:
            return int(db.scalar(select(func.count()).select_from(AuthSession)) or 0)
    finally:
        engine.dispose()


def test_first_setup_on_a_new_installation(
    monkeypatch: pytest.MonkeyPatch,
    layout: DataLayout,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts = _answers(monkeypatch, PASSWORD, PASSWORD)

    assert cli.main(["set-password"]) == 0

    assert len(prompts) == 2  # asked twice, through getpass (no echo)
    stored = _stored_hash(layout.db_path)
    assert stored is not None and auth.verify_password(PASSWORD, stored)
    assert (layout.data_dir.stat().st_mode & 0o777) == 0o700
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err
    assert "Password set." in output.out


def test_without_host_config_uses_the_development_resolver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "dev-data"
    monkeypatch.setenv("AUTOPUBLISHER_DATA_DIR", str(data_dir))

    assert _run(monkeypatch, PASSWORD, PASSWORD) == 0

    assert _stored_hash(data_dir / config.DB_FILE_NAME) is not None


def test_pre_020_database_is_migrated_then_set(
    monkeypatch: pytest.MonkeyPatch, layout: DataLayout
) -> None:
    layout.db_path.parent.mkdir(parents=True)
    command.upgrade(_alembic_config(layout.db_path), "0017")

    assert _run(monkeypatch, PASSWORD, PASSWORD) == 0

    assert _version(layout.db_path) == "0020"
    stored = _stored_hash(layout.db_path)
    assert stored is not None and auth.verify_password(PASSWORD, stored)


def test_reset_replaces_the_password_and_signs_everyone_out(
    monkeypatch: pytest.MonkeyPatch, layout: DataLayout, sessions: int
) -> None:
    assert _session_count(layout.db_path) == sessions

    assert _run(monkeypatch, PASSWORD, PASSWORD) == 0

    stored = _stored_hash(layout.db_path)
    assert stored is not None
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("the old password", stored)
    assert _session_count(layout.db_path) == 0


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ((PASSWORD, PASSWORD + "x"), "do not match"),
        (("too short", "too short"), "12 to 1024"),
        (("x" * 1025, "x" * 1025), "12 to 1024"),
    ],
    ids=["mismatch", "short", "long"],
)
def test_unusable_password_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    layout: DataLayout,
    capsys: pytest.CaptureFixture[str],
    answers: tuple[str, str],
    message: str,
) -> None:
    assert _run(monkeypatch, *answers) == 2
    assert not layout.db_path.exists()  # nothing migrated or written
    output = capsys.readouterr()
    assert message in output.err
    assert answers[0] not in output.out + output.err


def test_busy_maintenance_lock(
    monkeypatch: pytest.MonkeyPatch,
    layout: DataLayout,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with instance_lock.hold(instance_lock.maintenance_locks(layout)):
        assert _run(monkeypatch, PASSWORD, PASSWORD) == 75
    assert "maintenance operation" in capsys.readouterr().err
    assert not layout.db_path.exists()


def test_running_server_with_an_older_schema_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
    layout: DataLayout,
    capsys: pytest.CaptureFixture[str],
) -> None:
    layout.db_path.parent.mkdir(parents=True)
    command.upgrade(_alembic_config(layout.db_path), "0017")
    server = instance_lock.server_locks(layout.data_dir, layout.db_path)

    with instance_lock.hold(server):
        assert _run(monkeypatch, PASSWORD, PASSWORD) == 75

    assert "Restart AutoPublisher first." in capsys.readouterr().err
    assert _version(layout.db_path) == "0017"  # schema untouched


def test_running_server_at_head_gets_the_new_password(
    monkeypatch: pytest.MonkeyPatch, layout: DataLayout, sessions: int
) -> None:
    server = instance_lock.server_locks(layout.data_dir, layout.db_path)
    with instance_lock.hold(server):
        assert _run(monkeypatch, PASSWORD, PASSWORD) == 0
    stored = _stored_hash(layout.db_path)
    assert stored is not None and auth.verify_password(PASSWORD, stored)
    assert _session_count(layout.db_path) == 0


def test_invalid_host_config_exits_78(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text("port = 1\n")
    assert _run(monkeypatch, PASSWORD, PASSWORD) == 78
    assert "port" in capsys.readouterr().err


def test_cancelled_prompt(monkeypatch: pytest.MonkeyPatch, layout: DataLayout) -> None:
    def interrupted(text: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(getpass, "getpass", interrupted)
    assert cli.main(["set-password"]) == 1
    assert not layout.db_path.exists()


def test_real_invocation() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "uv run python -m app.cli" in result.stdout
    assert "set-password" in result.stdout
    assert "autopublisher set-password" not in result.stdout


# --- configure, status, backup and restore (T028) -------------------------------------

FAKE_EXECUTABLE = re.compile(
    r"(?<![\w./-])autopublisher (set-password|serve|configure|status|backup|"
    r"restore|install-service|uninstall-service)\b"
)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_health", lambda port: "not reachable")
    monkeypatch.setattr("app.deployment._primary_address", lambda: "192.168.1.40")


def _output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert not FAKE_EXECUTABLE.search(text), text
    return text


def test_configure_writes_from_flags_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    assert (
        cli.main(
            [
                "configure",
                "--data-dir",
                str(data_dir),
                "--port",
                "8123",
                "--lan",
                "--allow-host",
                "My-PC.local",
            ]
        )
        == 0
    )
    stored = load_host_config(config_path())
    assert (stored.data_dir, stored.port, stored.lan_enabled) == (data_dir, 8123, True)
    assert stored.allowed_hosts == ("my-pc.local",)
    assert (config_path().stat().st_mode & 0o777) == 0o600
    assert (config_path().parent.stat().st_mode & 0o777) == 0o700
    assert not data_dir.exists()  # never touches data
    text = _output(capsys)
    assert "port 8123 is not 8000" in text
    assert "systemctl --user restart autopublisher" in text

    # A later call only changes the given flags.
    assert cli.main(["configure", "--no-lan"]) == 0
    updated = load_host_config(config_path())
    assert (updated.port, updated.lan_enabled, updated.allowed_hosts) == (
        8123,
        False,
        ("my-pc.local",),
    )


@pytest.mark.parametrize(
    "flags",
    [["--port", "80"], ["--allow-host", "http://evil"], ["--port", "70000"]],
)
def test_configure_rejects_invalid_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    assert cli.main(["configure", "--data-dir", str(tmp_path / "d")]) == 0
    before = config_path().read_bytes()
    assert cli.main(["configure", *flags]) == 78
    assert config_path().read_bytes() == before
    _output(capsys)


def test_status_banner_and_overrides(
    tmp_path: Path,
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    assert cli.main(["configure", "--data-dir", str(data_dir), "--lan"]) == 0
    data_dir.mkdir()
    (data_dir / "tiktok-app.json").write_text('{"client_secret": "TOP-SECRET"}')
    monkeypatch.setenv("AUTOPUBLISHER_MEDIA_DIR", str(tmp_path / "media-elsewhere"))
    capsys.readouterr()

    assert cli.main(["status"]) == 0

    text = _output(capsys)
    assert f"Host configuration: {config_path()}" in text
    assert f"Data directory: {data_dir}" in text
    assert f"Database: {data_dir / config.DB_FILE_NAME}" in text
    assert "the service does not see them" in text
    assert "AUTOPUBLISHER_MEDIA_DIR=" in text
    assert "Port 8000; access from other devices on." in text
    assert "http://192.168.1.40:8000" in text
    assert "TOP-SECRET" not in text


def test_status_observes_a_running_server_without_waiting(
    tmp_path: Path, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    assert cli.main(["configure", "--data-dir", str(data_dir)]) == 0
    capsys.readouterr()
    server = instance_lock.server_locks(data_dir, data_dir / config.DB_FILE_NAME)
    with instance_lock.hold(server):
        started = time.monotonic()
        assert cli.main(["status"]) == 0
        assert time.monotonic() - started < 5
    text = _output(capsys)
    assert "A server holds the data directory (recorded process" in text
    assert "A server holds the database" in text


def test_backup_and_restore_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    assert cli.main(["configure", "--data-dir", str(data_dir)]) == 0
    run_migrations(data_dir / config.DB_FILE_NAME)
    output = tmp_path / "backups"

    assert cli.main(["backup", "--output", str(output)]) == 0
    text = _output(capsys)
    assert f"Data directory: {data_dir}" in text  # banner first
    [archive] = list(output.glob("autopublisher-backup-*.tar"))
    assert f"Backup written to {archive}" in text
    assert "keep it private" in text

    assert cli.main(["backup", "--output", str(data_dir / "inside")]) == 1
    assert "outside the data directory" in _output(capsys)

    server = instance_lock.server_locks(data_dir, data_dir / config.DB_FILE_NAME)
    with instance_lock.hold(server):
        assert cli.main(["restore", str(archive), "--yes"]) == 75
    assert "Stop AutoPublisher first" in _output(capsys)

    assert cli.main(["restore", str(archive), "--yes"]) == 0
    text = _output(capsys)
    assert "uv run python -m app.cli set-password" in text  # no password yet
    assert "systemctl --user start autopublisher" in text
    assert list(tmp_path.glob("data.before-restore-*"))


def test_restore_asks_before_replacing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    assert cli.main(["configure", "--data-dir", str(data_dir)]) == 0
    run_migrations(data_dir / config.DB_FILE_NAME)
    assert cli.main(["backup", "--output", str(tmp_path / "backups")]) == 0
    [archive] = list((tmp_path / "backups").glob("*.tar"))
    marker = data_dir / "keep.txt"
    marker.write_text("untouched")
    monkeypatch.setattr("builtins.input", lambda prompt: "no")

    assert cli.main(["restore", str(archive)]) == 1

    assert marker.read_text() == "untouched"
    assert "nothing was changed" in _output(capsys)


def test_development_data_reminder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    development = tmp_path / "backend-data"
    monkeypatch.setattr(config, "DEFAULT_DATA_DIR", development)
    run_migrations(development / config.DB_FILE_NAME)

    assert cli.main(["backup", "--output", str(tmp_path / "backups")]) == 0
    assert "stop using backend/data" in _output(capsys)

    [archive] = list((tmp_path / "backups").glob("*.tar"))
    assert cli.main(["configure", "--data-dir", str(tmp_path / "installed")]) == 0
    assert cli.main(["restore", str(archive), "--yes"]) == 0
    assert "stop using backend/data" in _output(capsys)
