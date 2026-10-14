"""Pure OAuth logic for TikTok Login Kit for Desktop: app config, PKCE, authorization
URL, strict callback parsing and pending attempts.

Nothing here talks to TikTok. TikTok redirects the browser to the backend's loopback
callback (`TIKTOK_CALLBACK_PATH`). Pending attempts live only in memory: their
`state`, PKCE `code_verifier` and any credential awaiting confirmation are never
persisted (see specs/012-tiktok-oauth-connection/research.md §3–§6).
"""

import hashlib
import json
import secrets
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from app.config import (
    DEFAULT_TIKTOK_REDIRECT_URI,
    TIKTOK_ATTEMPT_RETENTION,
    TIKTOK_ATTEMPT_TTL,
    TIKTOK_CALLBACK_PATH,
)
from app.db import utc_now

TIKTOK_AUTH_ENDPOINT = "https://www.tiktok.com/v2/auth/authorize/"
# The only permissions needed to identify the account and publish later (research §5).
SCOPES = ("user.info.basic", "video.publish")
REQUIRED_SCOPES = frozenset(SCOPES)

# Desktop redirect URIs must be loopback (research §3).
_REDIRECT_HOSTS = frozenset({"127.0.0.1", "localhost"})
MAX_REDIRECT_URI_LENGTH = 512
MAX_CODE_LENGTH = 1024
# Parameters TikTok documents for the callback; any of them repeated is invalid.
CALLBACK_PARAMS = frozenset({"code", "scopes", "state", "error", "error_description"})


def parse_scopes(value: str) -> frozenset[str]:
    """TikTok's comma-separated scope list (spaces around names are ignored)."""
    return frozenset(name.strip() for name in value.split(",") if name.strip())


class TikTokOAuthNotConfigured(Exception):
    def __init__(self) -> None:
        super().__init__(
            "TikTok integration is not configured. See docs/tiktok-accounts.md."
        )


@dataclass(frozen=True)
class TikTokAppConfig:
    client_key: str
    client_secret: str = field(repr=False)
    redirect_uri: str = DEFAULT_TIKTOK_REDIRECT_URI


