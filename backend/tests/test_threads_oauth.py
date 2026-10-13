"""Pure Threads OAuth logic: app config, authorization URL, strict parsing of the pasted
redirect URL and the in-memory attempt registry."""

import json
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.threads_oauth import (
    AttemptExpired,
    AttemptNotConfirmable,
    AttemptNotFound,
    AttemptStateInvalid,
    InvalidRedirectUrl,
    ThreadsAppConfig,
    ThreadsAttemptRegistry,
    ThreadsAttemptStatus,
    ThreadsIdentity,
    ThreadsOAuthNotConfigured,
    build_authorization_url,
    generate_state,
    load_threads_app_config,
    parse_redirect_url,
)
from tests.fakes import (
    FAKE_TH_APP_ID,
    FAKE_TH_APP_SECRET,
    FAKE_TH_REDIRECT_URI,
    FakeClock,
    threads_app_config_json,
)

CONFIG = ThreadsAppConfig(FAKE_TH_APP_ID, FAKE_TH_APP_SECRET, FAKE_TH_REDIRECT_URI)


# --- Config ------------------------------------------------------------------------


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "threads-app.json"
    path.write_text(content)
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    config = load_threads_app_config(_write(tmp_path, threads_app_config_json()))

    assert config == CONFIG
    assert FAKE_TH_APP_SECRET not in repr(config)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        json.dumps({"app_secret": "s", "redirect_uri": FAKE_TH_REDIRECT_URI}),
        threads_app_config_json(app_id=""),
        threads_app_config_json(app_id="abc"),
        threads_app_config_json(app_secret=""),
        threads_app_config_json(redirect_uri="http://localhost/callback"),
        threads_app_config_json(redirect_uri="https:///callback"),
        threads_app_config_json(redirect_uri="https://user@localhost/callback"),
        threads_app_config_json(redirect_uri="https://localhost/callback?x=1"),
        threads_app_config_json(redirect_uri="https://localhost/callback#frag"),
        threads_app_config_json(redirect_uri="https://localhost:99999/callback"),
        threads_app_config_json(redirect_uri=""),
    ],
)
def test_invalid_config_is_not_configured(tmp_path: Path, content: str) -> None:
    with pytest.raises(ThreadsOAuthNotConfigured):
        load_threads_app_config(_write(tmp_path, content))


def test_missing_config_file_is_not_configured(tmp_path: Path) -> None:
    with pytest.raises(ThreadsOAuthNotConfigured):
        load_threads_app_config(tmp_path / "missing.json")


# --- Authorization URL ---------------------------------------------------------------


def test_authorization_url_has_exact_parameters() -> None:
    state = generate_state()
    url = build_authorization_url(CONFIG, state)

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://threads.com/oauth/authorize"
    )
    assert "scope=threads_basic%2Cthreads_content_publish" in url
    params = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert params == {
        "client_id": FAKE_TH_APP_ID,
        "redirect_uri": FAKE_TH_REDIRECT_URI,
        "scope": "threads_basic,threads_content_publish",
        "response_type": "code",
        "state": state,
    }
    assert "code_challenge" not in url
    assert FAKE_TH_APP_SECRET not in url


def test_states_are_random_and_long() -> None:
    first, second = generate_state(), generate_state()
    assert first != second
    assert len(first) >= 43


# --- Pasted redirect URL --------------------------------------------------------------


def test_parse_success_ignores_meta_suffix() -> None:
    result = parse_redirect_url(
        f"  {FAKE_TH_REDIRECT_URI}?code=abc123&state=xyz#_  ", CONFIG
    )
    assert (result.code, result.state, result.error) == ("abc123", "xyz", None)


def test_parse_success_strips_encoded_suffix() -> None:
    result = parse_redirect_url(
        f"{FAKE_TH_REDIRECT_URI}?code=abc123%23_&state=xyz", CONFIG
    )
    assert result.code == "abc123"


def test_parse_denied() -> None:
    result = parse_redirect_url(
        f"{FAKE_TH_REDIRECT_URI}?error=access_denied&error_reason=user_denied"
        "&error_description=Permissions+error&state=s",
        CONFIG,
    )
    assert (result.error, result.code, result.state) == ("access_denied", None, "s")


def test_parse_other_error() -> None:
    result = parse_redirect_url(f"{FAKE_TH_REDIRECT_URI}?error=server_error", CONFIG)
    assert result.error == "server_error"
    assert result.state is None


