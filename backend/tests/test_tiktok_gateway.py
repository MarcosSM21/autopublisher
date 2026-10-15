"""TikTok gateway contract against FakeTikTok: form bodies, response parsing and the
error classification of research §14 (tested only here)."""

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
import pytest

from app.tiktok_gateway import (
    TOKEN_ENDPOINT,
    TikTokClientError,
    TikTokCredential,
    TikTokError,
    TikTokGateway,
    TikTokGrantInvalid,
    TikTokRejected,
    TikTokScopeMissing,
    TikTokTokenInvalid,
    TikTokUnavailable,
    TikTokUnexpectedResponse,
)
from app.tiktok_oauth import TikTokAppConfig
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_CLIENT_KEY,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_CODE,
    FAKE_TT_ERROR_TEXT,
    FAKE_TT_LOG_ID,
    FAKE_TT_OPEN_ID,
    FAKE_TT_REDIRECT_URI,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    FAKE_TT_ROTATED_REFRESH_TOKEN,
    TT_ACCESS_SECONDS,
    TT_REFRESH_SECONDS,
    TT_REVOKE_URL,
    TT_USER_INFO_URL,
    FakeClock,
    FakeTikTok,
)

VERIFIER = "v" * 64
CONFIG = TikTokAppConfig(FAKE_TT_CLIENT_KEY, FAKE_TT_CLIENT_SECRET)
SECRETS = (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_CODE,
    FAKE_TT_CLIENT_SECRET,
    VERIFIER,
    FAKE_TT_ERROR_TEXT,
    "open.tiktokapis.com",
)


@pytest.fixture
def fake() -> FakeTikTok:
    fake = FakeTikTok()
    fake.register_challenge(hashlib.sha256(VERIFIER.encode()).hexdigest())
    return fake


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 14, 10, tzinfo=UTC))


@pytest.fixture
def gateway(fake: FakeTikTok, clock: FakeClock) -> Iterator[TikTokGateway]:
    with httpx.Client(transport=fake.transport()) as client:
        yield TikTokGateway(client, clock.now)


def _credential(**overrides: object) -> TikTokCredential:
    now = datetime(2026, 10, 14, 10, tzinfo=UTC)
    values: dict[str, object] = {
        "open_id": FAKE_TT_OPEN_ID,
        "access_token": FAKE_TT_ACCESS_TOKEN,
        "refresh_token": FAKE_TT_REFRESH_TOKEN,
        "access_expires_at": now + timedelta(days=1),
        "refresh_expires_at": now + timedelta(days=365),
        "scopes": frozenset({"user.info.basic", "video.publish"}),
        "scopes_source": "token_exchange",
        "obtained_at": now,
    }
    values.update(overrides)
    return TikTokCredential(**values)  # type: ignore[arg-type]


def _assert_safe(error: TikTokError) -> None:
    text = str(error) + repr(error) + repr(error.args)
    for secret in SECRETS:
        assert secret not in text
    # Nothing chained: httpx errors carry the URL.
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__


# --- Exchange ------------------------------------------------------------------------


def test_exchange_sends_the_documented_form(
    gateway: TikTokGateway, fake: FakeTikTok, clock: FakeClock
) -> None:
    credential = gateway.exchange_code(FAKE_TT_CODE, VERIFIER, CONFIG)

    [request] = fake.requests
    assert request.method == "POST"
    assert request.url == TOKEN_ENDPOINT
    assert request.form == {
        "client_key": FAKE_TT_CLIENT_KEY,
        "client_secret": FAKE_TT_CLIENT_SECRET,
        "code": FAKE_TT_CODE,
        "grant_type": "authorization_code",
        "redirect_uri": FAKE_TT_REDIRECT_URI,
        "code_verifier": VERIFIER,
    }
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert request.headers["cache-control"] == "no-cache"
    now = clock.now()
    assert credential.open_id == FAKE_TT_OPEN_ID
    assert credential.access_token == FAKE_TT_ACCESS_TOKEN
    assert credential.refresh_token == FAKE_TT_REFRESH_TOKEN
    assert credential.obtained_at == now
    assert credential.access_expires_at == now + timedelta(seconds=TT_ACCESS_SECONDS)
    assert credential.refresh_expires_at == now + timedelta(seconds=TT_REFRESH_SECONDS)
    assert credential.scopes == frozenset(
        {"user.info.basic", "video.publish", "video.upload"}
    )
    assert credential.scopes_source == "token_exchange"
    assert credential.has_required_scopes()
    assert credential.has_requested_scopes()
    assert credential.can_upload_to_inbox()


