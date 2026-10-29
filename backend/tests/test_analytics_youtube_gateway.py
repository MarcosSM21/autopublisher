"""`GoogleGateway.get_video_statistics` (Feature 027 T027)."""

from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest

from app.youtube_gateway import (
    MAX_IDS_PER_VIDEOS_LIST,
    GoogleForbidden,
    GoogleGateway,
    GoogleQuotaExceeded,
    GoogleRejected,
    GoogleUnauthorized,
    GoogleUnavailable,
)
from tests.fakes import FAKE_ACCESS_TOKEN, FAKE_GOOGLE_ERROR_TEXT, FakeGoogle


@pytest.fixture
def fake() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def gateway(fake: FakeGoogle) -> Iterator[GoogleGateway]:
    with httpx.Client(transport=fake.transport()) as client:
        yield GoogleGateway(client)


def test_statistics_are_parsed_as_integers_and_absent_fields_stay_absent(
    fake: FakeGoogle, gateway: GoogleGateway
) -> None:
    fake.statistics = {
        "A": {
            "viewCount": "120",
            "likeCount": "0",
            "favoriteCount": "0",
            "commentCount": "7",
        },
        # Likes hidden and comments disabled: YouTube omits the fields.
        "B": {"viewCount": "5", "bogus": "x", "negative": -1},
    }

    result = gateway.get_video_statistics(FAKE_ACCESS_TOKEN, ["A", "B"])

    assert result.found == {
        "A": {"viewCount": 120, "likeCount": 0, "favoriteCount": 0, "commentCount": 7},
        "B": {"viewCount": 5},
    }
    assert result.missing == frozenset()
    (request,) = fake.statistics_requests
    query = parse_qs(urlsplit(request.url).query)
    assert query == {"part": ["statistics"], "id": ["A,B"]}
    assert request.headers["authorization"] == f"Bearer {FAKE_ACCESS_TOKEN}"


def test_an_id_missing_from_items_is_reported_separately(
    fake: FakeGoogle, gateway: GoogleGateway
) -> None:
    fake.statistics = {"A": {"viewCount": "1"}}

    result = gateway.get_video_statistics(FAKE_ACCESS_TOKEN, ["A", "GONE"])

    assert set(result.found) == {"A"}
    assert result.missing == {"GONE"}


def test_a_paged_answer_never_reports_an_absence(
    fake: FakeGoogle, gateway: GoogleGateway
) -> None:
    fake.statistics = {"A": {"viewCount": "1"}}
    fake.statistics_outcomes = ["paged"]

    result = gateway.get_video_statistics(FAKE_ACCESS_TOKEN, ["A", "B"])

    assert set(result.found) == {"A"}
    assert result.missing == frozenset()


def test_video_not_found_is_an_absence_only_for_a_single_id(
    fake: FakeGoogle, gateway: GoogleGateway
) -> None:
    fake.statistics_outcomes = ["not_found", "not_found"]

    single = gateway.get_video_statistics(FAKE_ACCESS_TOKEN, ["GONE"])
    assert single.found == {} and single.missing == {"GONE"}

    with pytest.raises(GoogleRejected):
        gateway.get_video_statistics(FAKE_ACCESS_TOKEN, ["A", "GONE"])


def test_a_full_batch_is_one_call(fake: FakeGoogle, gateway: GoogleGateway) -> None:
    ids = [f"V{i}" for i in range(MAX_IDS_PER_VIDEOS_LIST)]
    fake.statistics = {video_id: {"viewCount": "3"} for video_id in ids}

    result = gateway.get_video_statistics(FAKE_ACCESS_TOKEN, ids)

    assert len(result.found) == MAX_IDS_PER_VIDEOS_LIST
    assert len(fake.statistics_requests) == 1


@pytest.mark.parametrize("count", [0, MAX_IDS_PER_VIDEOS_LIST + 1])
def test_batches_outside_the_bounds_are_refused_without_a_call(
    fake: FakeGoogle, gateway: GoogleGateway, count: int
) -> None:
    with pytest.raises(ValueError):
        gateway.get_video_statistics(FAKE_ACCESS_TOKEN, [f"V{i}" for i in range(count)])
    assert fake.statistics_requests == []


@pytest.mark.parametrize(
    ("outcome", "error", "daily"),
    [
        ("quota", GoogleQuotaExceeded, True),
        ("rate_limit", GoogleQuotaExceeded, False),
        ("unauthorized", GoogleUnauthorized, None),
        ("forbidden", GoogleForbidden, None),
        ("server_error", GoogleUnavailable, None),
        ("timeout", GoogleUnavailable, None),
    ],
)
def test_errors_are_classified_without_leaking_the_body(
    fake: FakeGoogle,
    gateway: GoogleGateway,
    outcome: str,
    error: type[Exception],
    daily: bool | None,
) -> None:
    fake.statistics_outcomes = [outcome]

    with pytest.raises(error) as raised:
        gateway.get_video_statistics(FAKE_ACCESS_TOKEN, ["A"])

    if daily is not None:
        assert isinstance(raised.value, GoogleQuotaExceeded)
        assert raised.value.daily is daily
    assert FAKE_GOOGLE_ERROR_TEXT not in str(raised.value)
    assert FAKE_ACCESS_TOKEN not in str(raised.value)
