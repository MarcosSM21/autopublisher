"""Host configuration and data layout (see specs/020-deployment-mobile-readiness).

The host configuration is a TOML file that belongs to this machine only: data
directory, port, LAN access and extra host names. It never holds secrets and is
never part of a backup. The data layout classifies every path the application uses
as portable (moves with a backup), runtime (regenerated) or host-specific.
"""

import ipaddress
import json
import os
import re
import shlex
import socket
import stat
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from app import config

CONFIG_ENV = "AUTOPUBLISHER_CONFIG"
APP_DIR_NAME = "autopublisher"
DEFAULT_PORT = 8000
MIN_PORT = 1024
MAX_PORT = 65535
# Exit code for an invalid or incomplete configuration (EX_CONFIG).
EXIT_CONFIG = 78
CONFIGURE_COMMAND = "uv run python -m app.cli configure"
# The compiled frontend of this checkout (research §3); `frontend_dist` overrides it.
DEFAULT_FRONTEND_DIST = config.BACKEND_DIR.parent / "frontend" / "dist"

# The platform configuration files that are portable state (shared with backup).
PORTABLE_PLATFORM_FILES = (
    config.GOOGLE_OAUTH_CLIENT_FILE_NAME,
    config.INSTAGRAM_APP_FILE_NAME,
    config.THREADS_APP_FILE_NAME,
    config.TIKTOK_APP_FILE_NAME,
    config.TELEGRAM_APP_FILE_NAME,
    config.MEDIA_DELIVERY_FILE_NAME,
)

_HOST_KEYS = {"data_dir", "port", "lan_enabled", "allowed_hosts", "frontend_dist"}
# A lowercase DNS/mDNS name or IPv4 literal: no scheme, port or path.
_HOST_NAME = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$"
)
_PRIVATE_DIR = 0o700
_PRIVATE_FILE = 0o600


class HostConfigError(Exception):
    """The host configuration is missing or invalid; the message says how to fix it."""

    exit_code = EXIT_CONFIG


# --- XDG locations ------------------------------------------------------------------


def _xdg_home(env_name: str, fallback: str) -> Path:
    # The XDG spec ignores relative values.
    value = os.environ.get(env_name, "").strip()
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback


def config_home() -> Path:
    return _xdg_home("XDG_CONFIG_HOME", ".config") / APP_DIR_NAME


def data_home() -> Path:
    return _xdg_home("XDG_DATA_HOME", ".local/share") / APP_DIR_NAME


def state_home() -> Path:
    return _xdg_home("XDG_STATE_HOME", ".local/state") / APP_DIR_NAME


def config_path() -> Path:
    """AUTOPUBLISHER_CONFIG, or `$XDG_CONFIG_HOME/autopublisher/config.toml`."""
    override = os.environ.get(CONFIG_ENV, "").strip()
    if override:
        return Path(override)
    return config_home() / "config.toml"


# --- Environment overrides (M3) -----------------------------------------------------

# Path overrides, in precedence order (research §5). The service never sees them:
# a persistent installation keeps its paths in the host configuration only.
PATH_OVERRIDE_ENVS = (
    config.DATA_DIR_ENV,
    "AUTOPUBLISHER_DB_PATH",
    "AUTOPUBLISHER_MEDIA_DIR",
    "AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE",
    "AUTOPUBLISHER_INSTAGRAM_APP_FILE",
    "AUTOPUBLISHER_THREADS_APP_FILE",
    "AUTOPUBLISHER_TIKTOK_APP_FILE",
    "AUTOPUBLISHER_TELEGRAM_APP_FILE",
    "AUTOPUBLISHER_MEDIA_DELIVERY_FILE",
)
# Overrides of one specific file inside the data directory.
SPECIFIC_PATH_OVERRIDE_ENVS = PATH_OVERRIDE_ENVS[1:]


