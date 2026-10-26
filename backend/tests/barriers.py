"""Deterministic concurrency helpers (Feature 021 delete tests, Feature 024
PATCH tests): threads and `threading.Event` barriers, never `sleep`."""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models import PublicationAttempt
from tests.fakes import FakePublisher

TIMEOUT = 10


class Background:
    """Run `call` in a thread; `result()` joins it and returns or re-raises."""

    def __init__(self, call: Callable[[], Any]) -> None:
        self._value: Any = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(call,), daemon=True)
        self._thread.start()

    def _run(self, call: Callable[[], Any]) -> None:
        try:
            self._value = call()
        except BaseException as error:  # noqa: BLE001 - re-raised in result()
            self._error = error

    def result(self) -> Any:
        self._thread.join(TIMEOUT)
        assert not self._thread.is_alive(), "background call did not finish"
        if self._error is not None:
            raise self._error
        return self._value


class Gate:
    """`reached` is set when the paused code arrives; it waits for `release`."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self._go = threading.Event()

    def pause(self) -> None:
        self.reached.set()
        assert self._go.wait(TIMEOUT), "gate never released"

    def wait_reached(self) -> None:
        assert self.reached.wait(TIMEOUT), "gate never reached"

    def release(self) -> None:
        self._go.set()


@contextmanager
def pause_before_commit(
    session_factory: sessionmaker[Session], when: Callable[[Session], bool]
) -> Iterator[Gate]:
    """Pause the first commit of a session of `session_factory` for which `when`
    is true, with its writes already executed (SQLite's writer lock held)."""
    gate = Gate()
    fired = threading.Event()

    def before_commit(session: Session) -> None:
        if not fired.is_set() and when(session):
            fired.set()
            gate.pause()

    event.listen(session_factory, "before_commit", before_commit)
    try:
        yield gate
    finally:
        gate.release()
        event.remove(session_factory, "before_commit", before_commit)


@contextmanager
def statement_reached(engine: Engine, prefix: str) -> Iterator[threading.Event]:
    """Set when a statement starting with `prefix` is about to run (before it
    waits for SQLite's writer lock)."""
    reached = threading.Event()

    def before(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if statement.startswith(prefix):
            reached.set()

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield reached
    finally:
        event.remove(engine, "before_cursor_execute", before)


@contextmanager
def pause_after_call(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str
) -> Iterator[Gate]:
    """Wrap `module.name`: its first call runs the original and then waits on the
    gate (later calls pass through). The gate is always released on exit."""
    gate = Gate()
    fired = threading.Event()
    original = getattr(module, name)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if not fired.is_set():
            fired.set()
            gate.pause()
        return result

    monkeypatch.setattr(module, name, wrapper)
    try:
        yield gate
    finally:
        gate.release()
        monkeypatch.setattr(module, name, original)


def pause_in_prepare(publisher: FakePublisher) -> Gate:
    """The preflight (`prepare`) of the first start waits on the gate."""
    gate = Gate()
    fired = threading.Event()

    def hook(_: int) -> None:
        if not fired.is_set():
            fired.set()
            gate.pause()

    publisher.prepare_hook = hook
    return gate


def is_claim(session: Session) -> bool:
    """The commit of a publication claim: its running attempt is pending."""
    return any(isinstance(item, PublicationAttempt) for item in session.new)
