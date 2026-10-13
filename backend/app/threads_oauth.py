"""Pure OAuth logic for the Threads API: app config, authorization URL, strict parsing
of the pasted redirect URL and pending attempts.

Nothing here talks to Meta. Meta only accepts HTTPS redirect URIs, so there is no
callback server: the user pastes the redirect URL the browser was sent to and the
backend extracts `code`/`state` from it after checking it really points at the
configured redirect URI (see specs/010-threads-oauth-connection/research.md §3–§4).
Pending attempts live only in memory: their `state` and any credentials awaiting
confirmation are never persisted.
"""

import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, parse_qs, urlencode, urlsplit

from app.config import THREADS_ATTEMPT_RETENTION, THREADS_ATTEMPT_TTL
from app.db import utc_now

THREADS_AUTH_ENDPOINT = "https://threads.com/oauth/authorize"
# The only permissions needed to identify the account and publish later (research §1).
SCOPES = ("threads_basic", "threads_content_publish")
REQUIRED_SCOPES = frozenset(SCOPES)


class ThreadsOAuthNotConfigured(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Threads integration is not configured. See docs/threads-accounts.md."
        )


@dataclass(frozen=True)
class ThreadsAppConfig:
    app_id: str
    app_secret: str = field(repr=False)
    redirect_uri: str


def _effective_port(parts: SplitResult) -> int | None:
    """Explicit port, or the default one of the scheme; raises ValueError if invalid."""
    port = parts.port
    if port is not None:
        return port
    return 443 if parts.scheme.lower() == "https" else None


