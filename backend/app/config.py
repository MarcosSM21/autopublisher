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

# Data directory (see specs/020-deployment-mobile-readiness/research.md §5–§6).
DEFAULT_DATA_DIR = BACKEND_DIR / "data"
DATA_DIR_ENV = "AUTOPUBLISHER_DATA_DIR"
DB_FILE_NAME = "autopublisher.db"
MEDIA_DIR_NAME = "media"
GOOGLE_OAUTH_CLIENT_FILE_NAME = "google-oauth-client.json"
INSTAGRAM_APP_FILE_NAME = "instagram-app.json"
THREADS_APP_FILE_NAME = "threads-app.json"
TIKTOK_APP_FILE_NAME = "tiktok-app.json"
TELEGRAM_APP_FILE_NAME = "telegram-app.json"
MEDIA_DELIVERY_FILE_NAME = "media-delivery.json"

# Set only by the installation entrypoint, from the host configuration.
_installation_data_dir: Path | None = None


def set_installation_data_dir(path: Path | None) -> None:
    """Inject the host configuration's `data_dir` (installation mode only)."""
    global _installation_data_dir
    _installation_data_dir = path


def get_data_dir() -> Path:
    """Return the data directory: AUTOPUBLISHER_DATA_DIR, then the installation's
    `data_dir`, then `backend/data` (development)."""
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override)
    if _installation_data_dir is not None:
        return _installation_data_dir
    return DEFAULT_DATA_DIR


def _resolve(env_name: str, default_name: str) -> Path:
    """A specific AUTOPUBLISHER_* override always wins over the data directory."""
    override = os.environ.get(env_name, "").strip()
    if override:
        return Path(override)
    return get_data_dir() / default_name


def get_db_path() -> Path:
    """Return the SQLite database path, overridable with AUTOPUBLISHER_DB_PATH."""
    return _resolve("AUTOPUBLISHER_DB_PATH", DB_FILE_NAME)


def get_media_dir() -> Path:
    """Return the media storage root, overridable with AUTOPUBLISHER_MEDIA_DIR."""
    return _resolve("AUTOPUBLISHER_MEDIA_DIR", MEDIA_DIR_NAME)


# YouTube OAuth (see specs/005-youtube-oauth-connection/research.md).
DEFAULT_OAUTH_REDIRECT_URI = "http://127.0.0.1:8000/api/youtube/oauth/callback"
OAUTH_ATTEMPT_TTL = timedelta(minutes=10)
# How long a finished attempt is kept, without secrets, so the UI can read its result.
OAUTH_ATTEMPT_RETENTION = timedelta(minutes=10)
_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def get_google_oauth_client_file() -> Path:
    """Return the Google OAuth client file (AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE)."""
    return _resolve(
        "AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE", GOOGLE_OAUTH_CLIENT_FILE_NAME
    )


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
    return _resolve("AUTOPUBLISHER_INSTAGRAM_APP_FILE", INSTAGRAM_APP_FILE_NAME)


# Threads API (see specs/010-threads-oauth-connection/research.md).
THREADS_ATTEMPT_TTL = timedelta(minutes=10)
# How long a finished Threads attempt is kept, without secrets.
THREADS_ATTEMPT_RETENTION = timedelta(minutes=10)


def get_threads_app_file() -> Path:
    """Return the Threads app config file (AUTOPUBLISHER_THREADS_APP_FILE)."""
    return _resolve("AUTOPUBLISHER_THREADS_APP_FILE", THREADS_APP_FILE_NAME)


# TikTok Login Kit (see specs/012-tiktok-oauth-connection/research.md).
TIKTOK_ATTEMPT_TTL = timedelta(minutes=10)
# How long a finished TikTok attempt is kept, without secrets.
TIKTOK_ATTEMPT_RETENTION = timedelta(minutes=10)
# The callback route served by the backend; registered as is (no trailing slash).
TIKTOK_CALLBACK_PATH = "/api/tiktok/oauth/callback"
DEFAULT_TIKTOK_REDIRECT_URI = "http://127.0.0.1:8000" + TIKTOK_CALLBACK_PATH


def get_tiktok_app_file() -> Path:
    """Return the TikTok app config file (AUTOPUBLISHER_TIKTOK_APP_FILE)."""
    return _resolve("AUTOPUBLISHER_TIKTOK_APP_FILE", TIKTOK_APP_FILE_NAME)


# Telegram user account (see specs/015-telegram-user-publishing/research.md).
# How long a login waiting for its code or 2FA password is kept in memory.
TELEGRAM_LOGIN_TTL = timedelta(minutes=10)


def get_telegram_app_file() -> Path:
    """Return the Telegram app config file (AUTOPUBLISHER_TELEGRAM_APP_FILE)."""
    return _resolve("AUTOPUBLISHER_TELEGRAM_APP_FILE", TELEGRAM_APP_FILE_NAME)


# Temporary media delivery (see specs/009-instagram-media-publishing/research.md).


def get_media_delivery_file() -> Path:
    """Return the media delivery config file (AUTOPUBLISHER_MEDIA_DELIVERY_FILE)."""
    return _resolve("AUTOPUBLISHER_MEDIA_DELIVERY_FILE", MEDIA_DELIVERY_FILE_NAME)
