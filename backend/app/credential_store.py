"""Secrets in the operating system's secure credential storage, through `keyring`.

Only allow-listed native backends are used. There is deliberately no fallback: when no
secure backend is available, or it is locked or failing, operations raise
`CredentialStoreUnavailable` and nothing is written anywhere else.
"""

import threading
import time
from collections.abc import Callable
from typing import Literal, Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "autopublisher.youtube"
INSTAGRAM_SERVICE = "autopublisher.instagram"
THREADS_SERVICE = "autopublisher.threads"
TIKTOK_SERVICE = "autopublisher.tiktok"
TELEGRAM_SERVICE = "autopublisher.telegram"

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


# --- Non-interactive status probe (Feature 020, research §18) -----------------------

ProbeStatus = Literal["available", "locked", "unavailable", "unknown"]
PROBE_CACHE_SECONDS = 60.0
SECRET_SERVICE_BACKEND = "keyring.backends.SecretService.Keyring"


def _probe_secret_service() -> ProbeStatus:
    """Look at the **existing** default collection without any prompt.

    Never `get_default_collection()` or `create_collection()` (they create it, with a
    dialog), never `unlock()`, never a secret or item read.
    """
    try:
        import secretstorage
        from secretstorage.exceptions import ItemNotFoundException
    except ImportError:
        return "unknown"
    try:
        connection = secretstorage.dbus_init()
    except Exception:  # No session bus or no Secret Service.
        return "unavailable"
    try:
        # The `default` alias keyring uses; reading its properties never prompts.
        collection = secretstorage.Collection(connection)
        locked = collection.is_locked()
    except ItemNotFoundException:
        return "unknown"  # keyring would create it, with a dialog
    except Exception:  # D-Bus errors
        return "unavailable"
    finally:
        connection.close()
    return "locked" if locked else "available"


def probe_credential_store() -> ProbeStatus:
    """`unknown` is never reported as `available`: only a Secret Service collection
    seen unlocked is. Other allowed backends cannot be checked without interaction."""
    try:
        backend = keyring.get_keyring()
        ensure_secure_backend(backend)
    except (KeyringError, CredentialStoreUnavailable):
        return "unavailable"
    backends = (
        list(backend.backends) if isinstance(backend, ChainerBackend) else [backend]
    )
    if any(_qualified_name(item) == SECRET_SERVICE_BACKEND for item in backends):
        return _probe_secret_service()
    return "unknown"


class CredentialStoreProbe:
    """The probe, cached for 60 s (only the signed-in diagnostics call it)."""

    def __init__(
        self,
        check: Callable[[], ProbeStatus] = probe_credential_store,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._check = check
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._cached: tuple[float, ProbeStatus] | None = None

    def status(self) -> ProbeStatus:
        with self._lock:
            now = self._monotonic()
            if self._cached is not None and now - self._cached[0] < PROBE_CACHE_SECONDS:
                return self._cached[1]
            result = self._check()
            self._cached = (now, result)
            return result
