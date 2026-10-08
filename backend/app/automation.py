"""Rules of automatic publishing (see contracts/api.md and research.md §3–§10).

Generic: nothing here knows any platform. It defines the automatic window, the
derived state shown to the user (overdue is a condition, never a status), the
global pause and the guards of the atomic claim used by the scheduler.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, Request
from sqlalchemy import exists, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db import get_session
from app.models import (
    AttemptStatus,
    AttemptTrigger,
    AutomationSettings,
    AutoPublishState,
    Publication,
    PublicationAttempt,
    PublicationStatus,
)
from app.schemas import AutomationStatusRead, AutomationUpdate

logger = logging.getLogger(__name__)

AUTO_PUBLISH_WINDOW = timedelta(minutes=10)
AUTO_PUBLISH_RETRY_INTERVAL = timedelta(seconds=120)
DEFAULT_MAX_CONCURRENT_SCHEDULED = 2
SETTINGS_ID = 1

Clock = Callable[[], datetime]


class _Schedulable(Protocol):
    status: str
    auto_publish_enabled: bool
    scheduled_at: datetime | None


# --- Pure rules ---------------------------------------------------------------------


def window_ends_at(scheduled_at: datetime) -> datetime:
    return scheduled_at + AUTO_PUBLISH_WINDOW


def in_window(scheduled_at: datetime, now: datetime) -> bool:
    """Whether `now` is inside the automatic window; both ends included."""
    return scheduled_at <= now <= window_ends_at(scheduled_at)


def is_overdue(
    status: str, armed: bool, scheduled_at: datetime | None, now: datetime
) -> bool:
    """An armed scheduled publication that missed its automatic window. A disarmed
    one is never overdue: nobody expected it to start by itself."""
    return (
        status == PublicationStatus.SCHEDULED
        and armed
        and scheduled_at is not None
        and now > window_ends_at(scheduled_at)
    )


def auto_publish_state(
    status: str,
    armed: bool,
    scheduled_at: datetime | None,
    paused: bool,
    now: datetime,
) -> AutoPublishState | None:
    if status != PublicationStatus.SCHEDULED or scheduled_at is None:
        return None
    if not armed:
        return AutoPublishState.DISABLED
    if is_overdue(status, armed, scheduled_at, now):
        return AutoPublishState.OVERDUE
    if paused:
        return AutoPublishState.PAUSED
    if now < scheduled_at:
        return AutoPublishState.WAITING
    return AutoPublishState.DUE


def auto_start_blocker(
    publication: _Schedulable, paused: bool, now: datetime
) -> str | None:
    """Why the scheduler may not start this publication now, or None."""
    if publication.status != PublicationStatus.SCHEDULED:
        return "not scheduled"
    if not publication.auto_publish_enabled:
        return "auto-publish disabled"
    if paused:
        return "automation paused"
    if publication.scheduled_at is None or not in_window(publication.scheduled_at, now):
        return "outside the automatic window"
    return None


# --- Persistence --------------------------------------------------------------------


def is_paused(session: Session) -> bool:
    settings = session.get(AutomationSettings, SETTINGS_ID)
    if settings is None:
        logger.warning("Automation settings are missing; automation is paused.")
        return True
    return settings.automation_paused


def set_paused(session: Session, paused: bool, now: datetime) -> None:
    settings = session.get(AutomationSettings, SETTINGS_ID)
    if settings is None:
        session.add(
            AutomationSettings(id=SETTINGS_ID, automation_paused=paused, updated_at=now)
        )
    elif settings.automation_paused != paused:
        settings.automation_paused = paused
        settings.updated_at = now
    session.commit()


def disarm_values() -> dict[str, Any]:
    """Columns to write whenever a publication leaves `scheduled` or is disarmed."""
    return {
        "auto_publish_enabled": False,
        "auto_publish_error_code": None,
        "auto_publish_error_message": None,
        "auto_publish_failed_at": None,
    }


def clear_auto_publish_error(publication: Publication) -> None:
    publication.auto_publish_error_code = None
    publication.auto_publish_error_message = None
    publication.auto_publish_failed_at = None


def disarm(publication: Publication) -> None:
    publication.auto_publish_enabled = False
    clear_auto_publish_error(publication)


def running_scheduled_attempts(session: Session) -> int:
    """Automatic slots in use: running attempts started by the scheduler."""
    return (
        session.scalar(
            select(func.count(PublicationAttempt.id)).where(
                PublicationAttempt.status == AttemptStatus.RUNNING,
                PublicationAttempt.trigger == AttemptTrigger.SCHEDULED,
            )
        )
        or 0
    )


def scheduled_claim_conditions(
    now: datetime, max_concurrent: int
) -> list[ColumnElement[bool]]:
    """Guards re-checked by the claim UPDATE of a scheduled start (research.md §5)."""
    running = PublicationAttempt.status == AttemptStatus.RUNNING
    slots_in_use = (
        select(func.count(PublicationAttempt.id))
        .where(running, PublicationAttempt.trigger == AttemptTrigger.SCHEDULED)
        .scalar_subquery()
    )
    return [
        Publication.status == PublicationStatus.SCHEDULED,
        Publication.auto_publish_enabled.is_(True),
        ~exists().where(
            AutomationSettings.id == SETTINGS_ID,
            AutomationSettings.automation_paused.is_(True),
        ),
        Publication.scheduled_at <= now,
        Publication.scheduled_at >= now - AUTO_PUBLISH_WINDOW,
        ~exists().where(PublicationAttempt.publication_id == Publication.id, running),
        slots_in_use < max_concurrent,
    ]


def record_auto_publish_error(
    session: Session,
    publication_id: int,
    scheduled_at: datetime,
    code: str,
    message: str,
    now: datetime,
) -> bool:
    """Store the last automatic failure, only if the publication is still armed for
    the same date (a reschedule in between makes the error stale)."""
    result = session.execute(
        update(Publication)
        .where(
            Publication.id == publication_id,
            Publication.status == PublicationStatus.SCHEDULED,
            Publication.auto_publish_enabled.is_(True),
            Publication.scheduled_at == scheduled_at,
        )
        .values(
            auto_publish_error_code=code,
            auto_publish_error_message=message,
            auto_publish_failed_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


# --- Dependencies -------------------------------------------------------------------


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


# --- API ----------------------------------------------------------------------------

router = APIRouter(prefix="/api", tags=["automation"])


def _status(request: Request, session: Session) -> AutomationStatusRead:
    scheduler = request.app.state.scheduler
    return AutomationStatusRead(
        paused=is_paused(session),
        running=scheduler.running,
        last_check_at=scheduler.last_check_at,
        check_interval_seconds=scheduler.settings.interval,
        window_minutes=int(AUTO_PUBLISH_WINDOW.total_seconds() // 60),
    )


@router.get("/automation", response_model=AutomationStatusRead)
def get_automation(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> AutomationStatusRead:
    """Whether automatic publishing is paused and whether the scheduler runs."""
    return _status(request, session)


@router.put("/automation", response_model=AutomationStatusRead)
def update_automation(
    body: AutomationUpdate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AutomationStatusRead:
    """Pause or resume automatic publishing. Pausing never stops running uploads
    nor "Publish now"; resuming only starts publications still in their window."""
    clock: Clock = request.app.state.clock
    set_paused(session, body.paused, clock())
    if not body.paused:
        request.app.state.scheduler.wake()
    return _status(request, session)
