"""Local scheduler: starts armed scheduled publications when their time comes.

It only decides *when* to call the generic `start_publication` service (see
research.md §1–§7); it never uploads, validates or knows any platform. It lives in
the backend process: while the backend is not running, nothing is published.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import publishing
from app.automation import (
    AUTO_PUBLISH_RETRY_INTERVAL,
    AUTO_PUBLISH_WINDOW,
    DEFAULT_MAX_CONCURRENT_SCHEDULED,
    Clock,
    is_paused,
    record_auto_publish_error,
    running_scheduled_attempts,
)
from app.db import utc_now
from app.errors import AppError, ConflictError, NotFoundError
from app.models import AttemptTrigger, Platform, Publication, PublicationStatus
from app.publishing import PublicationRunner, PublishContext, Publisher

# Lost races, a pause, an expired window or no free slot: nothing to fix.
NOT_CLAIMED_CODES = {"publication_in_progress", "publication_not_eligible"}
INTERNAL_ERROR_MESSAGE = "AutoPublisher could not start this publication automatically."

Outcome = Literal["started", "not_claimed", "failed"]


class Candidate(NamedTuple):
    id: int
    scheduled_at: datetime
    failed_at: datetime | None


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerSettings:
    clock: Clock = utc_now
    # Seconds between two cycles.
    interval: float = 30.0
    # Waits up to the given seconds; returns early when woken. Defaults to an
    # interruptible wait on the scheduler's own events.
    wait: Callable[[float], object] | None = None
    autostart: bool = True
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_SCHEDULED
    preflight_retry_interval: float = AUTO_PUBLISH_RETRY_INTERVAL.total_seconds()
    stop_timeout: float = 5.0


@dataclass
class TickReport:
    """What one cycle did, for tests and logs."""

    started: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    skipped_capacity: list[int] = field(default_factory=list)
    skipped_retry: list[int] = field(default_factory=list)


class Scheduler:
    """Runs `run_once()` at start-up and then every `interval` seconds in a daemon
    thread; the database is the only source of truth."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        ctx: PublishContext,
        runner: PublicationRunner,
        publishers: Mapping[Platform, Publisher],
        settings: SchedulerSettings,
    ) -> None:
        self.session_factory = session_factory
        self.ctx = ctx
        self.runner = runner
        self.publishers = publishers
        self.settings = settings
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_check_at: datetime | None = None

    # --- Lifecycle ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="publication-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(self.settings.stop_timeout)

    def wake(self) -> None:
        """Run the next cycle now instead of waiting for the interval."""
        self._wake_event.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_check_at(self) -> datetime | None:
        return self._last_check_at

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._tick()
            if self._stop_event.is_set():
                break
            self._wait()

    def _wait(self) -> None:
        if self.settings.wait is not None:
            self.settings.wait(self.settings.interval)
            return
        self._wake_event.wait(self.settings.interval)
        self._wake_event.clear()

    def _tick(self) -> None:
        try:
            self.run_once()
        except Exception as exc:  # A failed cycle never stops the scheduler.
            logger.error("Scheduler cycle failed (%s).", type(exc).__name__)

    # --- One cycle ------------------------------------------------------------------

    def run_once(self) -> TickReport:
        """One cycle: select due armed publications in a stable order and try to
        start each one through the generic publishing service."""
        report = TickReport()
        now = self.settings.clock()
        if self._paused():
            # Nothing is selected nor checked: no platform is contacted.
            self._last_check_at = now
            return report
        retry_after = timedelta(seconds=self.settings.preflight_retry_interval)
        # Pre-check of automatic slots, so no preflight runs for publications that
        # could not start anyway; the guarantee itself is in the atomic claim.
        free_slots = self.settings.max_concurrent - self._slots_in_use()
        for candidate in self._candidates(now):
            if self._stop_event.is_set():
                break
            # The time of the last failure is persisted, so the throttle also
            # holds after a restart.
            if candidate.failed_at is not None and now < candidate.failed_at + (
                retry_after
            ):
                report.skipped_retry.append(candidate.id)
                continue
            if len(report.started) >= free_slots:
                report.skipped_capacity.append(candidate.id)
                continue
            outcome = self._start(candidate)
            if outcome == "started":
                report.started.append(candidate.id)
            elif outcome == "failed":
                report.failed.append(candidate.id)
        self._last_check_at = now
        return report

    def _slots_in_use(self) -> int:
        with self.session_factory() as session:
            return running_scheduled_attempts(session)

    def _paused(self) -> bool:
        with self.session_factory() as session:
            return is_paused(session)

    def _candidates(self, now: datetime) -> list[Candidate]:
        with self.session_factory() as session:
            rows = session.execute(
                select(
                    Publication.id,
                    Publication.scheduled_at,
                    Publication.auto_publish_failed_at,
                )
                .where(
                    Publication.status == PublicationStatus.SCHEDULED,
                    Publication.auto_publish_enabled.is_(True),
                    Publication.scheduled_at <= now,
                    Publication.scheduled_at >= now - AUTO_PUBLISH_WINDOW,
                )
                .order_by(Publication.scheduled_at, Publication.id)
            ).all()
        return [
            Candidate(publication_id, scheduled_at, failed_at)
            for publication_id, scheduled_at, failed_at in rows
            if scheduled_at is not None
        ]

    def _start(self, candidate: Candidate) -> Outcome:
        """Start one candidate; a failed preflight is recorded, never raised."""
        try:
            with self.session_factory() as session:
                publishing.start_publication(
                    session,
                    candidate.id,
                    confirm_remote_checked=False,
                    ctx=self.ctx,
                    runner=self.runner,
                    publishers=self.publishers,
                    trigger=AttemptTrigger.SCHEDULED,
                    clock=self.settings.clock,
                    max_concurrent=self.settings.max_concurrent,
                )
        except (ConflictError, AppError, NotFoundError) as error:
            code = getattr(error, "code", "not_found")
            if code in NOT_CLAIMED_CODES:
                logger.debug(
                    "Publication %s was not started automatically (%s).",
                    candidate.id,
                    code,
                )
                return "not_claimed"
            # API errors carry fixed, safe messages (Features 005/006).
            self._record_failure(candidate, code, error.message)
            return "failed"
        except Exception as exc:  # Never let one publication stop the cycle.
            # Only the class name: messages of arbitrary errors may hold secrets.
            logger.error(
                "Automatic start of publication %s failed (%s).",
                candidate.id,
                type(exc).__name__,
            )
            self._record_failure(candidate, "internal_error", INTERNAL_ERROR_MESSAGE)
            return "failed"
        logger.info("Started publication %s automatically.", candidate.id)
        return "started"

    def _record_failure(self, candidate: Candidate, code: str, message: str) -> None:
        logger.warning(
            "Publication %s could not start automatically (%s).", candidate.id, code
        )
        with self.session_factory() as session:
            record_auto_publish_error(
                session,
                candidate.id,
                candidate.scheduled_at,
                code,
                message,
                self.settings.clock(),
            )
