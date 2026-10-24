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
        "automation_settings",
        "instagram_connections",
        "threads_connections",
        "tiktok_connections",
        "tiktok_publication_options",
        "tiktok_publish_runs",
        "distribution_presets",
        "distribution_preset_accounts",
        "installation_auth",
        "auth_sessions",
        "library_folders",
        "pending_file_deletions",
        "pending_credential_deletions",
    } <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"

    run_migrations(db_path)
    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert version.scalar_one() == "0019"
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
        "ck_publications_auto_publish_only_scheduled",
        "ck_publications_auto_publish_error_only_armed",
        "ck_publications_auto_publish_error_pair",
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
        {"stage": "verifying"},
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
        "ck_publication_attempts_trigger_valid",
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


# --- 0006: automatic publishing ----------------------------------------------------


def _attempt_row(
    connection: Connection, publication_id: int, status: str, error_code: str | None
) -> None:
    _insert_attempt(
        connection,
        publication_id,
        status=status,
        stage="done" if status == "succeeded" else "uploading",
        finished_at=NOW,
        error_code=error_code,
        bytes_sent=10 if status == "succeeded" else 0,
    )


def test_automatic_publishing_migration_disarms_everything(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0005")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication_row(connection, "scheduled", "2100-01-01 10:00:00")
        published = _insert_publication_row(connection, "published", published_at=NOW)
        _attempt_row(connection, published, "succeeded", None)
        cancelled = _insert_publication_row(connection, "cancelled")
        _attempt_row(connection, cancelled, "failed", "network_error")
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT status, auto_publish_enabled, auto_publish_error_code, "
                "auto_publish_error_message, auto_publish_failed_at FROM publications"
            )
        ).all()
        assert sorted(row[0] for row in rows) == ["cancelled", "published", "scheduled"]
        assert all(tuple(row[1:]) == (0, None, None, None) for row in rows)
        triggers = connection.execute(text("SELECT trigger FROM publication_attempts"))
        assert [row[0] for row in triggers] == ["manual", "manual"]
        settings = connection.execute(
            text("SELECT id, automation_paused FROM automation_settings")
        ).all()
        assert [tuple(row) for row in settings] == [(1, 0)]
    engine.dispose()


def test_automatic_publishing_migration_keeps_every_scheduled_row(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0005")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        connection.execute(
            text(
                "INSERT INTO contents (id, project_id, media_type, media_format, "
                "storage_path, original_filename, checksum, size_bytes, hashtags, "
                "created_at, updated_at) VALUES (2, 1, 'image', 'png', "
                "'projects/1/b.png', 'b.png', 'def', 3, '[]', :now, :now), "
                "(3, 1, 'image', 'png', 'projects/1/c.png', 'c.png', 'ghi', 3, "
                "'[]', :now, :now)"
            ),
            {"now": NOW},
        )
        recent = utc_now().replace(tzinfo=None).isoformat(sep=" ")
        for content_id, scheduled_at in (
            (1, "2020-01-01 10:00:00"),
            (2, recent),
            (3, "2100-01-01 10:00:00"),
        ):
            connection.execute(
                text(
                    "INSERT INTO publications (project_id, content_id, account_id, "
                    "status, scheduled_at, created_at, updated_at) VALUES (1, :c, 1, "
                    "'scheduled', :s, :now, :now)"
                ),
                {"c": content_id, "s": scheduled_at, "now": NOW},
            )
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT status, auto_publish_enabled FROM publications ORDER BY id")
        ).all()
        assert [tuple(row) for row in rows] == [("scheduled", 0)] * 3
    engine.dispose()


def test_automatic_publishing_migration_has_no_external_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx2

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("A migration must never contact a platform.")

    monkeypatch.setattr(httpx2.Client, "send", fail)
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", fail)

    run_migrations(tmp_path / "app.db")


def _arm(connection: Connection, publication_id: int) -> None:
    connection.execute(
        text("UPDATE publications SET auto_publish_enabled = 1 WHERE id = :id"),
        {"id": publication_id},
    )


@pytest.mark.parametrize("status", ["unscheduled", "publishing", "failed"])
def test_only_scheduled_publications_can_be_armed(
    seeded_engine: Engine, status: str
) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, status)
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _arm(connection, publication_id)


def test_scheduled_publications_can_be_armed(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(
            connection, "scheduled", "2100-01-01 10:00:00"
        )
        _arm(connection, publication_id)


@pytest.mark.parametrize(
    ("armed", "values"),
    [
        (False, ("reconnect_required", "Reconnect.", NOW)),
        (True, ("reconnect_required", None, NOW)),
        (True, ("reconnect_required", "Reconnect.", None)),
        (True, (None, "Reconnect.", NOW)),
    ],
)
def test_auto_publish_error_constraints(
    seeded_engine: Engine, armed: bool, values: tuple[str | None, ...]
) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(
            connection, "scheduled", "2100-01-01 10:00:00"
        )
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE publications SET auto_publish_enabled = :armed, "
                "auto_publish_error_code = :code, auto_publish_error_message = :msg, "
                "auto_publish_failed_at = :at WHERE id = :id"
            ),
            {
                "armed": armed,
                "code": values[0],
                "msg": values[1],
                "at": values[2],
                "id": publication_id,
            },
        )


def test_auto_publish_error_accepted_when_armed(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(
            connection, "scheduled", "2100-01-01 10:00:00"
        )
        connection.execute(
            text(
                "UPDATE publications SET auto_publish_enabled = 1, "
                "auto_publish_error_code = 'not_connected', "
                "auto_publish_error_message = 'Connect.', auto_publish_failed_at = :at "
                "WHERE id = :id"
            ),
            {"at": NOW, "id": publication_id},
        )


def test_attempt_trigger_constraint(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "publishing")
        _insert_attempt(connection, publication_id)
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        connection.execute(text("UPDATE publication_attempts SET trigger = 'other'"))
    with seeded_engine.begin() as connection:
        connection.execute(
            text("UPDATE publication_attempts SET trigger = 'scheduled'")
        )


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO automation_settings (id, automation_paused, updated_at) "
        "VALUES (2, 0, '2026-10-07 10:00:00')",
        "INSERT INTO automation_settings (id, automation_paused, updated_at) "
        "VALUES (1, 0, '2026-10-07 10:00:00')",
    ],
)
def test_automation_settings_is_a_singleton(
    seeded_engine: Engine, statement: str
) -> None:
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        connection.execute(text(statement))


def test_automatic_publishing_names(seeded_engine: Engine) -> None:
    inspector = inspect(seeded_engine)
    assert "ix_publications_status_auto_publish_scheduled_at" in {
        ix["name"] for ix in inspector.get_indexes("publications")
    }
    assert inspector.get_pk_constraint("automation_settings")["name"] == (
        "pk_automation_settings"
    )
    assert {
        ck["name"] for ck in inspector.get_check_constraints("automation_settings")
    } == {"ck_automation_settings_singleton"}
    # Partial unique indexes survive the table rebuilds.
    indexes = {ix["name"]: ix for ix in inspector.get_indexes("publication_attempts")}
    assert "uq_publication_attempts_running" in indexes


def test_automatic_publishing_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    command.downgrade(_alembic_config(db_path), "0005")

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    assert "automation_settings" not in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("publications")}
    assert not {c for c in columns if c.startswith("auto_publish")}
    attempt_columns = {
        column["name"] for column in inspector.get_columns("publication_attempts")
    }
    assert "trigger" not in attempt_columns
    engine.dispose()


# --- 0007: Instagram connections ----------------------------------------------------


def _insert_instagram_connection(
    connection: Connection,
    account_id: int = 2,
    project_id: int = 1,
    instagram_user_id: str = "1784_A",
    status: str = "connected",
    account_type: str = "BUSINESS",
    credential_ref: str = "ig-ref-1",
) -> None:
    connection.execute(
        text(
            "INSERT INTO instagram_connections (account_id, project_id, "
            "instagram_user_id, username, account_type, status, credential_ref, "
            "credential_expires_at, connected_at, updated_at) VALUES (:account_id, "
            ":project_id, :instagram_user_id, 'cyber', :account_type, :status, "
            ":credential_ref, '2026-12-07 10:00:00', '2026-10-08 10:00:00', "
            "'2026-10-08 10:00:00')"
        ),
        {
            "account_id": account_id,
            "project_id": project_id,
            "instagram_user_id": instagram_user_id,
            "status": status,
            "account_type": account_type,
            "credential_ref": credential_ref,
        },
    )


