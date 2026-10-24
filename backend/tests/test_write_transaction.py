"""`write_transaction` (Feature 021, research §4): its own session, `BEGIN IMMEDIATE`
first, a single SQLite writer at a time, and nothing left locked after a rollback.

Concurrency uses events and SQLite's own lock errors (`timeout=0`), never sleeps."""

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db import create_db_engine, database_url, run_migrations, write_transaction


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    run_migrations(path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, v TEXT)")
        connection.execute("INSERT INTO counter VALUES (1, '')")
    return path


@pytest.fixture
def engine(db_file: Path) -> Iterator[Engine]:
    engine = create_db_engine(db_file)
    with engine.connect():  # first connect: dialect initialisation out of the way
        pass
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def _value(engine: Engine) -> str:
    with engine.connect() as connection:
        value: str = connection.execute(
            text("SELECT v FROM counter WHERE id = 1")
        ).scalar_one()
    return value


def _try_writer_lock(db_file: Path) -> bool:
    """Whether another connection gets the writer lock right now (no waiting)."""
    connection = sqlite3.connect(db_file, timeout=0, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as error:
        assert "locked" in str(error)
        return False
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()
    return True


def test_begin_immediate_is_the_first_statement(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    with write_transaction(factory) as session:
        session.execute(text("UPDATE counter SET v = 'x' WHERE id = 1"))
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    event.remove(engine, "before_cursor_execute", record)

    assert statements[0] == "BEGIN IMMEDIATE"
    assert _value(engine) == "x"


def test_a_second_writer_waits_for_the_commit_and_sees_it(
    db_file: Path, engine: Engine, factory: sessionmaker[Session]
) -> None:
    writer_ready = threading.Event()
    writer_done = threading.Event()
    errors: list[BaseException] = []
    writer_engine = create_db_engine(db_file)

    def second_writer() -> None:
        # A plain UPDATE + commit, like the scheduler's claim.
        try:
            with writer_engine.begin() as connection:
                writer_ready.set()
                connection.execute(text("UPDATE counter SET v = v || 'B' WHERE id = 1"))
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)
        finally:
            writer_ready.set()
            writer_done.set()

    with write_transaction(factory) as session:
        # Everything read inside is the committed state, under the writer lock.
        assert session.execute(text("SELECT v FROM counter")).scalar_one() == ""
        assert not _try_writer_lock(db_file)
        thread = threading.Thread(target=second_writer)
        thread.start()
        writer_ready.wait()
        session.execute(text("UPDATE counter SET v = v || 'A' WHERE id = 1"))
        # The second writer cannot have committed while this transaction is open.
        assert not writer_done.is_set()
        assert not _try_writer_lock(db_file)
    thread.join()
    writer_engine.dispose()

    assert errors == []
    # B ran after A's commit and built on it.
    assert _value(engine) == "AB"


def test_a_transaction_reads_what_an_earlier_writer_committed(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE counter SET v = 'committed' WHERE id = 1"))

    with write_transaction(factory) as session:
        assert session.execute(text("SELECT v FROM counter")).scalar_one() == (
            "committed"
        )


def test_an_exception_rolls_back_and_releases_the_writer_lock(
    db_file: Path, engine: Engine, factory: sessionmaker[Session]
) -> None:
    with (
        pytest.raises(ValueError, match="boom"),
        write_transaction(factory) as session,
    ):
        session.execute(text("UPDATE counter SET v = 'lost' WHERE id = 1"))
        assert not _try_writer_lock(db_file)
        raise ValueError("boom")

    assert _value(engine) == ""
    # The next writer gets the lock immediately, without waiting.
    assert _try_writer_lock(db_file)
    with write_transaction(factory) as session:
        session.execute(text("UPDATE counter SET v = 'next' WHERE id = 1"))
    assert _value(engine) == "next"


def test_a_connection_with_an_open_transaction_is_an_error(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("UPDATE counter SET v = 'pending' WHERE id = 1"))
        bound = sessionmaker(bind=connection)

        with pytest.raises(RuntimeError, match="open transaction"):
            with write_transaction(bound):
                pytest.fail("never reached")  # pragma: no cover

        # No defensive rollback: the caller's pending write is still there.
        assert connection.connection.driver_connection.in_transaction  # type: ignore[union-attr]
        assert (
            connection.execute(text("SELECT v FROM counter")).scalar_one() == "pending"
        )
        connection.rollback()


def test_a_request_session_with_completed_reads_does_not_block(
    engine: Engine, factory: sessionmaker[Session]
) -> None:
    """Usage rule: the request session may have read, but has no pending writes."""
    with factory() as request_session:
        assert request_session.execute(text("SELECT v FROM counter")).scalar_one() == ""
        with write_transaction(factory) as session:
            session.execute(text("UPDATE counter SET v = 'written' WHERE id = 1"))
        request_session.expire_all()
        assert request_session.execute(text("SELECT v FROM counter")).scalar_one() == (
            "written"
        )


def test_pending_writes_in_another_session_of_the_same_thread_would_block(
    db_file: Path,
) -> None:
    """Why the rule exists: with uncommitted writes elsewhere the writer lock never
    comes (shown with `timeout=0` instead of waiting for SQLite's 5 s)."""
    engine = create_engine(database_url(db_file), connect_args={"timeout": 0})
    factory = sessionmaker(engine)
    with factory() as request_session:
        request_session.execute(text("UPDATE counter SET v = 'dirty' WHERE id = 1"))
        with pytest.raises(OperationalError, match="locked"):
            with write_transaction(factory):
                pass  # pragma: no cover
        request_session.rollback()
    engine.dispose()
