"""AutoPublisher command line (contracts/cli.md).

Run from `backend/`: `uv run python -m app.cli <command>`. The backend is not a
packaged project, so there is no installed console script.

Exit codes: 0 ok, 1 error, 2 usage, 75 resource busy (lock), 78 invalid or
incomplete configuration.
"""

import argparse
import getpass
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

import uvicorn
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app import auth, backup, config, instance_lock, service, spa
from app.credential_store import probe_credential_store
from app.db import create_db_engine, run_migrations, schema_is_current, utc_now
from app.deployment import (
    DEFAULT_PORT,
    EXIT_CONFIG,
    PATH_OVERRIDE_ENVS,
    DataLayout,
    DeploymentSettings,
    HostConfig,
    HostConfigError,
    config_path,
    data_home,
    environment_overrides,
    host_paths,
    http_url,
    lan_addresses,
    load_host_config,
    make_private_dir,
    parse_host_config,
    path_overrides,
    write_host_config,
)
from app.logging_setup import LOG_FILE_NAME, configure_logging
from app.models import InstallationAuth

logger = logging.getLogger("app.cli")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
CLI_COMMAND = "uv run python -m app.cli"

Prompt = Callable[[str], str]

LOOPBACK_BIND = "127.0.0.1"
# With LAN access on, every interface; the Host guard only accepts the real socket
# address, `allowed_hosts` and loopback names (research §14).
LAN_BIND = "0.0.0.0"  # noqa: S104 - opt-in LAN access, behind auth and Host checks
GRACEFUL_SHUTDOWN_SECONDS = 20


class _SchemaBehind(Exception):
    exit_code = instance_lock.EXIT_BUSY


def _error(message: str) -> None:
    print(message, file=sys.stderr)


def resolve_layout() -> DataLayout:
    """The host configuration's data directory when it exists, otherwise the
    development defaults, both through the same resolver (research §5)."""
    return _effective()[0]


def _effective() -> tuple[DataLayout, HostConfig | None]:
    path = config_path()
    host_config = load_host_config(path) if path.exists() else None
    if host_config is not None:
        config.set_installation_data_dir(host_config.data_dir)
    return DataLayout.resolve(), host_config


def _print_banner(layout: DataLayout, host_config: HostConfig | None) -> None:
    """Which installation a command acts on, before it acts (M3). No secrets."""
    if host_config is not None:
        print(f"Host configuration: {host_config.path}")
    else:
        print(
            f"Host configuration: none at {config_path()} "
            "(development defaults are used)"
        )
    print(f"Data directory: {layout.data_dir}")
    print(f"Database: {layout.db_path}")
    overrides = environment_overrides()
    if overrides:
        print(
            "This command is using environment overrides; "
            "the service does not see them:"
        )
        for name, value in overrides.items():
            print(f"  {name}={value}")
    print()


def _retire_development_reminder() -> None:
    print(
        "Important: once this data works in the installation, stop using "
        "backend/data with these accounts. Both copies use the same keyring "
        "credentials, so using both would break the connections."
    )


def _read_new_password(prompt: Prompt) -> str | None:
    """Ask twice without echo; None (after explaining why) when unusable."""
    password = prompt("New password: ")
    error = auth.password_length_error(password)
    if error is not None:
        _error(f"Password not changed. {error}")
        return None
    if prompt("Repeat the new password: ") != password:
        _error("Password not changed. The two passwords do not match.")
        return None
    return password


def _prepare_schema(layout: DataLayout) -> None:
    """Migrate only while no server holds the data directory or database (L4).

    A running server keeps its own schema version: never migrate under it. If it is
    already at the latest version the password can be written next to it.
    """
    try:
        with instance_lock.hold(
            instance_lock.server_locks(layout.data_dir, layout.db_path)
        ):
            make_private_dir(layout.db_path.parent)
            run_migrations(layout.db_path)
    except instance_lock.LockBusy:
        if not schema_is_current(layout.db_path):
            raise _SchemaBehind(
                "AutoPublisher is running with an older database version. "
                "Restart AutoPublisher first."
            ) from None


