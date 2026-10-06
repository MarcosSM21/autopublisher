"""Pure OAuth logic for YouTube: client config, PKCE, authorization URL and attempts.

Nothing here talks to Google. Pending attempts live only in memory: their `state`,
PKCE `code_verifier` and any credentials awaiting confirmation are never persisted.
"""

import base64
import hashlib
import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.config import OAUTH_ATTEMPT_RETENTION, OAUTH_ATTEMPT_TTL
from app.db import utc_now

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
# Minimum scopes: identify the channel (channels.list) and upload videos later
# (videos.insert). See research.md, decision 3.
SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
)
REQUIRED_SCOPES = frozenset(SCOPES)


class OAuthNotConfigured(Exception):
    def __init__(self) -> None:
        super().__init__(
            "YouTube integration is not configured. "
            "See the README section 'Connecting YouTube'."
        )


@dataclass(frozen=True)
class OAuthClientConfig:
    client_id: str
    client_secret: str = field(repr=False)


def load_client_config(path: Path) -> OAuthClientConfig:
    """Read a Google "Desktop app" client JSON; raise OAuthNotConfigured if unusable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise OAuthNotConfigured() from None
    installed = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(installed, dict):
        raise OAuthNotConfigured()
    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")
    if not isinstance(client_id, str) or not client_id:
        raise OAuthNotConfigured()
    if not isinstance(client_secret, str) or not client_secret:
        raise OAuthNotConfigured()
    return OAuthClientConfig(client_id, client_secret)


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_pkce_pair() -> tuple[str, str]:
    """Return a PKCE (code_verifier, S256 code_challenge) pair."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    client_id: str, redirect_uri: str, state: str, code_challenge: str
) -> str:
    """Google consent URL: always offline access and an explicit consent prompt."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        # `consent` guarantees a new refresh token even if access was granted before.
        "prompt": "select_account consent",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


@dataclass(frozen=True)
class ChannelInfo:
    """Public information about a YouTube channel."""

    id: str
    title: str
    handle: str | None = None
    thumbnail_url: str | None = None


class AttemptStatus(StrEnum):
    """OAuth attempt statuses. Keep in sync with OAuthAttemptStatus in types.ts."""

    PENDING = "pending"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATUSES = frozenset(
    {
        AttemptStatus.COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
        AttemptStatus.EXPIRED,
    }
)


@dataclass(eq=False)
class OAuthAttempt:
    attempt_id: str
    account_id: int
    state: str
    code_verifier: str | None = field(repr=False)
    created_at: datetime
    expires_at: datetime
    status: str = AttemptStatus.PENDING
    error: dict[str, str] | None = None
    current_channel: ChannelInfo | None = None
    new_channel: ChannelInfo | None = None
    # Credentials waiting for a channel-change confirmation (memory only).
    pending_credentials: Any = field(default=None, repr=False)
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
            "current_channel": asdict(self.current_channel)
            if self.current_channel
            else None,
            "new_channel": asdict(self.new_channel) if self.new_channel else None,
            "connection": self.connection,
        }


class AttemptNotFound(Exception):
    pass


class AttemptNotConfirmable(Exception):
    pass


class OAuthAttemptRegistry:
    """In-memory OAuth attempts, safe to use from several request threads.

    Single expiry and retention rule (data-model.md): a non-terminal attempt past
    `expires_at` becomes `expired`; any terminal attempt is kept, without secrets, for
    OAUTH_ATTEMPT_RETENTION after `finished_at`, and only then purged.
    """

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, OAuthAttempt] = {}
        self._by_state: dict[str, str] = {}

    def _finish_locked(
        self,
        attempt: OAuthAttempt,
        status: str,
        error: dict[str, str] | None = None,
        connection: dict[str, Any] | None = None,
    ) -> None:
        attempt.status = status
        attempt.error = error
        attempt.connection = connection
        attempt.finished_at = self.clock()
        attempt.code_verifier = None
        attempt.pending_credentials = None
        self._by_state.pop(attempt.state, None)

    def _refresh_locked(self) -> None:
        now = self.clock()
        for attempt in list(self._attempts.values()):
            if not attempt.is_terminal and now >= attempt.expires_at:
                self._finish_locked(attempt, AttemptStatus.EXPIRED)
                # An expired attempt finishes when its validity ended.
                attempt.finished_at = attempt.expires_at
        for attempt_id, attempt in list(self._attempts.items()):
            finished_at = attempt.finished_at
            if (
                attempt.is_terminal
                and finished_at is not None
                and now > finished_at + OAUTH_ATTEMPT_RETENTION
            ):
                del self._attempts[attempt_id]
                self._by_state.pop(attempt.state, None)

    def create(
        self,
        account_id: int,
        state: str,
        code_verifier: str,
        current_channel: ChannelInfo | None = None,
    ) -> OAuthAttempt:
        """Start an attempt; any earlier unfinished attempt of the account expires."""
        with self._lock:
            self._refresh_locked()
            for attempt in self._attempts.values():
                if attempt.account_id == account_id and not attempt.is_terminal:
                    self._finish_locked(attempt, AttemptStatus.EXPIRED)
            now = self.clock()
            attempt = OAuthAttempt(
                attempt_id=secrets.token_urlsafe(16),
                account_id=account_id,
                state=state,
                code_verifier=code_verifier,
                created_at=now,
                expires_at=now + OAUTH_ATTEMPT_TTL,
                current_channel=current_channel,
            )
            self._attempts[attempt.attempt_id] = attempt
            self._by_state[state] = attempt.attempt_id
            return attempt

    def consume_state(self, state: str) -> OAuthAttempt | None:
        """Return the pending attempt for `state` once; later calls return None."""
        with self._lock:
            self._refresh_locked()
            attempt_id = self._by_state.pop(state, None)
            if attempt_id is None:
                return None
            attempt = self._attempts.get(attempt_id)
            if attempt is None or attempt.status != AttemptStatus.PENDING:
                return None
            return attempt

    def get(self, attempt_id: str) -> OAuthAttempt | None:
        with self._lock:
            self._refresh_locked()
            return self._attempts.get(attempt_id)

    def finish(
        self,
        attempt: OAuthAttempt,
        status: str,
        error: dict[str, str] | None = None,
        connection: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._finish_locked(attempt, status, error, connection)

    def await_confirmation(
        self,
        attempt: OAuthAttempt,
        new_channel: ChannelInfo,
        credentials: Any,
        current_channel: ChannelInfo | None = None,
    ) -> None:
        with self._lock:
            attempt.status = AttemptStatus.AWAITING_CONFIRMATION
            attempt.new_channel = new_channel
            if current_channel is not None:
                attempt.current_channel = current_channel
            attempt.pending_credentials = credentials
            attempt.code_verifier = None

    def claim_confirmation(self, attempt_id: str) -> tuple[OAuthAttempt, Any]:
        """Take the pending credentials of an attempt awaiting confirmation, once."""
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if attempt.status != AttemptStatus.AWAITING_CONFIRMATION or attempt.claimed:
                raise AttemptNotConfirmable()
            attempt.claimed = True
            return attempt, attempt.pending_credentials

    def cancel(self, attempt_id: str) -> OAuthAttempt:
        with self._lock:
            self._refresh_locked()
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise AttemptNotFound()
            if attempt.status == AttemptStatus.CANCELLED:
                return attempt
            if attempt.is_terminal or attempt.claimed:
                raise AttemptNotConfirmable()
            self._finish_locked(attempt, AttemptStatus.CANCELLED)
            return attempt

    def expire_for_account(self, account_id: int) -> None:
        with self._lock:
            for attempt in self._attempts.values():
                if attempt.account_id == account_id and not attempt.is_terminal:
                    self._finish_locked(attempt, AttemptStatus.EXPIRED)
