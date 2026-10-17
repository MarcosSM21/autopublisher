"""What the user sees about a post (Feature 018, research.md §7).

The only implementation of the visible state: `publication_to_read` and the
overview both call `post_display_state`, so the frontend never derives it again.
Pure: no database, no clock of its own.
"""

from datetime import datetime

from app.automation import is_overdue
from app.models import AttemptStatus, PublicationAttempt
from app.models import PublicationStatus as Status
from app.schemas import PostDisplayState


def needs_manual_review(attempt: PublicationAttempt) -> bool:
    failed = attempt.status == AttemptStatus.FAILED
    return failed and attempt.outcome_determined is False


def post_display_state(
    status: str,
    armed: bool,
    scheduled_at: datetime | None,
    paused: bool,
    latest_attempt: PublicationAttempt | None,
    now: datetime,
) -> PostDisplayState:
    """The table of research.md §7, rule by rule in its order."""
    if status == Status.PUBLISHING:
        return "publishing"
    if status == Status.PUBLISHED:
        return "published"
    if status == Status.CANCELLED:
        return "cancelled"
    if status == Status.AWAITING_USER_ACTION:
        return "needs_action"
    if status == Status.FAILED:
        if latest_attempt is not None and needs_manual_review(latest_attempt):
            return "needs_review"
        return "failed"
    if status != Status.SCHEDULED or scheduled_at is None:
        return "draft"
    if is_overdue(status, armed, scheduled_at, now):
        return "missed"
    if not armed and scheduled_at <= now:
        return "missed"
    if armed and paused:
        return "scheduled_paused"
    return "scheduled_automatic" if armed else "scheduled_manual"