def _insert_instagram_accounts(connection: Connection) -> None:
    now = "'2026-10-08 10:00:00'"
    connection.execute(
        text(
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            f"updated_at) VALUES (2, 'Other', 'other', 1, {now}, {now})"
        )
    )
    accounts = ((2, 1, "ig-a"), (3, 1, "ig-b"), (4, 2, "ig-c"))
    for account_id, project_id, handle in accounts:
        connection.execute(
            text(
                "INSERT INTO accounts (id, project_id, platform, handle, handle_key, "
                "is_active, created_at, updated_at) VALUES (:id, :project_id, "
                f"'instagram', :handle, :handle, 1, {now}, {now})"
            ),
            {"id": account_id, "project_id": project_id, "handle": handle},
        )


@pytest.fixture
def instagram_engine(seeded_engine: Engine) -> Engine:
    with seeded_engine.begin() as connection:
        _insert_instagram_accounts(connection)
    return seeded_engine


def test_migration_0007_creates_instagram_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0006")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication(connection, "unscheduled")
    assert "instagram_connections" not in inspect(engine).get_table_names()
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    table = "instagram_connections"
    assert {column["name"] for column in inspector.get_columns(table)} == {
        "id",
        "account_id",
        "project_id",
        "instagram_user_id",
        "app_scoped_id",
        "username",
        "account_type",
        "profile_picture_url",
        "status",
        "credential_ref",
        "credential_expires_at",
        "connected_at",
        "last_verified_at",
        "updated_at",
    }
    names: dict[str, object] = {
        "fks": {fk["name"] for fk in inspector.get_foreign_keys(table)},
        "uqs": {uq["name"] for uq in inspector.get_unique_constraints(table)},
        "cks": {ck["name"] for ck in inspector.get_check_constraints(table)},
    }
    assert names == {
        "fks": {
            "fk_instagram_connections_account_id_accounts",
            "fk_instagram_connections_project_id_projects",
        },
        "uqs": {
            "uq_instagram_connections_account_id",
            "uq_instagram_connections_project_id_instagram_user_id",
            "uq_instagram_connections_credential_ref",
        },
        "cks": {
            "ck_instagram_connections_status",
            "ck_instagram_connections_account_type",
        },
    }
    for fk in inspector.get_foreign_keys(table):
        assert fk["options"].get("ondelete") == "RESTRICT"
    with engine.connect() as connection:
        for existing, expected in (
            ("projects", 1),
            ("accounts", 1),
            ("publications", 1),
        ):
            count = connection.execute(text(f"SELECT COUNT(*) FROM {existing}"))
            assert count.scalar_one() == expected
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0006")
    engine = create_db_engine(db_path)
    assert "instagram_connections" not in inspect(engine).get_table_names()
    engine.dispose()


def test_one_instagram_connection_per_account(instagram_engine: Engine) -> None:
    with instagram_engine.begin() as connection:
        _insert_instagram_connection(connection)
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_instagram_connection(
            connection, instagram_user_id="1784_B", credential_ref="ig-ref-2"
        )


def test_one_instagram_account_per_project(instagram_engine: Engine) -> None:
    with instagram_engine.begin() as connection:
        _insert_instagram_connection(connection)
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_instagram_connection(connection, account_id=3, credential_ref="ig-2")
    with instagram_engine.begin() as connection:
        _insert_instagram_connection(
            connection, account_id=4, project_id=2, credential_ref="ig-ref-3"
        )


def test_instagram_connection_checks_and_reference(instagram_engine: Engine) -> None:
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_instagram_connection(connection, status="not_connected")
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_instagram_connection(connection, account_type="PERSONAL")
    with instagram_engine.begin() as connection:
        _insert_instagram_connection(
            connection, status="reconnect_required", account_type="MEDIA_CREATOR"
        )
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_instagram_connection(
            connection, account_id=3, instagram_user_id="1784_B"
        )


# --- 0008: Instagram publishing ------------------------------------------------------


@pytest.mark.parametrize("stage", ["processing", "finalizing"])
def test_new_attempt_stages_are_accepted(seeded_engine: Engine, stage: str) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "publishing")
        _insert_attempt(connection, publication_id, stage=stage)


def test_migration_0008_creates_instagram_publishing_tables(
    seeded_engine: Engine,
) -> None:
    inspector = inspect(seeded_engine)
    assert {
        "instagram_publication_options",
        "instagram_publish_runs",
        "temporary_media_objects",
    } <= set(inspector.get_table_names())
    assert {
        ck["name"] for ck in inspector.get_check_constraints("instagram_publish_runs")
    } == {
        "ck_instagram_publish_runs_phase_valid",
        "ck_instagram_publish_runs_media_kind_valid",
    }
    assert {ix["name"] for ix in inspector.get_indexes("temporary_media_objects")} == {
        "ix_temporary_media_objects_pending"
    }
    assert {
        ck["name"]
        for ck in inspector.get_check_constraints("instagram_publication_options")
    } == {"ck_instagram_publication_options_alt_text_length"}
    # The partial unique index survives the rebuild of publication_attempts.
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "publishing")
        _insert_attempt(connection, publication_id)
        _insert_attempt(connection, publication_id)


def test_instagram_options_reject_long_alt_text(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "unscheduled")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO instagram_publication_options (publication_id, "
                "is_ai_generated, share_to_feed, alt_text, updated_at) "
                "VALUES (:id, 0, 1, :alt, :now)"
            ),
            {"id": publication_id, "alt": "a" * 1001, "now": NOW},
        )


