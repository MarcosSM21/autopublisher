"""Pure TikTok OAuth logic: config, PKCE (hex), authorization URL, callback parsing and
the attempt registry (specs/012-tiktok-oauth-connection/research.md §3–§6)."""

import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import (
    DEFAULT_TIKTOK_REDIRECT_URI,
    TIKTOK_ATTEMPT_RETENTION,
    TIKTOK_ATTEMPT_TTL,
)
from app.tiktok_oauth import (
    TIKTOK_AUTH_ENDPOINT,
    AttemptNotConfirmable,
    AttemptNotFound,
    CallbackInvalid,
    TikTokAppConfig,
    TikTokAttemptRegistry,
    TikTokAttemptStatus,
    TikTokIdentity,
    TikTokOAuthNotConfigured,
    build_authorization_url,
    extract_state,
    generate_tiktok_pkce_pair,
    load_tiktok_app_config,
    parse_callback,
    parse_scopes,
)
from tests.fakes import (
    FAKE_TT_CLIENT_KEY,
    FAKE_TT_CLIENT_SECRET,
    FakeClock,
    tiktok_app_config_json,
)

UNRESERVED = re.compile(r"^[A-Za-z0-9\-._~]+$")


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "tiktok-app.json"
    path.write_text(content)
    return path


# --- Config ------------------------------------------------------------------------


def test_config_defaults_the_redirect_uri(tmp_path: Path) -> None:
    config = load_tiktok_app_config(_write(tmp_path, tiktok_app_config_json()))

    assert config.client_key == FAKE_TT_CLIENT_KEY
    assert config.client_secret == FAKE_TT_CLIENT_SECRET
    assert config.redirect_uri == DEFAULT_TIKTOK_REDIRECT_URI
    assert DEFAULT_TIKTOK_REDIRECT_URI == (
        "http://127.0.0.1:8000/api/tiktok/oauth/callback"
    )
    assert FAKE_TT_CLIENT_SECRET not in repr(config)


@pytest.mark.parametrize(
    "uri",
    [
        "http://127.0.0.1:8000/api/tiktok/oauth/callback",
        "http://localhost:8123/api/tiktok/oauth/callback",
    ],
)
def test_config_accepts_loopback_redirect_uris(tmp_path: Path, uri: str) -> None:
    path = _write(tmp_path, tiktok_app_config_json(redirect_uri=uri))

    assert load_tiktok_app_config(path).redirect_uri == uri


def test_missing_config_is_not_configured(tmp_path: Path) -> None:
    with pytest.raises(TikTokOAuthNotConfigured):
        load_tiktok_app_config(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"client_secret": "s"}),
        json.dumps({"client_key": "k"}),
        json.dumps({"client_key": "", "client_secret": "s"}),
        json.dumps({"client_key": "k", "client_secret": ""}),
        json.dumps({"client_key": "k", "client_secret": "   "}),
        json.dumps({"client_key": 1, "client_secret": "s"}),
    ],
)
def test_invalid_config_is_not_configured(tmp_path: Path, content: str) -> None:
    with pytest.raises(TikTokOAuthNotConfigured):
        load_tiktok_app_config(_write(tmp_path, content))


@pytest.mark.parametrize(
    "uri",
    [
        "https://127.0.0.1:8000/api/tiktok/oauth/callback",
        "http://192.168.1.5:8000/api/tiktok/oauth/callback",
        "http://example.com:8000/api/tiktok/oauth/callback",
        "http://[::1]:8000/api/tiktok/oauth/callback",
        "http://127.0.0.1/api/tiktok/oauth/callback",
        "http://127.0.0.1:*/api/tiktok/oauth/callback",
        "http://127.0.0.1:8000/api/tiktok/oauth/callback/",
        "http://127.0.0.1:8000/api/tiktok/oauth",
        "http://127.0.0.1:8000/api/tiktok/oauth/callbackx",
        "http://127.0.0.1:8000/api/youtube/oauth/callback",
        "http://user@127.0.0.1:8000/api/tiktok/oauth/callback",
        "http://127.0.0.1:8000/api/tiktok/oauth/callback?x=1",
        "http://127.0.0.1:8000/api/tiktok/oauth/callback?",
        "http://127.0.0.1:8000/api/tiktok/oauth/callback#frag",
        "http://127.0.0.1:8000/api/tiktok/oauth/callback" + "x" * 470,
        "",
        42,
    ],
)
def test_invalid_redirect_uri_is_not_configured(tmp_path: Path, uri: Any) -> None:
    with pytest.raises(TikTokOAuthNotConfigured):
        load_tiktok_app_config(
            _write(tmp_path, tiktok_app_config_json(redirect_uri=uri))
        )


