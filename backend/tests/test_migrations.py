from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
    assert {
        "projects",
        "accounts",
        "contents",
        "publications",
        "youtube_connections",
        "publication_attempts",
        "youtube_publication_options",
    } <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"

    run_migrations(db_path)
    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert version.scalar_one() == "0005"
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
        "ck_publications_published_at_matches_status",
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


def _insert_connection(
    connection: Connection,
    account_id: int = 1,
    project_id: int = 1,
    channel_id: str = "UC1",
    status: str = "connected",
    credential_ref: str = "ref-1",
) -> None:
    connection.execute(
        text(
            "INSERT INTO youtube_connections (account_id, project_id, channel_id, "
            "channel_title, status, credential_ref, connected_at, updated_at) VALUES "
            "(:account_id, :project_id, :channel_id, 'Channel', :status, "
            ":credential_ref, '2026-10-06 10:00:00', '2026-10-06 10:00:00')"
        ),
        {
            "account_id": account_id,
            "project_id": project_id,
            "channel_id": channel_id,
            "status": status,
            "credential_ref": credential_ref,
        },
    )


def _insert_youtube_accounts(connection: Connection) -> None:
    now = "'2026-10-06 10:00:00'"
    connection.execute(
        text(
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            f"updated_at) VALUES (2, 'Other', 'other', 1, {now}, {now})"
        )
    )
    accounts = ((2, 1, "yt-a"), (3, 1, "yt-b"), (4, 2, "yt-c"))
    for account_id, project_id, handle in accounts:
        connection.execute(
            text(
                "INSERT INTO accounts (id, project_id, platform, handle, handle_key, "
                "is_active, created_at, updated_at) VALUES (:id, :project_id, "
                f"'youtube', :handle, :handle, 1, {now}, {now})"
            ),
            {"id": account_id, "project_id": project_id, "handle": handle},
        )


def test_youtube_connections_migration_keeps_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0003")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_youtube_accounts(connection)
        _insert_publication(connection, "unscheduled")
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        for table, expected in (
            ("projects", 2),
            ("accounts", 4),
            ("contents", 1),
            ("publications", 1),
            ("youtube_connections", 0),
        ):
            count = connection.execute(text(f"SELECT COUNT(*) FROM {table}"))
            assert count.scalar_one() == expected
    engine.dispose()


@pytest.fixture
def youtube_engine(seeded_engine: Engine) -> Engine:
    with seeded_engine.begin() as connection:
        _insert_youtube_accounts(connection)
    return seeded_engine


def test_one_connection_per_account(youtube_engine: Engine) -> None:
    with youtube_engine.begin() as connection:
        _insert_connection(connection, account_id=2)
    with pytest.raises(IntegrityError), youtube_engine.begin() as connection:
        _insert_connection(
            connection, account_id=2, channel_id="UC2", credential_ref="ref-2"
        )


def test_one_channel_per_project(youtube_engine: Engine) -> None:
    with youtube_engine.begin() as connection:
        _insert_connection(connection, account_id=2)
    with pytest.raises(IntegrityError), youtube_engine.begin() as connection:
        _insert_connection(connection, account_id=3, credential_ref="ref-2")
    with youtube_engine.begin() as connection:
        _insert_connection(
            connection, account_id=4, project_id=2, credential_ref="ref-3"
        )


def test_connection_status_and_reference_constraints(youtube_engine: Engine) -> None:
    with pytest.raises(IntegrityError), youtube_engine.begin() as connection:
        _insert_connection(connection, account_id=2, status="not_connected")
    with youtube_engine.begin() as connection:
        _insert_connection(connection, account_id=2, status="reconnect_required")
    with pytest.raises(IntegrityError), youtube_engine.begin() as connection:
        _insert_connection(connection, account_id=3, channel_id="UC2")