def test_migration_0008_downgrade_without_new_stages(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    command.downgrade(_alembic_config(db_path), "0007")

    engine = create_db_engine(db_path)
    tables = set(inspect(engine).get_table_names())
    assert "instagram_publish_runs" not in tables
    assert "temporary_media_objects" not in tables
    assert "instagram_publication_options" not in tables
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        publication_id = _insert_publication_row(connection, "publishing")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_attempt(connection, publication_id, stage="processing")
    engine.dispose()


def test_migration_0008_downgrade_aborts_when_new_stages_are_used(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        publication_id = _insert_publication_row(connection, "publishing")
        _insert_attempt(connection, publication_id, stage="finalizing")
    engine.dispose()

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(_alembic_config(db_path), "0007")

    engine = create_db_engine(db_path)
    assert "instagram_publish_runs" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        stage = connection.execute(text("SELECT stage FROM publication_attempts"))
        assert stage.scalar_one() == "finalizing"
        version = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert version.scalar_one() == "0008"
    engine.dispose()


# --- 0009: Threads connections -------------------------------------------------------


def _insert_threads_connection(
    connection: Connection,
    account_id: int = 2,
    project_id: int = 1,
    threads_user_id: str = "2584_A",
    status: str = "connected",
    credential_ref: str = "th-ref-1",
) -> None:
    connection.execute(
        text(
            "INSERT INTO threads_connections (account_id, project_id, "
            "threads_user_id, username, status, credential_ref, token_obtained_at, "
            "credential_expires_at, connected_at, updated_at) VALUES (:account_id, "
            ":project_id, :threads_user_id, 'cyber', :status, :credential_ref, "
            "'2026-10-13 10:00:00', '2026-12-12 10:00:00', '2026-10-13 10:00:00', "
            "'2026-10-13 10:00:00')"
        ),
        {
            "account_id": account_id,
            "project_id": project_id,
            "threads_user_id": threads_user_id,
            "status": status,
            "credential_ref": credential_ref,
        },
    )


def test_migration_0009_creates_threads_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0008")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication(connection, "unscheduled")
    assert "threads_connections" not in inspect(engine).get_table_names()
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    table = "threads_connections"
    assert {column["name"] for column in inspector.get_columns(table)} == {
        "id",
        "account_id",
        "project_id",
        "threads_user_id",
        "username",
        "display_name",
        "profile_picture_url",
        "status",
        "credential_ref",
        "token_obtained_at",
        "credential_expires_at",
        "data_access_expires_at",
        "connected_at",
        "last_verified_at",
        "updated_at",
    }
    names: dict[str, object] = {
        "fks": {fk["name"] for fk in inspector.get_foreign_keys(table)},
        "uqs": {uq["name"] for uq in inspector.get_unique_constraints(table)},
        "cks": {ck["name"] for ck in inspector.get_check_constraints(table)},
    }
    assert names == {
        "fks": {
            "fk_threads_connections_account_id_accounts",
            "fk_threads_connections_project_id_projects",
        },
        "uqs": {
            "uq_threads_connections_account_id",
            "uq_threads_connections_project_id_threads_user_id",
            "uq_threads_connections_credential_ref",
        },
        "cks": {"ck_threads_connections_status"},
    }
    for fk in inspector.get_foreign_keys(table):
        assert fk["options"].get("ondelete") == "RESTRICT"
    with engine.connect() as connection:
        for existing, expected in (
            ("projects", 1),
            ("accounts", 1),
            ("publications", 1),
        ):
            count = connection.execute(text(f"SELECT COUNT(*) FROM {existing}"))
            assert count.scalar_one() == expected
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0008")
    engine = create_db_engine(db_path)
    assert "threads_connections" not in inspect(engine).get_table_names()
    engine.dispose()


def test_threads_connection_constraints(instagram_engine: Engine) -> None:
    # The seeded accounts are reused: the table itself does not check the platform.
    with instagram_engine.begin() as connection:
        _insert_threads_connection(connection)
    # One connection per account.
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_threads_connection(
            connection, threads_user_id="2584_B", credential_ref="th-ref-2"
        )
    # One Threads account per project; allowed in another project.
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_threads_connection(connection, account_id=3, credential_ref="th-2")
    with instagram_engine.begin() as connection:
        _insert_threads_connection(
            connection, account_id=4, project_id=2, credential_ref="th-ref-3"
        )
    # Status check and unique credential reference.
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_threads_connection(
            connection,
            account_id=3,
            threads_user_id="2584_C",
            status="not_connected",
            credential_ref="th-ref-4",
        )
    with pytest.raises(IntegrityError), instagram_engine.begin() as connection:
        _insert_threads_connection(
            connection,
            account_id=3,
            threads_user_id="2584_C",
            credential_ref="th-ref-1",
        )


# --- 0010: Threads publishing --------------------------------------------------------

PUBLICATIONS_CHECKS = {
    "ck_publications_status_valid",
    "ck_publications_status_matches_schedule",
    "ck_publications_published_at_matches_status",
    "ck_publications_auto_publish_only_scheduled",
    "ck_publications_auto_publish_error_only_armed",
    "ck_publications_auto_publish_error_pair",
}


def _insert_text_publication(
    connection: Connection, status: str = "unscheduled"
) -> int:
    result = connection.execute(
        text(
            "INSERT INTO publications (project_id, content_id, account_id, status, "
            "description_override, created_at, updated_at) VALUES (1, NULL, 1, "
            ":status, 'Text only', :now, :now)"
        ),
        {"status": status, "now": NOW},
    )
    row_id = result.lastrowid
    assert row_id is not None
    return row_id


def _active_index_sql(engine: Engine) -> str:
    with engine.connect() as connection:
        sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = "
                "'uq_publications_active_content_account'"
            )
        ).scalar_one()
    assert isinstance(sql, str)
    return sql


def test_migration_0010_upgrade_keeps_publications_and_checks(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0009")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication(connection, "unscheduled")
        _insert_publication(connection, "cancelled")
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("publications")}
    assert columns["content_id"]["nullable"] is True
    assert {
        ck["name"] for ck in inspector.get_check_constraints("publications")
    } == PUBLICATIONS_CHECKS
    assert "WHERE" in _active_index_sql(engine).upper()
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT content_id, status FROM publications ORDER BY id")
        ).all()
    assert [tuple(row) for row in rows] == [(1, "unscheduled"), (1, "cancelled")]
    # Still one active publication per content and account.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_publication(connection, "scheduled", "2100-01-01 10:00:00")
    # The CHECKs survived the rebuild.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_publication(connection, "scheduled")
    engine.dispose()


