"""`serve` (Feature 020 T016, contracts/cli.md, research §3, §7).

`uvicorn.run` is replaced by a recorder: no network server is started. Preconditions
run in-process against a host configuration under `tmp_path`.
"""

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from alembic import command
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import auth, cli, config, db, instance_lock
from app.db import run_migrations, utc_now
from app.deployment import DataLayout, HostConfig, config_path, write_host_config
from tests.conftest import (
    INSTALLATION_PASSWORD,
    INSTALLATION_URL,
    create_project,
    installation_client,
    make_mp4,
    sign_in,
)
from tests.test_migrations import _alembic_config


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


pytestmark = pytest.mark.usefixtures("serve_process_state")


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def record(app: FastAPI, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(uvicorn, "run", record)
    return calls


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<!doctype html>")
    return root


def _configure(tmp_path: Path, dist: Path | None, **values: Any) -> Path:
    data_dir = tmp_path / "installation-data"
    write_host_config(
        HostConfig(path=config_path(), data_dir=data_dir, frontend_dist=dist, **values)
    )
    return data_dir


def _set_password(data_dir: Path) -> None:
    db_path = data_dir / config.DB_FILE_NAME
    run_migrations(db_path)
    engine = db.create_db_engine(db_path)
    with sessionmaker(engine)() as session:
        auth.set_password(session, INSTALLATION_PASSWORD, utc_now())
    engine.dispose()


@pytest.fixture
def ready(tmp_path: Path, dist: Path) -> Path:
    data_dir = _configure(tmp_path, dist)
    _set_password(data_dir)
    return data_dir


def test_serve_runs_one_installation_process(
    runs: list[dict[str, Any]], ready: Path
) -> None:
    assert cli.main(["serve"]) == 0

    [call] = runs
    assert call["host"] == "127.0.0.1"  # LAN off
    assert call["port"] == 8000
    assert call["proxy_headers"] is False
    assert call["reload"] is False and call["workers"] == 1
    assert call["access_log"] is False and call["server_header"] is False
    assert call["timeout_graceful_shutdown"] == 20
    app: FastAPI = call["app"]
    assert app.state.deployment.is_installation
    assert app.state.deployment.layout.data_dir == ready
    assert app.state.deployment.layout.db_path == ready / config.DB_FILE_NAME


def test_lan_and_port_come_from_the_host_config(
    runs: list[dict[str, Any]], tmp_path: Path, dist: Path
) -> None:
    data_dir = _configure(tmp_path, dist, port=8123, lan_enabled=True)
    _set_password(data_dir)
    assert cli.main(["serve"]) == 0
    assert (runs[0]["host"], runs[0]["port"]) == ("0.0.0.0", 8123)


def test_config_data_dir_is_applied_before_the_layout(
    runs: list[dict[str, Any]], ready: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Path] = []
    original = DataLayout.resolve

    def resolve() -> DataLayout:
        seen.append(config.get_data_dir())
        return original()

    monkeypatch.setattr(DataLayout, "resolve", staticmethod(resolve))
    assert cli.main(["serve"]) == 0
    assert seen == [ready]


def test_private_temporary_directory(runs: list[dict[str, Any]], ready: Path) -> None:
    assert cli.main(["serve"]) == 0
    tmp = ready / "tmp"
    assert tempfile.gettempdir() == str(tmp)
    assert os.environ["TMPDIR"] == str(tmp)
    assert (tmp.stat().st_mode & 0o777) == 0o700


def test_large_upload_spools_into_the_data_directory(
    runs: list[dict[str, Any]], ready: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["serve"]) == 0
    spooled: list[str] = []
    original = tempfile.TemporaryFile

    def recording(*args: Any, **kwargs: Any) -> Any:
        spooled.append(kwargs.get("dir") or tempfile.gettempdir())
        return original(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryFile", recording)
    app: FastAPI = runs[0]["app"]
    with installation_client(app) as client:
        sign_in(client, app)
        project = create_project(client, "Cyber")
        data = make_mp4(payload=b"x" * (1024 * 1024 + 1))  # > 1 MiB: rolls over
        response = client.post(
            f"/api/projects/{project['id']}/contents",
            files=[("files", ("big.mp4", data))],
        )
        assert response.status_code == 200, response.text
    assert spooled and set(spooled) == {str(ready / "tmp")}


def test_missing_host_config(
    runs: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["serve"]) == 78
    assert "uv run python -m app.cli configure" in capsys.readouterr().err
    assert runs == []


def test_missing_password(
    runs: list[dict[str, Any]],
    tmp_path: Path,
    dist: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = _configure(tmp_path, dist)
    assert cli.main(["serve"]) == 78
    assert "uv run python -m app.cli set-password" in capsys.readouterr().err
    assert runs == []
    assert not data_dir.exists()  # nothing created before the checks pass


def test_pre_020_database_has_no_password(
    runs: list[dict[str, Any]], tmp_path: Path, dist: Path
) -> None:
    data_dir = _configure(tmp_path, dist)
    data_dir.mkdir()
    command.upgrade(_alembic_config(data_dir / config.DB_FILE_NAME), "0017")
    assert cli.main(["serve"]) == 78
    assert runs == []


@pytest.mark.parametrize("build", ["missing-dir", "missing-index"])
def test_missing_frontend_build(
    runs: list[dict[str, Any]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    build: str,
) -> None:
    dist = tmp_path / "dist"
    if build == "missing-index":
        (dist / "assets").mkdir(parents=True)
    _set_password(_configure(tmp_path, dist))
    assert cli.main(["serve"]) == 78
    assert "npm ci && npm run build" in capsys.readouterr().err
    assert runs == []


def test_running_server_exits_75(
    runs: list[dict[str, Any]], ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server = instance_lock.server_locks(ready, ready / config.DB_FILE_NAME)
    with instance_lock.hold(server):
        assert cli.main(["serve"]) == 75
    assert "already running" in capsys.readouterr().err
    assert runs == []


def test_failing_migration_aborts_startup(
    runs: list[dict[str, Any]], ready: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert cli.main(["serve"]) == 0
    app: FastAPI = runs[0]["app"]

    def broken(path: Path) -> None:
        raise RuntimeError("migration failed")

    monkeypatch.setattr("app.main.run_migrations", broken)
    with pytest.raises(RuntimeError, match="migration failed"):
        with TestClient(app, base_url=INSTALLATION_URL):
            pass  # never serves
