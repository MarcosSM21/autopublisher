"""Threads gateway against the fake Threads API: requests, parsing and error
classification.

These are the only tests that look at Meta's numeric error codes (research §10); the
service tests work with the semantic exceptions.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest

from app.threads_gateway import (
    THREADS_API_VERSION,
    ShortLivedToken,
    ThreadsError,
    ThreadsGateway,
    ThreadsPermissionDenied,
    ThreadsRejected,
    ThreadsToken,
    ThreadsTokenInvalid,
    ThreadsUnavailable,
    ThreadsUnexpectedResponse,
)
from app.threads_oauth import ThreadsAppConfig
from tests.fakes import (
    FAKE_META_ERROR_TEXT,
    FAKE_TH_APP_ID,
    FAKE_TH_APP_SECRET,
    FAKE_TH_CODE,
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REDIRECT_URI,
    FAKE_TH_REFRESHED_TOKEN,
    FAKE_TH_SHORT_TOKEN,
    LONG_LIVED_SECONDS,
    TH_ALL_SCOPES,
    TH_BASIC,
    TH_DATA_ACCESS_EXPIRES_AT,
    TH_PUBLISH,
    TH_USER_ID,
    FakeClock,
    FakeThreads,
)

CONFIG = ThreadsAppConfig(FAKE_TH_APP_ID, FAKE_TH_APP_SECRET, FAKE_TH_REDIRECT_URI)
SECRETS = (
    FAKE_TH_CODE,
    FAKE_TH_SHORT_TOKEN,
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REFRESHED_TOKEN,
    FAKE_TH_APP_SECRET,
    FAKE_META_ERROR_TEXT,
    "graph.threads.net",
)


@pytest.fixture
def threads() -> FakeThreads:
    return FakeThreads()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def gateway(threads: FakeThreads, clock: FakeClock) -> Iterator[ThreadsGateway]:
    with httpx.Client(transport=threads.transport()) as client:
        yield ThreadsGateway(client, clock.now)


def _long_token(clock: FakeClock) -> ThreadsToken:
    now = clock.now()
    return ThreadsToken(
        FAKE_TH_LONG_TOKEN,
        now,
        now + timedelta(days=60),
        frozenset({TH_BASIC, TH_PUBLISH}),
    )


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def test_exchange_code(gateway: ThreadsGateway, threads: FakeThreads) -> None:
    short = gateway.exchange_code(FAKE_TH_CODE, CONFIG)

    assert short == ShortLivedToken(FAKE_TH_SHORT_TOKEN, TH_USER_ID)
    [request] = threads.requests_to("code")
    assert request.method == "POST"
    # Everything travels in the form body, nothing in the request URL.
    assert urlsplit(request.url).query == ""
    assert request.form == {
        "client_id": FAKE_TH_APP_ID,
        "client_secret": FAKE_TH_APP_SECRET,
        "code": FAKE_TH_CODE,
        "grant_type": "authorization_code",
        "redirect_uri": FAKE_TH_REDIRECT_URI,
    }


def test_exchange_code_normalizes_numeric_user_id(
    gateway: ThreadsGateway, threads: FakeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        threads,
        "_code",
        lambda form: {"access_token": FAKE_TH_SHORT_TOKEN, "user_id": 2584},
    )

    assert gateway.exchange_code(FAKE_TH_CODE, CONFIG).user_id == "2584"


@pytest.mark.parametrize("fault", ["missing_fields", "bad_json"])
def test_exchange_code_malformed_response(
    gateway: ThreadsGateway, threads: FakeThreads, fault: str
) -> None:
    threads.faults["code"] = fault

    with pytest.raises(ThreadsUnexpectedResponse):
        gateway.exchange_code(FAKE_TH_CODE, CONFIG)


def test_exchange_code_rejected(gateway: ThreadsGateway, threads: FakeThreads) -> None:
    threads.faults["code"] = "graph_100"

    with pytest.raises(ThreadsRejected):
        gateway.exchange_code(FAKE_TH_CODE, CONFIG)
    assert len(threads.requests_to("code")) == 1


def test_exchange_long_lived(
    gateway: ThreadsGateway, threads: FakeThreads, clock: FakeClock
) -> None:
    token = gateway.exchange_long_lived(
        ShortLivedToken(FAKE_TH_SHORT_TOKEN, TH_USER_ID), CONFIG
    )

    now = clock.now()
    assert token == ThreadsToken(
        FAKE_TH_LONG_TOKEN,
        now,
        now + timedelta(seconds=LONG_LIVED_SECONDS),
        frozenset(),
    )
    [request] = threads.requests_to("long_lived")
    assert request.method == "GET"
    assert _query(request.url) == {
        "grant_type": "th_exchange_token",
        "client_secret": FAKE_TH_APP_SECRET,
        "access_token": FAKE_TH_SHORT_TOKEN,
    }


@pytest.mark.parametrize("expires_in", [0, -5, None, "60", True])
def test_long_lived_without_valid_expiry_is_unexpected(
    gateway: ThreadsGateway,
    threads: FakeThreads,
    monkeypatch: pytest.MonkeyPatch,
    expires_in: object,
) -> None:
    payload: dict[str, object] = {"access_token": FAKE_TH_LONG_TOKEN}
    if expires_in is not None:
        payload["expires_in"] = expires_in
    monkeypatch.setattr(threads, "_long", lambda params: payload)

    with pytest.raises(ThreadsUnexpectedResponse):
        gateway.exchange_long_lived(
            ShortLivedToken(FAKE_TH_SHORT_TOKEN, TH_USER_ID), CONFIG
        )


def test_refresh(
    gateway: ThreadsGateway, threads: FakeThreads, clock: FakeClock
) -> None:
    original = _long_token(clock)
    clock.advance(timedelta(days=55).total_seconds())
    threads.refreshed_expires_in = 5_000_000

    refreshed = gateway.refresh(original)

    now = clock.now()
    assert refreshed == ThreadsToken(
        FAKE_TH_REFRESHED_TOKEN,
        now,
        now + timedelta(seconds=5_000_000),
        original.scopes,
    )
    [request] = threads.requests_to("refresh")
    assert _query(request.url) == {
        "grant_type": "th_refresh_token",
        "access_token": FAKE_TH_LONG_TOKEN,
    }
    assert FAKE_TH_APP_SECRET not in request.url


def test_debug_token(gateway: ThreadsGateway, threads: FakeThreads) -> None:
    info = gateway.debug_token(FAKE_TH_LONG_TOKEN)

    assert info.is_valid is True
    assert info.user_id == TH_USER_ID
    assert info.scopes == frozenset(TH_ALL_SCOPES)
    assert info.data_access_expires_at == datetime.fromtimestamp(
        TH_DATA_ACCESS_EXPIRES_AT, UTC
    )
    [request] = threads.requests_to("debug")
    assert f"/{THREADS_API_VERSION}/debug_token" in request.url
    # The token inspects itself: no app access token is used.
    assert _query(request.url) == {
        "input_token": FAKE_TH_LONG_TOKEN,
        "access_token": FAKE_TH_LONG_TOKEN,
    }
    assert "TH|" not in request.url and "TH%7C" not in request.url


@pytest.mark.parametrize("value", [0, None])
def test_debug_token_unknown_data_access_expiry(
    gateway: ThreadsGateway, threads: FakeThreads, value: int | None
) -> None:
    threads.debug_data_access_expires_at = value

    assert gateway.debug_token(FAKE_TH_LONG_TOKEN).data_access_expires_at is None


def test_debug_token_invalid_token_is_reported(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    threads.debug_is_valid = False
    threads.debug_scopes = []

    info = gateway.debug_token(FAKE_TH_LONG_TOKEN)

    assert info.is_valid is False
    assert info.scopes == frozenset()


@pytest.mark.parametrize("missing", ["is_valid", "scopes"])
def test_debug_token_missing_fields_is_unexpected(
    gateway: ThreadsGateway, threads: FakeThreads, missing: str
) -> None:
    setattr(threads, f"debug_{missing}", None)

    with pytest.raises(ThreadsUnexpectedResponse):
        gateway.debug_token(FAKE_TH_LONG_TOKEN)


def test_debug_token_ill_typed_scopes_is_unexpected(
    gateway: ThreadsGateway, threads: FakeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        threads,
        "_debug",
        lambda params: {
            "data": {"is_valid": True, "user_id": TH_USER_ID, "scopes": "a,b"}
        },
    )

    with pytest.raises(ThreadsUnexpectedResponse):
        gateway.debug_token(FAKE_TH_LONG_TOKEN)


def test_fetch_me(gateway: ThreadsGateway, threads: FakeThreads) -> None:
    identity = gateway.fetch_me(FAKE_TH_LONG_TOKEN)

    assert identity.threads_user_id == TH_USER_ID
    assert identity.username == "cyber.studio"
    assert identity.display_name == "Cyber Studio"
    assert identity.profile_picture_url == "https://scontent.example/th-pic.jpg"
    [request] = threads.requests_to("me")
    assert f"/{THREADS_API_VERSION}/me" in request.url
    assert _query(request.url) == {
        "fields": "id,username,name,threads_profile_picture_url",
        "access_token": FAKE_TH_LONG_TOKEN,
    }


def test_fetch_me_optional_fields(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    threads.set_identity(name=None, threads_profile_picture_url=None)

    identity = gateway.fetch_me(FAKE_TH_LONG_TOKEN)

    assert identity.display_name is None
    assert identity.profile_picture_url is None


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("transport", ThreadsUnavailable),
        ("server_error", ThreadsUnavailable),
        ("rate_limited", ThreadsUnavailable),
        ("graph_1", ThreadsUnavailable),
        ("graph_2", ThreadsUnavailable),
        ("graph_4", ThreadsUnavailable),
        ("graph_17", ThreadsUnavailable),
        ("graph_32", ThreadsUnavailable),
        ("graph_613", ThreadsUnavailable),
        ("graph_190", ThreadsTokenInvalid),
        ("graph_10", ThreadsPermissionDenied),
        ("graph_200", ThreadsPermissionDenied),
        ("graph_299", ThreadsPermissionDenied),
        ("graph_100", ThreadsRejected),
        ("bad_json", ThreadsUnexpectedResponse),
        ("missing_fields", ThreadsUnexpectedResponse),
    ],
)
@pytest.mark.parametrize("endpoint", ["code", "long_lived", "refresh", "debug", "me"])
def test_error_classification(
    gateway: ThreadsGateway,
    threads: FakeThreads,
    clock: FakeClock,
    endpoint: str,
    fault: str,
    expected: type[ThreadsError],
) -> None:
    threads.faults[endpoint] = fault
    calls: dict[str, Callable[[], object]] = {
        "code": lambda: gateway.exchange_code(FAKE_TH_CODE, CONFIG),
        "long_lived": lambda: gateway.exchange_long_lived(
            ShortLivedToken(FAKE_TH_SHORT_TOKEN, TH_USER_ID), CONFIG
        ),
        "refresh": lambda: gateway.refresh(_long_token(clock)),
        "debug": lambda: gateway.debug_token(FAKE_TH_LONG_TOKEN),
        "me": lambda: gateway.fetch_me(FAKE_TH_LONG_TOKEN),
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
        (TH_PUBLISH, TH_PUBLISH),
        (TH_BASIC, TH_BASIC),
        (None, None),
        ("threads_manage_replies", None),
        (f"{TH_BASIC} and {TH_PUBLISH}", None),
    ],
)
def test_permission_denied_names_only_a_required_scope(
    gateway: ThreadsGateway,
    threads: FakeThreads,
    named: str | None,
    expected: str | None,
) -> None:
    threads.faults["me"] = "graph_200"
    threads.error_permission = named

    with pytest.raises(ThreadsPermissionDenied) as raised:
        gateway.fetch_me(FAKE_TH_LONG_TOKEN)

    assert raised.value.permission == expected


def test_token_json_round_trip(clock: FakeClock) -> None:
    token = _long_token(clock)

    assert ThreadsToken.from_json(token.to_json()) == token
    assert FAKE_TH_LONG_TOKEN not in repr(token)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        '{"access_token": "t", "token_obtained_at": "2026-10-13T10:00:00", '
        '"expires_at": "2026-12-12T10:00:00", "scopes": []}',
        '{"access_token": "", "token_obtained_at": "2026-10-13T10:00:00+00:00", '
        '"expires_at": "2026-12-12T10:00:00+00:00", "scopes": []}',
        '{"access_token": "t", "token_obtained_at": "2026-10-13T10:00:00+00:00", '
        '"expires_at": "2026-12-12T10:00:00+00:00", "scopes": "x"}',
        '{"access_token": "t", "expires_at": "2026-12-12T10:00:00+00:00", '
        '"scopes": []}',
    ],
)
def test_invalid_stored_token_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        ThreadsToken.from_json(raw)