def test_publications_accept_null_content(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        first = _insert_text_publication(connection)
        second = _insert_text_publication(connection)
        content_id = connection.execute(
            text("SELECT content_id FROM publications WHERE id = :id"), {"id": first}
        ).scalar_one()
    assert content_id is None
    assert first != second


def test_migration_0010_creates_threads_publishing_tables(
    seeded_engine: Engine,
) -> None:
    inspector = inspect(seeded_engine)
    assert {"threads_publication_options", "threads_publish_runs"} <= set(
        inspector.get_table_names()
    )
    assert {
        ck["name"] for ck in inspector.get_check_constraints("threads_publish_runs")
    } == {
        "ck_threads_publish_runs_phase_valid",
        "ck_threads_publish_runs_media_kind_valid",
    }
    assert {ix["name"] for ix in inspector.get_indexes("threads_publish_runs")} == {
        "ix_threads_publish_runs_publication_id_container_created_at"
    }
    assert {
        ck["name"]
        for ck in inspector.get_check_constraints("threads_publication_options")
    } == {"ck_threads_publication_options_alt_text_length"}
    for table in ("threads_publication_options", "threads_publish_runs"):
        for fk in inspector.get_foreign_keys(table):
            assert fk["options"].get("ondelete") == "RESTRICT"


def test_threads_publishing_constraints(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_text_publication(connection, "publishing")
        _insert_attempt(connection, publication_id, stage="processing")
        attempt_id = connection.execute(
            text("SELECT id FROM publication_attempts")
        ).scalar_one()
    insert_run = text(
        "INSERT INTO threads_publish_runs (attempt_id, publication_id, media_kind, "
        "phase, updated_at) VALUES (:attempt, :publication, :kind, :phase, :now)"
    )
    for kind, phase in (("reel", "preparing"), ("text", "waiting")):
        with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
            connection.execute(
                insert_run,
                {
                    "attempt": attempt_id,
                    "publication": publication_id,
                    "kind": kind,
                    "phase": phase,
                    "now": NOW,
                },
            )
    with seeded_engine.begin() as connection:
        connection.execute(
            insert_run,
            {
                "attempt": attempt_id,
                "publication": publication_id,
                "kind": "text",
                "phase": "preparing",
                "now": NOW,
            },
        )
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO threads_publication_options (publication_id, alt_text, "
                "updated_at) VALUES (:id, :alt, :now)"
            ),
            {"id": publication_id, "alt": "a" * 1001, "now": NOW},
        )


def test_migration_0010_downgrade_without_text_publications(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication(connection, "unscheduled")
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0009")

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "threads_publish_runs" not in tables
    assert "threads_publication_options" not in tables
    columns = {c["name"]: c for c in inspector.get_columns("publications")}
    assert columns["content_id"]["nullable"] is False
    assert {
        ck["name"] for ck in inspector.get_check_constraints("publications")
    } == PUBLICATIONS_CHECKS
    assert "WHERE" in _active_index_sql(engine).upper()
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM publications"))
        assert count.scalar_one() == 1
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_publication(connection, "scheduled", "2100-01-01 10:00:00")
    engine.dispose()


def test_migration_0010_downgrade_aborts_with_text_publications(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_text_publication(connection)
    engine.dispose()

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(_alembic_config(db_path), "0009")

    engine = create_db_engine(db_path)
    assert "threads_publish_runs" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        content_id = connection.execute(text("SELECT content_id FROM publications"))
        assert content_id.scalar_one() is None
        version = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert version.scalar_one() == "0010"
    engine.dispose()


def _insert_tiktok_connection(
    connection: Connection,
    account_id: int = 1,
    open_id: str = "oid-A",
    credential_ref: str = "tt-ref-1",
    status: str = "connected",
) -> None:
    connection.execute(
        text(
            "INSERT INTO tiktok_connections (account_id, project_id, open_id, status, "
            "credential_ref, access_expires_at, refresh_expires_at, connected_at, "
            "updated_at) VALUES (:account_id, 1, :open_id, :status, :ref, :now, :now, "
            ":now, :now)"
        ),
        {
            "account_id": account_id,
            "open_id": open_id,
            "status": status,
            "ref": credential_ref,
            "now": "2026-10-14 10:00:00",
        },
    )


def test_migration_0011_creates_tiktok_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0010")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication(connection, "unscheduled")
    assert "tiktok_connections" not in inspect(engine).get_table_names()
    engine.dispose()

    command.upgrade(_alembic_config(db_path), "0011")

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    table = "tiktok_connections"
    assert {column["name"] for column in inspector.get_columns(table)} == {
        "id",
        "account_id",
        "project_id",
        "open_id",
        "display_name",
        "avatar_url",
        "status",
        "credential_ref",
        "access_expires_at",
        "refresh_expires_at",
        "connected_at",
        "last_verified_at",
        "updated_at",
    }
    assert {
        "fks": {fk["name"] for fk in inspector.get_foreign_keys(table)},
        "uqs": {uq["name"] for uq in inspector.get_unique_constraints(table)},
        "cks": {ck["name"] for ck in inspector.get_check_constraints(table)},
    } == {
        "fks": {
            "fk_tiktok_connections_account_id_accounts",
            "fk_tiktok_connections_project_id_projects",
        },
        "uqs": {
            "uq_tiktok_connections_account_id",
            "uq_tiktok_connections_project_id_open_id",
            "uq_tiktok_connections_credential_ref",
        },
        "cks": {"ck_tiktok_connections_status"},
    }
    for fk in inspector.get_foreign_keys(table):
        assert fk["options"].get("ondelete") == "RESTRICT"
    orphans = "tiktok_credential_orphans"
    assert {column["name"] for column in inspector.get_columns(orphans)} == {
        "credential_ref",
        "account_id",
        "created_at",
    }
    assert inspector.get_pk_constraint(orphans)["constrained_columns"] == [
        "credential_ref"
    ]
    assert inspector.get_foreign_keys(orphans) == []

    with engine.begin() as connection:
        _insert_tiktok_connection(connection)
    # One connection per account.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_tiktok_connection(connection, open_id="oid-B", credential_ref="r2")
    # One open_id per project.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts (project_id, platform, handle, handle_key, "
                "is_active, created_at, updated_at) SELECT project_id, 'tiktok', "
                "'other', 'other', 1, created_at, updated_at FROM accounts LIMIT 1"
            )
        )
        _insert_tiktok_connection(connection, account_id=2, credential_ref="r3")
    # Unique credential reference.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM tiktok_connections"))
        _insert_tiktok_connection(connection, credential_ref="r4")
        connection.execute(
            text(
                "INSERT INTO accounts (project_id, platform, handle, handle_key, "
                "is_active, created_at, updated_at) SELECT project_id, 'tiktok', "
                "'other', 'other', 1, created_at, updated_at FROM accounts LIMIT 1"
            )
        )
        _insert_tiktok_connection(
            connection, account_id=2, open_id="oid-B", credential_ref="r4"
        )
    # Only the documented statuses.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM tiktok_connections"))
        _insert_tiktok_connection(connection, status="pending")
    with engine.connect() as connection:
        for existing, expected in (
            ("projects", 1),
            ("accounts", 1),
            ("publications", 1),
        ):
            count = connection.execute(text(f"SELECT COUNT(*) FROM {existing}"))
            assert count.scalar_one() == expected
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0010")
    engine = create_db_engine(db_path)
    tables = set(inspect(engine).get_table_names())
    assert "tiktok_connections" not in tables
    assert "tiktok_credential_orphans" not in tables
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM publications"))
        assert count.scalar_one() == 1
    engine.dispose()


# --- 0012: TikTok publishing ---------------------------------------------------------

TIKTOK_OPTIONS_CHECKS = {
    "ck_tiktok_publication_options_privacy_valid",
    "ck_tiktok_publication_options_brand_toggles_need_disclosure",
    "ck_tiktok_publication_options_branded_not_private",
    "ck_tiktok_publication_options_consent_complete",
}
TIKTOK_RUN_CHECKS = {
    "ck_tiktok_publish_runs_phase_valid",
    "ck_tiktok_publish_runs_confirmed_bytes_range",
    "ck_tiktok_publish_runs_total_chunk_count_range",
    "ck_tiktok_publish_runs_write_ahead_needs_publish_id",
}


def _insert_tiktok_options(
    connection: Connection, publication_id: int, **values: Any
) -> None:
    row: dict[str, Any] = {
        "publication_id": publication_id,
        "privacy_level": None,
        "allow_comment": 0,
        "allow_duet": 0,
        "allow_stitch": 0,
        "commercial_disclosure_enabled": 0,
        "brand_organic_toggle": 0,
        "brand_content_toggle": 0,
        "is_aigc": None,
        "consent_fingerprint": None,
        "consent_declaration_version": None,
        "consented_at": None,
        "updated_at": NOW,
    }
    row.update(values)
    columns = ", ".join(row)
    params = ", ".join(f":{name}" for name in row)
    connection.execute(
        text(f"INSERT INTO tiktok_publication_options ({columns}) VALUES ({params})"),
        row,
    )


OMIT = object()


def _insert_tiktok_run(
    connection: Connection, attempt_id: int, publication_id: int, **values: Any
) -> None:
    row: dict[str, Any] = {
        "attempt_id": attempt_id,
        "publication_id": publication_id,
        "phase": "preparing",
        "publish_id": None,
        "video_size": 100,
        "chunk_size": 100,
        "total_chunk_count": 1,
        "confirmed_bytes": 0,
        "final_chunk_started_at": None,
        "mode": "DIRECT_POST",
        "created_at": NOW,
        "updated_at": NOW,
    }
    row.update(values)
    # Columns that did not exist yet at older revisions.
    row = {name: value for name, value in row.items() if value is not OMIT}
    columns = ", ".join(row)
    params = ", ".join(f":{name}" for name in row)
    connection.execute(
        text(f"INSERT INTO tiktok_publish_runs ({columns}) VALUES ({params})"), row
    )


def test_migration_0012_creates_tiktok_publishing_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0011")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication(connection, "unscheduled")
    engine.dispose()

    command.upgrade(_alembic_config(db_path), "0012")

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    assert {
        column["name"] for column in inspector.get_columns("tiktok_publication_options")
    } == {
        "publication_id",
        "privacy_level",
        "allow_comment",
        "allow_duet",
        "allow_stitch",
        "commercial_disclosure_enabled",
        "brand_organic_toggle",
        "brand_content_toggle",
        "is_aigc",
        "consent_fingerprint",
        "consent_declaration_version",
        "consented_at",
        "updated_at",
    }
    run_columns = {c["name"] for c in inspector.get_columns("tiktok_publish_runs")}
    assert run_columns == {
        "attempt_id",
        "publication_id",
        "phase",
        "publish_id",
        "video_size",
        "chunk_size",
        "total_chunk_count",
        "confirmed_bytes",
        "remote_uploaded_bytes",
        "initialized_at",
        "final_chunk_started_at",
        "final_chunk_http_status",
        "last_remote_status",
        "fail_reason",
        "last_log_id",
        "last_status_at",
        "created_at",
        "updated_at",
    }
    # The upload URL is a secret: no column could ever hold it.
    assert not any("url" in name for name in run_columns)
    assert {
        ck["name"]
        for ck in inspector.get_check_constraints("tiktok_publication_options")
    } == TIKTOK_OPTIONS_CHECKS
    assert {
        ck["name"] for ck in inspector.get_check_constraints("tiktok_publish_runs")
    } == TIKTOK_RUN_CHECKS
    assert {ix["name"] for ix in inspector.get_indexes("tiktok_publish_runs")} == {
        "ix_tiktok_publish_runs_publication_id"
    }
    assert {
        uq["name"] for uq in inspector.get_unique_constraints("tiktok_publish_runs")
    } == {"uq_tiktok_publish_runs_publish_id"}
    for table in ("tiktok_publication_options", "tiktok_publish_runs"):
        for fk in inspector.get_foreign_keys(table):
            assert fk["options"].get("ondelete") == "RESTRICT"
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM publications"))
        assert count.scalar_one() == 1
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0011")
    engine = create_db_engine(db_path)
    tables = set(inspect(engine).get_table_names())
    assert "tiktok_publication_options" not in tables
    assert "tiktok_publish_runs" not in tables
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM publications"))
        assert count.scalar_one() == 1
    engine.dispose()


@pytest.mark.parametrize(
    "values",
    [
        {"privacy_level": "EVERYONE"},
        # Toggles need the disclosure.
        {"brand_organic_toggle": 1},
        {"brand_content_toggle": 1, "privacy_level": "FOLLOWER_OF_CREATOR"},
        # Branded content can never be private.
        {
            "commercial_disclosure_enabled": 1,
            "brand_content_toggle": 1,
            "privacy_level": "SELF_ONLY",
        },
        # Consent fields are all set or all empty.
        {"consent_fingerprint": "a" * 64},
        {"consent_fingerprint": "a" * 64, "consent_declaration_version": "v"},
        {"consented_at": NOW},
    ],
)
def test_tiktok_options_constraints(
    seeded_engine: Engine, values: dict[str, Any]
) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "unscheduled")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_tiktok_options(connection, publication_id, **values)


