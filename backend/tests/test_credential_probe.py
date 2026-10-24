"""Non-interactive credential-store probe (Feature 020 T019, research §18).

`secretstorage` is replaced by a fake module whose prompt-capable functions fail the
test if called: the probe must never create, unlock or read anything.
"""

import sys
import types
from collections.abc import Iterator
from typing import Any

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError
from secretstorage import exceptions as secret_exceptions

from app import credential_store
from app.credential_store import CredentialStoreProbe, probe_credential_store


def _backend(module: str) -> KeyringBackend:
    body = {
        name: _forbidden(f"backend.{name}")
        for name in ("get_password", "set_password", "delete_password")
    }
    cls = type("Keyring", (KeyringBackend,), {"priority": 1, **body})
    cls.__module__ = module
    cls.__qualname__ = "Keyring"
    return cls()  # type: ignore[no-any-return]


def _forbidden(name: str) -> Any:
    def call(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"the probe must never call {name}")

    return call


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeSecretStorage:
    """Behaviour of the default collection: missing, locked, unlocked or failing."""

    def __init__(self, collection: str = "unlocked", bus: bool = True) -> None:
        self.collection_state = collection
        self.bus = bus
        self.connections: list[_Connection] = []
        self.module = types.ModuleType("secretstorage")
        self.module.dbus_init = self.dbus_init  # type: ignore[attr-defined]
        self.module.Collection = self.collection  # type: ignore[attr-defined]
        for name in (
            "get_default_collection",
            "create_collection",
            "get_all_collections",
            "get_any_collection",
            "search_items",
        ):
            setattr(self.module, name, _forbidden(f"secretstorage.{name}"))

    def dbus_init(self) -> _Connection:
        if not self.bus:
            raise secret_exceptions.SecretServiceNotAvailableException("no bus")
        connection = _Connection()
        self.connections.append(connection)
        return connection

    def collection(self, connection: _Connection, *args: Any) -> Any:
        assert not args, "only the existing default alias may be opened"
        if self.collection_state == "missing":
            raise secret_exceptions.ItemNotFoundException("no default alias")
        state = self.collection_state

        class Collection:
            unlock = _forbidden("Collection.unlock")
            get_all_items = _forbidden("Collection.get_all_items")
            search_items = _forbidden("Collection.search_items")
            create_item = _forbidden("Collection.create_item")

            def is_locked(self) -> bool:
                if state == "dbus-error":
                    raise RuntimeError("org.freedesktop.DBus.Error.NoReply")
                return state == "locked"

        return Collection()


@pytest.fixture(autouse=True)
def no_secret_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("get_password", "set_password", "get_credential"):
        monkeypatch.setattr(keyring, name, _forbidden(f"keyring.{name}"))


def _use(monkeypatch: pytest.MonkeyPatch, backend: KeyringBackend) -> None:
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)


def _secret_service(
    monkeypatch: pytest.MonkeyPatch, fake: _FakeSecretStorage
) -> _FakeSecretStorage:
    _use(monkeypatch, _backend("keyring.backends.SecretService"))
    monkeypatch.setitem(sys.modules, "secretstorage", fake.module)
    return fake


@pytest.mark.parametrize(
    ("collection", "expected"),
    [
        ("unlocked", "available"),
        ("locked", "locked"),
        ("missing", "unknown"),
        ("dbus-error", "unavailable"),
    ],
)
def test_secret_service_states(
    monkeypatch: pytest.MonkeyPatch, collection: str, expected: str
) -> None:
    fake = _secret_service(monkeypatch, _FakeSecretStorage(collection))
    assert probe_credential_store() == expected
    assert fake.connections and all(c.closed for c in fake.connections)


def test_no_session_bus_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _secret_service(monkeypatch, _FakeSecretStorage(bus=False))
    assert probe_credential_store() == "unavailable"


def test_backend_not_allowed_is_unavailable() -> None:
    # conftest installs keyring's failing backend, which is not allow-listed.
    assert probe_credential_store() == "unavailable"


def test_keyring_error_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> KeyringBackend:
        raise KeyringError("no backend")

    monkeypatch.setattr(keyring, "get_keyring", broken)
    assert probe_credential_store() == "unavailable"


@pytest.mark.parametrize(
    "module",
    [
        "keyring.backends.libsecret",
        "keyring.backends.macOS",
    ],
)
def test_other_allowed_backends_are_unknown(
    monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    _use(monkeypatch, _backend(module))
    monkeypatch.setitem(sys.modules, "secretstorage", None)  # never imported
    assert probe_credential_store() == "unknown"


def test_chainer_with_secret_service_is_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chainer = ChainerBackend.__new__(ChainerBackend)
    backends = [
        _backend("keyring.backends.SecretService"),
        _backend("keyring.backends.libsecret"),
    ]
    monkeypatch.setattr(ChainerBackend, "backends", property(lambda self: backends))
    _use(monkeypatch, chainer)
    monkeypatch.setitem(
        sys.modules, "secretstorage", _FakeSecretStorage("locked").module
    )
    assert probe_credential_store() == "locked"


def test_without_secretstorage_the_state_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _backend("keyring.backends.SecretService"))
    monkeypatch.setitem(sys.modules, "secretstorage", None)
    assert probe_credential_store() == "unknown"


def test_results_are_cached_for_a_minute() -> None:
    now = [0.0]
    results: Iterator[credential_store.ProbeStatus] = iter(["unknown", "locked"])
    calls: list[int] = []

    def check() -> credential_store.ProbeStatus:
        calls.append(1)
        return next(results)

    probe = CredentialStoreProbe(check=check, monotonic=lambda: now[0])
    assert probe.status() == "unknown"  # never turned into "available"
    now[0] = 59.0
    assert probe.status() == "unknown"
    now[0] = 60.0
    assert probe.status() == "locked"
    assert len(calls) == 2
