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