def test_tiktok_options_accept_valid_rows(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        first = _insert_publication_row(connection, "unscheduled")
        _insert_tiktok_options(connection, first)
        connection.execute(text("UPDATE publications SET status = 'cancelled'"))
        second = _insert_publication_row(connection, "unscheduled")
        _insert_tiktok_options(
            connection,
            second,
            privacy_level="SELF_ONLY",
            commercial_disclosure_enabled=1,
            brand_organic_toggle=1,
            is_aigc=0,
            consent_fingerprint="a" * 64,
            consent_declaration_version="music-usage-2026-10-14",
            consented_at=NOW,
        )
        count = connection.execute(
            text("SELECT COUNT(*) FROM tiktok_publication_options")
        )
        assert count.scalar_one() == 2


@pytest.mark.parametrize(
    "values",
    [
        {"phase": "waiting"},
        {"confirmed_bytes": -1},
        {"confirmed_bytes": 101},
        {"total_chunk_count": 0},
        {"total_chunk_count": 1001},
        # The write-ahead needs the publish_id on record.
        {"final_chunk_started_at": NOW},
    ],
)
def test_tiktok_publish_run_constraints(
    seeded_engine: Engine, values: dict[str, Any]
) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "publishing")
        _insert_attempt(connection, publication_id, stage="preparing")
        attempt_id = connection.execute(
            text("SELECT id FROM publication_attempts")
        ).scalar_one()
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_tiktok_run(connection, attempt_id, publication_id, **values)


def test_tiktok_publish_id_is_unique(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "failed")
        _insert_attempt(
            connection,
            publication_id,
            status="failed",
            finished_at=NOW,
            error_code="interrupted",
        )
        _insert_attempt(
            connection,
            publication_id,
            status="failed",
            finished_at=NOW,
            error_code="interrupted",
        )
        first, second = connection.execute(
            text("SELECT id FROM publication_attempts ORDER BY id")
        ).scalars()
        _insert_tiktok_run(
            connection,
            first,
            publication_id,
            phase="final_chunk",
            publish_id="v_pub_file~v2-1.1",
            final_chunk_started_at=NOW,
        )
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_tiktok_run(
            connection, second, publication_id, publish_id="v_pub_file~v2-1.1"
        )


# --- 0013: TikTok Upload to Inbox -------------------------------------------------

TIKTOK_RUN_CHECKS_0013 = TIKTOK_RUN_CHECKS | {
    "ck_tiktok_publish_runs_mode_valid",
    "ck_tiktok_publish_runs_delivered_only_inbox",
    "ck_tiktok_publish_runs_user_published_only_inbox",
    "ck_tiktok_publish_runs_public_post_count_valid",
}
TIKTOK_RUN_COLUMNS_0013 = {
    "mode",
    "delivered_to_inbox_at",
    "user_published_at",
    "public_post_count",
}


def _insert_tiktok_account(connection: Connection, account_id: int = 2) -> None:
    connection.execute(
        text(
            "INSERT INTO accounts (id, project_id, platform, handle, handle_key, "
            "is_active, created_at, updated_at) VALUES (:id, 1, 'tiktok', :handle, "
            ":handle, 1, :now, :now)"
        ),
        {"id": account_id, "handle": f"tt{account_id}", "now": NOW},
    )


def _insert_publication_for(
    connection: Connection,
    account_id: int,
    status: str,
    published_at: str | None = None,
    scheduled_at: str | None = None,
) -> int:
    result = connection.execute(
        text(
            "INSERT INTO publications (project_id, content_id, account_id, status, "
            "scheduled_at, published_at, created_at, updated_at) VALUES (1, 1, "
            ":account_id, :status, :scheduled_at, :published_at, :now, :now)"
        ),
        {
            "account_id": account_id,
            "status": status,
            "scheduled_at": scheduled_at,
            "published_at": published_at,
            "now": NOW,
        },
    )
    row_id = result.lastrowid
    assert row_id is not None
    return row_id


def _attempt_id(connection: Connection, publication_id: int) -> int:
    attempt_id: int = connection.execute(
        text("SELECT id FROM publication_attempts WHERE publication_id = :id"),
        {"id": publication_id},
    ).scalar_one()
    return attempt_id


def _rows(engine: Engine, sql: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(text(sql))]


def _seed_0012_tiktok(db_path: Path) -> dict[str, int]:
    """At 0012: TikTok publications with and without options rows in several
    statuses, one Instagram publication and one TikTok run."""
    command.upgrade(_alembic_config(db_path), "0012")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        # Accounts 2-4 are TikTok; 4 has no publication.
        for account_id in (2, 3, 4):
            _insert_tiktok_account(connection, account_id)
        with_options = _insert_publication_for(connection, 2, "failed")
        _insert_tiktok_options(connection, with_options, privacy_level="SELF_ONLY")
        _insert_attempt(
            connection,
            with_options,
            status="failed",
            finished_at=NOW,
            error_code="interrupted",
        )
        _insert_tiktok_run(
            connection,
            _attempt_id(connection, with_options),
            with_options,
            phase="failed",
            mode=OMIT,
        )
        published = _insert_publication_for(connection, 2, "published", NOW)
        cancelled = _insert_publication_for(connection, 2, "cancelled")
        unscheduled = _insert_publication_for(connection, 3, "unscheduled")
        instagram = _insert_publication_for(connection, 1, "unscheduled")
    engine.dispose()
    return {
        "with_options": with_options,
        "published": published,
        "cancelled": cancelled,
        "unscheduled": unscheduled,
        "instagram": instagram,
    }


def test_migration_0013_sets_direct_post_on_every_tiktok_publication(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    ids = _seed_0012_tiktok(db_path)

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    options = {
        row["publication_id"]: row
        for row in _rows(engine, "SELECT * FROM tiktok_publication_options")
    }
    tiktok_ids = {ids[name] for name in ("with_options", "published", "cancelled")}
    tiktok_ids.add(ids["unscheduled"])
    # Every TikTok publication (any status) has options with Direct Post; Instagram
    # publications get none.
    assert set(options) == tiktok_ids
    assert {row["mode"] for row in options.values()} == {"DIRECT_POST"}
    # Existing options keep their values; inserted rows use the 0012 defaults.
    assert options[ids["with_options"]]["privacy_level"] == "SELF_ONLY"
    inserted = options[ids["unscheduled"]]
    assert inserted["privacy_level"] is None
    assert inserted["is_aigc"] is None
    assert inserted["consent_fingerprint"] is None
    assert inserted["allow_comment"] == 0
    [run] = _rows(engine, "SELECT * FROM tiktok_publish_runs")
    assert run["mode"] == "DIRECT_POST"
    assert run["delivered_to_inbox_at"] is None
    assert run["user_published_at"] is None
    assert run["public_post_count"] is None
    inspector = inspect(engine)
    assert TIKTOK_RUN_COLUMNS_0013 <= {
        c["name"] for c in inspector.get_columns("tiktok_publish_runs")
    }
    assert {
        ck["name"] for ck in inspector.get_check_constraints("tiktok_publish_runs")
    } == TIKTOK_RUN_CHECKS_0013
    assert {
        ck["name"]
        for ck in inspector.get_check_constraints("tiktok_publication_options")
    } == TIKTOK_OPTIONS_CHECKS | {"ck_tiktok_publication_options_mode_valid"}
    # The partial unique index keeps its WHERE clause after the rebuild.
    assert "WHERE" in _active_index_sql(engine)
    engine.dispose()


def test_new_tiktok_options_have_no_default_mode(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "unscheduled")
        _insert_tiktok_options(connection, publication_id)
        mode = connection.execute(
            text("SELECT mode FROM tiktok_publication_options")
        ).scalar_one()
    assert mode is None


@pytest.mark.parametrize("mode", ["DIRECT_POST", "INBOX_UPLOAD"])
def test_tiktok_options_accept_valid_modes(seeded_engine: Engine, mode: str) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "unscheduled")
        _insert_tiktok_options(connection, publication_id, mode=mode)


