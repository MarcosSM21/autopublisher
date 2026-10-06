import base64
import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import get_google_oauth_client_file, get_oauth_redirect_uri
from app.youtube_oauth import (
    ChannelInfo,
    OAuthAttemptRegistry,
    OAuthNotConfigured,
    build_authorization_url,
    generate_pkce_pair,
    generate_state,
    load_client_config,
)
from tests.fakes import FAKE_CLIENT_ID, FAKE_CLIENT_SECRET, client_config_json

VERIFIER_ALPHABET = re.compile(r"^[A-Za-z0-9\-._~]+$")


def test_pkce_pair_uses_s256() -> None:
    verifier, challenge = generate_pkce_pair()

    assert 43 <= len(verifier) <= 128
    assert VERIFIER_ALPHABET.match(verifier)
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert generate_pkce_pair()[0] != verifier


def test_state_is_long_and_unique() -> None:
    state = generate_state()
    assert len(state) >= 43
    assert generate_state() != state


def test_authorization_url_has_exactly_the_expected_parameters() -> None:
    verifier, challenge = generate_pkce_pair()
    url = build_authorization_url(
        FAKE_CLIENT_ID, "http://127.0.0.1:8000/cb", "the-state", challenge
    )

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    params = parse_qs(parts.query)
    assert {key: values[0] for key, values in params.items()} == {
        "response_type": "code",
        "client_id": FAKE_CLIENT_ID,
        "redirect_uri": "http://127.0.0.1:8000/cb",
        "scope": "https://www.googleapis.com/auth/youtube.readonly "
        "https://www.googleapis.com/auth/youtube.upload",
        "state": "the-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "select_account consent",
    }
    assert verifier not in url
    assert "include_granted_scopes" not in url


def _write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def test_load_client_config_accepts_a_desktop_client(tmp_path: Path) -> None:
    config = load_client_config(_write(tmp_path / "c.json", client_config_json()))
    assert config.client_id == FAKE_CLIENT_ID
    assert config.client_secret == FAKE_CLIENT_SECRET
    assert FAKE_CLIENT_SECRET not in repr(config)


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not json",
        '{"web": {"client_id": "a", "client_secret": "b"}}',
        '{"installed": {"client_secret": "b"}}',
        '{"installed": {"client_id": "a"}}',
        '{"installed": {"client_id": "", "client_secret": "b"}}',
        "[]",
    ],
)
def test_load_client_config_rejects_unusable_files(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / "c.json"
    if content is not None:
        path.write_text(content)
    with pytest.raises(OAuthNotConfigured) as error:
        load_client_config(path)
    assert str(path) not in str(error.value)


def test_client_file_path_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE", raising=False)
    assert get_google_oauth_client_file().parts[-2:] == (
        "data",
        "google-oauth-client.json",
    )
    monkeypatch.setenv("AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE", "/tmp/x.json")
    assert get_google_oauth_client_file() == Path("/tmp/x.json")


def test_redirect_uri_defaults_to_the_backend_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTOPUBLISHER_OAUTH_REDIRECT_URI", raising=False)
    assert get_oauth_redirect_uri() == (
        "http://127.0.0.1:8000/api/youtube/oauth/callback"
    )
    monkeypatch.setenv("AUTOPUBLISHER_OAUTH_REDIRECT_URI", "http://[::1]:9000/x")
    assert get_oauth_redirect_uri() == "http://[::1]:9000/x"


@pytest.mark.parametrize(
    "uri",
    [
        "https://127.0.0.1:8000/cb",
        "http://localhost:8000/cb",
        "http://example.com/cb",
        "http://192.168.1.10:8000/cb",
    ],
)
def test_redirect_uri_must_be_http_loopback_ip(
    monkeypatch: pytest.MonkeyPatch, uri: str
) -> None:
    monkeypatch.setenv("AUTOPUBLISHER_OAUTH_REDIRECT_URI", uri)
    with pytest.raises(ValueError):
        get_oauth_redirect_uri()


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2100, 1, 1, 10, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def registry(clock: Clock) -> OAuthAttemptRegistry:
    return OAuthAttemptRegistry(clock=clock)


def test_create_returns_a_pending_attempt(
    registry: OAuthAttemptRegistry, clock: Clock
) -> None:
    attempt = registry.create(1, "state-1", "verifier-1")
    assert attempt.status == "pending"
    assert attempt.expires_at == clock.now + timedelta(minutes=10)
    assert attempt.account_id == 1


def test_state_is_single_use(registry: OAuthAttemptRegistry) -> None:
    attempt = registry.create(1, "state-1", "verifier-1")
    assert registry.consume_state("state-1") is attempt
    assert registry.consume_state("state-1") is None
    assert registry.consume_state("unknown") is None


def test_expiry_and_retention_rule(
    registry: OAuthAttemptRegistry, clock: Clock
) -> None:
    attempt = registry.create(1, "state-1", "verifier-1")
    clock.advance(minutes=10, seconds=1)

    assert registry.consume_state("state-1") is None
    expired = registry.get(attempt.attempt_id)
    assert expired is not None
    assert expired.status == "expired"
    assert expired.finished_at is not None
    assert expired.code_verifier is None

    finished_at = expired.finished_at
    clock.now = finished_at + timedelta(minutes=9, seconds=59)
    assert registry.get(attempt.attempt_id) is not None
    clock.now = finished_at + timedelta(minutes=10, seconds=1)
    assert registry.get(attempt.attempt_id) is None


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_attempts_are_retained_ten_minutes(
    registry: OAuthAttemptRegistry, clock: Clock, status: str
) -> None:
    attempt = registry.create(1, "state-1", "verifier-1")
    registry.finish(attempt, status)
    clock.advance(minutes=9, seconds=59)
    kept = registry.get(attempt.attempt_id)
    assert kept is not None and kept.status == status
    clock.advance(seconds=2)
    assert registry.get(attempt.attempt_id) is None


def test_new_attempt_expires_the_previous_one_of_the_account(
    registry: OAuthAttemptRegistry,
) -> None:
    first = registry.create(1, "state-1", "verifier-1")
    other = registry.create(2, "state-2", "verifier-2")
    registry.create(1, "state-3", "verifier-3")

    assert first.status == "expired"
    assert registry.consume_state("state-1") is None
    assert other.status == "pending"


def test_terminal_transitions_clear_secrets(registry: OAuthAttemptRegistry) -> None:
    attempt = registry.create(1, "state-1", "verifier-1")
    channel = ChannelInfo("UC1", "New", None, None)
    registry.await_confirmation(attempt, channel, object())
    assert attempt.status == "awaiting_confirmation"
    assert attempt.code_verifier is None
    assert attempt.pending_credentials is not None

    registry.finish(attempt, "cancelled")
    assert attempt.pending_credentials is None
    public = attempt.to_read()
    assert set(public) == {
        "attempt_id",
        "account_id",
        "status",
        "expires_at",
        "error",
        "current_channel",
        "new_channel",
        "connection",
    }
    assert "verifier-1" not in repr(public)


def test_expire_for_account(registry: OAuthAttemptRegistry) -> None:
    attempt = registry.create(1, "state-1", "verifier-1")
    registry.expire_for_account(1)
    assert attempt.status == "expired"
    assert registry.consume_state("state-1") is None
