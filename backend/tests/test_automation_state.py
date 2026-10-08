"""Pure rules of automatic publishing: window, overdue and derived state."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.automation import (
    AUTO_PUBLISH_WINDOW,
    auto_publish_state,
    auto_start_blocker,
    in_window,
    is_overdue,
    window_ends_at,
)
from app.models import AutoPublishState, PublicationStatus

SCHEDULED_AT = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
SCHEDULED = PublicationStatus.SCHEDULED


def at(hour: int, minute: int, second: int = 0, microsecond: int = 0) -> datetime:
    return datetime(2026, 10, 7, hour, minute, second, microsecond, tzinfo=UTC)


def test_window_is_ten_minutes_after_the_scheduled_time() -> None:
    assert AUTO_PUBLISH_WINDOW == timedelta(minutes=10)
    assert window_ends_at(SCHEDULED_AT) == at(18, 10)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (at(17, 59, 59), False),
        (at(18, 0), True),
        (at(18, 9), True),
        (at(18, 10), True),
        (at(18, 10, 0, 1), False),
        (at(18, 11), False),
    ],
)
def test_window_is_inclusive_at_both_ends(now: datetime, expected: bool) -> None:
    assert in_window(SCHEDULED_AT, now) is expected


@pytest.mark.parametrize(
    ("now", "paused", "expected"),
    [
        (at(17, 59, 59), False, AutoPublishState.WAITING),
        (at(18, 0), False, AutoPublishState.DUE),
        (at(18, 9), False, AutoPublishState.DUE),
        (at(18, 10), False, AutoPublishState.DUE),
        (at(18, 10, 0, 1), False, AutoPublishState.OVERDUE),
        (at(17, 0), True, AutoPublishState.PAUSED),
        (at(18, 5), True, AutoPublishState.PAUSED),
        (at(18, 11), True, AutoPublishState.OVERDUE),
    ],
)
def test_state_of_an_armed_publication(
    now: datetime, paused: bool, expected: AutoPublishState
) -> None:
    assert auto_publish_state(SCHEDULED, True, SCHEDULED_AT, paused, now) == expected


@pytest.mark.parametrize("now", [at(17, 0), at(18, 5), at(23, 0)])
@pytest.mark.parametrize("paused", [False, True])
def test_disarmed_publications_are_never_overdue(now: datetime, paused: bool) -> None:
    assert auto_publish_state(SCHEDULED, False, SCHEDULED_AT, paused, now) == (
        AutoPublishState.DISABLED
    )
    assert is_overdue(SCHEDULED, False, SCHEDULED_AT, now) is False


@pytest.mark.parametrize(
    ("now", "expected"),
    [(at(18, 10), False), (at(18, 10, 0, 1), True), (at(23, 0), True)],
)
def test_overdue_is_a_derived_condition(now: datetime, expected: bool) -> None:
    assert is_overdue(SCHEDULED, True, SCHEDULED_AT, now) is expected


@pytest.mark.parametrize(
    "status",
    [
        PublicationStatus.UNSCHEDULED,
        PublicationStatus.PUBLISHING,
        PublicationStatus.PUBLISHED,
        PublicationStatus.FAILED,
        PublicationStatus.CANCELLED,
    ],
)
def test_only_scheduled_publications_have_an_automation_state(
    status: PublicationStatus,
) -> None:
    assert auto_publish_state(status, False, SCHEDULED_AT, False, at(23, 0)) is None
    assert is_overdue(status, False, SCHEDULED_AT, at(23, 0)) is False


def _publication(
    status: str = SCHEDULED, armed: bool = True, scheduled_at: datetime | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        auto_publish_enabled=armed,
        scheduled_at=scheduled_at or SCHEDULED_AT,
    )


def test_auto_start_allowed_only_when_every_condition_holds() -> None:
    assert auto_start_blocker(_publication(), False, at(18, 5)) is None


@pytest.mark.parametrize(
    ("publication", "paused", "now"),
    [
        (_publication(status=PublicationStatus.UNSCHEDULED), False, at(18, 5)),
        (_publication(status=PublicationStatus.FAILED), False, at(18, 5)),
        (_publication(armed=False), False, at(18, 5)),
        (_publication(), True, at(18, 5)),
        (_publication(), False, at(17, 59)),
        (_publication(), False, at(18, 10, 0, 1)),
    ],
)
def test_auto_start_is_blocked(
    publication: SimpleNamespace, paused: bool, now: datetime
) -> None:
    assert auto_start_blocker(publication, paused, now) is not None


def test_offsets_and_dst_are_evaluated_in_utc() -> None:
    # 25 October 2026: Europe/Madrid goes back from +02:00 to +01:00 at 03:00.
    summer = timezone(timedelta(hours=2))
    winter = timezone(timedelta(hours=1))
    first = datetime(2026, 10, 25, 2, 30, tzinfo=summer)  # 00:30Z
    repeated = datetime(2026, 10, 25, 2, 30, tzinfo=winter)  # 01:30Z
    utc = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)

    assert in_window(first, utc) and in_window(utc, first)
    assert in_window(first, utc + timedelta(minutes=10))
    assert not in_window(first, repeated)  # one real hour later
    assert is_overdue(SCHEDULED, True, first, repeated)
    assert auto_publish_state(SCHEDULED, True, repeated, False, first) == (
        AutoPublishState.WAITING
    )