def environment_overrides() -> dict[str, str]:
    """Every `AUTOPUBLISHER_*` variable set in this process (names and values are
    paths or URLs, never secrets), except the config file location itself."""
    return {
        name: value
        for name, value in sorted(os.environ.items())
        if name.startswith("AUTOPUBLISHER_") and name != CONFIG_ENV and value.strip()
    }


def path_overrides(names: Iterable[str] = PATH_OVERRIDE_ENVS) -> dict[str, str]:
    return {
        name: os.environ[name].strip()
        for name in names
        if os.environ.get(name, "").strip()
    }


# --- Host configuration -------------------------------------------------------------


@dataclass(frozen=True)
class HostConfig:
    path: Path
    data_dir: Path
    port: int = DEFAULT_PORT
    lan_enabled: bool = False
    allowed_hosts: tuple[str, ...] = ()
    frontend_dist: Path | None = None


def load_host_config(path: Path | None = None) -> HostConfig:
    """Read and validate the host configuration; raise `HostConfigError` if needed."""
    resolved = path or config_path()
    try:
        text = resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HostConfigError(
            f"The host configuration {resolved} does not exist. Create it from "
            f"backend/ with `{CONFIGURE_COMMAND} --data-dir PATH` "
            "(see docs/deployment.md)."
        ) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise HostConfigError(
            f"The host configuration {resolved} cannot be read ({exc})."
        ) from None
    try:
        values = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise HostConfigError(
            f"The host configuration {resolved} is not valid TOML: {exc}."
        ) from None
    return parse_host_config(values, resolved)


def parse_host_config(values: Mapping[str, Any], path: Path) -> HostConfig:
    """Validate already parsed values; every error names the key."""
    unknown = sorted(set(values) - _HOST_KEYS)
    if unknown:
        raise HostConfigError(
            f"{path}: unknown setting(s) {', '.join(unknown)}. "
            f"Valid settings: {', '.join(sorted(_HOST_KEYS))}."
        )
    data_dir = _absolute_path(values, "data_dir", path) or data_home()
    port = values.get("port", DEFAULT_PORT)
    if type(port) is not int or not MIN_PORT <= port <= MAX_PORT:
        raise HostConfigError(
            f"{path}: port must be a whole number from {MIN_PORT} to {MAX_PORT}."
        )
    lan_enabled = values.get("lan_enabled", False)
    if type(lan_enabled) is not bool:
        raise HostConfigError(f"{path}: lan_enabled must be true or false.")
    hosts = values.get("allowed_hosts", [])
    if not isinstance(hosts, list) or not all(
        isinstance(host, str) and _HOST_NAME.match(host) for host in hosts
    ):
        raise HostConfigError(
            f"{path}: allowed_hosts must be a list of lowercase host names without "
            'scheme or port, for example ["my-pc.local"].'
        )
    return HostConfig(
        path=path,
        data_dir=data_dir,
        port=port,
        lan_enabled=lan_enabled,
        allowed_hosts=tuple(hosts),
        frontend_dist=_absolute_path(values, "frontend_dist", path),
    )


def _absolute_path(values: Mapping[str, Any], key: str, path: Path) -> Path | None:
    if key not in values:
        return None
    value = values[key]
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise HostConfigError(f"{path}: {key} must be an absolute path.")
    return Path(value)


def render_host_config(host_config: HostConfig) -> str:
    """The configuration file text (a template: no TOML writer dependency)."""
    # JSON strings are valid TOML basic strings.
    hosts = ", ".join(json.dumps(host) for host in host_config.allowed_hosts)
    dist = (
        f"frontend_dist = {json.dumps(str(host_config.frontend_dist))}"
        if host_config.frontend_dist is not None
        else '# frontend_dist = "/path/to/frontend/dist"   # optional'
    )
    return (
        "# AutoPublisher host configuration "
        "(this machine only; never restored from a backup)\n"
        f"data_dir = {json.dumps(str(host_config.data_dir))}\n"
        f"port = {host_config.port}\n"
        f"lan_enabled = {'true' if host_config.lan_enabled else 'false'}\n"
        f'allowed_hosts = [{hosts}]          # extra names, e.g. ["my-pc.local"]\n'
        f"{dist}\n"
    )


