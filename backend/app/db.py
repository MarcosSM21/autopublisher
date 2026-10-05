from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session, sessionmaker
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


def run_migrations(db_path: Path) -> None:
    """Create the database if needed and apply every pending migration."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # Config values go through configparser interpolation, so '%' must be escaped.
    config.set_main_option(
        "script_location", str(BACKEND_DIR / "migrations").replace("%", "%%")
    )
    config.set_main_option("sqlalchemy.url", database_url(db_path).replace("%", "%%"))
    command.upgrade(config, "head")


def get_session(request: Request) -> Iterator[Session]:
    """Provide one database session per request."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