def set_password(prompt: Prompt | None = None) -> int:
    """First-time setup and forgotten-password reset; signs every browser out."""
    try:
        layout = resolve_layout()
        password = _read_new_password(prompt or getpass.getpass)
        if password is None:
            return EXIT_USAGE
        with instance_lock.hold(instance_lock.maintenance_locks(layout)):
            _prepare_schema(layout)
            engine = create_db_engine(layout.db_path)
            try:
                with sessionmaker(engine, expire_on_commit=False)() as db:
                    auth.set_password(db, password, utc_now())
            finally:
                engine.dispose()
    except HostConfigError as exc:
        _error(str(exc))
        return exc.exit_code
    except (instance_lock.LockBusy, _SchemaBehind) as exc:
        _error(str(exc))
        return exc.exit_code
    except instance_lock.LockRootUnsafe as exc:
        _error(str(exc))
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        _error("\nCancelled. The password was not changed.")
        return EXIT_ERROR
    print(
        "Password set. Every signed-in browser was signed out and must sign in "
        "again with the new password."
    )
    return EXIT_OK


class _NotReady(Exception):
    exit_code = EXIT_CONFIG


def password_configured(db_path: Path) -> bool:
    """Read-only: an existing database with a stored password hash."""
    if not db_path.is_file():
        return False
    engine = create_db_engine(db_path)
    try:
        with sessionmaker(engine)() as db:
            stored = db.scalar(
                select(InstallationAuth.password_hash).where(InstallationAuth.id == 1)
            )
    except SQLAlchemyError:  # e.g. a database from before Feature 020
        return False
    finally:
        engine.dispose()
    return bool(stored)


def _ensure_not_running(layout: DataLayout) -> None:
    """A friendly early exit (75); the server's own locks are the real guard."""
    for kind, resource in instance_lock.server_locks(layout.data_dir, layout.db_path):
        observed = instance_lock.observe(kind, resource)
        if observed.held:
            raise instance_lock.LockBusy(kind, resource, observed.pid)


def _use_private_tmp(layout: DataLayout) -> None:
    """Uploads spool to `<data_dir>/tmp` (0700, on disk), never a tmpfs `/tmp`;
    child processes such as ffmpeg/ffprobe inherit it (research §7)."""
    make_private_dir(layout.tmp_dir)
    tempfile.tempdir = str(layout.tmp_dir)
    os.environ["TMPDIR"] = str(layout.tmp_dir)


def prepare_installation() -> DeploymentSettings:
    """Every `serve` precondition, in order; nothing is created before they pass."""
    host_config = load_host_config()
    # The configured data directory must be in place before any path is resolved.
    config.set_installation_data_dir(host_config.data_dir)
    layout = DataLayout.resolve()
    if not password_configured(layout.db_path):
        raise _NotReady(
            "No installation password is set. Set it with "
            f"`{CLI_COMMAND} set-password` from backend/ (see docs/deployment.md)."
        )
    settings = DeploymentSettings.installation(host_config, layout)
    assert settings.frontend_dist is not None
    spa.check_build(settings.frontend_dist)
    _ensure_not_running(layout)
    layout.ensure_dirs()
    _use_private_tmp(layout)
    for warning in layout.permission_warnings():
        logger.warning(warning)
    return settings