def write_host_config(host_config: HostConfig) -> None:
    """Write the file atomically with mode 0600 (its directory 0700 if new)."""
    target = host_config.path
    make_private_dir(target.parent)
    partial = target.with_name(f".{target.name}.partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PRIVATE_FILE)
    try:
        os.fchmod(fd, _PRIVATE_FILE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(render_host_config(host_config))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    os.replace(partial, target)


def make_private_dir(path: Path) -> None:
    """Create `path` (and missing parents) as 0700; existing ones are left as is."""
    if path.is_dir():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir(mode=_PRIVATE_DIR)
    except FileExistsError:
        return
    os.chmod(path, _PRIVATE_DIR)


# --- Data layout --------------------------------------------------------------------


@dataclass(frozen=True)
class HostPaths:
    """Host-specific locations: never inside the data directory, never backed up."""

    config_file: Path
    state_dir: Path
    logs_dir: Path
    backups_dir: Path


def host_paths() -> HostPaths:
    state = state_home()
    return HostPaths(
        config_file=config_path(),
        state_dir=state,
        logs_dir=state / "logs",
        backups_dir=Path.home() / "autopublisher-backups",
    )


@dataclass(frozen=True)
class DataLayout:
    """The effective paths, after the precedence of research §5 (config.py)."""

    data_dir: Path
    db_path: Path
    media_dir: Path
    platform_files: Mapping[str, Path]

    @classmethod
    def resolve(cls) -> "DataLayout":
        return cls(
            data_dir=config.get_data_dir(),
            db_path=config.get_db_path(),
            media_dir=config.get_media_dir(),
            platform_files={
                config.GOOGLE_OAUTH_CLIENT_FILE_NAME: (
                    config.get_google_oauth_client_file()
                ),
                config.INSTAGRAM_APP_FILE_NAME: config.get_instagram_app_file(),
                config.THREADS_APP_FILE_NAME: config.get_threads_app_file(),
                config.TIKTOK_APP_FILE_NAME: config.get_tiktok_app_file(),
                config.TELEGRAM_APP_FILE_NAME: config.get_telegram_app_file(),
                config.MEDIA_DELIVERY_FILE_NAME: config.get_media_delivery_file(),
            },
        )

    # Portable state: moves with a backup and a restore.
    @property
    def media_projects_dir(self) -> Path:
        return self.media_dir / "projects"

    @property
    def portable_paths(self) -> tuple[Path, ...]:
        return (self.db_path, self.media_projects_dir, *self.platform_files.values())

    # Runtime state: regenerated, never backed up.
    @property
    def tmp_dir(self) -> Path:
        """Upload spooling (TMPDIR of the installation process)."""
        return self.data_dir / "tmp"

    @property
    def media_tmp_dir(self) -> Path:
        return self.media_dir / "tmp"

    @property
    def runtime_paths(self) -> tuple[Path, ...]:
        return (self.tmp_dir, self.media_tmp_dir)

    def ensure_dirs(self, hosts: HostPaths | None = None) -> None:
        """Create missing data, tmp and state directories as 0700."""
        resolved_hosts = hosts or host_paths()
        for path in (
            self.data_dir,
            self.tmp_dir,
            resolved_hosts.state_dir,
            resolved_hosts.logs_dir,
        ):
            make_private_dir(path)

    def permission_warnings(self) -> list[str]:
        """Existing data directory or platform files readable by group/others (FR-044).

        Only reported, never changed: a legacy `backend/data` keeps working.
        """
        warnings = []
        checks = [(self.data_dir, "700")] + [
            (path, "600") for path in self.platform_files.values()
        ]
        for path, fix in checks:
            try:
                mode = path.stat().st_mode
            except OSError:
                continue
            if mode & 0o077:
                warnings.append(
                    f"{path} is accessible by other users "
                    f"(mode {stat.S_IMODE(mode):o}). Restrict it with: "
                    f"chmod {fix} {shlex.quote(str(path))}"
                )
        return warnings


def canonical(path: Path) -> Path:
    """Absolute path with symlinks resolved; the path does not need to exist."""
    return path.resolve()


def is_inside(path: Path, directory: Path) -> bool:
    """Whether `path` is `directory` or below it, comparing canonical paths."""
    return canonical(path).is_relative_to(canonical(directory))


# --- Application modes --------------------------------------------------------------


class AppMode(StrEnum):
    DEVELOPMENT = "development"
    INSTALLATION = "installation"


@dataclass(frozen=True)
class DeploymentSettings:
    """How the application is exposed; the entrypoint decides the mode (research §4).

    There is deliberately no setting, environment variable or host configuration key
    that selects the mode or disables authentication: development comes only from
    `development()` (the module app run by `uvicorn --reload`) and installation
    only from `installation()` with a loaded `HostConfig` (the `serve` command).
    """

    mode: AppMode
    port: int | None = None
    lan_enabled: bool = False
    allowed_hosts: tuple[str, ...] = ()
    layout: DataLayout | None = None
    frontend_dist: Path | None = None

    def __post_init__(self) -> None:
        if self.mode is AppMode.INSTALLATION and (
            self.port is None or self.layout is None
        ):
            raise ValueError("Installation mode needs a port and a data layout.")
        if self.mode is AppMode.DEVELOPMENT and (
            self.port is not None
            or self.lan_enabled
            or self.allowed_hosts
            or self.layout is not None
            or self.frontend_dist is not None
        ):
            raise ValueError("Development mode takes no host configuration.")

    @classmethod
    def development(cls) -> "DeploymentSettings":
        """Loopback clients only, no password, Vite in front, FastAPI docs kept."""
        return cls(mode=AppMode.DEVELOPMENT)

    @classmethod
    def installation(
        cls, host_config: HostConfig, layout: DataLayout
    ) -> "DeploymentSettings":
        """The installed application, built from the host configuration.

        `layout` is resolved by the entrypoint after injecting the configured data
        directory, so the specific `AUTOPUBLISHER_*` overrides keep precedence.
        """
        if not isinstance(host_config, HostConfig):
            raise TypeError("Installation mode is built from a HostConfig.")
        return cls(
            mode=AppMode.INSTALLATION,
            port=host_config.port,
            lan_enabled=host_config.lan_enabled,
            allowed_hosts=host_config.allowed_hosts,
            layout=layout,
            frontend_dist=host_config.frontend_dist or DEFAULT_FRONTEND_DIST,
        )

    @property
    def is_installation(self) -> bool:
        return self.mode is AppMode.INSTALLATION


# --- LAN addresses (research §23) ----------------------------------------------------
#
# Only shown to the signed-in user (Settings, `status`); never a security decision.

# A private, non-routable destination: `connect()` on a UDP socket only picks the
# outgoing interface, no packet is sent.
_ROUTE_PROBE = ("10.255.255.255", 1)


def _primary_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(_ROUTE_PROBE)
            address = probe.getsockname()[0]
    except OSError:
        return None
    return address if isinstance(address, str) else None


def lan_addresses(extra: Iterable[str | None] = ()) -> list[str]:
    """Private, non-loopback, non-link-local addresses of this host; `[]` if none.

    `extra` adds known local addresses, such as the socket of the current request.
    """
    found: list[str] = []
    for candidate in (_primary_address(), *extra):
        if not candidate:
            continue
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or not address.is_private
        ):
            continue
        text = str(address)
        if text not in found:
            found.append(text)
    return found


def suggested_host_names() -> list[str]:
    """`<hostname>.local`, which may work if the network supports mDNS."""
    try:
        name = socket.gethostname().split(".")[0].lower()
    except OSError:
        return []
    return [f"{name}.local"] if _HOST_NAME.match(name) else []


def http_url(host: str, port: int) -> str:
    literal = f"[{host}]" if ":" in host else host
    return f"http://{literal}:{port}"
