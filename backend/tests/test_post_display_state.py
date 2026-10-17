"""The visible state of a post: one row per line of the table in research.md §7."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import AttemptStatus, PublicationAttempt
from app.post_state import post_display_state

NOW = datetime(2100, 1, 1, 12, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(hours=1)
JUST_PASSED = NOW - timedelta(minutes=5)  # inside the 10-minute automatic window
LONG_AGO = NOW - timedelta(hours=1)  # after the automatic window

UNCERTAIN = PublicationAttempt(status=AttemptStatus.FAILED, outcome_determined=False)
DETERMINED = PublicationAttempt(status=AttemptStatus.FAILED, outcome_determined=True)


@pytest.mark.parametrize(
    ("status", "armed", "scheduled_at", "paused", "attempt", "expected"),
    [
        ("publishing", False, None, False, None, "publishing"),
        ("published", False, None, False, None, "published"),
        ("cancelled", False, None, False, None, "cancelled"),
        ("awaiting_user_action", False, None, False, None, "needs_action"),
        ("failed", False, None, False, UNCERTAIN, "needs_review"),
        ("failed", False, None, False, DETERMINED, "failed"),
        ("failed", False, None, False, None, "failed"),
        ("unscheduled", False, None, False, None, "draft"),
        # Armed and its automatic window passed: missed, paused or not.
        ("scheduled", True, LONG_AGO, False, None, "missed"),
        ("scheduled", True, LONG_AGO, True, None, "missed"),
        # Manual and its time passed: nobody will publish it.
        ("scheduled", False, JUST_PASSED, False, None, "missed"),
        ("scheduled", True, FUTURE, True, None, "scheduled_paused"),
        ("scheduled", True, JUST_PASSED, True, None, "scheduled_paused"),
        ("scheduled", True, FUTURE, False, None, "scheduled_automatic"),
        # Inside its window and not paused: the scheduler will start it.
        ("scheduled", True, JUST_PASSED, False, None, "scheduled_automatic"),
        ("scheduled", False, FUTURE, False, None, "scheduled_manual"),
        ("scheduled", False, FUTURE, True, None, "scheduled_manual"),
    ],
)
def test_post_display_state(
    status: str,
    armed: bool,
    scheduled_at: datetime | None,
    paused: bool,
    attempt: PublicationAttempt | None,
    expected: str,
) -> None:
    assert (
        post_display_state(status, armed, scheduled_at, paused, attempt, NOW)
        == expected
    )
