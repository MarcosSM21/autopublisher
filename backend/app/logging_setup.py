"""Logging of the installed application (research §19).

A rotating file under `$XDG_STATE_HOME/autopublisher/logs` (host state: never in
the data directory or a backup), bounded to 5 × 5 MiB, private to the user, plus
stderr for the user journal. Access logs stay off. Development keeps uvicorn's
own logging: only `serve` calls this.
"""

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO

from app.deployment import make_private_dir

LOG_FILE_NAME = "autopublisher.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_PRIVATE_FILE = 0o600
_MARKER = "_autopublisher_handler"

# Defence in depth on every handler; the module filters installed by `create_app`
# (OAuth callbacks, platform URLs) stay in place. Each pattern keeps its first
# group and replaces the secret itself.
_SECRET_NAMES = (
    r"(?:current_|new_)?password|code|state|code_verifier|"
    r"(?:access_|refresh_|id_)?token|client_secret|app_secret|secret"
)
_REDACTIONS = (
    # Query strings and form bodies: password=…, code=…, state=…, token=…
    (re.compile(rf"(?i)\b((?:{_SECRET_NAMES})=)[^&\s\"']+"), r"\1[redacted]"),
    # JSON bodies: "password": "…"
    (
        re.compile(rf"(?i)(\"(?:{_SECRET_NAMES})\"\s*:\s*)\"[^\"]*\""),
        r'\1"[redacted]"',
    ),
    (re.compile(r"(?i)(autopublisher_session=)[^;\s\"']+"), r"\1[redacted]"),
    (re.compile(r"(?i)\b(Bearer\s+)[^\s\"']+"), r"\1[redacted]"),
    (re.compile(r"(?i)(authorization:\s*)[^\n]+"), r"\1[redacted]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Creates the log (and each new one after a rotation) as 0600."""

    def _open(self) -> IO[str]:  # type: ignore[override]
        fd = os.open(
            self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, _PRIVATE_FILE
        )
        os.fchmod(fd, _PRIVATE_FILE)
        return os.fdopen(fd, "a", encoding=self.encoding, errors=self.errors)


def configure_logging(logs_dir: Path) -> Path:
    """Install the file and stderr handlers once; returns the log file path."""
    make_private_dir(logs_dir)
    log_file = logs_dir / LOG_FILE_NAME
    formatter = logging.Formatter(FORMAT)
    file_handler = _PrivateRotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    stderr_handler = logging.StreamHandler(sys.stderr)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MARKER, False):
            root.removeHandler(handler)
            handler.close()
    for handler in (file_handler, stderr_handler):
        handler.setFormatter(formatter)
        handler.addFilter(RedactSecrets())
        setattr(handler, _MARKER, True)
        root.addHandler(handler)
    root.setLevel(logging.WARNING)
    for name in ("app", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.INFO)
    # No access log: request lines (and callback URLs) are never written.
    logging.getLogger("uvicorn.access").disabled = True
    return log_file
