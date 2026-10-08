"""Secrets in the operating system's secure credential storage, through `keyring`.

Only allow-listed native backends are used. There is deliberately no fallback: when no
secure backend is available, or it is locked or failing, operations raise
`CredentialStoreUnavailable` and nothing is written anywhere else.
"""

from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "autopublisher.youtube"
INSTAGRAM_SERVICE = "autopublisher.instagram"

# Native backends of the OS secure storage (see research.md, decision 8).
ALLOWED_BACKENDS = frozenset(
    {
        "keyring.backends.SecretService.Keyring",
        "keyring.backends.libsecret.Keyring",
        "keyring.backends.kwallet.DBusKeyring",
        "keyring.backends.macOS.Keyring",
        "keyring.backends.Windows.WinVaultKeyring",
    }
)


class CredentialStoreUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("The system's secure credential storage is not available.")


class CredentialStore(Protocol):
    def get(self, ref: str) -> str | None: ...

    def set(self, ref: str, value: str) -> None: ...

    def delete(self, ref: str) -> None: ...


def _qualified_name(backend: KeyringBackend) -> str:
    backend_class = type(backend)
    return f"{backend_class.__module__}.{backend_class.__qualname__}"


def ensure_secure_backend(backend: KeyringBackend) -> None:
    """Accept only allow-listed backends, or a chainer made exclusively of them."""
    if isinstance(backend, ChainerBackend):
        chained = list(backend.backends)
        if chained and all(
            _qualified_name(item) in ALLOWED_BACKENDS for item in chained
        ):
            return
        raise CredentialStoreUnavailable()
    if _qualified_name(backend) not in ALLOWED_BACKENDS:
        raise CredentialStoreUnavailable()


class KeyringCredentialStore:
    """CredentialStore backed by the system keyring, checked before every operation."""

    def __init__(self, service: str = SERVICE) -> None:
        self.service = service

    def _backend(self) -> KeyringBackend:
        try:
            backend = keyring.get_keyring()
        except KeyringError:
            raise CredentialStoreUnavailable() from None
        ensure_secure_backend(backend)
        return backend

    def get(self, ref: str) -> str | None:
        backend = self._backend()
        try:
            return backend.get_password(self.service, ref)
        except KeyringError:
            raise CredentialStoreUnavailable() from None

    def set(self, ref: str, value: str) -> None:
        backend = self._backend()
        try:
            backend.set_password(self.service, ref, value)
        except KeyringError:
            raise CredentialStoreUnavailable() from None

    def delete(self, ref: str) -> None:
        backend = self._backend()
        try:
            backend.delete_password(self.service, ref)
        except PasswordDeleteError:
            return  # Already gone.
        except KeyringError:
            raise CredentialStoreUnavailable() from None