def test_youtube_connection_constraint_names(youtube_engine: Engine) -> None:
    inspector = inspect(youtube_engine)
    table = "youtube_connections"
    names: dict[str, object] = {
        "pk": inspector.get_pk_constraint(table)["name"],
        "fks": {fk["name"] for fk in inspector.get_foreign_keys(table)},
        "uqs": {uq["name"] for uq in inspector.get_unique_constraints(table)},
        "cks": {ck["name"] for ck in inspector.get_check_constraints(table)},
    }
    expected: dict[str, object] = {
        "pk": "pk_youtube_connections",
        "fks": {
            "fk_youtube_connections_account_id_accounts",
            "fk_youtube_connections_project_id_projects",
        },
        "uqs": {
            "uq_youtube_connections_account_id",
            "uq_youtube_connections_project_id_channel_id",
            "uq_youtube_connections_credential_ref",
        },
        "cks": {"ck_youtube_connections_status"},
    }
    assert names == expected
    model_names = {
        constraint.name for constraint in Base.metadata.tables[table].constraints
    }
    assert model_names == {
        "pk_youtube_connections",
        "fk_youtube_connections_account_id_accounts",
        "fk_youtube_connections_project_id_projects",
        "uq_youtube_connections_account_id",
        "uq_youtube_connections_project_id_channel_id",
        "uq_youtube_connections_credential_ref",
        "ck_youtube_connections_status",
    }


# --- 0005: publication execution ---------------------------------------------------

NOW = "2026-10-07 10:00:00"


def _insert_publication_row(
    connection: Connection,
    status: str,
    scheduled_at: str | None = None,
    published_at: str | None = None,
) -> int:
    result = connection.execute(
        text(
            "INSERT INTO publications (project_id, content_id, account_id, status, "
            "scheduled_at, published_at, created_at, updated_at) VALUES (1, 1, 1, "
            ":status, :scheduled_at, :published_at, :now, :now)"
        ),
        {
            "status": status,
            "scheduled_at": scheduled_at,
            "published_at": published_at,
            "now": NOW,
        },
    )
    row_id = result.lastrowid
    assert row_id is not None
    return row_id


def _insert_attempt(
    connection: Connection,
    publication_id: int,
    status: str = "running",
    stage: str = "uploading",
    finished_at: str | None = None,
    error_code: str | None = None,
    bytes_sent: int = 0,
    total_bytes: int = 10,
) -> None:
    connection.execute(
        text(
            "INSERT INTO publication_attempts (publication_id, platform, status, "
            "stage, started_at, finished_at, bytes_sent, total_bytes, error_code, "
            "submitted, details, warnings) VALUES (:publication_id, 'youtube', "
            ":status, :stage, :now, :finished_at, :bytes_sent, :total_bytes, "
            ":error_code, '{}', '{}', '[]')"
        ),
        {
            "publication_id": publication_id,
            "status": status,
            "stage": stage,
            "now": NOW,
            "finished_at": finished_at,
            "bytes_sent": bytes_sent,
            "total_bytes": total_bytes,
            "error_code": error_code,
        },
    )


def test_execution_migration_keeps_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0004")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_youtube_accounts(connection)
        _insert_publication(connection, "cancelled")
        _insert_publication(connection, "scheduled", "2100-01-01 10:00:00")
        _insert_connection(connection, account_id=2)
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        for table, expected in (
            ("projects", 2),
            ("accounts", 4),
            ("contents", 1),
            ("publications", 2),
            ("youtube_connections", 1),
            ("publication_attempts", 0),
            ("youtube_publication_options", 0),
        ):
            count = connection.execute(text(f"SELECT COUNT(*) FROM {table}"))
            assert count.scalar_one() == expected
        statuses = connection.execute(
            text("SELECT status, published_at FROM publications ORDER BY id")
        ).all()
        assert [tuple(row) for row in statuses] == [
            ("cancelled", None),
            ("scheduled", None),
        ]
    engine.dispose()


@pytest.mark.parametrize("status", ["publishing", "failed"])
def test_new_statuses_accept_any_schedule(seeded_engine: Engine, status: str) -> None:
    with seeded_engine.begin() as connection:
        _insert_publication_row(connection, status, "2100-01-01 10:00:00")
    with seeded_engine.begin() as connection:
        connection.execute(text("DELETE FROM publications"))
        _insert_publication_row(connection, status)