def test_tiktok_options_reject_unknown_modes(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "unscheduled")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_tiktok_options(connection, publication_id, mode="DRAFT")


@pytest.mark.parametrize("scheduled_at", [None, NOW])
def test_awaiting_user_action_is_accepted_without_published_at(
    seeded_engine: Engine, scheduled_at: str | None
) -> None:
    with seeded_engine.begin() as connection:
        _insert_publication_row(connection, "awaiting_user_action", scheduled_at)


def test_awaiting_user_action_rejects_published_at(seeded_engine: Engine) -> None:
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_publication_row(connection, "awaiting_user_action", published_at=NOW)


def test_awaiting_user_action_counts_as_active(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        _insert_publication_row(connection, "awaiting_user_action")
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_publication_row(connection, "unscheduled")


def _run_fixture(engine: Engine) -> tuple[int, int]:
    with engine.begin() as connection:
        publication_id = _insert_publication_row(connection, "publishing")
        _insert_attempt(connection, publication_id, stage="preparing")
        return _attempt_id(connection, publication_id), publication_id


@pytest.mark.parametrize(
    "values",
    [
        {"mode": None},
        {"mode": "DRAFT"},
        # Delivery to the inbox only exists in Upload to Inbox.
        {"phase": "delivered"},
        {"delivered_to_inbox_at": NOW},
        {"user_published_at": NOW},
        {"mode": "INBOX_UPLOAD", "public_post_count": -1},
    ],
)
def test_tiktok_run_0013_constraints(
    seeded_engine: Engine, values: dict[str, Any]
) -> None:
    attempt_id, publication_id = _run_fixture(seeded_engine)
    with pytest.raises(IntegrityError), seeded_engine.begin() as connection:
        _insert_tiktok_run(connection, attempt_id, publication_id, **values)


def test_tiktok_run_accepts_an_inbox_delivery(seeded_engine: Engine) -> None:
    attempt_id, publication_id = _run_fixture(seeded_engine)
    with seeded_engine.begin() as connection:
        _insert_tiktok_run(
            connection,
            attempt_id,
            publication_id,
            mode="INBOX_UPLOAD",
            phase="delivered",
            publish_id="v_inbox_file~v2-1.1",
            last_remote_status="SEND_TO_USER_INBOX",
            delivered_to_inbox_at=NOW,
            user_published_at=NOW,
            public_post_count=2,
        )


def test_migration_0013_downgrade_without_awaiting_publications(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    ids = _seed_0012_tiktok(db_path)
    run_migrations(db_path)

    command.downgrade(_alembic_config(db_path), "0012")

    engine = create_db_engine(db_path)
    inspector = inspect(engine)
    assert "mode" not in {
        c["name"] for c in inspector.get_columns("tiktok_publication_options")
    }
    assert not TIKTOK_RUN_COLUMNS_0013 & {
        c["name"] for c in inspector.get_columns("tiktok_publish_runs")
    }
    assert {
        ck["name"] for ck in inspector.get_check_constraints("tiktok_publish_runs")
    } == TIKTOK_RUN_CHECKS
    assert {
        ck["name"]
        for ck in inspector.get_check_constraints("tiktok_publication_options")
    } == TIKTOK_OPTIONS_CHECKS
    statuses = {
        row["id"]: row["status"]
        for row in _rows(engine, "SELECT id, status FROM publications")
    }
    assert statuses[ids["published"]] == "published"
    assert len(statuses) == 5
    assert len(_rows(engine, "SELECT * FROM tiktok_publish_runs")) == 1
    # The awaiting status is gone from the publication CHECKs.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_publication_for(connection, 4, "awaiting_user_action")
    assert "WHERE" in _active_index_sql(engine)
    engine.dispose()


def test_migration_0013_downgrade_fails_with_awaiting_publications(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    ids = _seed_0012_tiktok(db_path)
    run_migrations(db_path)
    # Start from 0013: later revisions are not part of this check.
    command.downgrade(_alembic_config(db_path), "0013")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE publications SET status = 'awaiting_user_action' WHERE id = :id"
            ),
            {"id": ids["unscheduled"]},
        )
    before = {
        table: _rows(engine, f"SELECT * FROM {table}")
        for table in (
            "publications",
            "tiktok_publication_options",
            "tiktok_publish_runs",
        )
    }
    schema_before = _rows(engine, "SELECT name, sql FROM sqlite_master ORDER BY name")
    engine.dispose()

    with pytest.raises(
        RuntimeError,
        match=r"Cannot downgrade: 1 publication\(s\) are awaiting user action in "
        r"TikTok; resolve them first\.",
    ):
        command.downgrade(_alembic_config(db_path), "0012")

    engine = create_db_engine(db_path)
    for table, rows in before.items():
        assert _rows(engine, f"SELECT * FROM {table}") == rows
    assert (
        _rows(engine, "SELECT name, sql FROM sqlite_master ORDER BY name")
        == schema_before
    )
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert version.scalar_one() == "0013"
    engine.dispose()


# --- 0015: content metadata sanitization -------------------------------------------


def test_migration_0015_metadata_status(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0014")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    row = _rows(engine, "SELECT * FROM contents")[0]
    assert row["metadata_status"] == "unknown"
    assert row["sanitized_storage_path"] is None
    # A sanitized content must carry the whole clean copy.
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("UPDATE contents SET metadata_status = 'sanitized' WHERE id = 1")
        )
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0014")
    engine = create_db_engine(db_path)
    columns = {column["name"] for column in inspect(engine).get_columns("contents")}
    assert "metadata_status" not in columns
    assert not {c for c in columns if c.startswith("sanitized")}
    assert len(_rows(engine, "SELECT * FROM contents")) == 1
    engine.dispose()


# --- 0017: optional account handle (provisional accounts) ---------------------------


def _insert_account(connection: Connection, handle: str | None) -> None:
    connection.execute(
        text(
            "INSERT INTO accounts (project_id, platform, handle, handle_key, "
            "is_active, created_at, updated_at) VALUES (1, 'youtube', :handle, "
            ":key, 1, '2026-10-17 10:00:00', '2026-10-17 10:00:00')"
        ),
        {"handle": handle, "key": handle.lower() if handle else None},
    )


def test_migration_0017_keeps_legacy_accounts_and_allows_null_handles(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0016")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id, name, name_key, is_active, created_at, "
                "updated_at) VALUES (1, 'Cyber', 'cyber', 1, '2026-10-17 10:00:00', "
                "'2026-10-17 10:00:00')"
            )
        )
        _insert_account(connection, "Legacy")
    engine.dispose()

    command.upgrade(_alembic_config(db_path), "0017")

    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_account(connection, None)
        _insert_account(connection, None)  # NULLs never collide
    assert _rows(engine, "SELECT handle, handle_key FROM accounts ORDER BY id") == [
        {"handle": "Legacy", "handle_key": "legacy"},
        {"handle": None, "handle_key": None},
        {"handle": None, "handle_key": None},
    ]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_account(connection, "LEGACY")  # unique key still holds
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts (project_id, platform, handle, handle_key, "
                "is_active, created_at, updated_at) VALUES (1, 'x', 'half', NULL, 1, "
                "'2026-10-17 10:00:00', '2026-10-17 10:00:00')"
            )
        )  # handle and handle_key are NULL together or not at all
    engine.dispose()

    # Downgrade refuses while provisional accounts exist, and changes nothing.
    with pytest.raises(RuntimeError, match=r"2 account\(s\) have no handle yet"):
        command.downgrade(_alembic_config(db_path), "0016")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM accounts WHERE handle IS NULL"))
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0016")

    engine = create_db_engine(db_path)
    columns = {c["name"]: c for c in inspect(engine).get_columns("accounts")}
    assert columns["handle"]["nullable"] is False
    assert columns["handle_key"]["nullable"] is False
    assert _rows(engine, "SELECT handle FROM accounts") == [{"handle": "Legacy"}]
    engine.dispose()