def serve() -> int:
    """Installation mode: one process, one port, compiled UI and API (no reload)."""
    # Every file this process creates is private (the unit also sets UMask=0077).
    os.umask(0o077)
    log_file = configure_logging(host_paths().logs_dir)
    try:
        settings = prepare_installation()
    except (HostConfigError, _NotReady, spa.FrontendBuildMissing) as exc:
        _error(str(exc))
        return exc.exit_code
    except instance_lock.LockBusy as exc:
        _error(str(exc))
        return exc.exit_code
    except instance_lock.LockRootUnsafe as exc:
        _error(str(exc))
        return exc.exit_code
    from app.main import create_app

    app = create_app(deployment=settings)
    host = LAN_BIND if settings.lan_enabled else LOOPBACK_BIND
    layout = settings.layout
    assert layout is not None
    logger.info(
        "Starting AutoPublisher (installation) on port %s, LAN access %s; "
        "data directory %s, database %s; log %s.",
        settings.port,
        "on" if settings.lan_enabled else "off",
        layout.data_dir,
        layout.db_path,
        log_file,
    )
    overrides = path_overrides()
    if overrides:
        logger.warning(
            "Environment path overrides are active (%s): they are not part of "
            "the host configuration.",
            ", ".join(sorted(overrides)),
        )
    stop_logged = False

    def log_stop() -> None:
        nonlocal stop_logged
        if not stop_logged:
            stop_logged = True
            logger.info("AutoPublisher stopped.")

    def stop_on_sigterm(signum: int, frame: object) -> None:
        # uvicorn re-raises SIGTERM after its graceful shutdown; the default action
        # kills the process before `finally` runs, so log first, then terminate
        # exactly as before (killed by SIGTERM, a clean stop for systemd).
        log_stop()
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)

    previous_sigterm = signal.signal(signal.SIGTERM, stop_on_sigterm)
    # A failing start-up (locks, migrations) makes uvicorn exit non-zero.
    try:
        _run_uvicorn(app, host, settings.port or DEFAULT_PORT)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        log_stop()
    return EXIT_OK


def _run_uvicorn(app: object, host: str, port: int) -> None:
    uvicorn.run(
        app,  # type: ignore[arg-type]
        host=host,
        port=port,
        reload=False,
        workers=1,
        proxy_headers=False,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        log_config=None,
    )


# --- configure (flags only, L10) ------------------------------------------------------


def configure(args: argparse.Namespace) -> int:
    """Create or update the host configuration; never touches any data."""
    path = config_path()
    try:
        current = load_host_config(path) if path.exists() else None
        values: dict[str, object] = {
            "data_dir": str(current.data_dir if current else data_home()),
            "port": current.port if current else DEFAULT_PORT,
            "lan_enabled": current.lan_enabled if current else False,
            "allowed_hosts": list(current.allowed_hosts) if current else [],
        }
        if current is not None and current.frontend_dist is not None:
            values["frontend_dist"] = str(current.frontend_dist)
        if args.data_dir is not None:
            values["data_dir"] = str(Path(args.data_dir).expanduser().absolute())
        if args.port is not None:
            values["port"] = args.port
        if args.lan is not None:
            values["lan_enabled"] = args.lan
        if args.allow_host:
            values["allowed_hosts"] = [name.lower() for name in args.allow_host]
        if args.clear_allowed_hosts:
            values["allowed_hosts"] = []
        if args.frontend_dist is not None:
            values["frontend_dist"] = str(
                Path(args.frontend_dist).expanduser().absolute()
            )
        host_config = parse_host_config(values, path)
    except HostConfigError as exc:
        _error(str(exc))
        return exc.exit_code
    write_host_config(host_config)
    print(f"Host configuration written to {path}:")
    print(f"  data_dir = {host_config.data_dir}")
    print(f"  port = {host_config.port}")
    print(f"  lan_enabled = {'true' if host_config.lan_enabled else 'false'}")
    print(f"  allowed_hosts = {list(host_config.allowed_hosts)}")
    if host_config.frontend_dist is not None:
        print(f"  frontend_dist = {host_config.frontend_dist}")
    if host_config.port != DEFAULT_PORT:
        print(
            f"Warning: port {host_config.port} is not {DEFAULT_PORT}. The YouTube "
            "and TikTok redirect URIs registered with those platforms must use "
            "the new port."
        )
    print("Restart the service to apply it: systemctl --user restart autopublisher")
    return EXIT_OK


# --- status (observation only, L3) ----------------------------------------------------


def _health(port: int) -> str:
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
            status = json.loads(response.read()).get("status")
    except (urllib.error.URLError, OSError, ValueError):
        return "not reachable"
    return str(status)


