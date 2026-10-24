"""`install-service` / `uninstall-service` (Feature 020 T030, research §8).

`systemctl` is replaced by a recorder: nothing is installed for real (STOP 1 does).
"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app import auth, cli, config, service
from app.db import create_db_engine, run_migrations, utc_now
from app.deployment import (
    PATH_OVERRIDE_ENVS,
    HostConfig,
    config_path,
    write_host_config,
)
from tests.conftest import INSTALLATION_PASSWORD


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@pytest.fixture(autouse=True)
def reset_installation_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_installation_data_dir", None)


@pytest.fixture
def systemctl(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def record(command: Sequence[str]) -> None:
        calls.append(list(command))

    monkeypatch.setattr(service, "default_runner", record)
    return calls


@pytest.fixture
def backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout elsewhere, with its virtual environment."""
    root = tmp_path / "checkout" / "backend"
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    monkeypatch.setattr(service, "backend_dir", lambda: root)
    return root


def _ready(tmp_path: Path, path: Path | None = None) -> Path:
    data_dir = tmp_path / "installation-data"
    write_host_config(HostConfig(path=path or config_path(), data_dir=data_dir))
    db_path = data_dir / config.DB_FILE_NAME
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with sessionmaker(engine)() as db:
        auth.set_password(db, INSTALLATION_PASSWORD, utc_now())
    engine.dispose()
    return data_dir


def _unit() -> str:
    return service.unit_path().read_text()


def test_unit_uses_absolute_paths_from_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, systemctl: list[list[str]]
) -> None:
    _ready(tmp_path)
    monkeypatch.chdir(tmp_path)  # the caller's cwd never matters

    assert cli.main(["install-service"]) == 0

    unit = _unit()
    backend = config.BACKEND_DIR
    assert backend.is_absolute()
    assert f"WorkingDirectory={backend}\n" in unit
    assert f"ExecStart={backend}/.venv/bin/python -m app.cli serve\n" in unit
    assert "uv " not in unit.split("[Unit]")[1]
    assert str(tmp_path) not in unit


def test_unit_directives(
    tmp_path: Path, backend: Path, systemctl: list[list[str]]
) -> None:
    _ready(tmp_path)
    assert cli.main(["install-service"]) == 0
    unit = _unit()
    for directive in (
        "Type=exec",
        f"WorkingDirectory={backend}",
        f"ExecStart={backend}/.venv/bin/python -m app.cli serve",
        "Environment=PYTHONUNBUFFERED=1",
        "UMask=0077",
        "Restart=on-failure",
        "RestartSec=5",
        "StartLimitIntervalSec=300",
        "StartLimitBurst=5",
        "RestartPreventExitStatus=78",
        "KillSignal=SIGTERM",
        "TimeoutStopSec=30",
        "PartOf=graphical-session.target",
        "After=graphical-session.target",
        "WantedBy=graphical-session.target",
    ):
        assert f"\n{directive}\n" in unit, directive
    assert "AUTOPUBLISHER_CONFIG" not in unit  # default config location
    assert "AUTOPUBLISHER_DATA_DIR" not in unit
    # Deterministic: the same inputs render the same unit.
    assert unit == service.render_unit(
        backend, backend / ".venv" / "bin" / "python", None
    )


def test_custom_config_location_is_written_to_the_unit(
    tmp_path: Path,
    backend: Path,
    systemctl: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    custom = tmp_path / "elsewhere" / "autopublisher.toml"
    monkeypatch.setenv("AUTOPUBLISHER_CONFIG", str(custom))
    _ready(tmp_path, custom)
    assert cli.main(["install-service"]) == 0
    assert f"\nEnvironment=AUTOPUBLISHER_CONFIG={custom}\n" in _unit()


@pytest.mark.parametrize("name", PATH_OVERRIDE_ENVS)
def test_environment_overrides_are_refused(
    tmp_path: Path,
    backend: Path,
    systemctl: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    _ready(tmp_path)
    monkeypatch.setenv(name, str(tmp_path / "override"))

    assert cli.main(["install-service"]) == 78

    err = capsys.readouterr().err
    assert "not persistent for the service" in err and name in err
    assert not service.unit_path().exists()
    assert systemctl == []


def test_missing_virtual_environment(
    tmp_path: Path,
    systemctl: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ready(tmp_path)
    monkeypatch.setattr(service, "backend_dir", lambda: tmp_path / "no-venv")
    assert cli.main(["install-service"]) == 78
    assert "uv sync --frozen --no-dev" in capsys.readouterr().err
    assert systemctl == []


def test_systemctl_sequence(
    tmp_path: Path, backend: Path, systemctl: list[list[str]]
) -> None:
    _ready(tmp_path)
    assert cli.main(["install-service"]) == 0
    assert systemctl == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "autopublisher.service"],
    ]


def test_no_enable_and_never_start_or_linger(
    tmp_path: Path,
    backend: Path,
    systemctl: list[list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ready(tmp_path)
    assert cli.main(["install-service", "--no-enable"]) == 0
    assert systemctl == [["systemctl", "--user", "daemon-reload"]]
    out = capsys.readouterr().out
    assert "systemctl --user start autopublisher" in out
    assert "keyring may still be locked" in out
    assert all("loginctl" not in " ".join(call) for call in systemctl)


def test_refused_without_config_or_password(
    tmp_path: Path, backend: Path, systemctl: list[list[str]]
) -> None:
    assert cli.main(["install-service"]) == 78  # no host configuration
    write_host_config(HostConfig(path=config_path(), data_dir=tmp_path / "empty"))
    assert cli.main(["install-service"]) == 78  # no password
    assert systemctl == []
    assert not service.unit_path().exists()


def test_uninstall(tmp_path: Path, backend: Path, systemctl: list[list[str]]) -> None:
    _ready(tmp_path)
    assert cli.main(["install-service"]) == 0
    systemctl.clear()

    assert cli.main(["uninstall-service"]) == 0

    assert not service.unit_path().exists()
    assert systemctl == [
        ["systemctl", "--user", "disable", "--now", "autopublisher.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]
    systemctl.clear()
    assert cli.main(["uninstall-service"]) == 0  # nothing installed: no calls
    assert systemctl == []


def test_status_detects_a_moved_checkout(
    tmp_path: Path,
    backend: Path,
    systemctl: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _ready(tmp_path)
    assert cli.main(["install-service"]) == 0
    moved = tmp_path / "moved" / "backend"
    monkeypatch.setattr(service, "backend_dir", lambda: moved)
    monkeypatch.setattr(cli, "_health", lambda port: "not reachable")
    capsys.readouterr()

    assert cli.main(["status"]) == 0

    assert "points to another checkout" in capsys.readouterr().out