def test_migration_0018_adds_auth_tables_to_a_pre_020_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0017")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id, name, name_key, is_active, created_at, "
                "updated_at) VALUES (1, 'Cyber', 'cyber', 1, '2026-10-22 10:00:00', "
                "'2026-10-22 10:00:00')"
            )
        )
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    assert _rows(engine, "SELECT name FROM projects") == [{"name": "Cyber"}]
    # No password yet: `set-password` sets it.
    assert _rows(engine, "SELECT * FROM installation_auth") == []
    assert _rows(engine, "SELECT * FROM auth_sessions") == []
    columns = {c["name"] for c in inspect(engine).get_columns("auth_sessions")}
    assert columns == {"token_hash", "created_at", "last_seen_at", "expires_at"}
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO installation_auth VALUES (1, 'scrypt$x', "
                "'2026-10-22 10:00:00')"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO installation_auth VALUES (2, 'scrypt$y', "
                "'2026-10-22 10:00:00')"
            )
        )  # a single row
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0017")
    engine = create_db_engine(db_path)
    tables = set(inspect(engine).get_table_names())
    assert not {"installation_auth", "auth_sessions"} & tables
    engine.dispose()


# --- 0019: deletion and Library folders (Feature 021) -------------------------------

RECREATED_0019 = (
    "projects",
    "accounts",
    "distribution_presets",
    "contents",
    "publications",
    "temporary_media_objects",
)
NEVER_REUSED_0019 = (
    "projects",
    "accounts",
    "distribution_presets",
    "contents",
    "publications",
    "library_folders",
)
SEEDED_0019 = (
    "projects",
    "accounts",
    "distribution_presets",
    "distribution_preset_accounts",
    "contents",
    "publications",
    "publication_attempts",
    "temporary_media_objects",
    "youtube_connections",
)


def _seed_0018(db_path: Path) -> None:
    """At 0018: two projects (the newest one empty), accounts, media with and
    without a clean copy, posts in several states, an attempt with a temporary
    object, a preset, a connection and two TikTok orphans."""
    command.upgrade(_alembic_config(db_path), "0018")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_tiktok_account(connection, 2)
        connection.execute(
            text(
                "INSERT INTO projects (id, name, name_key, is_active, created_at, "
                "updated_at) VALUES (3, 'Empty', 'empty', 1, :now, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO contents (id, project_id, media_type, media_format, "
                "storage_path, original_filename, checksum, size_bytes, hashtags, "
                "created_at, updated_at, metadata_status, sanitized_storage_path, "
                "sanitized_checksum, sanitized_size_bytes, sanitized_at) VALUES (2, "
                "1, 'image', 'png', 'projects/1/b.png', 'b.png', 'def', 3, '[]', "
                ":now, :now, 'sanitized', 'projects/1/b.clean.png', 'ghi', 2, :now)"
            ),
            {"now": NOW},
        )
        _insert_publication_for(connection, 1, "unscheduled")
        published = _insert_publication_for(connection, 2, "published", NOW)
        _insert_publication_for(connection, 2, "cancelled")
        _insert_attempt(
            connection,
            published,
            status="succeeded",
            stage="done",
            finished_at=NOW,
            bytes_sent=10,
        )
        connection.execute(
            text(
                "INSERT INTO temporary_media_objects (provider, object_key, "
                "attempt_id, content_type, size_bytes, created_at) VALUES ('s3', "
                "'key/1.png', :attempt_id, 'image/png', 3, :now)"
            ),
            {"attempt_id": _attempt_id(connection, published), "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO distribution_presets (id, project_id, name, name_key, "
                "created_at, updated_at) VALUES (1, 1, 'All', 'all', :now, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(
            text("INSERT INTO distribution_preset_accounts VALUES (1, 1), (1, 2)")
        )
        _insert_connection(connection)
        for ref, account_id in (("orphan-1", 2), ("orphan-2", None)):
            connection.execute(
                text(
                    "INSERT INTO tiktok_credential_orphans (credential_ref, "
                    "account_id, created_at) VALUES (:ref, :account_id, :now)"
                ),
                {"ref": ref, "account_id": account_id, "now": NOW},
            )
    engine.dispose()


def _table_shape(engine: Engine, table: str) -> dict[str, Any]:
    """Everything a rebuild could silently lose, as the inspector sees it."""
    inspector = inspect(engine)
    return {
        "columns": {
            column["name"]: (
                str(column["type"]),
                column["nullable"],
                column["default"],
                column.get("primary_key"),
            )
            for column in inspector.get_columns(table)
        },
        "checks": sorted(
            (check["name"], check["sqltext"])
            for check in inspector.get_check_constraints(table)
        ),
        "uniques": sorted(
            (unique["name"], tuple(unique["column_names"]))
            for unique in inspector.get_unique_constraints(table)
        ),
        "foreign_keys": sorted(
            (
                fk["name"],
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                fk["options"].get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table)
        ),
        "indexes": sorted(
            (index["name"], tuple(index["column_names"]), bool(index["unique"]))
            for index in inspector.get_indexes(table)
        ),
    }


def _index_sql(engine: Engine) -> dict[str, str]:
    return {
        row["name"]: row["sql"]
        for row in _rows(
            engine,
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' "
            "AND sql IS NOT NULL",
        )
    }


def test_migration_0019_keeps_every_row_id_and_constraint(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    _seed_0018(db_path)
    engine = create_db_engine(db_path)
    rows_before = {
        table: _rows(engine, f"SELECT * FROM {table} ORDER BY 1, 2")
        for table in SEEDED_0019
    }
    shapes_before = {table: _table_shape(engine, table) for table in RECREATED_0019}
    indexes_before = _index_sql(engine)
    engine.dispose()

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    for table in SEEDED_0019:
        after = _rows(engine, f"SELECT * FROM {table} ORDER BY 1, 2")
        if table == "contents":
            # Every pre-021 media item lands in Unsorted.
            assert {row.pop("folder_id") for row in after} == {None}
        assert after == rows_before[table], table
    # Rebuilt tables keep every column, default, check, unique, key and index.
    for table in RECREATED_0019:
        shape = _table_shape(engine, table)
        expected = shapes_before[table]
        if table == "contents":
            assert shape["columns"].pop("folder_id") == ("INTEGER", True, None, 0)
            assert ("ix_contents_folder_id", ("folder_id",), False) in shape["indexes"]
            shape["indexes"].remove(("ix_contents_folder_id", ("folder_id",), False))
            assert (
                "fk_contents_folder_id_library_folders",
                ("folder_id", "project_id"),
                "library_folders",
                ("id", "project_id"),
                "RESTRICT",
            ) in shape["foreign_keys"]
            shape["foreign_keys"] = [
                fk for fk in shape["foreign_keys"] if fk[2] != "library_folders"
            ]
        if table == "temporary_media_objects":
            assert shape["columns"]["attempt_id"][1] is True
            expected["columns"]["attempt_id"] = shape["columns"]["attempt_id"]
        assert shape == expected, table
    # Partial indexes keep their WHERE clause (batch rebuilds drop it).
    indexes_after = _index_sql(engine)
    for name, sql in indexes_before.items():
        assert indexes_after[name] == sql, name
    assert (
        "WHERE status NOT IN" in indexes_after["uq_publications_active_content_account"]
    )
    assert "WHERE parent_id IS NULL" in indexes_after["uq_library_folders_root_name"]
    assert (
        "WHERE parent_id IS NOT NULL" in indexes_after["uq_library_folders_child_name"]
    )
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
    engine.dispose()


def test_migration_0019_moves_tiktok_orphans_to_the_generic_queue(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    _seed_0018(db_path)

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    assert "tiktok_credential_orphans" not in inspect(engine).get_table_names()
    assert _rows(
        engine,
        "SELECT credential_ref, platform, account_id, created_at "
        "FROM pending_credential_deletions ORDER BY credential_ref",
    ) == [
        {
            "credential_ref": "orphan-1",
            "platform": "tiktok",
            "account_id": 2,
            "created_at": NOW,
        },
        {
            "credential_ref": "orphan-2",
            "platform": "tiktok",
            "account_id": None,
            "created_at": NOW,
        },
    ]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO pending_credential_deletions VALUES "
                "('ref-x', 'x', NULL, :now)"
            ),
            {"now": NOW},
        )  # only platforms with connections
    engine.dispose()


def test_migration_0019_ids_are_never_reused(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    _seed_0018(db_path)

    run_migrations(db_path)

    engine = create_db_engine(db_path)
    sql = {
        row["name"]: row["sql"]
        for row in _rows(engine, "SELECT name, sql FROM sqlite_master")
    }
    for table in NEVER_REUSED_0019:
        assert "AUTOINCREMENT" in sql[table], table
    # Internal tables keep plain rowids.
    assert "AUTOINCREMENT" not in sql["publication_attempts"]
    assert "AUTOINCREMENT" not in sql["youtube_connections"]
    sequence = {
        row["name"]: row["seq"]
        for row in _rows(engine, "SELECT name, seq FROM sqlite_sequence")
    }
    for table in ("projects", "accounts", "distribution_presets", "contents"):
        maximum = _rows(engine, f"SELECT MAX(id) AS id FROM {table}")[0]["id"]
        assert sequence[table] == maximum, table
    assert sequence["publications"] == 3

    with engine.begin() as connection:
        # The newest project (empty) and post are deleted, then new ones created.
        connection.execute(text("DELETE FROM projects WHERE id = 3"))
        connection.execute(text("DELETE FROM publications WHERE id = 3"))
        connection.execute(
            text(
                "INSERT INTO projects (name, name_key, is_active, created_at, "
                "updated_at) VALUES ('New', 'new', 1, :now, :now)"
            ),
            {"now": NOW},
        )
        new_post = _insert_publication_for(connection, 2, "cancelled")
    assert _rows(engine, "SELECT MAX(id) AS id FROM projects")[0]["id"] == 4
    assert new_post == 4
    engine.dispose()


def _folder(
    connection: Connection,
    name_key: str,
    *,
    project_id: int = 1,
    parent_id: int | None = None,
    depth: int = 1,
) -> int:
    result = connection.execute(
        text(
            "INSERT INTO library_folders (project_id, parent_id, name, name_key, "
            "depth, created_at, updated_at) VALUES (:project_id, :parent_id, "
            ":name, :name_key, :depth, :now, :now)"
        ),
        {
            "project_id": project_id,
            "parent_id": parent_id,
            "name": name_key.upper(),
            "name_key": name_key,
            "depth": depth,
            "now": NOW,
        },
    )
    row_id = result.lastrowid
    assert row_id is not None
    return row_id


@pytest.fixture
def folders_engine(seeded_engine: Engine) -> Engine:
    with seeded_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO projects (id, name, name_key, is_active, created_at, "
                "updated_at) VALUES (2, 'Other', 'other', 1, :now, :now)"
            ),
            {"now": NOW},
        )
    return seeded_engine


def test_folders_stay_in_their_project(folders_engine: Engine) -> None:
    with folders_engine.begin() as connection:
        root = _folder(connection, "lux")
        other_root = _folder(connection, "lux", project_id=2)
        _folder(connection, "mfa", parent_id=root, depth=2)
        connection.execute(
            text("UPDATE contents SET folder_id = :id WHERE id = 1"), {"id": root}
        )
    # A parent of another project.
    with pytest.raises(IntegrityError), folders_engine.begin() as connection:
        _folder(connection, "x", project_id=2, parent_id=root, depth=2)
    with pytest.raises(IntegrityError), folders_engine.begin() as connection:
        _folder(connection, "x", parent_id=999, depth=2)
    # Media in a folder of another project.
    with pytest.raises(IntegrityError), folders_engine.begin() as connection:
        connection.execute(
            text("UPDATE contents SET folder_id = :id WHERE id = 1"),
            {"id": other_root},
        )
    # A folder holding media or children cannot just disappear.
    with pytest.raises(IntegrityError), folders_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM library_folders WHERE id = :id"), {"id": root}
        )


