"""Persistent, private, redacted logs of the installed app (Feature 020 T029)."""

import logging
import signal
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app import auth, cli, config, logging_setup
from app.db import create_db_engine, run_migrations, utc_now
from app.deployment import HostConfig, config_path, host_paths, write_host_config
from app.scheduler import SchedulerSettings
from tests.conftest import (
    INSTALLATION_PASSWORD,
    installation_app,
    installation_client,
    installation_settings,
    sign_in,
)


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


pytestmark = pytest.mark.usefixtures("serve_process_state")


def _log_text() -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (host_paths().logs_dir / logging_setup.LOG_FILE_NAME).read_text()


def test_handlers_permissions_and_rotation(tmp_path: Path) -> None:
    logs = tmp_path / "state" / "logs"
    log_file = logging_setup.configure_logging(logs)

    assert log_file == logs / "autopublisher.log"
    assert (logs.stat().st_mode & 0o777) == 0o700
    assert (log_file.stat().st_mode & 0o777) == 0o600
    handlers = [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "_autopublisher_handler", False)
    ]
    [rotating] = [h for h in handlers if isinstance(h, RotatingFileHandler)]
    assert (rotating.maxBytes, rotating.backupCount) == (5 * 1024 * 1024, 5)
    assert any(type(h) is logging.StreamHandler for h in handlers)
    assert logging.getLogger("app").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("uvicorn.access").disabled
    # Configuring twice never duplicates lines.
    logging_setup.configure_logging(logs)
    marked = [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "_autopublisher_handler", False)
    ]
    assert len(marked) == 2


def test_rotated_files_stay_private(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logging_setup.configure_logging(logs)
    [rotating] = [
        h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)
    ]
    rotating.doRollover()
    for path in logs.iterdir():
        assert (path.stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("GET /api/youtube/oauth/callback?state=s3cr3t&code=4/abc", "s3cr3t"),
        ('{"password": "hunter2 hunter2"}', "hunter2"),
        ("cookie: autopublisher_session=tok-123", "tok-123"),
        ("Authorization: Bearer ya29.secret", "ya29.secret"),
        ("refresh_token=1//refresh", "1//refresh"),
        ('{"client_secret": "GOCSPX-xyz"}', "GOCSPX-xyz"),
    ],
)
def test_every_handler_redacts(tmp_path: Path, message: str, secret: str) -> None:
    logging_setup.configure_logging(tmp_path / "logs")
    logging.getLogger("app.test").warning("%s", message)
    text = (tmp_path / "logs" / "autopublisher.log").read_text()
    assert "[redacted]" in text
    assert secret not in text


def test_serve_logs_start_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    data_dir = tmp_path / "installation-data"
    write_host_config(
        HostConfig(path=config_path(), data_dir=data_dir, frontend_dist=dist)
    )
    run_migrations(data_dir / config.DB_FILE_NAME)
    engine = create_db_engine(data_dir / config.DB_FILE_NAME)
    with sessionmaker(engine)() as db:
        auth.set_password(db, INSTALLATION_PASSWORD, utc_now())
    engine.dispose()
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))

    assert cli.main(["serve"]) == 0

    text = _log_text()
    assert "Starting AutoPublisher (installation) on port 8000, LAN access off" in text
    assert str(data_dir) in text
    assert "AutoPublisher stopped." in text
    assert calls[0]["access_log"] is False
    assert not str(host_paths().logs_dir).startswith(str(data_dir))


def test_serve_logs_stop_once_on_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """uvicorn re-raises SIGTERM after a graceful shutdown (systemd stop); the stop
    line is written before that, once, and the signal is still re-raised."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    data_dir = tmp_path / "installation-data"
    write_host_config(
        HostConfig(path=config_path(), data_dir=data_dir, frontend_dist=dist)
    )
    run_migrations(data_dir / config.DB_FILE_NAME)
    engine = create_db_engine(data_dir / config.DB_FILE_NAME)
    with sessionmaker(engine)() as db:
        auth.set_password(db, INSTALLATION_PASSWORD, utc_now())
    engine.dispose()
    original = signal.getsignal(signal.SIGTERM)
    raised: list[int] = []
    monkeypatch.setattr(signal, "raise_signal", raised.append)

    def uvicorn_receiving_sigterm(app: object, **kwargs: Any) -> None:
        # What uvicorn does on exit: call the handler it found, re-raising the signal.
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)

    monkeypatch.setattr(uvicorn, "run", uvicorn_receiving_sigterm)

    assert cli.main(["serve"]) == 0

    assert _log_text().count("AutoPublisher stopped.") == 1
    assert raised == [signal.SIGTERM]
    assert signal.getsignal(signal.SIGTERM) == original


def test_a_redaction_run_leaves_no_secret_in_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_client_file: Path
) -> None:
    logging_setup.configure_logging(host_paths().logs_dir)
    settings = installation_settings(tmp_path)
    app: FastAPI = installation_app(
        settings, scheduler_settings=SchedulerSettings(autostart=False)
    )
    with installation_client(app) as client:
        wrong = client.post("/api/auth/login", json={"password": "wrong password 1"})
        assert wrong.status_code == 401
        sign_in(client, app)
        token = client.cookies.get(auth.SESSION_COOKIE)
        client.get(
            "/api/youtube/oauth/callback",
            params={"state": "state-secret-1", "code": "code-secret-1"},
        )
        logging.getLogger("app.publishing").error(
            "Publication failed: %s",
            "upload rejected (access_token=at-secret-1)",
        )
    text = _log_text()
    assert "Sign-in failed from 127.0.0.1." in text
    assert "Signed in from 127.0.0.1." in text
    for secret in (
        "wrong password 1",
        INSTALLATION_PASSWORD,
        token or "<no token>",
        "state-secret-1",
        "code-secret-1",
        "at-secret-1",
        "client_secret",
    ):
        assert secret not in text, secret