def test_exchange_parses_scopes_with_spaces(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.scope = " user.info.basic , video.publish "

    credential = gateway.exchange_code(FAKE_TT_CODE, VERIFIER, CONFIG)

    assert credential.scopes == frozenset({"user.info.basic", "video.publish"})


def test_exchange_with_partial_scopes_reports_the_missing_one(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.scope = "user.info.basic"

    credential = gateway.exchange_code(FAKE_TT_CODE, VERIFIER, CONFIG)

    assert not credential.has_required_scopes()
    assert credential.missing_scopes() == ["video.publish"]


def test_exchange_rejects_a_wrong_verifier(gateway: TikTokGateway) -> None:
    with pytest.raises(TikTokGrantInvalid) as raised:
        gateway.exchange_code(FAKE_TT_CODE, "w" * 64, CONFIG)

    assert raised.value.log_id == FAKE_TT_LOG_ID
    _assert_safe(raised.value)


@pytest.mark.parametrize(
    "fault", ["missing_fields", "bad_json", "bad_token_type", "empty_object"]
)
def test_exchange_unexpected_shapes(
    gateway: TikTokGateway, fake: FakeTikTok, fault: str
) -> None:
    fake.faults["exchange"] = fault

    with pytest.raises(TikTokUnexpectedResponse) as raised:
        gateway.exchange_code(FAKE_TT_CODE, VERIFIER, CONFIG)

    _assert_safe(raised.value)


@pytest.mark.parametrize(
    "field",
    [
        "access_token",
        "refresh_token",
        "open_id",
        "expires_in",
        "refresh_expires_in",
        "scope",
        "token_type",
    ],
)
def test_exchange_requires_every_field(field: str, clock: FakeClock) -> None:
    payload = {
        "access_token": FAKE_TT_ACCESS_TOKEN,
        "expires_in": 86400,
        "open_id": FAKE_TT_OPEN_ID,
        "refresh_expires_in": 31536000,
        "refresh_token": FAKE_TT_REFRESH_TOKEN,
        "scope": "user.info.basic,video.publish",
        "token_type": "Bearer",
    }
    del payload[field]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        gateway = TikTokGateway(client, clock.now)
        with pytest.raises(TikTokUnexpectedResponse):
            gateway.exchange_code(FAKE_TT_CODE, VERIFIER, CONFIG)


@pytest.mark.parametrize(
    ("field", "value"),
    [("expires_in", "86400"), ("expires_in", 0), ("refresh_expires_in", True)],
)
def test_exchange_rejects_ill_typed_fields(
    field: str, value: object, clock: FakeClock
) -> None:
    payload = {
        "access_token": FAKE_TT_ACCESS_TOKEN,
        "expires_in": 86400,
        "open_id": FAKE_TT_OPEN_ID,
        "refresh_expires_in": 31536000,
        "refresh_token": FAKE_TT_REFRESH_TOKEN,
        "scope": "user.info.basic,video.publish",
        "token_type": "bearer",
        field: value,
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(TikTokUnexpectedResponse):
            TikTokGateway(client, clock.now).exchange_code(
                FAKE_TT_CODE, VERIFIER, CONFIG
            )


# --- Classification (research §14) ---------------------------------------------------


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("transport", TikTokUnavailable),
        ("timeout", TikTokUnavailable),
        ("server_error", TikTokUnavailable),
        ("rate_limited", TikTokUnavailable),
        ("oauth_server_error", TikTokUnavailable),
        ("oauth_temporarily_unavailable", TikTokUnavailable),
        ("oauth_invalid_grant", TikTokGrantInvalid),
        ("oauth200_invalid_grant", TikTokGrantInvalid),
        ("oauth_access_denied", TikTokRejected),
        ("oauth_invalid_client", TikTokClientError),
        ("oauth200_invalid_client", TikTokClientError),
        ("oauth_unauthorized_client", TikTokClientError),
        ("oauth_invalid_request", TikTokClientError),
        ("oauth_invalid_scope", TikTokClientError),
        ("oauth_unsupported_grant_type", TikTokClientError),
        ("oauth_something_new", TikTokUnexpectedResponse),
        ("api_access_token_invalid", TikTokTokenInvalid),
        ("api_scope_not_authorized", TikTokScopeMissing),
        ("api_scope_permission_missed", TikTokScopeMissing),
        ("api_rate_limit_exceeded", TikTokUnavailable),
        ("api_internal_error", TikTokUnavailable),
        ("api_invalid_params", TikTokUnexpectedResponse),
        ("bad_json", TikTokUnexpectedResponse),
    ],
)
def test_error_classification(
    gateway: TikTokGateway,
    fake: FakeTikTok,
    fault: str,
    expected: type[TikTokError],
) -> None:
    fake.faults["exchange"] = fault

    with pytest.raises(TikTokError) as raised:
        gateway.exchange_code(FAKE_TT_CODE, VERIFIER, CONFIG)

    assert type(raised.value) is expected
    _assert_safe(raised.value)


def test_unsafe_log_ids_are_dropped(clock: FakeClock) -> None:
    body = {"error": "invalid_grant", "log_id": "<script>alert(1)</script>"}
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json=body))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(TikTokGrantInvalid) as raised:
            TikTokGateway(client, clock.now).exchange_code(
                FAKE_TT_CODE, VERIFIER, CONFIG
            )

    assert raised.value.log_id is None


