from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.db import create_db_engine, run_migrations
from app.models import Base


def test_migrations_create_tables_on_empty_database(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "app.db"

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    assert {"projects", "accounts"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"

    run_migrations(db_path)
    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert version.scalar_one() == "0001"
    engine.dispose()


def test_migrations_match_models(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()

    assert diff == []


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "app.db")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    engine.dispose()
