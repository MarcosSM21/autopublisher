"""Migration 0020: analytics snapshots, values and refresh state (Feature 027 T013)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import create_db_engine, run_migrations
from tests.test_migrations import (
    _alembic_config,
    _insert_project_account_content,
    _insert_publication_row,
    _rows,
)

TABLES = {"metric_snapshots", "metric_values", "publication_metric_states"}
NOW = "2026-10-29 10:00:00"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        _insert_project_account_content(connection)
        _insert_publication_row(connection, "published", published_at=NOW)
    yield engine
    engine.dispose()


def _snapshot(connection: Connection, **overrides: Any) -> int:
    values = {
        "publication_id": 1,
        "platform": "instagram",
        "remote_id": "IG-1",
        "captured_at": NOW,
        "source": "instagram.media:fields",
        "trigger": "automatic",
        **overrides,
    }
    result = connection.execute(
        text(
            "INSERT INTO metric_snapshots (publication_id, platform, remote_id, "
            "captured_at, source, trigger) VALUES (:publication_id, :platform, "
            ":remote_id, :captured_at, :source, :trigger)"
        ),
        values,
    )
    assert result.lastrowid is not None
    return result.lastrowid


def _value(connection: Connection, snapshot_id: int, **overrides: Any) -> None:
    values = {
        "snapshot_id": snapshot_id,
        "metric_name": "like_count",
        "value": 0,
        "origin": "public_counter",
        **overrides,
    }
    connection.execute(
        text(
            "INSERT INTO metric_values (snapshot_id, metric_name, value, origin) "
            "VALUES (:snapshot_id, :metric_name, :value, :origin)"
        ),
        values,
    )


def _state(connection: Connection, status: str) -> None:
    connection.execute(
        text(
            "INSERT INTO publication_metric_states (publication_id, status) "
            "VALUES (1, :status)"
        ),
        {"status": status},
    )


def test_upgrade_creates_the_tables_and_downgrade_removes_them(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app.db"
    command.upgrade(_alembic_config(db_path), "0019")
    command.upgrade(_alembic_config(db_path), "0020")
    engine = create_db_engine(db_path)
    assert TABLES <= set(inspect(engine).get_table_names())
    indexes = {i["name"] for i in inspect(engine).get_indexes("metric_snapshots")}
    assert "ix_metric_snapshots_publication_id_captured_at" in indexes
    engine.dispose()

    command.downgrade(_alembic_config(db_path), "0019")

    engine = create_db_engine(db_path)
    assert not TABLES & set(inspect(engine).get_table_names())
    engine.dispose()
    command.upgrade(_alembic_config(db_path), "0020")  # and up again


def test_valid_rows_are_accepted_and_zero_is_a_value(engine: Engine) -> None:
    with engine.begin() as connection:
        snapshot = _snapshot(connection, trigger="manual")
        _value(connection, snapshot, value=0)
        _value(connection, snapshot, metric_name="views", value=7, origin="insight")
        _state(connection, "ok")
    assert _rows(engine, "SELECT metric_name, value FROM metric_values ORDER BY 1") == [
        {"metric_name": "like_count", "value": 0},
        {"metric_name": "views", "value": 7},
    ]
    assert _rows(engine, "SELECT failure_count FROM publication_metric_states") == [
        {"failure_count": 0}
    ]


@pytest.mark.parametrize("status", ["error", "not_linked", "", "OK"])
def test_invalid_refresh_status_is_rejected(engine: Engine, status: str) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _state(connection, status)


@pytest.mark.parametrize(
    ("column", "value"),
    [("value", -1), ("value", None), ("origin", "scraped"), ("origin", None)],
)
def test_invalid_metric_value_is_rejected(
    engine: Engine, column: str, value: object
) -> None:
    with engine.begin() as connection:
        snapshot = _snapshot(connection)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _value(connection, snapshot, **{column: value})


def test_invalid_trigger_is_rejected(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _snapshot(connection, trigger="scheduled")


def test_a_metric_appears_once_per_snapshot(engine: Engine) -> None:
    with engine.begin() as connection:
        snapshot = _snapshot(connection)
        _value(connection, snapshot)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _value(connection, snapshot, value=3)


def test_snapshot_ids_are_never_reused(engine: Engine) -> None:
    with engine.begin() as connection:
        first = _snapshot(connection)
        connection.execute(text("DELETE FROM metric_snapshots"))
        assert _snapshot(connection) == first + 1


def test_rows_need_an_existing_publication(engine: Engine) -> None:
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _snapshot(connection, publication_id=99)
