import os
from pathlib import Path

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
