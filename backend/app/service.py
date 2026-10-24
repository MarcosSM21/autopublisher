"""The `systemd --user` service (research §8, contracts/cli.md).

The unit runs `<backend>/.venv/bin/python -m app.cli serve` from the backend
checkout this code lives in (absolute paths resolved from the code, never from the
caller's working directory). It does not inherit the shell: the host configuration
is its only source of settings. It belongs to the graphical session (D13): no
lingering, and no promise that the keyring is unlocked.
"""

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from app import config
from app.deployment import config_home, config_path, make_private_dir

SERVICE_NAME = "autopublisher.service"
VENV_PYTHON = Path(".venv") / "bin" / "python"

Runner = Callable[[Sequence[str]], object]


class ServiceError(Exception):
    exit_code = 78


def unit_path() -> Path:
    # `$XDG_CONFIG_HOME/systemd/user`, where the user manager looks for units.
    return config_home().parent / "systemd" / "user" / SERVICE_NAME


def backend_dir() -> Path:
    """This checkout's backend directory, absolute, from the code itself."""
    return config.BACKEND_DIR


def venv_python(backend: Path | None = None) -> Path:
    # Not resolved: the venv's own `python` entry (a symlink) is what activates it.
    return (backend or backend_dir()) / VENV_PYTHON


def custom_config_file() -> Path | None:
    """The host configuration path when it is not the default one."""
    path = config_path()
    default = config_home() / "config.toml"
    if path.absolute() == default.absolute():
        return None
    return path.absolute()


def render_unit(backend: Path, python: Path, config_file: Path | None) -> str:
    environment = ["Environment=PYTHONUNBUFFERED=1"]
    if config_file is not None:
        environment.append(f"Environment=AUTOPUBLISHER_CONFIG={config_file}")
    lines = [
        "# Written by `uv run python -m app.cli install-service`; run it again",
        "# after moving the checkout (and `uv sync --frozen --no-dev`).",
        "[Unit]",
        "Description=AutoPublisher",
        f"Documentation=file://{backend.parent}/docs/deployment.md",
        "PartOf=graphical-session.target",
        "After=graphical-session.target",
        "StartLimitIntervalSec=300",
        "StartLimitBurst=5",
        "",
        "[Service]",
        "Type=exec",
        f"WorkingDirectory={backend}",
        f"ExecStart={python} -m app.cli serve",
        *environment,
        "UMask=0077",
        "Restart=on-failure",
        "RestartSec=5",
        # An invalid configuration, a missing password or build: never loop.
        "RestartPreventExitStatus=78",
        "KillSignal=SIGTERM",
        "TimeoutStopSec=30",
        "",
        "[Install]",
        "WantedBy=graphical-session.target",
        "",
    ]
    return "\n".join(lines)


def installed_working_directory() -> Path | None:
    """The checkout an installed unit points to (to detect a moved checkout)."""
    try:
        text = unit_path().read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("WorkingDirectory="):
            return Path(line.removeprefix("WorkingDirectory="))
    return None


def _systemctl(run: Runner, *args: str) -> None:
    run(["systemctl", "--user", *args])


def write_unit(text: str) -> Path:
    target = unit_path()
    make_private_dir(target.parent)
    partial = target.with_name(f".{target.name}.partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(partial, target)
    return target


def default_runner(command: Sequence[str]) -> object:
    return subprocess.run(list(command), check=True)


def install(*, enable: bool, run: Runner | None = None) -> Path:
    python = venv_python()
    if not python.exists():
        raise ServiceError(
            f"{python} does not exist. Run `uv sync --frozen --no-dev` in backend/ "
            "first."
        )
    runner = run or default_runner
    target = write_unit(render_unit(backend_dir(), python, custom_config_file()))
    _systemctl(runner, "daemon-reload")
    if enable:
        _systemctl(runner, "enable", SERVICE_NAME)
    return target


def uninstall(*, run: Runner | None = None) -> bool:
    runner = run or default_runner
    target = unit_path()
    if not target.exists():
        return False
    try:
        _systemctl(runner, "disable", "--now", SERVICE_NAME)
    except subprocess.CalledProcessError:
        pass  # Not loaded or already stopped: removing the unit is what matters.
    target.unlink()
    _systemctl(runner, "daemon-reload")
    return True
