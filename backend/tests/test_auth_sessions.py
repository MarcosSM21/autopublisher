"""Opaque browser sessions (Feature 020 T011, research §11)."""

import hashlib
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app import auth
from app.db import create_db_engine, run_migrations
from app.models import AuthSession
from tests.fakes import FakeClock

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "app.db"
    run_migrations(path)
    return path


@pytest.fixture
def db(db_path: Path) -> Iterator[Session]:
    engine = create_db_engine(db_path)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def verified(db: Session, clock: FakeClock) -> str:
    auth.set_password(db, PASSWORD, clock.now())
    stored = auth.current_password_hash(db)
    assert stored is not None
    return stored


def _row(db: Session, token: str) -> AuthSession | None:
    db.expire_all()
    return db.get(AuthSession, auth.hash_token(token))


def test_only_the_token_hash_is_stored(
    db: Session, verified: str, clock: FakeClock
) -> None:
    token = auth.create_session(db, verified, clock.now())
    assert token is not None and len(token) >= 43  # 256 bits, url-safe
    row = _row(db, token)
    assert row is not None
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.expires_at == row.created_at + timedelta(days=30)
    dump = "\n".join(db.connection().connection.iterdump())
    assert token not in dump


def test_idle_expiry_at_seven_days(
    db: Session, verified: str, clock: FakeClock
) -> None:
    token = auth.create_session(db, verified, clock.now())
    assert token is not None
    clock.advance(timedelta(days=7).total_seconds() - 1)
    assert auth.authenticate(db, token, clock.now())  # renews the idle deadline
    clock.advance(timedelta(days=7).total_seconds() - 1)
    assert auth.authenticate(db, token, clock.now())
    clock.advance(timedelta(days=7).total_seconds())
    assert not auth.authenticate(db, token, clock.now())
    assert _row(db, token) is None  # deleted once invalid


def test_activity_never_extends_the_absolute_limit(
    db: Session, verified: str, clock: FakeClock
) -> None:
    token = auth.create_session(db, verified, clock.now())
    assert token is not None
    created = clock.now()
    # Used every day: still valid until day 30, never after.
    for _ in range(29):
        clock.advance(timedelta(days=1).total_seconds())
        assert auth.authenticate(db, token, clock.now())
    row = _row(db, token)
    assert row is not None and row.expires_at == created + timedelta(days=30)
    clock.set(created + timedelta(days=30))
    assert not auth.authenticate(db, token, clock.now())


def test_touch_is_written_at_most_every_ten_minutes(
    db: Session, verified: str, clock: FakeClock
) -> None:
    token = auth.create_session(db, verified, clock.now())
    assert token is not None
    start = clock.now()
    clock.advance(9 * 60)
    assert auth.authenticate(db, token, clock.now())
    assert _row(db, token).last_seen_at == start  # type: ignore[union-attr]
    clock.advance(60)
    assert auth.authenticate(db, token, clock.now())
    assert _row(db, token).last_seen_at == clock.now()  # type: ignore[union-attr]


def test_unknown_token_is_invalid(db: Session, verified: str, clock: FakeClock) -> None:
    assert not auth.authenticate(db, "forged", clock.now())


def test_delete_session(db: Session, verified: str, clock: FakeClock) -> None:
    token = auth.create_session(db, verified, clock.now())
    other = auth.create_session(db, verified, clock.now())
    assert token and other
    auth.delete_session(db, token)
    assert not auth.authenticate(db, token, clock.now())
    assert auth.authenticate(db, other, clock.now())


def test_purge_and_cap(db: Session, verified: str, clock: FakeClock) -> None:
    stale = auth.create_session(db, verified, clock.now())
    clock.advance(timedelta(days=8).total_seconds())
    tokens = []
    for _ in range(auth.MAX_SESSIONS + 5):
        clock.advance(1)
        token = auth.create_session(db, verified, clock.now())
        assert token is not None
        tokens.append(token)
    assert db.scalar(select(func.count()).select_from(AuthSession)) == auth.MAX_SESSIONS
    assert _row(db, stale or "") is None
    # The least recently used ones were dropped; the newest survive.
    assert all(_row(db, token) is None for token in tokens[:5])
    assert all(_row(db, token) is not None for token in tokens[5:])


def test_session_is_refused_when_the_hash_changed(
    db: Session, verified: str, clock: FakeClock
) -> None:
    auth.set_password(db, "a different password", clock.now())
    assert auth.create_session(db, verified, clock.now()) is None
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_no_password_means_no_session(db: Session, clock: FakeClock) -> None:
    assert auth.create_session(db, "scrypt$anything", clock.now()) is None


def test_sessions_survive_a_new_engine(
    db_path: Path, verified: str, clock: FakeClock
) -> None:
    engine = create_db_engine(db_path)
    with sessionmaker(engine)() as first:
        token = auth.create_session(first, verified, clock.now())
    engine.dispose()
    engine = create_db_engine(db_path)  # like a restarted backend
    with sessionmaker(engine)() as second:
        assert token is not None and auth.authenticate(second, token, clock.now())
        stored = second.execute(text("SELECT token_hash FROM auth_sessions")).scalars()
        assert token not in list(stored)
    engine.dispose()


def test_cookie_attributes(clock: FakeClock) -> None:
    response = Response()
    now = clock.now()
    auth.set_session_cookie(response, "tok", now + timedelta(days=30), now)
    cookie = response.headers["set-cookie"]
    parts = {part.strip().split("=")[0].lower() for part in cookie.split(";")}
    assert cookie.startswith("autopublisher_session=tok;")
    assert "Max-Age=2592000" in cookie
    assert "HttpOnly" in cookie and "Path=/" in cookie
    assert "samesite=lax" in cookie.lower()
    assert not {"domain", "secure", "expires"} & parts

    cleared = Response()
    auth.clear_session_cookie(cleared)
    assert "Max-Age=0" in cleared.headers["set-cookie"]