# --- PKCE ---------------------------------------------------------------------------


def test_pkce_pair_uses_a_hex_sha256_challenge() -> None:
    verifier, challenge = generate_tiktok_pkce_pair()

    assert len(verifier) == 64
    assert UNRESERVED.match(verifier)
    assert re.fullmatch(r"[0-9a-f]{64}", challenge)
    assert challenge == hashlib.sha256(verifier.encode("ascii")).hexdigest()
    # Explicitly not base64url (TikTok Desktop documents hex encoding).
    assert "-" not in challenge and "_" not in challenge


def test_pkce_known_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    # RFC 7636 appendix B verifier: its base64url challenge is
    # E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM; TikTok expects the hex digest.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    monkeypatch.setattr("app.tiktok_oauth.secrets.token_urlsafe", lambda _: verifier)

    assert generate_tiktok_pkce_pair() == (
        verifier,
        "13d31e961a1ad8ec2f16b10c4c982e0876a878ad6df144566ee1894acb70f9c3",
    )


def test_pkce_pairs_are_new_each_time() -> None:
    pairs = {generate_tiktok_pkce_pair() for _ in range(5)}

    assert len(pairs) == 5


# --- Authorization URL --------------------------------------------------------------


def test_authorization_url_has_exactly_the_documented_params() -> None:
    config = TikTokAppConfig(FAKE_TT_CLIENT_KEY, FAKE_TT_CLIENT_SECRET)

    url = build_authorization_url(config, "the-state", "a" * 64)

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == TIKTOK_AUTH_ENDPOINT
    assert parse_qs(parts.query) == {
        "client_key": [FAKE_TT_CLIENT_KEY],
        "scope": ["user.info.basic,video.publish,video.upload"],
        "response_type": ["code"],
        "redirect_uri": [DEFAULT_TIKTOK_REDIRECT_URI],
        "state": ["the-state"],
        "code_challenge": ["a" * 64],
        "code_challenge_method": ["S256"],
    }
    assert FAKE_TT_CLIENT_SECRET not in url


def test_parse_scopes_splits_and_trims() -> None:
    assert parse_scopes("user.info.basic, video.publish ,") == frozenset(
        {"user.info.basic", "video.publish"}
    )
    assert parse_scopes("") == frozenset()


# --- Callback parsing ---------------------------------------------------------------


def test_callback_with_code_only() -> None:
    result = parse_callback([("code", "c"), ("state", "s")])

    assert (result.code, result.state, result.error) == ("c", "s", None)
    assert "c" not in repr(result).replace("CallbackResult", "")


def test_callback_with_code_and_scopes_ignores_undocumented_params() -> None:
    result = parse_callback(
        [
            ("code", "c"),
            ("scopes", "user.info.basic,video.publish"),
            ("state", "s"),
            ("utm", "1"),
            ("utm", "2"),
        ]
    )

    assert (result.code, result.state) == ("c", "s")


@pytest.mark.parametrize("error", ["access_denied", "server_error"])
def test_callback_with_error(error: str) -> None:
    result = parse_callback(
        [("error", error), ("error_description", "free text"), ("state", "s")]
    )

    assert (result.code, result.error) == (None, error)


@pytest.mark.parametrize(
    "items",
    [
        [("code", "c"), ("code", "d"), ("state", "s")],
        [("code", "c"), ("state", "s"), ("state", "s")],
        [("error", "x"), ("error", "y"), ("state", "s")],
        [("code", "c"), ("scopes", "a"), ("scopes", "b"), ("state", "s")],
        [
            ("error", "x"),
            ("error_description", "a"),
            ("error_description", "b"),
            ("state", "s"),
        ],
        [("code", "c"), ("error", "x"), ("state", "s")],
        [("state", "s")],
        [("code", ""), ("state", "s")],
        [("code", "c" * 1025), ("state", "s")],
        [("error", ""), ("state", "s")],
        [("code", "c")],
        [("code", "c"), ("state", "")],
    ],
)
def test_invalid_callbacks_are_rejected(items: list[tuple[str, str]]) -> None:
    with pytest.raises(CallbackInvalid):
        parse_callback(items)


def test_extract_state_needs_exactly_one_value() -> None:
    assert extract_state([("state", "s"), ("code", "c")]) == "s"
    assert extract_state([("code", "c")]) is None
    assert extract_state([("state", "")]) is None
    assert extract_state([("state", "a"), ("state", "b")]) is None