@pytest.mark.parametrize(
    "pasted",
    [
        # Unparseable or not a URL.
        "not a url",
        "",
        "https://localhost:99999/autopublisher/threads/callback?code=c&state=s",
        # Different scheme.
        "http://localhost/autopublisher/threads/callback?code=c&state=s",
        # Host sharing a textual prefix, or the expected host in the path.
        "https://localhost.evil.example/autopublisher/threads/callback?code=c&state=s",
        "https://evil.example/localhost/autopublisher/threads/callback?code=c&state=s",
        # Port not configured.
        "https://localhost:8443/autopublisher/threads/callback?code=c&state=s",
        # Paths sharing a prefix, or with a trailing slash that is not configured.
        "https://localhost/autopublisher/threads/callback-other?code=c&state=s",
        "https://localhost/autopublisher/threads/callback/extra?code=c&state=s",
        "https://localhost/autopublisher/threads/callback/?code=c&state=s",
        "https://localhost/autopublisher/threads/?code=c&state=s",
        "https://localhost/AUTOPUBLISHER/threads/callback?code=c&state=s",
        # Credentials in the URL.
        "https://user@localhost/autopublisher/threads/callback?code=c&state=s",
        "https://user:pw@localhost/autopublisher/threads/callback?code=c&state=s",
        # Duplicated parameters.
        f"{FAKE_TH_REDIRECT_URI}?code=c&code=d&state=s",
        f"{FAKE_TH_REDIRECT_URI}?code=c&state=s&state=t",
        f"{FAKE_TH_REDIRECT_URI}?error=a&error=b",
        # Neither code nor error.
        f"{FAKE_TH_REDIRECT_URI}?state=s",
        f"{FAKE_TH_REDIRECT_URI}?code=&state=s",
        f"{FAKE_TH_REDIRECT_URI}",
        # Parameters only in the fragment are not read.
        f"{FAKE_TH_REDIRECT_URI}#code=c&state=s",
    ],
)
def test_parse_rejects_other_addresses(pasted: str) -> None:
    with pytest.raises(InvalidRedirectUrl):
        parse_redirect_url(pasted, CONFIG)


def test_parse_accepts_explicit_default_port_and_case_insensitive_host() -> None:
    explicit = "https://localhost:443/autopublisher/threads/callback?code=c&state=s"
    assert parse_redirect_url(explicit, CONFIG).code == "c"
    upper = "HTTPS://LOCALHOST/autopublisher/threads/callback?code=c&state=s"
    assert parse_redirect_url(upper, CONFIG).code == "c"


def test_parse_requires_the_configured_port() -> None:
    config = ThreadsAppConfig(
        FAKE_TH_APP_ID, FAKE_TH_APP_SECRET, "https://localhost:8443/cb"
    )
    assert parse_redirect_url("https://localhost:8443/cb?code=c&state=s", config).code
    with pytest.raises(InvalidRedirectUrl):
        parse_redirect_url("https://localhost/cb?code=c&state=s", config)


def test_parse_trailing_slash_only_when_configured() -> None:
    config = ThreadsAppConfig(
        FAKE_TH_APP_ID, FAKE_TH_APP_SECRET, FAKE_TH_REDIRECT_URI + "/"
    )
    assert parse_redirect_url(f"{FAKE_TH_REDIRECT_URI}/?code=c&state=s", config).code
    with pytest.raises(InvalidRedirectUrl):
        parse_redirect_url(f"{FAKE_TH_REDIRECT_URI}?code=c&state=s", config)


# --- Attempt registry ----------------------------------------------------------------

IDENTITY = ThreadsIdentity("2584_A", "old.account")
NEW_IDENTITY = ThreadsIdentity("2584_B", "new.account", "New")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def registry(clock: FakeClock) -> ThreadsAttemptRegistry:
    return ThreadsAttemptRegistry(clock.now)


def test_latest_attempt_wins(registry: ThreadsAttemptRegistry) -> None:
    first = registry.create(1, "state-1")
    other_account = registry.create(2, "state-2")
    second = registry.create(1, "state-3")

    assert first.status == ThreadsAttemptStatus.EXPIRED
    assert other_account.status == ThreadsAttemptStatus.PENDING
    with pytest.raises(AttemptExpired):
        registry.consume_state(first.attempt_id, "state-1")
    assert registry.consume_state(second.attempt_id, "state-3") is second


def test_attempt_expires_after_ttl(
    registry: ThreadsAttemptRegistry, clock: FakeClock
) -> None:
    attempt = registry.create(1, "state")
    clock.advance(timedelta(minutes=10).total_seconds())

    with pytest.raises(AttemptExpired):
        registry.consume_state(attempt.attempt_id, "state")
    assert attempt.status == ThreadsAttemptStatus.EXPIRED
    assert attempt.finished_at == attempt.expires_at


