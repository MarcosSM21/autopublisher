"""Host configuration, data directory precedence and data layout (Feature 020)."""

import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from app import config, deployment
from app.deployment import (
    PORTABLE_PLATFORM_FILES,
    DataLayout,
    HostConfig,
    HostConfigError,
    config_path,
    data_home,
    host_paths,
    is_inside,
    load_host_config,
    write_host_config,
)

# Every path getter, its specific override and its file name in the data directory.
PATHS: list[tuple[Callable[[], Path], str, str]] = [
    (config.get_db_path, "AUTOPUBLISHER_DB_PATH", "autopublisher.db"),
    (config.get_media_dir, "AUTOPUBLISHER_MEDIA_DIR", "media"),
    (
        config.get_google_oauth_client_file,
        "AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE",
        "google-oauth-client.json",
    ),
    (
        config.get_instagram_app_file,
        "AUTOPUBLISHER_INSTAGRAM_APP_FILE",
        "instagram-app.json",
    ),
    (config.get_threads_app_file, "AUTOPUBLISHER_THREADS_APP_FILE", "threads-app.json"),
    (config.get_tiktok_app_file, "AUTOPUBLISHER_TIKTOK_APP_FILE", "tiktok-app.json"),
    (
        config.get_telegram_app_file,
        "AUTOPUBLISHER_TELEGRAM_APP_FILE",
        "telegram-app.json",
    ),
    (
        config.get_media_delivery_file,
        "AUTOPUBLISHER_MEDIA_DELIVERY_FILE",
        "media-delivery.json",
    ),
]
PATH_IDS = [name for _, _, name in PATHS]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for _, env_name, _ in PATHS:
        monkeypatch.delenv(env_name, raising=False)
    yield
    config.set_installation_data_dir(None)


# --- Precedence (C3) ----------------------------------------------------------------


@pytest.mark.parametrize(("getter", "env_name", "name"), PATHS, ids=PATH_IDS)
def test_precedence_for_every_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    getter: Callable[[], Path],
    env_name: str,
    name: str,
) -> None:
    # (4) Default: identical to today's development paths.
    assert getter() == config.BACKEND_DIR / "data" / name
    # (3) The installation's data_dir from the host configuration.
    config.set_installation_data_dir(tmp_path / "host")
    assert getter() == tmp_path / "host" / name
    # (2) AUTOPUBLISHER_DATA_DIR wins over the host configuration.
    monkeypatch.setenv("AUTOPUBLISHER_DATA_DIR", str(tmp_path / "env"))
    assert getter() == tmp_path / "env" / name
    # (1) The existing specific override still wins over everything.
    monkeypatch.setenv(env_name, str(tmp_path / "specific"))
    assert getter() == tmp_path / "specific"


def test_data_dir_defaults_to_backend_data() -> None:
    assert config.get_data_dir() == config.BACKEND_DIR / "data"


def test_blank_values_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOPUBLISHER_DATA_DIR", "  ")
    monkeypatch.setenv("AUTOPUBLISHER_DB_PATH", "")
    assert config.get_db_path() == config.BACKEND_DIR / "data" / "autopublisher.db"


# --- Host configuration -------------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_location_follows_xdg_and_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert config_path() == tmp_path / "cfg" / "autopublisher" / "config.toml"
    monkeypatch.setenv("AUTOPUBLISHER_CONFIG", str(tmp_path / "other.toml"))
    assert config_path() == tmp_path / "other.toml"


def test_valid_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "config.toml",
        f'data_dir = "{tmp_path}/data"\nport = 8080\nlan_enabled = true\n'
        f'allowed_hosts = ["my-pc.local", "192.168.1.20"]\n'
        f'frontend_dist = "{tmp_path}/dist"\n',
    )

    assert load_host_config(path) == HostConfig(
        path=path,
        data_dir=tmp_path / "data",
        port=8080,
        lan_enabled=True,
        allowed_hosts=("my-pc.local", "192.168.1.20"),
        frontend_dist=tmp_path / "dist",
    )


