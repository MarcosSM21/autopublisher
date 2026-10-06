from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, Connection, Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR
from app.db import create_db_engine, database_url, run_migrations, utc_now
from app.models import Base, Publication


def test_migrations_create_tables_on_empty_database(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "app.db"

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    assert {"projects", "accounts", "contents", "publications"} <= set(
        inspect(engine).get_table_names()
    )
    engine.dispose()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"

    run_migrations(db_path)
    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert version.scalar_one() == "0003"
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


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url(db_path))
    return config


def test_contents_migration_keeps_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0001")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id, name, name_key, is_active, created_at, "
                "updated_at) VALUES (1, 'L4i4', 'l4i4', 1, '2026-10-05 10:00:00', "
                "'2026-10-05 10:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO accounts (project_id, platform, handle, handle_key, "
                "is_active, created_at, updated_at) VALUES (1, 'instagram', 'l4i4', "
                "'l4i4', 1, '2026-10-05 10:00:00', '2026-10-05 10:00:00')"
            )
        )
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM projects")).scalar_one() == (
            "L4i4"
        )
        assert (
            connection.execute(text("SELECT COUNT(*) FROM accounts")).scalar_one() == 1
        )
        assert (
            connection.execute(text("SELECT COUNT(*) FROM contents")).scalar_one() == 0
        )
    engine.dispose()


def test_publications_migration_keeps_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0002")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        for table in ("projects", "accounts", "contents"):
            count = connection.execute(text(f"SELECT COUNT(*) FROM {table}"))
            assert count.scalar_one() == 1
        count = connection.execute(text("SELECT COUNT(*) FROM publications"))
        assert count.scalar_one() == 0
    engine.dispose()


def _insert_project_account_content(connection: Connection) -> None:
    now = "'2026-10-06 10:00:00'"
    connection.execute(
        text(
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            f"updated_at) VALUES (1, 'L4i4', 'l4i4', 1, {now}, {now})"
        )
    )
    connection.execute(
        text(
            "INSERT INTO accounts (id, project_id, platform, handle, handle_key, "
            f"is_active, created_at, updated_at) VALUES (1, 1, 'instagram', 'l4i4', "
            f"'l4i4', 1, {now}, {now})"
        )
    )
    connection.execute(
        text(
            "INSERT INTO contents (id, project_id, media_type, media_format, "
            "storage_path, original_filename, checksum, size_bytes, hashtags, "
            "created_at, updated_at) VALUES (1, 1, 'image', 'png', "
            f"'projects/1/a.png', 'a.png', 'abc', 3, '[]', {now}, {now})"
        )
    )


def _insert_publication(
    connection: Connection, status: str, scheduled_at: str | None = None
) -> None:
    connection.execute(
        text(
            "INSERT INTO publications (project_id, content_id, account_id, status, "
            "scheduled_at, created_at, updated_at) VALUES (1, 1, 1, :status, "
            ":scheduled_at, '2026-10-06 10:00:00', '2026-10-06 10:00:00')"
        ),
        {"status": status, "scheduled_at": scheduled_at},
    )


@pytest.fixture
def seeded_engine(tmp_path: Path) -> Iterator[Engine]:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
    yield engine
    engine.dispose()


def test_only_one_active_publication_per_content_and_account(
    seeded_engine: Engine,
) -> None:
    with seeded_engine.begin() as connection:
        _insert_publication(connection, "unscheduled")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_publication(connection, "scheduled", "2100-01-01 10:00:00")


def test_cancelled_publications_do_not_count_as_active(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        _insert_publication(connection, "cancelled")
        _insert_publication(connection, "cancelled")
        _insert_publication(connection, "unscheduled")
        count = connection.execute(text("SELECT COUNT(*) FROM publications"))
        assert count.scalar_one() == 3


@pytest.mark.parametrize(
    ("status", "scheduled_at"),
    [
        ("scheduled", None),
        ("unscheduled", "2100-01-01 10:00:00"),
        ("draft", None),
        ("published", None),
    ],
)
def test_status_must_match_schedule(
    seeded_engine: Engine, status: str, scheduled_at: str | None
) -> None:
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_publication(connection, status, scheduled_at)


def test_check_constraint_names_match_the_model(seeded_engine: Engine) -> None:
    names = {
        check["name"]
        for check in inspect(seeded_engine).get_check_constraints("publications")
    }
    assert names == {
        "ck_publications_status_valid",
        "ck_publications_status_matches_schedule",
    }
    model_names = {
        constraint.name
        for constraint in Base.metadata.tables["publications"].constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert model_names == names


def test_hashtags_override_none_is_sql_null(seeded_engine: Engine) -> None:
    now = utc_now()
    overrides: list[list[str] | None] = [None, []]
    with Session(seeded_engine) as session:
        for override in overrides:
            session.add(
                Publication(
                    project_id=1,
                    content_id=1,
                    account_id=1,
                    status="cancelled",
                    hashtags_override=override,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()
        rows = session.execute(
            text(
                "SELECT hashtags_override IS NULL, hashtags_override FROM publications "
                "ORDER BY id"
            )
        ).all()
        assert [tuple(row) for row in rows] == [(1, None), (0, "[]")]
        loaded = session.scalars(select(Publication).order_by(Publication.id)).all()
        assert [p.hashtags_override for p in loaded] == [None, []]
