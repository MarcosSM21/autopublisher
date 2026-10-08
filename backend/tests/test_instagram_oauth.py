"""Pure Instagram Login logic: Meta App config, authorization URL, pasted redirect URL
parsing and the in-memory attempt registry."""

import json
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.instagram_oauth import (
    AttemptExpired,
    AttemptNotConfirmable,
    AttemptNotFound,
    AttemptStateInvalid,
    InstagramAttemptRegistry,
    InstagramAttemptStatus,
    InstagramIdentity,
    InstagramOAuthNotConfigured,
    InvalidRedirectUrl,
    MetaAppConfig,
    build_authorization_url,
    generate_state,
    load_meta_app_config,
    parse_redirect_url,
)
from tests.fakes import (
    FAKE_IG_APP_ID,
    FAKE_IG_APP_SECRET,
    FAKE_IG_REDIRECT_URI,
    FakeClock,
    instagram_app_config_json,
)

CONFIG = MetaAppConfig(FAKE_IG_APP_ID, FAKE_IG_APP_SECRET, FAKE_IG_REDIRECT_URI)


# --- Config ------------------------------------------------------------------------


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "instagram-app.json"
    path.write_text(content)
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    config = load_meta_app_config(_write(tmp_path, instagram_app_config_json()))

    assert config == CONFIG
    assert FAKE_IG_APP_SECRET not in repr(config)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        json.dumps({"app_secret": "s", "redirect_uri": FAKE_IG_REDIRECT_URI}),
        instagram_app_config_json(app_id=""),
        instagram_app_config_json(app_id="abc"),
        instagram_app_config_json(app_secret=""),
        instagram_app_config_json(redirect_uri="http://localhost/callback"),
        instagram_app_config_json(redirect_uri="https://localhost/callback#frag"),
        instagram_app_config_json(redirect_uri="https:///callback"),
        instagram_app_config_json(redirect_uri=""),
    ],
)
def test_invalid_config_is_not_configured(tmp_path: Path, content: str) -> None:
    with pytest.raises(InstagramOAuthNotConfigured):
        load_meta_app_config(_write(tmp_path, content))


def test_missing_config_file_is_not_configured(tmp_path: Path) -> None:
    with pytest.raises(InstagramOAuthNotConfigured):
        load_meta_app_config(tmp_path / "missing.json")


# --- Authorization URL ---------------------------------------------------------------


def test_authorization_url_has_exact_parameters() -> None:
    state = generate_state()
    url = build_authorization_url(CONFIG, state)

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://www.instagram.com/oauth/authorize"
    )
    assert "scope=instagram_business_basic%2Cinstagram_business_content_publish" in url
    params = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert params == {
        "client_id": FAKE_IG_APP_ID,
        "redirect_uri": FAKE_IG_REDIRECT_URI,
        "response_type": "code",
        "scope": "instagram_business_basic,instagram_business_content_publish",
        "state": state,
        "force_reauth": "true",
    }
    assert "code_challenge" not in url
    assert "enable_fb_login" not in url
    assert FAKE_IG_APP_SECRET not in url


def test_states_are_random_and_long() -> None:
    first, second = generate_state(), generate_state()
    assert first != second
    assert len(first) >= 43


# --- Pasted redirect URL --------------------------------------------------------------


def test_parse_success_strips_meta_suffix() -> None:
    result = parse_redirect_url(
        f"  {FAKE_IG_REDIRECT_URI}?code=abc123&state=xyz#_  ", CONFIG
    )
    assert (result.code, result.state, result.error) == ("abc123", "xyz", None)


def test_parse_success_strips_encoded_suffix() -> None:
    result = parse_redirect_url(
        f"{FAKE_IG_REDIRECT_URI}?code=abc123%23_&state=xyz", CONFIG
    )
    assert result.code == "abc123"


def test_parse_tolerates_trailing_slash() -> None:
    result = parse_redirect_url(f"{FAKE_IG_REDIRECT_URI}/?code=c&state=s", CONFIG)
    assert result.code == "c"
    config = MetaAppConfig(
        FAKE_IG_APP_ID, FAKE_IG_APP_SECRET, FAKE_IG_REDIRECT_URI + "/"
    )
    assert parse_redirect_url(f"{FAKE_IG_REDIRECT_URI}?code=c&state=s", config).code


def test_parse_denied() -> None:
    result = parse_redirect_url(
        f"{FAKE_IG_REDIRECT_URI}?error=access_denied&error_reason=user_denied"
        "&error_description=Permissions+error&state=s",
        CONFIG,
    )
    assert (result.error, result.code, result.state) == ("access_denied", None, "s")


def test_parse_other_error() -> None:
    result = parse_redirect_url(f"{FAKE_IG_REDIRECT_URI}?error=server_error", CONFIG)
    assert result.error == "server_error"
    assert result.state is None


@pytest.mark.parametrize(
    "pasted",
    [
        "https://evil.example.com/autopublisher/instagram/callback?code=c&state=s",
        "https://localhost/other/path?code=c&state=s",
        "http://localhost/autopublisher/instagram/callback?code=c&state=s",
        "https://localhost:8443/autopublisher/instagram/callback?code=c&state=s",
        "https://localhost/AUTOPUBLISHER/instagram/callback?code=c&state=s",
        f"{FAKE_IG_REDIRECT_URI}?state=s",
        f"{FAKE_IG_REDIRECT_URI}",
        "not a url",
        "",
    ],
)
def test_parse_rejects_other_addresses(pasted: str) -> None:
    with pytest.raises(InvalidRedirectUrl):
        parse_redirect_url(pasted, CONFIG)