def test_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.toml", "")

    assert load_host_config(path) == HostConfig(path=path, data_dir=data_home())
    assert data_home() == tmp_path / "xdg" / "xdg_data_home" / "autopublisher"


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ('data_dir = "relative/data"', "data_dir"),
        ("data_dir = 5", "data_dir"),
        ('port = "8000"', "port"),
        ("port = 80", "port"),
        ("port = 70000", "port"),
        ("port = true", "port"),
        ('lan_enabled = "yes"', "lan_enabled"),
        ('allowed_hosts = "my-pc.local"', "allowed_hosts"),
        ('allowed_hosts = ["http://my-pc.local"]', "allowed_hosts"),
        ('allowed_hosts = ["my-pc.local:8000"]', "allowed_hosts"),
        ('allowed_hosts = ["My-PC.local"]', "allowed_hosts"),
        ("allowed_hosts = [1]", "allowed_hosts"),
        ('frontend_dist = "dist"', "frontend_dist"),
        ('mode = "development"', "mode"),
        ("password = 'x'", "password"),
    ],
)
def test_invalid_setting_names_the_key(tmp_path: Path, text: str, key: str) -> None:
    path = _write(tmp_path / "config.toml", text + "\n")

    with pytest.raises(HostConfigError) as raised:
        load_host_config(path)

    assert key in str(raised.value)
    assert str(path) in str(raised.value)
    assert raised.value.exit_code == 78