def test_identity_views() -> None:
    identity = TikTokIdentity("open-id-123456", "Cyber", None)

    assert identity.suffix == "123456"
    assert identity.to_read() == {
        "open_id": "open-id-123456",
        "display_name": "Cyber",
        "avatar_url": None,
    }
    assert identity.to_attempt_read() == {
        "display_name": "Cyber",
        "avatar_url": None,
        "open_id_suffix": "123456",
    }


# --- Attempt registry ---------------------------------------------------------------


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def discarded() -> list[tuple[Any, int]]:
    return []


@pytest.fixture
def registry(
    clock: FakeClock, discarded: list[tuple[Any, int]]
) -> TikTokAttemptRegistry:
    return TikTokAttemptRegistry(
        clock.now,
        discard=lambda credential, account_id: discarded.append(
            (credential, account_id)
        ),
    )


def test_consume_state_hands_out_the_verifier_once(
    registry: TikTokAttemptRegistry,
) -> None:
    attempt = registry.create(7, "state-1", "verifier-1")

    consumed = registry.consume_state("state-1")

    assert consumed is not None
    assert consumed[0] is attempt
    assert consumed[1] == "verifier-1"
    assert attempt.status == TikTokAttemptStatus.PROCESSING
    assert attempt.code_verifier is None
    assert registry.consume_state("state-1") is None
    assert registry.consume_state("unknown") is None


def test_latest_attempt_wins(registry: TikTokAttemptRegistry) -> None:
    first = registry.create(7, "state-1", "v1")
    second = registry.create(7, "state-2", "v2")
    other = registry.create(8, "state-3", "v3")

    assert first.status == TikTokAttemptStatus.EXPIRED
    assert registry.consume_state("state-1") is None
    assert second.status == TikTokAttemptStatus.PENDING
    assert other.status == TikTokAttemptStatus.PENDING


def test_ttl_expiry_and_retention(
    registry: TikTokAttemptRegistry, clock: FakeClock
) -> None:
    attempt = registry.create(7, "state-1", "v1")

    clock.advance(TIKTOK_ATTEMPT_TTL.total_seconds())

    assert registry.consume_state("state-1") is None
    assert attempt.status == TikTokAttemptStatus.EXPIRED
    assert attempt.code_verifier is None
    assert registry.get(attempt.attempt_id) is attempt
    clock.advance(TIKTOK_ATTEMPT_RETENTION.total_seconds() + 1)
    assert registry.get(attempt.attempt_id) is None


def test_processing_attempts_do_not_expire(
    registry: TikTokAttemptRegistry, clock: FakeClock
) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")

    clock.advance(TIKTOK_ATTEMPT_TTL.total_seconds() + 60)
    registry.create(7, "state-2", "v2")
    registry.expire_for_account(7)

    assert attempt.status == TikTokAttemptStatus.PROCESSING


def test_finished_attempts_are_kept_then_purged(
    registry: TikTokAttemptRegistry, clock: FakeClock
) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")
    registry.finish(
        attempt, TikTokAttemptStatus.FAILED, error={"code": "x", "message": "m"}
    )

    clock.advance(TIKTOK_ATTEMPT_RETENTION.total_seconds())
    assert registry.get(attempt.attempt_id) is attempt
    clock.advance(1)
    assert registry.get(attempt.attempt_id) is None


def test_confirmation_is_claimed_once(registry: TikTokAttemptRegistry) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")
    registry.await_confirmation(attempt, TikTokIdentity("new"), "credential")

    claimed, credential = registry.claim_confirmation(attempt.attempt_id)

    assert claimed is attempt
    assert credential == "credential"
    with pytest.raises(AttemptNotConfirmable):
        registry.claim_confirmation(attempt.attempt_id)
    with pytest.raises(AttemptNotFound):
        registry.claim_confirmation("unknown")


def test_cancel_pending_and_is_idempotent(registry: TikTokAttemptRegistry) -> None:
    attempt = registry.create(7, "state-1", "v1")

    assert registry.cancel(attempt.attempt_id).status == TikTokAttemptStatus.CANCELLED
    assert registry.cancel(attempt.attempt_id).status == TikTokAttemptStatus.CANCELLED
    assert registry.consume_state("state-1") is None
    with pytest.raises(AttemptNotFound):
        registry.cancel("unknown")


def test_cancel_is_rejected_while_processing_or_finished(
    registry: TikTokAttemptRegistry,
) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")

    with pytest.raises(AttemptNotConfirmable):
        registry.cancel(attempt.attempt_id)
    registry.finish(attempt, TikTokAttemptStatus.COMPLETED)
    with pytest.raises(AttemptNotConfirmable):
        registry.cancel(attempt.attempt_id)