def test_parse_accepts_explicit_default_port() -> None:
    pasted = "https://localhost:443/autopublisher/instagram/callback?code=c&state=s"
    assert parse_redirect_url(pasted, CONFIG).code == "c"


# --- Attempt registry ----------------------------------------------------------------

IDENTITY = InstagramIdentity("1784_A", "old.account", "BUSINESS")
NEW_IDENTITY = InstagramIdentity("1784_B", "new.account", "MEDIA_CREATOR")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def registry(clock: FakeClock) -> InstagramAttemptRegistry:
    return InstagramAttemptRegistry(clock.now)


def test_latest_attempt_wins(registry: InstagramAttemptRegistry) -> None:
    first = registry.create(1, "state-1")
    other_account = registry.create(2, "state-2")
    second = registry.create(1, "state-3")

    assert first.status == InstagramAttemptStatus.EXPIRED
    assert other_account.status == InstagramAttemptStatus.PENDING
    with pytest.raises(AttemptExpired):
        registry.consume_state(first.attempt_id, "state-1")
    assert registry.consume_state(second.attempt_id, "state-3") is second


def test_attempt_expires_after_ttl(
    registry: InstagramAttemptRegistry, clock: FakeClock
) -> None:
    attempt = registry.create(1, "state")
    clock.advance(timedelta(minutes=10).total_seconds())

    with pytest.raises(AttemptExpired):
        registry.consume_state(attempt.attempt_id, "state")
    assert attempt.status == InstagramAttemptStatus.EXPIRED
    assert attempt.finished_at == attempt.expires_at


def test_mismatched_state_does_not_consume(registry: InstagramAttemptRegistry) -> None:
    attempt = registry.create(1, "right-state")

    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, "wrong-state")
    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, None)
    assert attempt.status == InstagramAttemptStatus.PENDING
    assert registry.consume_state(attempt.attempt_id, "right-state") is attempt


def test_state_is_consumed_once(registry: InstagramAttemptRegistry) -> None:
    attempt = registry.create(1, "state")
    registry.consume_state(attempt.attempt_id, "state")

    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, "state")
    registry.finish(attempt, InstagramAttemptStatus.COMPLETED)
    with pytest.raises(AttemptStateInvalid):
        registry.consume_state(attempt.attempt_id, "state")


def test_unknown_attempt(registry: InstagramAttemptRegistry) -> None:
    with pytest.raises(AttemptNotFound):
        registry.consume_state("missing", "state")
    with pytest.raises(AttemptNotFound):
        registry.cancel("missing")
    with pytest.raises(AttemptNotFound):
        registry.claim_confirmation("missing")


def test_state_comparison_is_constant_time(
    registry: InstagramAttemptRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    original = secrets.compare_digest

    def recording(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return original(a, b)

    # The registry calls `secrets.compare_digest` through the module.
    monkeypatch.setattr(secrets, "compare_digest", recording)
    attempt = registry.create(1, "state")
    registry.consume_state(attempt.attempt_id, "state")

    assert calls == [(b"state", b"state")]


def test_terminal_attempts_are_kept_then_purged(
    registry: InstagramAttemptRegistry, clock: FakeClock
) -> None:
    attempt = registry.create(1, "state")
    registry.finish(
        attempt, InstagramAttemptStatus.FAILED, error={"code": "x", "message": "y"}
    )
    clock.advance(timedelta(minutes=10).total_seconds())
    assert registry.get(attempt.attempt_id) is attempt

    clock.advance(1)
    assert registry.get(attempt.attempt_id) is None


def test_secrets_are_cleared_when_finished(registry: InstagramAttemptRegistry) -> None:
    attempt = registry.create(1, "state", current_identity=IDENTITY)
    registry.await_confirmation(attempt, NEW_IDENTITY, object())
    assert attempt.pending_credentials is not None

    registry.cancel(attempt.attempt_id)

    assert attempt.state == ""
    assert attempt.pending_credentials is None


def test_confirmation_can_be_claimed_once(registry: InstagramAttemptRegistry) -> None:
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


def test_cancel_is_idempotent(registry: InstagramAttemptRegistry) -> None:
    attempt = registry.create(1, "state")
    assert registry.cancel(attempt.attempt_id).status == "cancelled"
    assert registry.cancel(attempt.attempt_id).status == "cancelled"

    finished = registry.create(1, "other")
    registry.finish(finished, InstagramAttemptStatus.COMPLETED)
    with pytest.raises(AttemptNotConfirmable):
        registry.cancel(finished.attempt_id)


def test_expire_for_account(registry: InstagramAttemptRegistry) -> None:
    mine = registry.create(1, "a")
    other = registry.create(2, "b")

    registry.expire_for_account(1)

    assert mine.status == InstagramAttemptStatus.EXPIRED
    assert mine.state == ""
    assert other.status == InstagramAttemptStatus.PENDING


def test_attempt_read_has_no_secrets(registry: InstagramAttemptRegistry) -> None:
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
        "instagram_user_id": "1784_A",
        "username": "old.account",
        "account_type": "BUSINESS",
        "profile_picture_url": None,
    }