def test_folder_names_are_unique_among_siblings(folders_engine: Engine) -> None:
    with folders_engine.begin() as connection:
        root = _folder(connection, "lux")
        other = _folder(connection, "mfa")
        _folder(connection, "art", parent_id=root, depth=2)
        # The same name elsewhere is fine: another parent, another project.
        _folder(connection, "art", parent_id=other, depth=2)
        _folder(connection, "art")
        _folder(connection, "lux", project_id=2)
    with pytest.raises(IntegrityError), folders_engine.begin() as connection:
        _folder(connection, "lux")
    with pytest.raises(IntegrityError), folders_engine.begin() as connection:
        _folder(connection, "art", parent_id=root, depth=2)


@pytest.mark.parametrize(
    ("parent", "depth"),
    [(None, 2), ("parent", 1), ("parent", 6), (None, 0)],
)
def test_folder_depth_constraints(
    folders_engine: Engine, parent: str | None, depth: int
) -> None:
    with folders_engine.begin() as connection:
        parent_id = _folder(connection, "lux") if parent else None
    with pytest.raises(IntegrityError), folders_engine.begin() as connection:
        _folder(connection, "child", parent_id=parent_id, depth=depth)


def test_folders_nest_up_to_five_levels(folders_engine: Engine) -> None:
    with folders_engine.begin() as connection:
        parent_id: int | None = None
        for depth in range(1, 6):
            parent_id = _folder(
                connection, f"l{depth}", parent_id=parent_id, depth=depth
            )
    assert _rows(folders_engine, "SELECT MAX(depth) AS depth FROM library_folders") == [
        {"depth": 5}
    ]


def test_migration_0019_server_defaults_still_apply(seeded_engine: Engine) -> None:
    with seeded_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO contents (project_id, media_type, media_format, "
                "storage_path, original_filename, checksum, size_bytes, hashtags, "
                "created_at, updated_at) VALUES (1, 'image', 'png', "
                "'projects/1/c.png', 'c.png', 'zzz', 3, '[]', :now, :now)"
            ),
            {"now": NOW},
        )
        _insert_publication(connection, "unscheduled")
    row = _rows(
        seeded_engine,
        "SELECT metadata_status, folder_id FROM contents WHERE checksum = 'zzz'",
    )
    assert row == [{"metadata_status": "unknown", "folder_id": None}]
    assert _rows(seeded_engine, "SELECT auto_publish_enabled FROM publications") == [
        {"auto_publish_enabled": 0}
    ]


def test_migration_0019_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    _seed_0018(db_path)
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        root = _folder(connection, "lux")
        connection.execute(
            text("UPDATE contents SET folder_id = :id WHERE id = 1"), {"id": root}
        )
        connection.execute(
            text(
                "INSERT INTO pending_credential_deletions VALUES "
                "('yt-ref', 'youtube', 1, :now)"
            ),
            {"now": NOW},
        )
        connection.execute(text("UPDATE temporary_media_objects SET attempt_id = NULL"))
    engine.dispose()

    # Refused while a temporary object belongs to a deleted post; nothing changes.
    with pytest.raises(RuntimeError, match="temporary media object"):
        command.downgrade(_alembic_config(db_path), "0018")
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        connection.execute(text("UPDATE temporary_media_objects SET attempt_id = 1"))
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0018")

    engine = create_db_engine(db_path)
    tables = set(inspect(engine).get_table_names())
    assert (
        not {
            "library_folders",
            "pending_file_deletions",
            "pending_credential_deletions",
        }
        & tables
    )
    columns = {c["name"]: c for c in inspect(engine).get_columns("contents")}
    assert "folder_id" not in columns
    tmo = {c["name"]: c for c in inspect(engine).get_columns("temporary_media_objects")}
    assert tmo["attempt_id"]["nullable"] is False
    # Only TikTok rows go back to the old table.
    assert [
        row["credential_ref"]
        for row in _rows(
            engine,
            "SELECT credential_ref FROM tiktok_credential_orphans ORDER BY 1",
        )
    ] == ["orphan-1", "orphan-2"]
    assert len(_rows(engine, "SELECT id FROM contents")) == 2
    engine.dispose()

    run_migrations(db_path)  # and up again
    engine = create_db_engine(db_path)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
