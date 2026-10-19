"""What the user sees about a post (Feature 018, research.md §7).

The only implementation of the visible state: `publication_to_read` and the
overview both call `post_display_state`, so the frontend never derives it again.
`post_display_state` is pure (no database, no clock of its own);
`requires_remote_check` reads the latest attempt of a content and account.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automation import is_overdue
from app.models import AttemptStatus, Publication, PublicationAttempt
from app.models import PublicationStatus as Status
from app.schemas import PostDisplayState


def needs_manual_review(attempt: PublicationAttempt) -> bool:
    failed = attempt.status == AttemptStatus.FAILED
    return failed and attempt.outcome_determined is False


def requires_remote_check(session: Session, publication: Publication) -> bool:
    """Whether the latest attempt for this content and account left an uncertain
    remote outcome (research.md §13): publishing again needs explicit confirmation.
    Without content, each publication is its own post: only its attempts count."""
    query = select(PublicationAttempt).join(
        Publication, PublicationAttempt.publication_id == Publication.id
    )
    if publication.content_id is None:
        query = query.where(Publication.id == publication.id)
    else:
        query = query.where(
            Publication.content_id == publication.content_id,
            Publication.account_id == publication.account_id,
        )
    latest = session.scalars(
        query.order_by(
            PublicationAttempt.started_at.desc(), PublicationAttempt.id.desc()
        ).limit(1)
    ).first()
    return latest is not None and needs_manual_review(latest)


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