# --- Refresh -------------------------------------------------------------------------


@pytest.mark.parametrize("rotate", [True, False])
def test_refresh_keeps_the_returned_refresh_token(
    gateway: TikTokGateway, fake: FakeTikTok, clock: FakeClock, rotate: bool
) -> None:
    fake.rotate_refresh_token = rotate
    clock.advance(3600)

    refreshed = gateway.refresh(_credential(), CONFIG)

    assert fake.requests[-1].form == {
        "client_key": FAKE_TT_CLIENT_KEY,
        "client_secret": FAKE_TT_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": FAKE_TT_REFRESH_TOKEN,
    }
    assert refreshed.access_token == FAKE_TT_REFRESHED_ACCESS_TOKEN
    assert refreshed.refresh_token == (
        FAKE_TT_ROTATED_REFRESH_TOKEN if rotate else FAKE_TT_REFRESH_TOKEN
    )
    assert refreshed.scopes_source == "token_refresh"
    assert refreshed.obtained_at == clock.now()
    assert refreshed.access_expires_at == clock.now() + timedelta(
        seconds=TT_ACCESS_SECONDS
    )


def test_refresh_requires_a_refresh_token(clock: FakeClock) -> None:
    body = {
        "access_token": FAKE_TT_REFRESHED_ACCESS_TOKEN,
        "expires_in": 86400,
        "open_id": FAKE_TT_OPEN_ID,
        "refresh_expires_in": 31536000,
        "scope": "user.info.basic,video.publish",
        "token_type": "Bearer",
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(TikTokUnexpectedResponse):
            TikTokGateway(client, clock.now).refresh(_credential(), CONFIG)


def test_refresh_with_an_old_token_is_invalid_grant(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    gateway.refresh(_credential(), CONFIG)

    with pytest.raises(TikTokGrantInvalid):
        gateway.refresh(_credential(), CONFIG)


# --- Revoke --------------------------------------------------------------------------


@pytest.mark.parametrize("fault", [None, "empty_body"])
def test_revoke_success(
    gateway: TikTokGateway, fake: FakeTikTok, fault: str | None
) -> None:
    if fault:
        fake.faults["revoke"] = fault

    gateway.revoke(FAKE_TT_ACCESS_TOKEN, CONFIG)

    [request] = fake.requests
    assert request.url == TT_REVOKE_URL
    assert request.form == {
        "client_key": FAKE_TT_CLIENT_KEY,
        "client_secret": FAKE_TT_CLIENT_SECRET,
        "token": FAKE_TT_ACCESS_TOKEN,
    }


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("oauth_invalid_grant", TikTokGrantInvalid),
        ("api_access_token_invalid", TikTokTokenInvalid),
        ("server_error", TikTokUnavailable),
        ("timeout", TikTokUnavailable),
        ("bad_json", TikTokUnexpectedResponse),
    ],
)
def test_revoke_errors(
    gateway: TikTokGateway,
    fake: FakeTikTok,
    fault: str,
    expected: type[TikTokError],
) -> None:
    fake.faults["revoke"] = fault

    with pytest.raises(expected):
        gateway.revoke(FAKE_TT_ACCESS_TOKEN, CONFIG)