def _valid_redirect_uri(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if len(value) >= MAX_REDIRECT_URI_LENGTH or "?" in value or "#" in value:
        return False
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:  # For example a `*` port.
        return False
    return (
        parts.scheme == "http"
        and parts.hostname in _REDIRECT_HOSTS
        and "@" not in parts.netloc
        and port is not None
        and parts.path == TIKTOK_CALLBACK_PATH
    )


def load_tiktok_app_config(path: Path) -> TikTokAppConfig:
    """Read the local TikTok app JSON; raise TikTokOAuthNotConfigured if unusable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise TikTokOAuthNotConfigured() from None
    if not isinstance(data, dict):
        raise TikTokOAuthNotConfigured()
    client_key = data.get("client_key")
    client_secret = data.get("client_secret")
    redirect_uri = data.get("redirect_uri", DEFAULT_TIKTOK_REDIRECT_URI)
    if not isinstance(client_key, str) or not client_key.strip():
        raise TikTokOAuthNotConfigured()
    if not isinstance(client_secret, str) or not client_secret.strip():
        raise TikTokOAuthNotConfigured()
    if not _valid_redirect_uri(redirect_uri):
        raise TikTokOAuthNotConfigured()
    assert isinstance(redirect_uri, str)
    return TikTokAppConfig(client_key, client_secret, redirect_uri)


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_tiktok_pkce_pair() -> tuple[str, str]:
    """Return a PKCE (code_verifier, code_challenge) pair for TikTok Desktop.

    TikTok Desktop requires the S256 challenge as the lowercase **hex** SHA-256 of the
    verifier, not base64url (research §4). The verifier has 64 characters of
    `[A-Za-z0-9-_]`, within the 43–128 unreserved characters allowed.
    """
    verifier = secrets.token_urlsafe(48)
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    return verifier, challenge


def build_authorization_url(
    config: TikTokAppConfig, state: str, code_challenge: str
) -> str:
    """TikTok consent URL with the documented parameters only."""
    params = {
        "client_key": config.client_key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{TIKTOK_AUTH_ENDPOINT}?{urlencode(params)}"


class CallbackInvalid(Exception):
    pass


@dataclass(frozen=True)
class CallbackResult:
    state: str = field(repr=False)
    code: str | None = field(repr=False)
    error: str | None = None


def _documented_values(items: Sequence[tuple[str, str]]) -> dict[str, list[str]]:
    """Values of the documented parameters; undocumented ones are ignored."""
    values: dict[str, list[str]] = {}
    for name, value in items:
        if name in CALLBACK_PARAMS:
            values.setdefault(name, []).append(value)
    return values


def extract_state(items: Sequence[tuple[str, str]]) -> str | None:
    """The single non-empty `state` of a callback, or None (missing or repeated)."""
    states = _documented_values(items).get("state", [])
    if len(states) != 1 or not states[0]:
        return None
    return states[0]


def parse_callback(items: Sequence[tuple[str, str]]) -> CallbackResult:
    """Strictly validate the callback query (research §6).

    Any documented parameter repeated, `code` together with `error`, neither of them,
    or an empty or oversized `code` is invalid. `scopes` is only checked for
    repetition: the granted scopes come from the token response.
    """
    values = _documented_values(items)
    if any(len(found) > 1 for found in values.values()):
        raise CallbackInvalid()
    state = extract_state(items)
    if state is None:
        raise CallbackInvalid()
    code = values["code"][0] if "code" in values else None
    error = values["error"][0] if "error" in values else None
    if (code is None) == (error is None):
        raise CallbackInvalid()
    if code is not None and not 0 < len(code) <= MAX_CODE_LENGTH:
        raise CallbackInvalid()
    if error is not None and not error:
        raise CallbackInvalid()
    return CallbackResult(state=state, code=code, error=error)


@dataclass(frozen=True)
class TikTokIdentity:
    """Public information about a TikTok account; `open_id` is the identity."""

    open_id: str
    display_name: str | None = None
    avatar_url: str | None = None

    @property
    def suffix(self) -> str:
        """Last characters of `open_id`, to tell two accounts apart in the UI."""
        return self.open_id[-6:]

    def to_read(self) -> dict[str, Any]:
        return {
            "open_id": self.open_id,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
        }

    def to_attempt_read(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "open_id_suffix": self.suffix,
        }


class TikTokAttemptStatus(StrEnum):
    """Attempt statuses. Keep in sync with TikTokOAuthAttemptStatus in types.ts."""

    PENDING = "pending"
    # The state was used and the code is being exchanged.
    PROCESSING = "processing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATUSES = frozenset(
    {
        TikTokAttemptStatus.COMPLETED,
        TikTokAttemptStatus.FAILED,
        TikTokAttemptStatus.CANCELLED,
        TikTokAttemptStatus.EXPIRED,
    }
)


@dataclass(eq=False)
class TikTokOAuthAttempt:
    attempt_id: str
    account_id: int
    state: str = field(repr=False)
    code_verifier: str | None = field(repr=False)
    created_at: datetime
    expires_at: datetime
    status: str = TikTokAttemptStatus.PENDING
    error: dict[str, str] | None = None
    current_identity: TikTokIdentity | None = None
    new_identity: TikTokIdentity | None = None
    # Credential waiting for an account-change confirmation (memory only).
    pending_credential: Any = field(default=None, repr=False)
    connection: dict[str, Any] | None = None
    finished_at: datetime | None = None
    claimed: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_read(self) -> dict[str, Any]:
        """Public view of the attempt (never the state, verifier or credentials)."""
        return {
            "attempt_id": self.attempt_id,
            "account_id": self.account_id,
            "status": self.status,
            "expires_at": self.expires_at,
            "error": self.error,
            "current_identity": self.current_identity.to_attempt_read()
            if self.current_identity
            else None,
            "new_identity": self.new_identity.to_attempt_read()
            if self.new_identity
            else None,
            "connection": self.connection,
        }


class AttemptNotFound(Exception):
    pass


class AttemptNotConfirmable(Exception):
    pass


# Called with (credential, account_id) for a pending credential that is dropped.
DiscardCallback = Callable[[Any, int], None]


class TikTokAttemptRegistry:
    """In-memory TikTok OAuth attempts, safe to use from several request threads.

    Latest attempt wins; a pending or awaiting attempt past `expires_at` becomes
    `expired`; terminal attempts are kept without secrets for TIKTOK_ATTEMPT_RETENTION,
    then purged. A pending credential dropped by a cancellation or an expiry is handed
    to `discard` (best-effort revocation), outside the registry lock.
    """

    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        discard: DiscardCallback | None = None,
    ) -> None:
        self.clock = clock
        self.discard = discard
        self._lock = threading.Lock()
        self._attempts: dict[str, TikTokOAuthAttempt] = {}
        self._by_state: dict[str, str] = {}

    def _finish_locked(
        self,
        attempt: TikTokOAuthAttempt,
        status: str,
        error: dict[str, str] | None = None,
        connection: dict[str, Any] | None = None,
    ) -> tuple[Any, int] | None:
        """Finish the attempt; return a pending credential that must be discarded."""
        dropped = None
        if attempt.pending_credential is not None and not attempt.claimed:
            dropped = (attempt.pending_credential, attempt.account_id)
        attempt.status = status
        attempt.error = error
        attempt.connection = connection
        attempt.finished_at = self.clock()
        attempt.code_verifier = None
        attempt.pending_credential = None
        self._by_state.pop(attempt.state, None)
        attempt.state = ""
        return dropped

    def _refresh_locked(self) -> list[tuple[Any, int]]:
        dropped: list[tuple[Any, int]] = []
        now = self.clock()
        for attempt in list(self._attempts.values()):
            # A processing attempt is finishing its exchange: it is never expired.
            if (
                attempt.status
                in (
                    TikTokAttemptStatus.PENDING,
                    TikTokAttemptStatus.AWAITING_CONFIRMATION,
                )
                and not attempt.claimed
                and now >= attempt.expires_at
            ):
                item = self._finish_locked(attempt, TikTokAttemptStatus.EXPIRED)
                if item is not None:
                    dropped.append(item)
                # An expired attempt finishes when its validity ended.
                attempt.finished_at = attempt.expires_at
        for attempt_id, attempt in list(self._attempts.items()):
            finished_at = attempt.finished_at
            if (
                attempt.is_terminal
                and finished_at is not None
                and now > finished_at + TIKTOK_ATTEMPT_RETENTION
            ):
                del self._attempts[attempt_id]
        return dropped

    def _discard(self, dropped: list[tuple[Any, int]]) -> None:
        if self.discard is None:
            return
        for credential, account_id in dropped:
            self.discard(credential, account_id)

    def create(
        self,
        account_id: int,
        state: str,
        code_verifier: str,
        current_identity: TikTokIdentity | None = None,
    ) -> TikTokOAuthAttempt:
        """Start an attempt; earlier pending or awaiting attempts of the account
        expire."""
        with self._lock:
            dropped = self._refresh_locked()
            for attempt in self._attempts.values():
                if (
                    attempt.account_id == account_id
                    and attempt.status != TikTokAttemptStatus.PROCESSING
                    and not attempt.is_terminal
                    and not attempt.claimed
                ):
                    item = self._finish_locked(attempt, TikTokAttemptStatus.EXPIRED)
                    if item is not None:
                        dropped.append(item)
            now = self.clock()
            attempt = TikTokOAuthAttempt(
                attempt_id=secrets.token_urlsafe(16),
                account_id=account_id,
                state=state,
                code_verifier=code_verifier,
                created_at=now,
                expires_at=now + TIKTOK_ATTEMPT_TTL,
                current_identity=current_identity,
            )
            self._attempts[attempt.attempt_id] = attempt
            self._by_state[state] = attempt.attempt_id
        self._discard(dropped)
        return attempt

    def consume_state(self, state: str) -> tuple[TikTokOAuthAttempt, str] | None:
        """Use the pending attempt of `state` once: it becomes `processing` and its
        verifier is handed out and cleared. Later calls return None."""
        with self._lock:
            dropped = self._refresh_locked()
            attempt_id = self._by_state.pop(state, None)
            attempt = self._attempts.get(attempt_id) if attempt_id else None
            result = None
            if (
                attempt is not None
                and attempt.status == TikTokAttemptStatus.PENDING
                and attempt.code_verifier is not None
            ):
                verifier = attempt.code_verifier
                attempt.code_verifier = None
                attempt.state = ""
                attempt.status = TikTokAttemptStatus.PROCESSING
                result = (attempt, verifier)
        self._discard(dropped)
        return result

    def get(self, attempt_id: str) -> TikTokOAuthAttempt | None:
        with self._lock:
            dropped = self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
        self._discard(dropped)
        return attempt

    def finish(
        self,
        attempt: TikTokOAuthAttempt,
        status: str,
        error: dict[str, str] | None = None,
        connection: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            item = self._finish_locked(attempt, status, error, connection)
        self._discard([item] if item is not None else [])

    def await_confirmation(
        self,
        attempt: TikTokOAuthAttempt,
        new_identity: TikTokIdentity,
        credential: Any,
        current_identity: TikTokIdentity | None = None,
    ) -> None:
        with self._lock:
            attempt.status = TikTokAttemptStatus.AWAITING_CONFIRMATION
            attempt.new_identity = new_identity
            if current_identity is not None:
                attempt.current_identity = current_identity
            attempt.pending_credential = credential
            attempt.code_verifier = None

    def claim_confirmation(self, attempt_id: str) -> tuple[TikTokOAuthAttempt, Any]:
        """Take the pending credential of an attempt awaiting confirmation, once."""
        with self._lock:
            dropped = self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            claimable = (
                attempt is not None
                and attempt.status == TikTokAttemptStatus.AWAITING_CONFIRMATION
                and not attempt.claimed
            )
            if attempt is not None and claimable:
                attempt.claimed = True
                credential = attempt.pending_credential
        self._discard(dropped)
        if attempt is None:
            raise AttemptNotFound()
        if not claimable:
            raise AttemptNotConfirmable()
        return attempt, credential

    def cancel(self, attempt_id: str) -> TikTokOAuthAttempt:
        """Cancel a pending or awaiting attempt; idempotent on a cancelled one."""
        with self._lock:
            dropped = self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            cancellable = attempt is not None and (
                attempt.status == TikTokAttemptStatus.CANCELLED
                or (
                    attempt.status
                    in (
                        TikTokAttemptStatus.PENDING,
                        TikTokAttemptStatus.AWAITING_CONFIRMATION,
                    )
                    and not attempt.claimed
                )
            )
            if (
                attempt is not None
                and cancellable
                and attempt.status != TikTokAttemptStatus.CANCELLED
            ):
                item = self._finish_locked(attempt, TikTokAttemptStatus.CANCELLED)
                if item is not None:
                    dropped.append(item)
        self._discard(dropped)
        if attempt is None:
            raise AttemptNotFound()
        if not cancellable:
            raise AttemptNotConfirmable()
        return attempt

    def expire_for_account(self, account_id: int) -> None:
        dropped: list[tuple[Any, int]] = []
        with self._lock:
            for attempt in self._attempts.values():
                if (
                    attempt.account_id == account_id
                    and attempt.status != TikTokAttemptStatus.PROCESSING
                    and not attempt.is_terminal
                    and not attempt.claimed
                ):
                    item = self._finish_locked(attempt, TikTokAttemptStatus.EXPIRED)
                    if item is not None:
                        dropped.append(item)
        self._discard(dropped)