def test_mismatched_state_does_not_consume(registry: ThreadsAttemptRegistry) -> None:
    attempt = registry.create(1, "right-state")

    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, "wrong-state")
    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, None)
    assert attempt.status == ThreadsAttemptStatus.PENDING
    assert registry.consume_state(attempt.attempt_id, "right-state") is attempt


def test_state_is_consumed_once(registry: ThreadsAttemptRegistry) -> None:
    attempt = registry.create(1, "state")
    registry.consume_state(attempt.attempt_id, "state")

    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, "state")
    registry.finish(attempt, ThreadsAttemptStatus.COMPLETED)
    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, "state")


def test_unknown_attempt(registry: ThreadsAttemptRegistry) -> None:
    with pytest.raises(AttemptNotFound):
        registry.consume_state("missing", "state")
    with pytest.raises(AttemptNotFound):
        registry.cancel("missing")
    with pytest.raises(AttemptNotFound):
        registry.claim_confirmation("missing")


def test_state_comparison_is_constant_time(
    registry: ThreadsAttemptRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    original = secrets.compare_digest

    def recording(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(secrets, "compare_digest", recording)
    attempt = registry.create(1, "state")
    registry.consume_state(attempt.attempt_id, "state")

    assert calls == [(b"state", b"state")]


def test_terminal_attempts_are_kept_then_purged(
    registry: ThreadsAttemptRegistry, clock: FakeClock
) -> None:
    attempt = registry.create(1, "state")
    registry.finish(
        attempt, ThreadsAttemptStatus.FAILED, error={"code": "x", "message": "y"}
    )
    clock.advance(timedelta(minutes=10).total_seconds())
    assert registry.get(attempt.attempt_id) is attempt

    clock.advance(1)
    assert registry.get(attempt.attempt_id) is None


def test_secrets_are_cleared_when_finished(registry: ThreadsAttemptRegistry) -> None:
    attempt = registry.create(1, "state", current_identity=IDENTITY)
    registry.await_confirmation(attempt, NEW_IDENTITY, object())
    assert attempt.pending_credentials is not None

    registry.cancel(attempt.attempt_id)

    assert attempt.state == ""
    assert attempt.pending_credentials is None


def test_confirmation_can_be_claimed_once(registry: ThreadsAttemptRegistry) -> None:
    attempt = registry.create(1, "state", current_identity=IDENTITY)
    with pytest.raises(AttemptNotConfirmable):
        registry.claim_confirmation(attempt.attempt_id)
    credentials = object()
    registry.await_confirmation(attempt, NEW_IDENTITY, credentials)

    claimed, pending = registry.claim_confirmation(attempt.attempt_id)

    assert claimed is attempt
    assert pending is credentials
    with pytest.raises(AttemptNotConfirmable):
        registry.claim_confirmation(attempt.attempt_id)
    with pytest.raises(AttemptNotConfirmable):
        registry.cancel(attempt.attempt_id)


def test_cancel_is_idempotent(registry: ThreadsAttemptRegistry) -> None:
    attempt = registry.create(1, "state")
    assert registry.cancel(attempt.attempt_id).status == "cancelled"
    assert registry.cancel(attempt.attempt_id).status == "cancelled"

    finished = registry.create(1, "other")
    registry.finish(finished, ThreadsAttemptStatus.COMPLETED)
    with pytest.raises(AttemptNotConfirmable):
        registry.cancel(finished.attempt_id)


def test_expire_for_account(registry: ThreadsAttemptRegistry) -> None:
    mine = registry.create(1, "a")
    other = registry.create(2, "b")

    registry.expire_for_account(1)

    assert mine.status == ThreadsAttemptStatus.EXPIRED
    assert mine.state == ""
    assert other.status == ThreadsAttemptStatus.PENDING


def test_attempt_read_has_no_secrets(registry: ThreadsAttemptRegistry) -> None:
    attempt = registry.create(1, "secret-state-value", current_identity=IDENTITY)
    read = attempt.to_read()

    assert set(read) == {
        "attempt_id",
        "account_id",
        "status",
        "expires_at",
        "error",
        "current_identity",
        "new_identity",
        "connection",
    }
    assert "secret-state-value" not in json.dumps(read, default=str)
    assert "secret-state-value" not in repr(attempt)
    assert read["current_identity"] == {
        "threads_user_id": "2584_A",
        "username": "old.account",
        "display_name": None,
        "profile_picture_url": None,
    }