def status(args: argparse.Namespace) -> int:
    try:
        layout, host_config = _effective()
    except HostConfigError as exc:
        _error(str(exc))
        return exc.exit_code
    _print_banner(layout, host_config)
    port = host_config.port if host_config else DEFAULT_PORT
    if host_config is not None:
        print(
            f"Port {port}; access from other devices "
            f"{'on' if host_config.lan_enabled else 'off'}."
        )
    for kind, resource in instance_lock.server_locks(layout.data_dir, layout.db_path):
        observed = instance_lock.observe(kind, resource)
        what = "data directory" if kind is instance_lock.LockKind.DATA else "database"
        if observed.held:
            holder = f" (recorded process {observed.pid})" if observed.pid else ""
            print(f"A server holds the {what}{holder}.")
        else:
            print(f"No server holds the {what}.")
    print(f"Health at http://127.0.0.1:{port}/health: {_health(port)}")
    print(f"Secure storage: {probe_credential_store()}")
    addresses = [http_url(address, port) for address in lan_addresses()]
    print(
        "Addresses on this network: "
        + (", ".join(addresses) if addresses else "could not detect (run `ip -4 addr`)")
    )
    print(f"Logs: {host_paths().logs_dir / LOG_FILE_NAME}")
    installed = service.installed_working_directory()
    if installed is not None and installed != service.backend_dir():
        print(
            f"The user service points to another checkout ({installed}). Run "
            f"`{CLI_COMMAND} install-service` from this backend/ again."
        )
    for warning in layout.permission_warnings():
        print(f"Warning: {warning}")
    return EXIT_OK


# --- backup / restore -----------------------------------------------------------------


def run_backup(args: argparse.Namespace) -> int:
    try:
        layout, host_config = _effective()
        _print_banner(layout, host_config)
        output = Path(args.output) if args.output else host_paths().backups_dir
        result = backup.create_backup(layout, output.expanduser())
    except (HostConfigError, backup.BackupError, instance_lock.LockBusy) as exc:
        _error(str(exc))
        return exc.exit_code
    except instance_lock.LockRootUnsafe as exc:
        _error(str(exc))
        return exc.exit_code
    except KeyboardInterrupt:
        _error("\nCancelled. No backup was written.")
        return EXIT_ERROR
    print(f"Backup written to {result.path}")
    for line in backup.iter_summary(result.manifest):
        print(f"  {line}")
    print(
        "It contains your platform configuration files (app credentials): keep it "
        "private. Keyring tokens and sessions are never included."
    )
    if backup.is_development_data_dir(layout.data_dir):
        _retire_development_reminder()
    return EXIT_OK


def _ask_confirmation(target: Path) -> Callable[[backup.Manifest], bool]:
    def confirm(manifest: backup.Manifest) -> bool:
        print("Backup to restore:")
        for line in backup.iter_summary(manifest):
            print(f"  {line}")
        answer = input(f"Replace the data in {target}? Type 'yes' to continue: ")
        return answer.strip().lower() == "yes"

    return confirm


def run_restore(args: argparse.Namespace) -> int:
    try:
        layout, host_config = _effective()
        _print_banner(layout, host_config)
        confirm = (
            (lambda manifest: True) if args.yes else _ask_confirmation(layout.data_dir)
        )
        result = backup.restore_backup(layout, Path(args.archive), confirm=confirm)
    except instance_lock.LockBusy as exc:
        _error(f"{exc}\nStop AutoPublisher first: systemctl --user stop autopublisher")
        return exc.exit_code
    except (HostConfigError, backup.BackupError) as exc:
        _error(str(exc))
        return exc.exit_code
    except instance_lock.LockRootUnsafe as exc:
        _error(str(exc))
        return exc.exit_code
    except (KeyboardInterrupt, EOFError):
        _error("\nCancelled. Nothing was changed.")
        return EXIT_ERROR
    print(f"Restored into {result.target}.")
    if result.previous is not None:
        print(
            f"The previous data was kept in {result.previous}; delete it once "
            "everything works."
        )
    print("Next steps:")
    print("  Start AutoPublisher: systemctl --user start autopublisher")
    if result.password_set:
        print(
            "  Sign in with the password of the backup (every browser signs in again)."
        )
    else:
        print(f"  Set a password first: `{CLI_COMMAND} set-password` from backend/")
    print("  Reconnect the accounts marked “Reconnect needed”.")
    if result.manifest.from_development:
        _retire_development_reminder()
    return EXIT_OK


