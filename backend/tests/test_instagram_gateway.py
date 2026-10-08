"""Instagram gateway against the fake Meta: requests, parsing and error classification.

These are the only tests that look at Meta's numeric error codes (research §9); the
service tests work with the semantic exceptions.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest

from app.instagram_gateway import (
    GRAPH_API_VERSION,
    InstagramGateway,
    InstagramToken,
    MetaError,
    MetaPermissionDenied,
    MetaRejected,
    MetaTokenInvalid,
    MetaUnavailable,
    MetaUnexpectedResponse,
    ShortLivedToken,
)
from app.instagram_oauth import MetaAppConfig
from tests.fakes import (
    FAKE_IG_APP_ID,
    FAKE_IG_APP_SECRET,
    FAKE_IG_CODE,
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REDIRECT_URI,
    FAKE_IG_REFRESHED_TOKEN,
    FAKE_IG_SHORT_TOKEN,
    FAKE_META_ERROR_TEXT,
    IG_BASIC,
    IG_PUBLISH,
    LONG_LIVED_SECONDS,
    FakeClock,
    FakeMeta,
)

CONFIG = MetaAppConfig(FAKE_IG_APP_ID, FAKE_IG_APP_SECRET, FAKE_IG_REDIRECT_URI)
SECRETS = (
    FAKE_IG_CODE,
    FAKE_IG_SHORT_TOKEN,
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REFRESHED_TOKEN,
    FAKE_IG_APP_SECRET,
    FAKE_META_ERROR_TEXT,
    "graph.instagram.com",
    "api.instagram.com",
)


@pytest.fixture
def meta() -> FakeMeta:
    return FakeMeta()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def gateway(meta: FakeMeta, clock: FakeClock) -> Iterator[InstagramGateway]:
    with httpx.Client(transport=meta.transport()) as client:
        yield InstagramGateway(client, clock.now)


def _long_token(clock: FakeClock) -> InstagramToken:
    now = clock.now()
    return InstagramToken(
        FAKE_IG_LONG_TOKEN,
        now,
        now + timedelta(days=60),
        frozenset({IG_BASIC, IG_PUBLISH}),
    )


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


@pytest.mark.parametrize("wrap_data", [True, False])
def test_exchange_code(
    gateway: InstagramGateway, meta: FakeMeta, wrap_data: bool
) -> None:
    meta.wrap_data = wrap_data

    token = gateway.exchange_code(FAKE_IG_CODE, CONFIG)

    assert token.access_token == FAKE_IG_SHORT_TOKEN
    assert token.permissions == {IG_BASIC, IG_PUBLISH}
    (request,) = meta.requests_to("code")
    assert request.method == "POST"
    assert request.form == {
        "client_id": FAKE_IG_APP_ID,
        "client_secret": FAKE_IG_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": FAKE_IG_REDIRECT_URI,
        "code": FAKE_IG_CODE,
    }
    assert "?" not in request.url


def test_exchange_code_without_permissions_is_unexpected(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    meta.permissions = None
    with pytest.raises(MetaUnexpectedResponse):
        gateway.exchange_code(FAKE_IG_CODE, CONFIG)


@pytest.mark.parametrize("fault", ["missing_fields", "bad_json"])
def test_exchange_code_malformed_response(
    gateway: InstagramGateway, meta: FakeMeta, fault: str
) -> None:
    meta.faults["code"] = fault
    with pytest.raises(MetaUnexpectedResponse):
        gateway.exchange_code(FAKE_IG_CODE, CONFIG)


def test_exchange_code_oauth_exception_is_rejected(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    meta.faults["code"] = "oauth_exception"
    with pytest.raises(MetaRejected):
        gateway.exchange_code(FAKE_IG_CODE, CONFIG)


def test_exchange_long_lived(
    gateway: InstagramGateway, meta: FakeMeta, clock: FakeClock
) -> None:
    short = ShortLivedToken(FAKE_IG_SHORT_TOKEN, frozenset({IG_BASIC, IG_PUBLISH}))

    token = gateway.exchange_long_lived(short, CONFIG)

    assert token.access_token == FAKE_IG_LONG_TOKEN
    assert token.issued_at == clock.now()
    assert token.expires_at == clock.now() + timedelta(seconds=LONG_LIVED_SECONDS)
    assert token.permissions == short.permissions
    (request,) = meta.requests_to("long_lived")
    assert request.method == "GET"
    assert request.url.startswith("https://graph.instagram.com/access_token?")
    assert _query(request.url) == {
        "grant_type": "ig_exchange_token",
        "client_secret": FAKE_IG_APP_SECRET,
        "access_token": FAKE_IG_SHORT_TOKEN,
    }


def test_refresh(gateway: InstagramGateway, meta: FakeMeta, clock: FakeClock) -> None:
    token = _long_token(clock)
    clock.advance(timedelta(days=2).total_seconds())

    refreshed = gateway.refresh(token)

    assert refreshed.access_token == FAKE_IG_REFRESHED_TOKEN
    assert refreshed.issued_at == clock.now()
    assert refreshed.expires_at == clock.now() + timedelta(seconds=LONG_LIVED_SECONDS)
    assert refreshed.permissions == token.permissions
    (request,) = meta.requests_to("refresh")
    assert request.url.startswith("https://graph.instagram.com/refresh_access_token?")
    assert _query(request.url) == {
        "grant_type": "ig_refresh_token",
        "access_token": FAKE_IG_LONG_TOKEN,
    }
    assert FAKE_IG_APP_SECRET not in request.url


@pytest.mark.parametrize(
    ("account_type", "expected"),
    [
        ("Business", "BUSINESS"),
        ("Media_Creator", "MEDIA_CREATOR"),
        ("MEDIA_CREATOR", "MEDIA_CREATOR"),
        ("Personal", "PERSONAL"),
        (None, None),
    ],
)
def test_fetch_me(
    gateway: InstagramGateway,
    meta: FakeMeta,
    account_type: str | None,
    expected: str | None,
) -> None:
    meta.set_identity(account_type=account_type)

    identity = gateway.fetch_me(FAKE_IG_LONG_TOKEN)

    assert identity.instagram_user_id == "17841400000000001"
    assert identity.app_scoped_id == "9000000000000001"
    assert identity.username == "cyber.studio"
    assert identity.account_type == expected
    assert identity.profile_picture_url == "https://scontent.example.com/cyber.jpg"
    (request,) = meta.requests_to("me")
    assert GRAPH_API_VERSION == "v26.0"
    assert request.url.startswith("https://graph.instagram.com/v26.0/me?")
    assert _query(request.url) == {
        "fields": "user_id,id,username,account_type,profile_picture_url",
        "access_token": FAKE_IG_LONG_TOKEN,
    }


def test_fetch_me_without_picture(gateway: InstagramGateway, meta: FakeMeta) -> None:
    meta.set_identity(profile_picture_url=None)
    assert gateway.fetch_me(FAKE_IG_LONG_TOKEN).profile_picture_url is None


@pytest.mark.parametrize("field", ["user_id", "username"])
def test_fetch_me_missing_identity_is_unexpected(
    gateway: InstagramGateway, meta: FakeMeta, field: str
) -> None:
    meta.set_identity(**{field: ""})
    with pytest.raises(MetaUnexpectedResponse):
        gateway.fetch_me(FAKE_IG_LONG_TOKEN)


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("transport", MetaUnavailable),
        ("server_error", MetaUnavailable),
        ("rate_limited", MetaUnavailable),
        ("graph_1", MetaUnavailable),
        ("graph_2", MetaUnavailable),
        ("graph_4", MetaUnavailable),
        ("graph_17", MetaUnavailable),
        ("graph_32", MetaUnavailable),
        ("graph_613", MetaUnavailable),
        ("graph_190", MetaTokenInvalid),
        ("graph_10", MetaPermissionDenied),
        ("graph_200", MetaPermissionDenied),
        ("graph_299", MetaPermissionDenied),
        ("graph_100", MetaRejected),
        ("oauth_exception", MetaRejected),
        ("bad_json", MetaUnexpectedResponse),
        ("missing_fields", MetaUnexpectedResponse),
    ],
)
@pytest.mark.parametrize("endpoint", ["long_lived", "refresh", "me"])
def test_error_classification(
    gateway: InstagramGateway,
    meta: FakeMeta,
    clock: FakeClock,
    endpoint: str,
    fault: str,
    expected: type[MetaError],
) -> None:
    meta.faults[endpoint] = fault
    calls: dict[str, Callable[[], object]] = {
        "long_lived": lambda: gateway.exchange_long_lived(
            ShortLivedToken(FAKE_IG_SHORT_TOKEN, frozenset()), CONFIG
        ),
        "refresh": lambda: gateway.refresh(_long_token(clock)),
        "me": lambda: gateway.fetch_me(FAKE_IG_LONG_TOKEN),
    }

    with pytest.raises(expected) as raised:
        calls[endpoint]()

    error = raised.value
    assert type(error) is expected
    assert error.__cause__ is None
    # Never chained to httpx errors, which contain the URL.
    assert error.__context__ is None or error.__suppress_context__
    for secret in SECRETS:
        assert secret not in str(error)
        assert secret not in repr(error)


@pytest.mark.parametrize(
    ("named", "expected"),
    [
        (IG_PUBLISH, IG_PUBLISH),
        (IG_BASIC, IG_BASIC),
        (None, None),
        ("pages_read_engagement", None),
        (f"{IG_BASIC} and {IG_PUBLISH}", None),
    ],
)
def test_permission_denied_names_only_a_required_permission(
    gateway: InstagramGateway, meta: FakeMeta, named: str | None, expected: str | None
) -> None:
    meta.faults["me"] = "graph_200"
    meta.error_permission = named

    with pytest.raises(MetaPermissionDenied) as raised:
        gateway.fetch_me(FAKE_IG_LONG_TOKEN)

    assert raised.value.permission == expected


def test_token_json_round_trip(clock: FakeClock) -> None:
    token = _long_token(clock)

    assert InstagramToken.from_json(token.to_json()) == token
    assert FAKE_IG_LONG_TOKEN not in repr(token)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"access_token": "t", "issued_at": "2026-10-08T10:00:00", '
        '"expires_at": "2026-12-07T10:00:00", "permissions": []}',
        '{"access_token": "", "issued_at": "2026-10-08T10:00:00+00:00", '
        '"expires_at": "2026-12-07T10:00:00+00:00", "permissions": []}',
        '{"access_token": "t", "issued_at": "2026-10-08T10:00:00+00:00", '
        '"expires_at": "2026-12-07T10:00:00+00:00", "permissions": "x"}',
    ],
)
def test_invalid_stored_token_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        InstagramToken.from_json(raw)