def _valid_redirect_uri(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parts = urlsplit(value)
        _effective_port(parts)
    except ValueError:
        return False
    return (
        parts.scheme.lower() == "https"
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and not parts.query
        and not parts.fragment
    )


def load_threads_app_config(path: Path) -> ThreadsAppConfig:
    """Read the local Threads app JSON; raise ThreadsOAuthNotConfigured if unusable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ThreadsOAuthNotConfigured() from None
    if not isinstance(data, dict):
        raise ThreadsOAuthNotConfigured()
    app_id = data.get("app_id")
    app_secret = data.get("app_secret")
    redirect_uri = data.get("redirect_uri")
    if not isinstance(app_id, str) or not app_id.isdigit():
        raise ThreadsOAuthNotConfigured()
    if not isinstance(app_secret, str) or not app_secret:
        raise ThreadsOAuthNotConfigured()
    if not _valid_redirect_uri(redirect_uri):
        raise ThreadsOAuthNotConfigured()
    assert isinstance(redirect_uri, str)
    return ThreadsAppConfig(app_id, app_secret, redirect_uri)


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(config: ThreadsAppConfig, state: str) -> str:
    """Threads consent URL with the documented parameters only. No PKCE: it is not
    documented for the Threads API (research §5)."""
    params = {
        "client_id": config.app_id,
        "redirect_uri": config.redirect_uri,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "state": state,
    }
    return f"{THREADS_AUTH_ENDPOINT}?{urlencode(params)}"


class InvalidRedirectUrl(Exception):
    pass


@dataclass(frozen=True)
class RedirectResult:
    state: str | None = field(repr=False)
    code: str | None = field(repr=False)
    error: str | None = None


def parse_redirect_url(pasted: str, config: ThreadsAppConfig) -> RedirectResult:
    """Extract `state`, `code` or `error` from the redirect URL the user pasted.

    The URL is parsed and compared component by component with the configured redirect
    URI: scheme, hostname, effective port and path must be exactly equal (never a
    textual prefix match). Only then are the OAuth parameters read, from the query.
    Meta appends `#_` to successful redirects; it is not part of the code.
    """
    try:
        actual = urlsplit(pasted.strip())
        expected = urlsplit(config.redirect_uri)
        actual_port = _effective_port(actual)
        expected_port = _effective_port(expected)
    except ValueError:
        raise InvalidRedirectUrl() from None
    if (
        actual.username is not None
        or actual.password is not None
        or actual.scheme.lower() != expected.scheme.lower()
        or (actual.hostname or "") != (expected.hostname or "")
        or actual_port != expected_port
        or actual.path != expected.path
    ):
        raise InvalidRedirectUrl()
    query = parse_qs(actual.query, keep_blank_values=True)

    def single(name: str) -> str | None:
        values = query.get(name)
        if not values:
            return None
        if len(values) > 1:
            raise InvalidRedirectUrl()
        return values[0] or None

    code = single("code")
    if code is not None:
        code = code.removesuffix("#_") or None
    error = single("error")
    state = single("state")
    if code is None and error is None:
        raise InvalidRedirectUrl()
    return RedirectResult(state=state, code=code, error=error)


@dataclass(frozen=True)
class ThreadsIdentity:
    """Public information about a Threads account; `threads_user_id` is the identity."""

    threads_user_id: str
    username: str
    display_name: str | None = None
    profile_picture_url: str | None = None

    def to_read(self) -> dict[str, Any]:
        return {
            "threads_user_id": self.threads_user_id,
            "username": self.username,
            "display_name": self.display_name,
            "profile_picture_url": self.profile_picture_url,
        }


class ThreadsAttemptStatus(StrEnum):
    """Attempt statuses. Keep in sync with ThreadsOAuthAttemptStatus in types.ts."""

    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATUSES = frozenset(
    {
        ThreadsAttemptStatus.COMPLETED,
        ThreadsAttemptStatus.FAILED,
        ThreadsAttemptStatus.CANCELLED,
        ThreadsAttemptStatus.EXPIRED,
    }
)


@dataclass(eq=False)
class ThreadsOAuthAttempt:
    attempt_id: str
    account_id: int
    state: str = field(repr=False)
    created_at: datetime
    expires_at: datetime
    status: str = ThreadsAttemptStatus.PENDING
    error: dict[str, str] | None = None
    current_identity: ThreadsIdentity | None = None
    new_identity: ThreadsIdentity | None = None
    # Credentials waiting for an account-change confirmation (memory only).
    pending_credentials: Any = field(default=None, repr=False)
    connection: dict[str, Any] | None = None
    finished_at: datetime | None = None
    # Whether the state was already used by a redirect URL.
    consumed: bool = False
    claimed: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_read(self) -> dict[str, Any]:
        """Public view of the attempt (never the state or credentials)."""
        return {
            "attempt_id": self.attempt_id,
            "account_id": self.account_id,
            "status": self.status,
            "expires_at": self.expires_at,
            "error": self.error,
            "current_identity": self.current_identity.to_read()
            if self.current_identity
            else None,
            "new_identity": self.new_identity.to_read() if self.new_identity else None,
            "connection": self.connection,
        }


class AttemptNotFound(Exception):
    pass


class AttemptExpired(Exception):
    pass


class AttemptStateInvalid(Exception):
    """The state is missing or different, or the attempt can no longer be completed."""


class AttemptNotConfirmable(Exception):
    pass


class ThreadsAttemptRegistry:
    """In-memory Threads OAuth attempts, safe to use from several request threads.

    Latest attempt wins, a non-terminal attempt past `expires_at` becomes `expired`,
    and terminal attempts are kept without secrets for THREADS_ATTEMPT_RETENTION, then
    purged (research §14).
    """

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, ThreadsOAuthAttempt] = {}

    def _finish_locked(
        self,
        attempt: ThreadsOAuthAttempt,
        status: str,
        error: dict[str, str] | None = None,
        connection: dict[str, Any] | None = None,
    ) -> None:
        attempt.status = status
        attempt.error = error
        attempt.connection = connection
        attempt.finished_at = self.clock()
        attempt.state = ""
        attempt.pending_credentials = None

    def _refresh_locked(self) -> None:
        now = self.clock()
        for attempt in list(self._attempts.values()):
            if not attempt.is_terminal and now >= attempt.expires_at:
                self._finish_locked(attempt, ThreadsAttemptStatus.EXPIRED)
                # An expired attempt finishes when its validity ended.
                attempt.finished_at = attempt.expires_at
        for attempt_id, attempt in list(self._attempts.items()):
            finished_at = attempt.finished_at
            if (
                attempt.is_terminal
                and finished_at is not None
                and now > finished_at + THREADS_ATTEMPT_RETENTION
            ):
                del self._attempts[attempt_id]

    def create(
        self,
        account_id: int,
        state: str,
        current_identity: ThreadsIdentity | None = None,
    ) -> ThreadsOAuthAttempt:
        """Start an attempt; any earlier unfinished attempt of the account expires."""
        with self._lock:
            self._refresh_locked()
            for attempt in self._attempts.values():
                if attempt.account_id == account_id and not attempt.is_terminal:
                    self._finish_locked(attempt, ThreadsAttemptStatus.EXPIRED)
            now = self.clock()
            attempt = ThreadsOAuthAttempt(
                attempt_id=secrets.token_urlsafe(16),
                account_id=account_id,
                state=state,
                created_at=now,
                expires_at=now + THREADS_ATTEMPT_TTL,
                current_identity=current_identity,
            )
            self._attempts[attempt.attempt_id] = attempt
            return attempt

    def get(self, attempt_id: str) -> ThreadsOAuthAttempt | None:
        with self._lock:
            self._refresh_locked()
            return self._attempts.get(attempt_id)

    def consume_state(self, attempt_id: str, state: str | None) -> ThreadsOAuthAttempt:
        """Validate `state` against a pending attempt and use it, only once.

        A different state does not consume the attempt (a wrong paste can be fixed).
        Raises AttemptNotFound, AttemptExpired or AttemptStateInvalid.
        """
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if attempt.status == ThreadsAttemptStatus.EXPIRED:
                raise AttemptExpired()
            if attempt.status != ThreadsAttemptStatus.PENDING or attempt.consumed:
                raise AttemptStateInvalid()
            if not state or not secrets.compare_digest(
                state.encode(), attempt.state.encode()
            ):
                raise AttemptStateInvalid()
            attempt.consumed = True
            attempt.state = ""
            return attempt

    def finish(
        self,
        attempt: ThreadsOAuthAttempt,
        status: str,
        error: dict[str, str] | None = None,
        connection: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._finish_locked(attempt, status, error, connection)

    def await_confirmation(
        self,
        attempt: ThreadsOAuthAttempt,
        new_identity: ThreadsIdentity,
        credentials: Any,
        current_identity: ThreadsIdentity | None = None,
    ) -> None:
        with self._lock:
            attempt.status = ThreadsAttemptStatus.AWAITING_CONFIRMATION
            attempt.new_identity = new_identity
            if current_identity is not None:
                attempt.current_identity = current_identity
            attempt.pending_credentials = credentials
            attempt.state = ""

    def claim_confirmation(self, attempt_id: str) -> tuple[ThreadsOAuthAttempt, Any]:
        """Take the pending credentials of an attempt awaiting confirmation, once."""
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if (
                attempt.status != ThreadsAttemptStatus.AWAITING_CONFIRMATION
                or attempt.claimed
            ):
                raise AttemptNotConfirmable()
            attempt.claimed = True
            return attempt, attempt.pending_credentials

    def cancel(self, attempt_id: str) -> ThreadsOAuthAttempt:
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if attempt.status == ThreadsAttemptStatus.CANCELLED:
                return attempt
            if attempt.is_terminal or attempt.claimed:
                raise AttemptNotConfirmable()
            self._finish_locked(attempt, ThreadsAttemptStatus.CANCELLED)
            return attempt

    def expire_for_account(self, account_id: int) -> None:
        with self._lock:
            for attempt in self._attempts.values():
                if attempt.account_id == account_id and not attempt.is_terminal:
                    self._finish_locked(attempt, ThreadsAttemptStatus.EXPIRED)