def test_invalid_toml(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.toml", "port = = 1\n")

    with pytest.raises(HostConfigError, match="not valid TOML"):
        load_host_config(path)


def test_missing_file_gives_the_real_command(tmp_path: Path) -> None:
    path = tmp_path / "missing.toml"

    with pytest.raises(HostConfigError) as raised:
        load_host_config(path)

    message = str(raised.value)
    assert str(path) in message
    assert "uv run python -m app.cli configure" in message
    assert "backend/" in message


@pytest.mark.parametrize("dist", [None, 'odd "quoted" \\ dir'])
def test_writer_round_trip_and_permissions(tmp_path: Path, dist: str | None) -> None:
    written = HostConfig(
        path=tmp_path / "new" / "config.toml",
        data_dir=tmp_path / "data dir",
        port=9000,
        lan_enabled=True,
        allowed_hosts=("my-pc.local",),
        frontend_dist=None if dist is None else tmp_path / dist,
    )

    write_host_config(written)

    assert load_host_config(written.path) == written
    assert stat.S_IMODE(written.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(written.path.parent.stat().st_mode) == 0o700
    assert [p.name for p in written.path.parent.iterdir()] == ["config.toml"]


# --- Data layout --------------------------------------------------------------------


def _layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataLayout:
    monkeypatch.setenv("AUTOPUBLISHER_DATA_DIR", str(tmp_path / "data"))
    return DataLayout.resolve()


def test_layout_derives_every_path_from_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    layout = _layout(tmp_path, monkeypatch)

    assert layout.db_path == data / "autopublisher.db"
    assert layout.media_dir == data / "media"
    assert layout.media_projects_dir == data / "media" / "projects"
    assert layout.tmp_dir == data / "tmp"
    assert layout.media_tmp_dir == data / "media" / "tmp"
    assert set(layout.platform_files) == set(PORTABLE_PLATFORM_FILES)
    assert all(path == data / name for name, path in layout.platform_files.items())


def test_layout_keeps_specific_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOPUBLISHER_DB_PATH", str(tmp_path / "elsewhere.db"))

    layout = _layout(tmp_path, monkeypatch)

    assert layout.db_path == tmp_path / "elsewhere.db"
    assert layout.media_dir == tmp_path / "data" / "media"


def test_classification_is_disjoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path, monkeypatch)
    hosts = host_paths()

    for path in (hosts.config_file, hosts.state_dir, hosts.logs_dir):
        assert not is_inside(path, layout.data_dir)
    for runtime in layout.runtime_paths:
        assert not any(is_inside(runtime, p) for p in layout.portable_paths)
    assert (
        hosts.logs_dir == tmp_path / "xdg" / "xdg_state_home" / "autopublisher" / "logs"
    )


def test_is_inside_follows_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    assert is_inside(link / "autopublisher.db", real)
    assert is_inside(real / "media", link)
    assert not is_inside(tmp_path / "realish", real)


def test_ensure_dirs_creates_private_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path, monkeypatch)
    hosts = host_paths()
    old_umask = os.umask(0o022)
    try:
        layout.ensure_dirs()
    finally:
        os.umask(old_umask)

    for path in (
        layout.data_dir,
        layout.tmp_dir,
        hosts.state_dir,
        hosts.logs_dir,
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700, path


def test_legacy_open_permissions_warn_without_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _layout(tmp_path, monkeypatch)
    layout.data_dir.mkdir(mode=0o775)
    os.chmod(layout.data_dir, 0o775)
    secret = layout.platform_files["tiktok-app.json"]
    secret.write_text("{}")
    os.chmod(secret, 0o644)
    private = layout.platform_files["threads-app.json"]
    private.write_text("{}")
    os.chmod(private, 0o600)

    warnings = layout.permission_warnings()

    assert len(warnings) == 2
    assert f"chmod 700 {layout.data_dir}" in warnings[0]
    assert f"chmod 600 {secret}" in warnings[1]
    assert stat.S_IMODE(layout.data_dir.stat().st_mode) == 0o775
    assert stat.S_IMODE(secret.stat().st_mode) == 0o644
    # Already private (and the legacy layout still resolves as before).
    os.chmod(layout.data_dir, 0o700)
    os.chmod(secret, 0o600)
    assert layout.permission_warnings() == []


# --- LAN address discovery (T020, research §23) --------------------------------------


class _UdpSocket:
    """Records the route probe; `connect()` on UDP sends nothing."""

    def __init__(self, address: str | None) -> None:
        self.address = address
        self.connected: tuple[str, int] | None = None

    def __enter__(self) -> "_UdpSocket":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def connect(self, target: tuple[str, int]) -> None:
        self.connected = target
        if self.address is None:
            raise OSError("Network is unreachable")

    def getsockname(self) -> tuple[str, int]:
        assert self.address is not None
        return (self.address, 40000)


def _route(monkeypatch: pytest.MonkeyPatch, address: str | None) -> list[_UdpSocket]:
    created: list[_UdpSocket] = []

    def factory(*args: object) -> _UdpSocket:
        created.append(_UdpSocket(address))
        return created[-1]

    monkeypatch.setattr("app.deployment.socket.socket", factory)
    return created


@pytest.mark.parametrize(
    ("primary", "extra", "expected"),
    [
        ("192.168.1.40", [], ["192.168.1.40"]),
        ("192.168.1.40", ["192.168.1.40", "10.0.0.5"], ["192.168.1.40", "10.0.0.5"]),
        ("127.0.0.1", ["::1", None], []),  # loopback excluded
        ("169.254.10.1", ["fe80::1"], []),  # link-local excluded
        ("1.1.1.1", ["8.8.8.8"], []),  # public: never suggested
        ("192.168.1.40", ["fd00::5"], ["192.168.1.40", "fd00::5"]),
        (None, [], []),  # no route: unknown, gracefully
        (None, ["not-an-ip"], []),
    ],
)
def test_lan_addresses(
    monkeypatch: pytest.MonkeyPatch,
    primary: str | None,
    extra: list[str | None],
    expected: list[str],
) -> None:
    sockets = _route(monkeypatch, primary)
    assert deployment.lan_addresses(extra) == expected
    # A private, non-routable destination: no external service is contacted.
    assert sockets[0].connected == ("10.255.255.255", 1)


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [("My-PC", ["my-pc.local"]), ("pi.lan", ["pi.local"]), ("bad_name", [])],
)
def test_suggested_host_names(
    monkeypatch: pytest.MonkeyPatch, hostname: str, expected: list[str]
) -> None:
    monkeypatch.setattr("app.deployment.socket.gethostname", lambda: hostname)
    assert deployment.suggested_host_names() == expected


def test_http_url_brackets_ipv6() -> None:
    assert deployment.http_url("fd00::5", 8000) == "http://[fd00::5]:8000"
    assert deployment.http_url("my-pc.local", 8000) == "http://my-pc.local:8000"
