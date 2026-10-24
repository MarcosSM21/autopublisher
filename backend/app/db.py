from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

from app.config import BACKEND_DIR


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store datetimes as naive UTC and read them back as aware UTC.

    SQLite does not keep time zones, so the zone is restored on read.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use UTC.")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def database_url(db_path: Path) -> str:
    return f"sqlite:///{db_path}"


def _enable_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(db_path: Path) -> Engine:
    """Create an engine for the SQLite file with foreign keys enforced."""
    engine = create_engine(
        database_url(db_path), connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # Config values go through configparser interpolation, so '%' must be escaped.
    config.set_main_option(
        "script_location", str(BACKEND_DIR / "migrations").replace("%", "%%")
    )
    config.set_main_option("sqlalchemy.url", database_url(db_path).replace("%", "%%"))
    return config


def run_migrations(db_path: Path) -> None:
    """Create the database if needed and apply every pending migration."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(_alembic_config(db_path), "head")


def known_revision(revision: str) -> bool:
    """Whether this checkout's migrations know `revision` (older ones migrate)."""
    script = ScriptDirectory.from_config(_alembic_config(Path("unused.db")))
    try:
        return script.get_revision(revision) is not None
    except Exception:  # alembic raises several errors for unknown or bad ids
        return False


def schema_is_current(db_path: Path) -> bool:
    """Whether an existing database is already at the latest migration (read-only)."""
    if not db_path.is_file():
        return False
    head = ScriptDirectory.from_config(_alembic_config(db_path)).get_current_head()
    engine = create_engine(database_url(db_path), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    return current == head


def get_session(request: Request) -> Iterator[Session]:
    """Provide one database session per request."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