# --- user service ---------------------------------------------------------------------


def install_service(args: argparse.Namespace) -> int:
    overrides = path_overrides(PATH_OVERRIDE_ENVS)
    if overrides:
        _error(
            "These environment overrides are not persistent for the service: "
            f"{', '.join(sorted(overrides))}. Move them to the host configuration "
            f"(`{CLI_COMMAND} configure`) before installing the service."
        )
        return EXIT_CONFIG
    try:
        host_config = load_host_config()
        config.set_installation_data_dir(host_config.data_dir)
        layout = DataLayout.resolve()
        if not password_configured(layout.db_path):
            raise _NotReady(
                f"No installation password is set. Run `{CLI_COMMAND} "
                "set-password` from backend/ first."
            )
        target = service.install(enable=not args.no_enable)
    except (HostConfigError, _NotReady, service.ServiceError) as exc:
        _error(str(exc))
        return exc.exit_code
    except (OSError, subprocess.CalledProcessError) as exc:
        _error(f"Could not install the service ({exc}).")
        return EXIT_ERROR
    print(f"User service written to {target}.")
    print("Manage it with:")
    print("  systemctl --user start autopublisher")
    print("  systemctl --user stop|restart|status autopublisher")
    print("  journalctl --user -u autopublisher -e")
    print(
        "It starts with your desktop session. The keyring may still be locked "
        "then: unlock it so scheduled posts can be published."
    )
    return EXIT_OK


def uninstall_service(args: argparse.Namespace) -> int:
    try:
        removed = service.uninstall()
    except (OSError, subprocess.CalledProcessError) as exc:
        _error(f"Could not remove the service ({exc}).")
        return EXIT_ERROR
    print("User service removed." if removed else "The user service is not installed.")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=CLI_COMMAND,
        description="Manage this AutoPublisher installation (see docs/deployment.md).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "set-password",
        help="Set or reset the installation password (on this computer only).",
    )
    commands.add_parser(
        "serve", help="Run the installed application (used by the user service)."
    )
    configure_parser = commands.add_parser(
        "configure", help="Create or update the host configuration (flags only)."
    )
    configure_parser.add_argument("--data-dir")
    configure_parser.add_argument("--port", type=int)
    lan = configure_parser.add_mutually_exclusive_group()
    lan.add_argument("--lan", dest="lan", action="store_true", default=None)
    lan.add_argument("--no-lan", dest="lan", action="store_false")
    configure_parser.add_argument(
        "--allow-host", action="append", metavar="NAME", help="Repeatable."
    )
    configure_parser.add_argument("--clear-allowed-hosts", action="store_true")
    configure_parser.add_argument("--frontend-dist")
    commands.add_parser("status", help="Show the state of this installation.")
    backup_parser = commands.add_parser(
        "backup", help="Write an online backup of the portable data."
    )
    backup_parser.add_argument("--output", metavar="DIR")
    restore_parser = commands.add_parser(
        "restore", help="Replace the data with a backup (service stopped)."
    )
    restore_parser.add_argument("archive")
    restore_parser.add_argument("--yes", action="store_true")
    install_parser = commands.add_parser(
        "install-service", help="Install the systemd user service."
    )
    install_parser.add_argument("--no-enable", action="store_true")
    commands.add_parser("uninstall-service", help="Remove the systemd user service.")
    args = parser.parse_args(argv)
    if args.command == "set-password":
        return set_password()
    if args.command == "serve":
        return serve()
    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "configure": configure,
        "status": status,
        "backup": run_backup,
        "restore": run_restore,
        "install-service": install_service,
        "uninstall-service": uninstall_service,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
