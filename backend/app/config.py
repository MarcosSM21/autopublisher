import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Import limits (see specs/003-content-library/research.md, decision 8).
MAX_FILE_SIZE = 2 * 1024**3
MAX_FILES_PER_IMPORT = 100
MAX_FILENAME_LENGTH = 255
CHUNK_SIZE = 1024 * 1024


def get_db_path() -> Path:
    """Return the SQLite database path, overridable with AUTOPUBLISHER_DB_PATH."""
    override = os.environ.get("AUTOPUBLISHER_DB_PATH", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "autopublisher.db"


def get_media_dir() -> Path:
    """Return the media storage root, overridable with AUTOPUBLISHER_MEDIA_DIR."""
    override = os.environ.get("AUTOPUBLISHER_MEDIA_DIR", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "media"


# YouTube OAuth (see specs/005-youtube-oauth-connection/research.md).
DEFAULT_OAUTH_REDIRECT_URI = "http://127.0.0.1:8000/api/youtube/oauth/callback"
OAUTH_ATTEMPT_TTL = timedelta(minutes=10)
# How long a finished attempt is kept, without secrets, so the UI can read its result.
OAUTH_ATTEMPT_RETENTION = timedelta(minutes=10)
_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def get_google_oauth_client_file() -> Path:
    """Return the Google OAuth client file (AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE)."""
    override = os.environ.get("AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "google-oauth-client.json"


def get_oauth_redirect_uri() -> str:
    """Return the OAuth redirect URI; it must be plain HTTP on a loopback IP address."""
    uri = (
        os.environ.get("AUTOPUBLISHER_OAUTH_REDIRECT_URI", "").strip()
        or DEFAULT_OAUTH_REDIRECT_URI
    )
    parts = urlsplit(uri)
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(
            "AUTOPUBLISHER_OAUTH_REDIRECT_URI must use http with 127.0.0.1 or [::1]."
        )
    return uri


# Instagram Login (see specs/008-instagram-oauth-connection/research.md).
INSTAGRAM_ATTEMPT_TTL = timedelta(minutes=10)
# How long a finished Instagram attempt is kept, without secrets.
INSTAGRAM_ATTEMPT_RETENTION = timedelta(minutes=10)


def get_instagram_app_file() -> Path:
    """Return the Meta App config file (AUTOPUBLISHER_INSTAGRAM_APP_FILE)."""
    override = os.environ.get("AUTOPUBLISHER_INSTAGRAM_APP_FILE", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "instagram-app.json"


# Threads API (see specs/010-threads-oauth-connection/research.md).
THREADS_ATTEMPT_TTL = timedelta(minutes=10)
# How long a finished Threads attempt is kept, without secrets.
THREADS_ATTEMPT_RETENTION = timedelta(minutes=10)


def get_threads_app_file() -> Path:
    """Return the Threads app config file (AUTOPUBLISHER_THREADS_APP_FILE)."""
    override = os.environ.get("AUTOPUBLISHER_THREADS_APP_FILE", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "threads-app.json"


# TikTok Login Kit (see specs/012-tiktok-oauth-connection/research.md).
TIKTOK_ATTEMPT_TTL = timedelta(minutes=10)
# How long a finished TikTok attempt is kept, without secrets.
TIKTOK_ATTEMPT_RETENTION = timedelta(minutes=10)
# The callback route served by the backend; registered as is (no trailing slash).
TIKTOK_CALLBACK_PATH = "/api/tiktok/oauth/callback"
DEFAULT_TIKTOK_REDIRECT_URI = "http://127.0.0.1:8000" + TIKTOK_CALLBACK_PATH


def get_tiktok_app_file() -> Path:
    """Return the TikTok app config file (AUTOPUBLISHER_TIKTOK_APP_FILE)."""
    override = os.environ.get("AUTOPUBLISHER_TIKTOK_APP_FILE", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "tiktok-app.json"


# Telegram user account (see specs/015-telegram-user-publishing/research.md).
# How long a login waiting for its code or 2FA password is kept in memory.
TELEGRAM_LOGIN_TTL = timedelta(minutes=10)


def get_telegram_app_file() -> Path:
    """Return the Telegram app config file (AUTOPUBLISHER_TELEGRAM_APP_FILE)."""
    override = os.environ.get("AUTOPUBLISHER_TELEGRAM_APP_FILE", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "telegram-app.json"


# Temporary media delivery (see specs/009-instagram-media-publishing/research.md).


def get_media_delivery_file() -> Path:
    """Return the media delivery config file (AUTOPUBLISHER_MEDIA_DELIVERY_FILE)."""
    override = os.environ.get("AUTOPUBLISHER_MEDIA_DELIVERY_FILE", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "media-delivery.json"
