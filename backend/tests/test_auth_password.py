"""Installation password hashing and storage (Feature 020 T010, research §10)."""

import base64
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import auth
from app.db import create_db_engine, run_migrations
from app.models import AuthSession, InstallationAuth

NOW = datetime(2026, 10, 22, 10, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


def test_hash_uses_the_approved_parameters_and_format() -> None:
    encoded = auth.hash_password(PASSWORD)
    algorithm, n, r, p, salt, key = encoded.split("$")
    assert (algorithm, n, r, p) == ("scrypt", str(2**15), "8", "1")
    assert len(base64.b64decode(salt)) == 16
    assert len(base64.b64decode(key)) == 32
    assert PASSWORD not in encoded
    assert auth.verify_password(PASSWORD, encoded)
    assert not auth.needs_rehash(encoded)


@pytest.fixture(autouse=True)
def fast_scrypt(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the format test above pays the real cost.
    if request.node.name != "test_hash_uses_the_approved_parameters_and_format":
        monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


def test_round_trip_and_wrong_password() -> None:
    encoded = auth.hash_password(PASSWORD)
    assert auth.verify_password(PASSWORD, encoded)
    assert not auth.verify_password(PASSWORD + "!", encoded)
    assert not auth.verify_password("", encoded)


def test_salt_differs_for_the_same_password() -> None:
    first, second = auth.hash_password(PASSWORD), auth.hash_password(PASSWORD)
    assert first != second
    assert first.split("$")[4] != second.split("$")[4]


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "plain",
        "bcrypt$1$2$3$AAAA$BBBB",
        "scrypt$1024$8$1$AAAA",  # missing part
        "scrypt$1000$8$1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 44,  # n not a power of 2
        "scrypt$1024$0$1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 44,
        "scrypt$1024$8$1$not-base64!$" + "A" * 44,
        "scrypt$x$8$1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 44,
        f"scrypt${2**30}$8$1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 44,  # over maxmem
    ],
)
def test_malformed_hash_never_matches(encoded: str) -> None:
    assert not auth.verify_password(PASSWORD, encoded)
    assert auth.needs_rehash(encoded)


def test_rehash_when_parameters_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    old = auth.hash_password(PASSWORD)
    monkeypatch.setattr(auth, "SCRYPT_N", 2**11)
    assert auth.needs_rehash(old)
    assert auth.verify_password(PASSWORD, old)  # still verifies with its own params


@pytest.mark.parametrize(
    ("length", "ok"), [(0, False), (11, False), (12, True), (1024, True), (1025, False)]
)
def test_length_bounds(length: int, ok: bool) -> None:
    assert (auth.password_length_error("x" * length) is None) is ok


@pytest.fixture
def db(tmp_path: Path) -> Session:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    return sessionmaker(create_db_engine(db_path), expire_on_commit=False)()


def test_set_password_upserts_and_deletes_every_session(db: Session) -> None:
    auth.set_password(db, PASSWORD, NOW)
    first = auth.current_password_hash(db)
    assert first is not None and auth.verify_password(PASSWORD, first)
    for _ in range(3):
        assert auth.create_session(db, first, NOW) is not None

    auth.set_password(db, "another long password", NOW)

    row = db.scalars(select(InstallationAuth)).one()
    assert row.id == 1 and row.password_changed_at == NOW
    assert auth.verify_password("another long password", row.password_hash)
    assert not auth.verify_password(PASSWORD, row.password_hash)
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    # Only a hash is stored: never the password.
    assert PASSWORD not in row.password_hash