def test_cancel_awaiting_discards_the_pending_credential(
    registry: TikTokAttemptRegistry, discarded: list[tuple[Any, int]]
) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")
    registry.await_confirmation(attempt, TikTokIdentity("new"), "credential")

    registry.cancel(attempt.attempt_id)

    assert discarded == [("credential", 7)]
    assert attempt.pending_credential is None


def test_expiry_of_awaiting_discards_the_pending_credential(
    registry: TikTokAttemptRegistry,
    clock: FakeClock,
    discarded: list[tuple[Any, int]],
) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")
    registry.await_confirmation(attempt, TikTokIdentity("new"), "credential")

    clock.advance(TIKTOK_ATTEMPT_TTL.total_seconds() + 1)
    registry.get(attempt.attempt_id)

    assert attempt.status == TikTokAttemptStatus.EXPIRED
    assert discarded == [("credential", 7)]
    assert attempt.pending_credential is None


def test_claimed_credential_is_never_discarded(
    registry: TikTokAttemptRegistry, discarded: list[tuple[Any, int]]
) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")
    registry.await_confirmation(attempt, TikTokIdentity("new"), "credential")
    registry.claim_confirmation(attempt.attempt_id)

    registry.finish(attempt, TikTokAttemptStatus.COMPLETED)

    assert discarded == []


def test_expire_for_account(registry: TikTokAttemptRegistry) -> None:
    mine = registry.create(7, "state-1", "v1")
    other = registry.create(8, "state-2", "v2")

    registry.expire_for_account(7)

    assert mine.status == TikTokAttemptStatus.EXPIRED
    assert other.status == TikTokAttemptStatus.PENDING


def test_expire_for_account_discards_an_awaiting_credential_by_default(
    registry: TikTokAttemptRegistry, discarded: list[tuple[Any, int]]
) -> None:
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")
    registry.await_confirmation(attempt, TikTokIdentity("new"), "credential")

    registry.expire_for_account(7)

    assert discarded == [("credential", 7)]


def test_expire_for_account_without_revoke_never_contacts_tiktok(
    clock: FakeClock,
) -> None:
    """A deleted account (Feature 021): the pending credential is dropped in memory
    and the discard (revocation) callback is never called."""

    def discard(credential: Any, account_id: int) -> None:
        pytest.fail("TikTok must not be contacted")

    registry = TikTokAttemptRegistry(clock.now, discard=discard)
    attempt = registry.create(7, "state-1", "v1")
    registry.consume_state("state-1")
    registry.await_confirmation(attempt, TikTokIdentity("new"), "credential")

    registry.expire_for_account(7, revoke=False)

    assert attempt.status == TikTokAttemptStatus.EXPIRED
    assert attempt.pending_credential is None


def test_attempt_view_has_no_secrets(registry: TikTokAttemptRegistry) -> None:
    attempt = registry.create(
        7, "state-secret", "verifier-secret", TikTokIdentity("open-id-abcdef", "Old")
    )
    registry.consume_state("state-secret")
    registry.await_confirmation(
        attempt, TikTokIdentity("open-id-123456", "New"), "credential-secret"
    )

    view = attempt.to_read()

    text = repr(view) + repr(attempt)
    for secret in ("state-secret", "verifier-secret", "credential-secret"):
        assert secret not in text
    assert view["current_identity"]["open_id_suffix"] == "abcdef"
    assert view["new_identity"] == {
        "display_name": "New",
        "avatar_url": None,
        "open_id_suffix": "123456",
    }
    assert view["expires_at"] - attempt.created_at == timedelta(minutes=10)


def test_requested_scopes_are_exactly_base_plus_video_upload() -> None:
    """Feature 014 adds `video.upload` (Upload to Inbox) to the Feature 012 scopes;
    renewals keep requiring the base ones only; `video.list` and any other scope are
    never requested."""
    from urllib.parse import parse_qs, urlsplit

    from app.tiktok_oauth import (
        REQUESTED_SCOPES,
        REQUIRED_SCOPES,
        build_authorization_url,
    )

    assert REQUESTED_SCOPES == ("user.info.basic", "video.publish", "video.upload")
    assert REQUIRED_SCOPES == {"user.info.basic", "video.publish"}
    url = build_authorization_url(TikTokAppConfig("key", "secret"), "state", "c" * 43)
    scope = parse_qs(urlsplit(url).query)["scope"][0]
    assert scope.split(",") == ["user.info.basic", "video.publish", "video.upload"]
    assert "video.list" not in url
