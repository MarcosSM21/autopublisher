"""`InstagramGateway.get_media_counters` (Feature 027 T035, research §2)."""

from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest

from app.instagram_gateway import (
    InstagramGateway,
    MetaNotFound,
    MetaPermissionDenied,
    MetaRateLimited,
    MetaTokenInvalid,
    MetaUnavailable,
    MetaUnexpectedResponse,
)
from tests.fakes import FAKE_IG_LONG_TOKEN, FAKE_META_ERROR_TEXT, FakeMeta


@pytest.fixture
def fake() -> FakeMeta:
    return FakeMeta()


@pytest.fixture
def gateway(fake: FakeMeta) -> Iterator[InstagramGateway]:
    with httpx.Client(transport=fake.transport()) as client:
        yield InstagramGateway(client)


def test_counters_are_read_with_only_the_basic_fields(
    fake: FakeMeta, gateway: InstagramGateway
) -> None:
    fake.counters = {"M1": {"like_count": 12, "comments_count": 0}}

    assert gateway.get_media_counters(FAKE_IG_LONG_TOKEN, "M1") == {
        "like_count": 12,
        "comments_count": 0,
    }
    (request,) = fake.requests_for("counters")
    url = urlsplit(request.url)
    assert url.path == "/v26.0/M1"
    assert parse_qs(url.query)["fields"] == ["like_count,comments_count"]


def test_a_hidden_like_count_stays_absent(
    fake: FakeMeta, gateway: InstagramGateway
) -> None:
    fake.counters = {"M1": {"comments_count": 4}}

    assert gateway.get_media_counters(FAKE_IG_LONG_TOKEN, "M1") == {"comments_count": 4}


def test_values_that_are_not_counters_are_dropped(
    fake: FakeMeta, gateway: InstagramGateway
) -> None:
    fake.counters = {"M1": {"like_count": "7", "comments_count": -1}}

    assert gateway.get_media_counters(FAKE_IG_LONG_TOKEN, "M1") == {}


def test_object_does_not_exist_is_not_found(
    fake: FakeMeta, gateway: InstagramGateway
) -> None:
    with pytest.raises(MetaNotFound):
        gateway.get_media_counters(FAKE_IG_LONG_TOKEN, "GONE")


@pytest.mark.parametrize(
    ("fault", "error"),
    [
        ("graph_4", MetaRateLimited),
        ("graph_17", MetaRateLimited),
        ("graph_32", MetaRateLimited),
        ("graph_613", MetaRateLimited),
        ("graph_80002", MetaRateLimited),
        ("rate_limited", MetaRateLimited),  # HTTP 429
        ("graph_190", MetaTokenInvalid),
        ("graph_10", MetaPermissionDenied),
        ("graph_200", MetaPermissionDenied),
        ("server_error", MetaUnavailable),
        ("transport", MetaUnavailable),
        ("bad_json", MetaUnexpectedResponse),
        # Never an absence: a bare 100, another subcode or an unknown code.
        ("graph_100", MetaUnavailable),
        ("graph_100_2207008", MetaUnavailable),
        ("graph_9999", MetaUnavailable),
    ],
)
def test_errors_are_classified_without_leaking_the_body(
    fake: FakeMeta, gateway: InstagramGateway, fault: str, error: type[Exception]
) -> None:
    fake.counters = {"M1": {"like_count": 1}}
    fake.faults["counters"] = fault

    with pytest.raises(error) as raised:
        gateway.get_media_counters(FAKE_IG_LONG_TOKEN, "M1")

    assert type(raised.value) is error
    assert FAKE_META_ERROR_TEXT not in str(raised.value)
    assert FAKE_IG_LONG_TOKEN not in str(raised.value)
