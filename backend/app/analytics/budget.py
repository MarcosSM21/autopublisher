"""Internal daily budget of the YouTube general quota bucket used by analytics
(data-model rule 8).

An in-memory counter of units per Pacific day, independent of Google's own
`quotaExceeded`: reaching it only makes YouTube analytics wait for the reset. It
never touches the `videos.insert` bucket nor any other YouTube operation.
"""

import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

YOUTUBE_DAILY_UNITS = 200
# The YouTube Data API daily quota resets at midnight Pacific Time.
QUOTA_TIME_ZONE = ZoneInfo("America/Los_Angeles")


class BudgetExhausted(Exception):
    """Raised by an adapter before a call that no longer fits in the budget; the
    batch is left queued, never recorded as a failure."""


def quota_day(now: datetime) -> date:
    return now.astimezone(QUOTA_TIME_ZONE).date()


class DailyUnitBudget:
    def __init__(self, limit: int = YOUTUBE_DAILY_UNITS) -> None:
        self.limit = limit
        self._day: date | None = None
        self._spent = 0
        self._lock = threading.Lock()

    def _roll(self, now: datetime) -> None:
        day = quota_day(now)
        if day != self._day:
            self._day, self._spent = day, 0

    def remaining(self, now: datetime) -> int:
        with self._lock:
            self._roll(now)
            return self.limit - self._spent

    def try_spend(self, now: datetime, units: int = 1) -> bool:
        """Spend `units` right before a call; False (nothing spent) if they do not
        fit in today's budget."""
        with self._lock:
            self._roll(now)
            if self._spent + units > self.limit:
                return False
            self._spent += units
            return True
