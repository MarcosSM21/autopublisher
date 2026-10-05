import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def get_db_path() -> Path:
    """Return the SQLite database path, overridable with AUTOPUBLISHER_DB_PATH."""
    override = os.environ.get("AUTOPUBLISHER_DB_PATH", "").strip()
    if override:
        return Path(override)
    return BACKEND_DIR / "data" / "autopublisher.db"