# --- User info -----------------------------------------------------------------------


def test_user_info_request_and_parsing(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    identity = gateway.fetch_user_info(FAKE_TT_ACCESS_TOKEN)

    [request] = fake.requests
    assert request.method == "GET"
    assert (
        request.url == f"{TT_USER_INFO_URL}?fields=open_id%2Cdisplay_name%2Cavatar_url"
    )
    assert request.headers["authorization"] == f"Bearer {FAKE_TT_ACCESS_TOKEN}"
    assert identity.open_id == FAKE_TT_OPEN_ID
    assert identity.display_name == "Cyber Studio"
    assert identity.avatar_url == fake.avatar_url


def test_user_info_empty_optional_fields_become_none(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.display_name = None
    fake.avatar_url = None

    identity = gateway.fetch_user_info(FAKE_TT_ACCESS_TOKEN)

    assert (identity.display_name, identity.avatar_url) == (None, None)


def test_user_info_requires_open_id(gateway: TikTokGateway, fake: FakeTikTok) -> None:
    fake.user_open_id = ""

    with pytest.raises(TikTokUnexpectedResponse):
        gateway.fetch_user_info(FAKE_TT_ACCESS_TOKEN)


@pytest.mark.parametrize(
    "body",
    [
        {"data": {"user": {"open_id": "x"}}},
        {"data": {"user": {"open_id": "x"}}, "error": {"code": "weird"}},
        {"data": {}, "error": {"code": "ok"}},
        {"data": [], "error": {"code": "ok"}},
    ],
)
def test_user_info_unexpected_shapes(body: dict[str, object], clock: FakeClock) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(TikTokUnexpectedResponse):
            TikTokGateway(client, clock.now).fetch_user_info(FAKE_TT_ACCESS_TOKEN)


def test_user_info_scope_missing_names_user_info_basic(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.faults["user_info"] = "api_scope_not_authorized"

    with pytest.raises(TikTokScopeMissing) as raised:
        gateway.fetch_user_info(FAKE_TT_ACCESS_TOKEN)

    assert raised.value.scope == "user.info.basic"
    _assert_safe(raised.value)


def test_user_info_with_invalid_token(gateway: TikTokGateway) -> None:
    with pytest.raises(TikTokTokenInvalid) as raised:
        gateway.fetch_user_info("act.other")

    _assert_safe(raised.value)


# --- Stored credential ---------------------------------------------------------------


def test_credential_json_round_trip() -> None:
    credential = _credential()

    data = json.loads(credential.to_json())

    assert data == {
        "version": 1,
        "open_id": FAKE_TT_OPEN_ID,
        "access_token": FAKE_TT_ACCESS_TOKEN,
        "refresh_token": FAKE_TT_REFRESH_TOKEN,
        "access_expires_at": "2026-10-15T10:00:00+00:00",
        "refresh_expires_at": "2027-10-14T10:00:00+00:00",
        "scopes": ["user.info.basic", "video.publish"],
        "scopes_source": "token_exchange",
        "obtained_at": "2026-10-14T10:00:00+00:00",
    }
    assert TikTokCredential.from_json(credential.to_json()) == credential


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"access_token": ""},
        {"refresh_token": None},
        {"open_id": 5},
        {"access_expires_at": "2026-10-15T10:00:00"},
        {"obtained_at": "not a date"},
        {"scopes": "user.info.basic"},
        {"scopes_source": "guess"},
    ],
)
def test_invalid_stored_credentials_are_rejected(change: dict[str, object]) -> None:
    data = json.loads(_credential().to_json())
    data.update(change)

    with pytest.raises(ValueError):
        TikTokCredential.from_json(json.dumps(data))


@pytest.mark.parametrize("raw", ["", "{", "[]", json.dumps({"version": 1})])
def test_unreadable_stored_credentials_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        TikTokCredential.from_json(raw)


def test_credential_repr_hides_tokens() -> None:
    text = repr(_credential())

    assert FAKE_TT_ACCESS_TOKEN not in text
    assert FAKE_TT_REFRESH_TOKEN not in text