def test_published_requires_published_at(seeded_engine: Engine) -> None:
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_publication_row(connection, "published")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_publication_row(connection, "failed", published_at=NOW)
    with seeded_engine.begin() as connection:
        _insert_publication_row(
            connection, "published", "2100-01-01 10:00:00", published_at=NOW
        )


def test_published_does_not_count_as_active(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        _insert_publication_row(connection, "published", published_at=NOW)
        _insert_publication_row(connection, "unscheduled")


@pytest.mark.parametrize(
    ("first", "second"),
    [("publishing", "unscheduled"), ("failed", "scheduled"), ("failed", "publishing")],
)
def test_publishing_and_failed_count_as_active(
    seeded_engine: Engine, first: str, second: str
) -> None:
    with seeded_engine.begin() as connection:
        _insert_publication_row(connection, first)
    scheduled = "2100-01-01 10:00:00" if second == "scheduled" else None
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_publication_row(connection, second, scheduled)


def test_only_one_running_attempt_per_publication(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "publishing")
        _insert_attempt(
            connection,
            publication_id,
            status="failed",
            finished_at=NOW,
            error_code="network_error",
        )
        _insert_attempt(connection, publication_id)
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_attempt(connection, publication_id)


@pytest.mark.parametrize(
    "attempt",
    [
        {"status": "paused"},
        {"stage": "finalizing"},
        {"status": "running", "finished_at": NOW},
        {"status": "succeeded", "stage": "done"},
        {"status": "failed", "finished_at": NOW},
        {"status": "succeeded", "finished_at": NOW, "error_code": "network_error"},
        {"bytes_sent": 11, "total_bytes": 10},
        {"bytes_sent": -1},
    ],
)
def test_attempt_constraints(seeded_engine: Engine, attempt: dict[str, Any]) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "publishing")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_attempt(connection, publication_id, **attempt)


def _insert_options(
    connection: Connection, publication_id: int, privacy: str = "private"
) -> None:
    connection.execute(
        text(
            "INSERT INTO youtube_publication_options (publication_id, privacy_status, "
            "notify_subscribers, updated_at) VALUES (:publication_id, :privacy, 0, "
            ":now)"
        ),
        {"publication_id": publication_id, "privacy": privacy, "now": NOW},
    )


def test_youtube_options_constraints(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "unscheduled")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_options(connection, publication_id, privacy="friends")
    with seeded_engine.begin() as connection:
        _insert_options(connection, publication_id, privacy="unlisted")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_options(connection, publication_id)


def test_execution_constraint_names(seeded_engine: Engine) -> None:
    inspector = inspect(seeded_engine)
    attempts = "publication_attempts"
    options = "youtube_publication_options"
    assert inspector.get_pk_constraint(attempts)["name"] == "pk_publication_attempts"
    assert {fk["name"] for fk in inspector.get_foreign_keys(attempts)} == {
        "fk_publication_attempts_publication_id_publications"
    }
    attempt_checks = {
        "ck_publication_attempts_status_valid",
        "ck_publication_attempts_stage_valid",
        "ck_publication_attempts_finished_matches_status",
        "ck_publication_attempts_error_matches_status",
        "ck_publication_attempts_bytes_valid",
    }
    assert {ck["name"] for ck in inspector.get_check_constraints(attempts)} == (
        attempt_checks
    )
    assert {ix["name"] for ix in inspector.get_indexes(attempts)} == {
        "uq_publication_attempts_running",
        "ix_publication_attempts_publication_id_started_at",
    }
    assert inspector.get_pk_constraint(options)["name"] == (
        "pk_youtube_publication_options"
    )
    assert {fk["name"] for fk in inspector.get_foreign_keys(options)} == {
        "fk_youtube_publication_options_publication_id_publications"
    }
    assert {ck["name"] for ck in inspector.get_check_constraints(options)} == {
        "ck_youtube_publication_options_privacy_valid"
    }
    model_checks = {
        constraint.name
        for constraint in Base.metadata.tables[attempts].constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert model_checks == attempt_checks
    assert "uq_publications_active_content_account" in {
        ix["name"] for ix in inspector.get_indexes("publications")
    }
