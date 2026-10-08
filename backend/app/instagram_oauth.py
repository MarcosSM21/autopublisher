"""Pure OAuth logic for Instagram Login: Meta App config, authorization URL, parsing of
the pasted redirect URL and pending attempts.

Nothing here talks to Meta. Meta only accepts HTTPS redirect URIs, so there is no
callback server: the user pastes the redirect URL the browser was sent to and the
backend extracts `code`/`state` from it (see research.md §3). Pending attempts live
only in memory: their `state` and any credentials awaiting confirmation are never
persisted.
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
from urllib.parse import parse_qs, urlencode, urlsplit

from app.config import INSTAGRAM_ATTEMPT_RETENTION, INSTAGRAM_ATTEMPT_TTL
from app.db import utc_now

AUTH_ENDPOINT = "https://www.instagram.com/oauth/authorize"
# The only permissions needed to identify the account and publish later (research §1).
SCOPES = ("instagram_business_basic", "instagram_business_content_publish")
REQUIRED_PERMISSIONS = frozenset(SCOPES)


class InstagramOAuthNotConfigured(Exception):
    def __init__(self) -> None:
        super().__init__(
            "Instagram integration is not configured. See docs/instagram-accounts.md."
        )


@dataclass(frozen=True)
class MetaAppConfig:
    app_id: str
    app_secret: str = field(repr=False)
    redirect_uri: str


def _valid_redirect_uri(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError on an invalid port.
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and not parts.fragment


def load_meta_app_config(path: Path) -> MetaAppConfig:
    """Read the local Meta App JSON; raise InstagramOAuthNotConfigured if unusable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise InstagramOAuthNotConfigured() from None
    if not isinstance(data, dict):
        raise InstagramOAuthNotConfigured()
    app_id = data.get("app_id")
    app_secret = data.get("app_secret")
    redirect_uri = data.get("redirect_uri")
    if not isinstance(app_id, str) or not app_id.isdigit():
        raise InstagramOAuthNotConfigured()
    if not isinstance(app_secret, str) or not app_secret:
        raise InstagramOAuthNotConfigured()
    if not _valid_redirect_uri(redirect_uri):
        raise InstagramOAuthNotConfigured()
    assert isinstance(redirect_uri, str)
    return MetaAppConfig(app_id, app_secret, redirect_uri)


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(config: MetaAppConfig, state: str) -> str:
    """Instagram consent URL. `force_reauth` makes the user sign in consciously with
    the account to connect instead of silently reusing the browser session. No PKCE:
    it is not documented for Instagram Login (research §4)."""
    params = {
        "client_id": config.app_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
        "force_reauth": "true",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


class InvalidRedirectUrl(Exception):
    pass


@dataclass(frozen=True)
class RedirectResult:
    state: str | None = field(repr=False)
    code: str | None = field(repr=False)
    error: str | None = None


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    return 443 if scheme == "https" else None


def parse_redirect_url(pasted: str, config: MetaAppConfig) -> RedirectResult:
    """Extract `state`, `code` or `error` from the redirect URL the user pasted.

    The URL must point at the configured redirect URI (scheme, host, port and path; a
    trailing slash is tolerated). Meta appends `#_` to successful redirects; it is not
    part of the code.
    """
    try:
        actual = urlsplit(pasted.strip())
        expected = urlsplit(config.redirect_uri)
        actual_port = _effective_port(actual.scheme.lower(), actual.port)
        expected_port = _effective_port(expected.scheme.lower(), expected.port)
    except ValueError:
        raise InvalidRedirectUrl() from None
    if (
        actual.scheme.lower() != expected.scheme.lower()
        or (actual.hostname or "") != (expected.hostname or "")
        or actual_port != expected_port
        or actual.path.rstrip("/") != expected.path.rstrip("/")
    ):
        raise InvalidRedirectUrl()
    query = parse_qs(actual.query)

    def first(name: str) -> str | None:
        values = query.get(name)
        return values[0] if values else None

    code = first("code")
    if code is not None:
        code = code.removesuffix("#_") or None
    error = first("error")
    if code is None and error is None:
        raise InvalidRedirectUrl()
    return RedirectResult(state=first("state"), code=code, error=error)


@dataclass(frozen=True)
class InstagramIdentity:
    """Public information about an Instagram Professional account."""

    instagram_user_id: str
    username: str
    account_type: str | None
    profile_picture_url: str | None = None
    app_scoped_id: str | None = None

    def to_read(self) -> dict[str, Any]:
        return {
            "instagram_user_id": self.instagram_user_id,
            "username": self.username,
            "account_type": self.account_type,
            "profile_picture_url": self.profile_picture_url,
        }


class InstagramAttemptStatus(StrEnum):
    """Attempt statuses. Keep in sync with InstagramOAuthAttemptStatus in types.ts."""

    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATUSES = frozenset(
    {
        InstagramAttemptStatus.COMPLETED,
        InstagramAttemptStatus.FAILED,
        InstagramAttemptStatus.CANCELLED,
        InstagramAttemptStatus.EXPIRED,
    }
)


@dataclass(eq=False)
class InstagramOAuthAttempt:
    attempt_id: str
    account_id: int
    state: str = field(repr=False)
    created_at: datetime
    expires_at: datetime
    status: str = InstagramAttemptStatus.PENDING
    error: dict[str, str] | None = None
    current_identity: InstagramIdentity | None = None
    new_identity: InstagramIdentity | None = None
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


class InstagramAttemptRegistry:
    """In-memory Instagram OAuth attempts, safe to use from several request threads.

    Same rules as the YouTube registry (research §11): latest attempt wins, a
    non-terminal attempt past `expires_at` becomes `expired`, and terminal attempts are
    kept without secrets for INSTAGRAM_ATTEMPT_RETENTION, then purged.
    """

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, InstagramOAuthAttempt] = {}

    def _finish_locked(
        self,
        attempt: InstagramOAuthAttempt,
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
                self._finish_locked(attempt, InstagramAttemptStatus.EXPIRED)
                # An expired attempt finishes when its validity ended.
                attempt.finished_at = attempt.expires_at
        for attempt_id, attempt in list(self._attempts.items()):
            finished_at = attempt.finished_at
            if (
                attempt.is_terminal
                and finished_at is not None
                and now > finished_at + INSTAGRAM_ATTEMPT_RETENTION
            ):
                del self._attempts[attempt_id]

    def create(
        self,
        account_id: int,
        state: str,
        current_identity: InstagramIdentity | None = None,
    ) -> InstagramOAuthAttempt:
        """Start an attempt; any earlier unfinished attempt of the account expires."""
        with self._lock:
            self._refresh_locked()
            for attempt in self._attempts.values():
                if attempt.account_id == account_id and not attempt.is_terminal:
                    self._finish_locked(attempt, InstagramAttemptStatus.EXPIRED)
            now = self.clock()
            attempt = InstagramOAuthAttempt(
                attempt_id=secrets.token_urlsafe(16),
                account_id=account_id,
                state=state,
                created_at=now,
                expires_at=now + INSTAGRAM_ATTEMPT_TTL,
                current_identity=current_identity,
            )
            self._attempts[attempt.attempt_id] = attempt
            return attempt

    def get(self, attempt_id: str) -> InstagramOAuthAttempt | None:
        with self._lock:
            self._refresh_locked()
            return self._attempts.get(attempt_id)

    def consume_state(
        self, attempt_id: str, state: str | None
    ) -> InstagramOAuthAttempt:
        """Validate `state` against a pending attempt and use it, only once.

        A different state does not consume the attempt (a wrong paste can be fixed).
        Raises AttemptNotFound, AttemptExpired or AttemptStateInvalid.
        """
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if attempt.status == InstagramAttemptStatus.EXPIRED:
                raise AttemptExpired()
            if attempt.status != InstagramAttemptStatus.PENDING or attempt.consumed:
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
        attempt: InstagramOAuthAttempt,
        status: str,
        error: dict[str, str] | None = None,
        connection: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._finish_locked(attempt, status, error, connection)

    def await_confirmation(
        self,
        attempt: InstagramOAuthAttempt,
        new_identity: InstagramIdentity,
        credentials: Any,
        current_identity: InstagramIdentity | None = None,
    ) -> None:
        with self._lock:
            attempt.status = InstagramAttemptStatus.AWAITING_CONFIRMATION
            attempt.new_identity = new_identity
            if current_identity is not None:
                attempt.current_identity = current_identity
            attempt.pending_credentials = credentials
            attempt.state = ""

    def claim_confirmation(self, attempt_id: str) -> tuple[InstagramOAuthAttempt, Any]:
        """Take the pending credentials of an attempt awaiting confirmation, once."""
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if (
                attempt.status != InstagramAttemptStatus.AWAITING_CONFIRMATION
                or attempt.claimed
            ):
                raise AttemptNotConfirmable()
            attempt.claimed = True
            return attempt, attempt.pending_credentials

    def cancel(self, attempt_id: str) -> InstagramOAuthAttempt:
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if attempt.status == InstagramAttemptStatus.CANCELLED:
                return attempt
            if attempt.is_terminal or attempt.claimed:
                raise AttemptNotConfirmable()
            self._finish_locked(attempt, InstagramAttemptStatus.CANCELLED)
            return attempt

    def expire_for_account(self, account_id: int) -> None:
        with self._lock:
            for attempt in self._attempts.values():
                if attempt.account_id == account_id and not attempt.is_terminal:
                    self._finish_locked(attempt, InstagramAttemptStatus.EXPIRED)
