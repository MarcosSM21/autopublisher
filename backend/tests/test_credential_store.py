from collections.abc import Callable
from typing import Any

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail, null
from keyring.backends.chainer import ChainerBackend
from keyring.errors import InitError, KeyringError, KeyringLocked, PasswordDeleteError

from app.credential_store import (
    CredentialStoreUnavailable,
    KeyringCredentialStore,
    ensure_secure_backend,
)

SECRET = "super-secret-token-value-123"


class MemoryBackend(KeyringBackend):
    """A keyring backend that keeps passwords in memory."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.passwords:
            raise PasswordDeleteError("No such password!")
        del self.passwords[(service, username)]


def _backend_named(module: str, name: str = "Keyring") -> type[MemoryBackend]:
    """A memory backend that looks like the real class `module.name`."""
    return type(name, (MemoryBackend,), {"__module__": module})


SecretService = _backend_named("keyring.backends.SecretService")
LibSecret = _backend_named("keyring.backends.libsecret")
KWallet = _backend_named("keyring.backends.kwallet", "DBusKeyring")
MacOS = _backend_named("keyring.backends.macOS")
WinVault = _backend_named("keyring.backends.Windows", "WinVaultKeyring")
Plaintext = _backend_named("keyrings.alt.file", "PlaintextKeyring")
Unknown = _backend_named("some_vendor.keyring", "Keyring")


def _chainer(*backends: KeyringBackend) -> ChainerBackend:
    chainer_class: Any = type(
        "ChainerBackend", (ChainerBackend,), {"backends": list(backends)}
    )
    chainer: ChainerBackend = chainer_class()
    return chainer


@pytest.mark.parametrize(
    "backend_class", [SecretService, LibSecret, KWallet, MacOS, WinVault]
)
def test_allow_listed_backends_round_trip(backend_class: type[MemoryBackend]) -> None:
    backend = backend_class()
    keyring.set_keyring(backend)
    store = KeyringCredentialStore()

    store.set("ref-1", SECRET)
    assert store.get("ref-1") == SECRET
    assert backend.passwords == {("autopublisher.youtube", "ref-1"): SECRET}
    store.delete("ref-1")
    assert store.get("ref-1") is None
    store.delete("ref-1")  # deleting a missing entry is not an error


def test_chainer_of_secure_backends_is_accepted() -> None:
    chainer = _chainer(SecretService(), KWallet())
    ensure_secure_backend(chainer)


def test_autouse_fixture_installs_a_failing_backend() -> None:
    with pytest.raises(CredentialStoreUnavailable):
        KeyringCredentialStore().set("ref-1", SECRET)


@pytest.mark.parametrize(
    "backend_factory",
    [
        lambda: fail.Keyring(),  # type: ignore[no-untyped-call]
        lambda: null.Keyring(),  # type: ignore[no-untyped-call]
        Plaintext,
        Unknown,
        lambda: _chainer(SecretService(), Plaintext()),
        lambda: _chainer(),
    ],
)
def test_insecure_backends_are_rejected_without_writing(backend_factory: Any) -> None:
    backend = backend_factory()
    keyring.set_keyring(backend)
    store = KeyringCredentialStore()

    operations: list[Callable[[], object]] = [
        lambda: store.set("ref-1", SECRET),
        lambda: store.get("ref-1"),
        lambda: store.delete("ref-1"),
    ]
    for operation in operations:
        with pytest.raises(CredentialStoreUnavailable) as error:
            operation()
        assert SECRET not in str(error.value)

    if isinstance(backend, MemoryBackend):
        assert backend.passwords == {}
    if isinstance(backend, ChainerBackend):
        for chained in backend.backends:
            if isinstance(chained, MemoryBackend):
                assert chained.passwords == {}


@pytest.mark.parametrize(
    "error", [KeyringLocked("locked"), InitError("no dbus"), KeyringError("boom")]
)
@pytest.mark.parametrize("operation", ["get", "set", "delete"])
def test_backend_errors_become_unavailable(error: KeyringError, operation: str) -> None:
    class Broken(SecretService):  # type: ignore[valid-type,misc]
        def get_password(self, service: str, username: str) -> str | None:
            raise error

        def set_password(self, service: str, username: str, password: str) -> None:
            raise error

        def delete_password(self, service: str, username: str) -> None:
            raise error

    Broken.__module__ = "keyring.backends.SecretService"
    Broken.__qualname__ = "Keyring"
    keyring.set_keyring(Broken())
    store = KeyringCredentialStore()

    with pytest.raises(CredentialStoreUnavailable) as raised:
        if operation == "get":
            store.get("ref-1")
        elif operation == "set":
            store.set("ref-1", SECRET)
        else:
            store.delete("ref-1")
    assert SECRET not in str(raised.value)
