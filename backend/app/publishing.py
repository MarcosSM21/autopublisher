"""Generic execution of publications (see contracts/api.md and research.md §1–§9).

This core owns publication statuses, attempts, concurrency, progress, results and
recovery after a restart. Everything platform-specific lives in a `Publisher`
registered by `main.py`; this module never imports a platform adapter, credentials or
an HTTP client.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.automation import (
    DEFAULT_MAX_CONCURRENT_SCHEDULED,
    Clock,
    auto_start_blocker,
    disarm_values,
    is_paused,
    scheduled_claim_conditions,
)
from app.contents import StorageDep
from app.db import utc_now
from app.errors import AppError, ConflictError
from app.models import (
    Account,
    AttemptStage,
    AttemptStatus,
    AttemptTrigger,
    Platform,
    Project,
    Publication,
    PublicationAttempt,
    PublicationStatus,
)
from app.publications import (
    ClockDep,
    SessionDep,
    attempt_to_read,
    get_publication_or_404,
    needs_manual_review,
    publication_read,
)
from app.schemas import (
    PublicationAttemptRead,
    PublicationRead,
    PublishCheckRead,
    PublishProblemRead,
    PublishRequest,
    PublishSummaryItemRead,
)
from app.storage import MediaStorage

logger = logging.getLogger(__name__)

# Statuses from which "Publish now" may start an execution (research.md §13).
ELIGIBLE_STATUSES = (
    PublicationStatus.UNSCHEDULED,
    PublicationStatus.SCHEDULED,
    PublicationStatus.FAILED,
)

INTERRUPTED_MESSAGE = (
    "The upload was interrupted because AutoPublisher stopped. Nothing is retried "
    "automatically."
)
INTERRUPTED_REVIEW_MESSAGE = (
    "The upload was interrupted while sending its last part, so the platform may "
    "have received the video. Check it manually before publishing again."
)
RESULT_NOT_SAVED_MESSAGE = (
    "The platform may have accepted the video, but AutoPublisher could not save the "
    "result. Check it manually (channel, title and time of the attempt) before "
    "publishing again."
)
INTERNAL_ERROR_MESSAGE = "An unexpected error stopped the upload."
INTERNAL_ERROR_REVIEW_MESSAGE = (
    "An unexpected error stopped the upload while sending its last part, so the "
    "platform may have received the video. Check it manually before publishing again."
)
IN_PROGRESS_MESSAGE = "This publication is already being published."
NOT_ELIGIBLE_MESSAGE = "This publication cannot be published in its current state."


# --- Contracts --------------------------------------------------------------------


@dataclass(frozen=True)
class PublishingSettings:
    """Platform-independent runtime settings of the execution core."""

    sleep: Callable[[float], None] = time.sleep
    # Waits before retrying a failed SQLite write of a result (research.md §7).
    persist_retry_waits: tuple[float, ...] = (0.5, 1.0, 2.0)
    # Minimum seconds between two progress writes.
    progress_interval: float = 1.0
    # How long `PublicationRunner.stop()` waits for running uploads.
    stop_timeout: float = 5.0


@dataclass(frozen=True)
class PublishContext:
    """Generic dependencies given to publishers; nothing platform-specific."""

    session_factory: sessionmaker[Session]
    storage: MediaStorage
    settings: PublishingSettings


@dataclass(frozen=True)
class PublishProblem:
    """A reason why a publication cannot be published right now."""

    code: str
    message: str
    field: str | None = None
    status_code: int = 409


@dataclass(frozen=True)
class PublishCheck:
    problems: list[PublishProblem]
    # (label, value) pairs shown in the confirmation dialog.
    summary: list[tuple[str, str]]


@dataclass(frozen=True)
class PreparedPublication:
    """Result of the preflight. `payload` is opaque to the core."""

    publication_id: int
    file_path: Path
    total_bytes: int
    # Non-sensitive snapshot of what is sent to the platform.
    submitted: dict[str, Any]
    payload: object


@dataclass(frozen=True)
class PublishOutcome:
    external_id: str
    external_url: str
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)


class PublishFailure(Exception):
    """An execution that could not complete; `determined` is False when the remote
    outcome is uncertain."""

    def __init__(self, code: str, message: str, *, determined: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.determined = determined


class ProgressReporter(Protocol):
    def report_bytes(self, sent: int, *, confirmed: bool = False) -> None:
        """Record bytes sent; `confirmed` marks a point acknowledged remotely."""

    def enter_final_chunk(self) -> bool:
        """Commit the `final_chunk` stage; send the last part only if True."""

    def leave_final_chunk(self) -> None:
        """The platform confirmed the upload is incomplete: back to `uploading`."""

    def should_stop(self) -> bool:
        """Whether the application is shutting down."""


class Publisher(Protocol):
    def check(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PublishCheck:
        """Local checks only: no network."""

    def prepare(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PreparedPublication:
        """Full preflight, possibly using the network; raises domain errors."""

    def upload(
        self,
        prepared: PreparedPublication,
        reporter: ProgressReporter,
        ctx: PublishContext,
    ) -> PublishOutcome:
        """Run the real upload; raises `PublishFailure`."""

    def refresh_details(
        self,
        prepared: PreparedPublication,
        outcome: PublishOutcome,
        ctx: PublishContext,
    ) -> PublishOutcome:
        """Best-effort light check after a success; may raise."""


# --- Attempts: reading -------------------------------------------------------------


def requires_remote_check(session: Session, content_id: int, account_id: int) -> bool:
    """Whether the latest attempt for this content and account left an uncertain
    remote outcome (research.md §13): publishing again needs explicit confirmation."""
    latest = session.scalars(
        select(PublicationAttempt)
        .join(Publication, PublicationAttempt.publication_id == Publication.id)
        .where(
            Publication.content_id == content_id,
            Publication.account_id == account_id,
        )
        .order_by(PublicationAttempt.started_at.desc(), PublicationAttempt.id.desc())
        .limit(1)
    ).first()
    return latest is not None and needs_manual_review(latest)


# --- Attempts: writing -------------------------------------------------------------


def create_running_attempt(
    session: Session,
    publication: Publication,
    prepared: PreparedPublication,
    platform: str,
    *,
    trigger: AttemptTrigger = AttemptTrigger.MANUAL,
    clock: Clock = utc_now,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_SCHEDULED,
) -> int:
    """Move the publication to `publishing` and create its running attempt, atomically.

    The conditional UPDATE and the unique index on running attempts guarantee that
    concurrent requests start at most one execution (research.md §8). A scheduled
    start re-checks, in the same UPDATE and with the clock read right now, that the
    publication is still armed, in its window, not paused and that an automatic slot
    is free (Feature 007). Leaving `scheduled` always disarms the publication.
    """
    now = clock()
    conditions = [Publication.id == publication.id]
    if trigger == AttemptTrigger.SCHEDULED:
        conditions += scheduled_claim_conditions(now, max_concurrent)
    else:
        conditions.append(Publication.status.in_(ELIGIBLE_STATUSES))
    result = session.execute(
        update(Publication)
        .where(*conditions)
        .values(status=PublicationStatus.PUBLISHING, updated_at=now, **disarm_values())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.rollback()
        raise _not_startable(session, publication.id)
    attempt = PublicationAttempt(
        publication_id=publication.id,
        platform=platform,
        trigger=trigger,
        status=AttemptStatus.RUNNING,
        stage=AttemptStage.PREPARING,
        started_at=now,
        bytes_sent=0,
        total_bytes=prepared.total_bytes,
        submitted=prepared.submitted,
        details={},
        warnings=[],
    )
    session.add(attempt)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ConflictError("publication_in_progress", IN_PROGRESS_MESSAGE) from None
    session.refresh(publication)
    return attempt.id


def _not_startable(session: Session, publication_id: int) -> ConflictError:
    current = session.get(Publication, publication_id)
    if current is not None and current.status == PublicationStatus.PUBLISHING:
        return ConflictError("publication_in_progress", IN_PROGRESS_MESSAGE)
    return ConflictError("publication_not_eligible", NOT_ELIGIBLE_MESSAGE)


def report_progress(ctx: PublishContext, attempt_id: int, bytes_sent: int) -> None:
    """Persist progress; a failed write never stops the upload."""
    try:
        with ctx.session_factory() as session:
            session.execute(
                update(PublicationAttempt)
                .where(
                    PublicationAttempt.id == attempt_id,
                    PublicationAttempt.status == AttemptStatus.RUNNING,
                )
                .values(bytes_sent=bytes_sent, progress_updated_at=utc_now())
            )
            session.commit()
    except SQLAlchemyError:
        logger.warning("Could not save the progress of attempt %s.", attempt_id)


def set_stage(ctx: PublishContext, attempt_id: int, stage: AttemptStage) -> bool:
    """Commit a stage change; False when it could not be saved."""
    try:
        with ctx.session_factory() as session:
            session.execute(
                update(PublicationAttempt)
                .where(
                    PublicationAttempt.id == attempt_id,
                    PublicationAttempt.status == AttemptStatus.RUNNING,
                )
                .values(stage=stage)
            )
            session.commit()
    except SQLAlchemyError:
        logger.warning("Could not save the stage of attempt %s.", attempt_id)
        return False
    return True


def _with_retries(ctx: PublishContext, write: Callable[[Session], None]) -> bool:
    waits = ctx.settings.persist_retry_waits
    for try_number in range(len(waits) + 1):
        try:
            with ctx.session_factory() as session:
                write(session)
                session.commit()
            return True
        except SQLAlchemyError:
            if try_number < len(waits):
                ctx.settings.sleep(waits[try_number])
    return False


def persist_success(
    ctx: PublishContext, attempt_id: int, outcome: PublishOutcome
) -> bool:
    """Save the remote result, the successful attempt and the published publication
    in one transaction, right after the platform returned it (research.md §7)."""

    def write(session: Session) -> None:
        now = utc_now()
        attempt = session.get_one(PublicationAttempt, attempt_id)
        attempt.status = AttemptStatus.SUCCEEDED
        attempt.stage = AttemptStage.DONE
        attempt.finished_at = now
        attempt.outcome_determined = True
        attempt.bytes_sent = attempt.total_bytes
        attempt.external_id = outcome.external_id
        attempt.external_url = outcome.external_url
        attempt.details = dict(outcome.details)
        attempt.warnings = list(outcome.warnings)
        publication = session.get_one(Publication, attempt.publication_id)
        publication.status = PublicationStatus.PUBLISHED
        publication.published_at = now
        publication.updated_at = now

    return _with_retries(ctx, write)


def persist_failure(
    ctx: PublishContext,
    attempt_id: int,
    code: str,
    message: str,
    *,
    determined: bool,
) -> bool:
    """Close the attempt as failed and the publication as `failed`. Never stores an
    external id: a result that could not be saved is not kept anywhere."""

    def write(session: Session) -> None:
        now = utc_now()
        attempt = session.get_one(PublicationAttempt, attempt_id)
        attempt.status = AttemptStatus.FAILED
        attempt.finished_at = now
        attempt.error_code = code
        attempt.error_message = message
        attempt.outcome_determined = determined
        publication = session.get_one(Publication, attempt.publication_id)
        publication.status = PublicationStatus.FAILED
        publication.updated_at = now

    return _with_retries(ctx, write)


def update_details(
    ctx: PublishContext, attempt_id: int, outcome: PublishOutcome
) -> None:
    """Store refined, non-sensitive details of a successful attempt (best effort)."""
    try:
        with ctx.session_factory() as session:
            attempt = session.get_one(PublicationAttempt, attempt_id)
            attempt.details = dict(outcome.details)
            attempt.warnings = list(outcome.warnings)
            session.commit()
    except SQLAlchemyError:
        logger.warning("Could not save the details of attempt %s.", attempt_id)


def recover_interrupted_attempts(session_factory: sessionmaker[Session]) -> int:
    """Close attempts left running by a previous process. Nothing is resumed or
    uploaded again; an attempt that reached `final_chunk` needs manual review."""
    with session_factory() as session:
        attempts = list(
            session.scalars(
                select(PublicationAttempt).where(
                    PublicationAttempt.status == AttemptStatus.RUNNING
                )
            )
        )
        now = utc_now()
        for attempt in attempts:
            determined = attempt.stage != AttemptStage.FINAL_CHUNK
            attempt.status = AttemptStatus.FAILED
            attempt.finished_at = now
            attempt.error_code = "interrupted"
            attempt.error_message = (
                INTERRUPTED_MESSAGE if determined else INTERRUPTED_REVIEW_MESSAGE
            )
            attempt.outcome_determined = determined
            publication = session.get_one(Publication, attempt.publication_id)
            if publication.status == PublicationStatus.PUBLISHING:
                publication.status = PublicationStatus.FAILED
                publication.updated_at = now
        session.commit()
    if attempts:
        logger.warning("Closed %s interrupted publication attempt(s).", len(attempts))
    return len(attempts)


# --- Runner ------------------------------------------------------------------------


class _AttemptReporter:
    def __init__(
        self, ctx: PublishContext, attempt_id: int, stop_event: threading.Event
    ) -> None:
        self.ctx = ctx
        self.attempt_id = attempt_id
        self.stop_event = stop_event
        self.stage = AttemptStage.PREPARING
        self._last_write = 0.0

    def report_bytes(self, sent: int, *, confirmed: bool = False) -> None:
        if self.stage == AttemptStage.PREPARING:
            set_stage(self.ctx, self.attempt_id, AttemptStage.UPLOADING)
            self.stage = AttemptStage.UPLOADING
        now = time.monotonic()
        if confirmed or now - self._last_write >= self.ctx.settings.progress_interval:
            self._last_write = now
            report_progress(self.ctx, self.attempt_id, sent)

    def enter_final_chunk(self) -> bool:
        if not set_stage(self.ctx, self.attempt_id, AttemptStage.FINAL_CHUNK):
            return False
        self.stage = AttemptStage.FINAL_CHUNK
        return True

    def leave_final_chunk(self) -> None:
        set_stage(self.ctx, self.attempt_id, AttemptStage.UPLOADING)
        self.stage = AttemptStage.UPLOADING

    def should_stop(self) -> bool:
        return self.stop_event.is_set()


class PublicationRunner:
    """Runs uploads in daemon threads so the API never waits for them."""

    def __init__(self, ctx: PublishContext) -> None:
        self.ctx = ctx
        self._threads: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def start(
        self, attempt_id: int, prepared: PreparedPublication, publisher: Publisher
    ) -> None:
        thread = threading.Thread(
            target=self._run,
            args=(attempt_id, prepared, publisher),
            name=f"publication-attempt-{attempt_id}",
            daemon=True,
        )
        with self._lock:
            self._threads[attempt_id] = thread
        try:
            thread.start()
        except RuntimeError:
            with self._lock:
                self._threads.pop(attempt_id, None)
            persist_failure(
                self.ctx,
                attempt_id,
                "internal_error",
                INTERNAL_ERROR_MESSAGE,
                determined=True,
            )

    def _run(
        self, attempt_id: int, prepared: PreparedPublication, publisher: Publisher
    ) -> None:
        reporter = _AttemptReporter(self.ctx, attempt_id, self._stop_event)
        try:
            self._execute(attempt_id, prepared, publisher, reporter)
        finally:
            with self._lock:
                self._threads.pop(attempt_id, None)

    def _execute(
        self,
        attempt_id: int,
        prepared: PreparedPublication,
        publisher: Publisher,
        reporter: _AttemptReporter,
    ) -> None:
        try:
            outcome = publisher.upload(prepared, reporter, self.ctx)
        except PublishFailure as failure:
            persist_failure(
                self.ctx,
                attempt_id,
                failure.code,
                failure.message,
                determined=failure.determined,
            )
            return
        except Exception as exc:  # The thread must always close its attempt.
            # Only the class name: messages of HTTP errors may contain URLs.
            logger.error(
                "Publication attempt %s stopped unexpectedly (%s).",
                attempt_id,
                type(exc).__name__,
            )
            determined = reporter.stage != AttemptStage.FINAL_CHUNK
            persist_failure(
                self.ctx,
                attempt_id,
                "internal_error",
                INTERNAL_ERROR_MESSAGE if determined else INTERNAL_ERROR_REVIEW_MESSAGE,
                determined=determined,
            )
            return

        if not persist_success(self.ctx, attempt_id, outcome):
            # Never logged: the external id may give access to the uploaded item.
            logger.error(
                "The result of publication attempt %s could not be saved "
                "(result_not_saved); manual review is required.",
                attempt_id,
            )
            persist_failure(
                self.ctx,
                attempt_id,
                "result_not_saved",
                RESULT_NOT_SAVED_MESSAGE,
                determined=False,
            )
            return
        try:
            refined = publisher.refresh_details(prepared, outcome, self.ctx)
        except Exception as exc:  # The light check is optional.
            logger.info(
                "Light check after attempt %s skipped (%s).",
                attempt_id,
                type(exc).__name__,
            )
            return
        update_details(self.ctx, attempt_id, refined)

    @property
    def stopping(self) -> bool:
        return self._stop_event.is_set()

    def is_live(self, attempt_id: int) -> bool:
        with self._lock:
            return attempt_id in self._threads

    def wait_idle(self, timeout: float = 10) -> bool:
        """Wait until no upload is running (used by tests)."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                threads = list(self._threads.values())
            if not threads:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            threads[0].join(remaining)

    def stop(self) -> None:
        """Ask running uploads to stop and wait for them, up to `stop_timeout`."""
        self._stop_event.set()
        deadline = time.monotonic() + self.ctx.settings.stop_timeout
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)


# --- Service -----------------------------------------------------------------------

PLATFORM_NAMES = {
    Platform.YOUTUBE: "YouTube",
    Platform.INSTAGRAM: "Instagram",
    Platform.TIKTOK: "TikTok",
    Platform.X: "X",
    Platform.THREADS: "Threads",
    Platform.TELEGRAM: "Telegram",
}


def local_check(
    session: Session,
    publication: Publication,
    ctx: PublishContext,
    publishers: Mapping[Platform, Publisher],
) -> PublishCheck:
    """Every check that needs no network, in the order of contracts/api.md: the
    generic ones here, then the publisher's own."""
    problems: list[PublishProblem] = []
    if publication.status == PublicationStatus.PUBLISHING:
        problems.append(PublishProblem("publication_in_progress", IN_PROGRESS_MESSAGE))
    elif publication.status not in ELIGIBLE_STATUSES:
        problems.append(
            PublishProblem("publication_not_eligible", NOT_ELIGIBLE_MESSAGE)
        )
    project = session.get_one(Project, publication.project_id)
    account = session.get_one(Account, publication.account_id)
    if not project.is_active:
        problems.append(
            PublishProblem(
                "project_inactive", "Reactivate the project before publishing."
            )
        )
    if not account.is_active:
        problems.append(
            PublishProblem(
                "account_inactive", "Reactivate the account before publishing."
            )
        )
    publisher = publishers.get(Platform(account.platform))
    if publisher is None:
        name = PLATFORM_NAMES[Platform(account.platform)]
        problems.append(
            PublishProblem(
                "platform_not_supported",
                f"Publishing to {name} is not available yet.",
            )
        )
        return PublishCheck(problems, [])
    check = publisher.check(session, publication, ctx)
    return PublishCheck(problems + check.problems, check.summary)


def problem_error(problems: list[PublishProblem]) -> AppError:
    """The first problem, with the fields of every problem sharing its code."""
    first = problems[0]
    fields = [
        {"field": problem.field, "message": problem.message}
        for problem in problems
        if problem.code == first.code and problem.field is not None
    ]
    return AppError(first.status_code, first.code, first.message, fields=fields)


def start_publication(
    session: Session,
    publication_id: int,
    *,
    confirm_remote_checked: bool,
    ctx: PublishContext,
    runner: "PublicationRunner",
    publishers: Mapping[Platform, Publisher],
    trigger: AttemptTrigger = AttemptTrigger.MANUAL,
    clock: Clock = utc_now,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_SCHEDULED,
) -> int:
    """Preflight, atomic move to `publishing` and background upload.

    A plain function without HTTP types, so the scheduler reuses it. No failing check
    changes the publication or contacts the upload endpoint. A scheduled start is
    first checked without network, never confirms a remote review on behalf of the
    user, and reads `clock` again just before the atomic claim.
    """
    publication = get_publication_or_404(session, publication_id)
    if trigger == AttemptTrigger.SCHEDULED:
        confirm_remote_checked = False
        if auto_start_blocker(publication, is_paused(session), clock()) is not None:
            raise ConflictError("publication_not_eligible", NOT_ELIGIBLE_MESSAGE)
    check = local_check(session, publication, ctx, publishers)
    if check.problems:
        raise problem_error(check.problems)
    if not confirm_remote_checked and requires_remote_check(
        session, publication.content_id, publication.account_id
    ):
        raise ConflictError(
            "remote_check_required",
            "The last attempt may have published the video. Check the platform "
            "(channel, title and time of the attempt) and confirm before publishing "
            "again.",
        )
    account = session.get_one(Account, publication.account_id)
    platform = Platform(account.platform)
    publisher = publishers[platform]
    prepared = publisher.prepare(session, publication, ctx)
    attempt_id = create_running_attempt(
        session,
        publication,
        prepared,
        platform,
        trigger=trigger,
        clock=clock,
        max_concurrent=max_concurrent,
    )
    runner.start(attempt_id, prepared, publisher)
    return attempt_id


# --- API ---------------------------------------------------------------------------

router = APIRouter(prefix="/api", tags=["publishing"])


def get_publishers(request: Request) -> Mapping[Platform, Publisher]:
    publishers: Mapping[Platform, Publisher] = request.app.state.publishers
    return publishers


def get_publish_context(request: Request) -> PublishContext:
    ctx: PublishContext = request.app.state.publish_context
    return ctx


def get_runner(request: Request) -> "PublicationRunner":
    runner: PublicationRunner = request.app.state.publication_runner
    return runner


PublishersDep = Annotated[Mapping[Platform, Publisher], Depends(get_publishers)]
ContextDep = Annotated[PublishContext, Depends(get_publish_context)]
RunnerDep = Annotated["PublicationRunner", Depends(get_runner)]


@router.get(
    "/publications/{publication_id}/publish-check", response_model=PublishCheckRead
)
def get_publish_check(
    publication_id: int,
    session: SessionDep,
    ctx: ContextDep,
    publishers: PublishersDep,
) -> PublishCheckRead:
    """What "Publish now" would do, without contacting any platform."""
    publication = get_publication_or_404(session, publication_id)
    check = local_check(session, publication, ctx, publishers)
    return PublishCheckRead(
        eligible=not check.problems,
        problems=[
            PublishProblemRead(code=p.code, message=p.message, field=p.field)
            for p in check.problems
        ],
        requires_remote_check=requires_remote_check(
            session, publication.content_id, publication.account_id
        ),
        summary=[
            PublishSummaryItemRead(label=label, value=value)
            for label, value in check.summary
        ],
        scheduled_at=(
            publication.scheduled_at
            if publication.status == PublicationStatus.SCHEDULED
            else None
        ),
    )


@router.post(
    "/publications/{publication_id}/publish",
    response_model=PublicationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def publish_now(
    publication_id: int,
    body: PublishRequest,
    session: SessionDep,
    storage: StorageDep,
    ctx: ContextDep,
    runner: RunnerDep,
    publishers: PublishersDep,
    clock: ClockDep,
) -> PublicationRead:
    """Start the upload and answer at once; progress is read with GET."""
    start_publication(
        session,
        publication_id,
        confirm_remote_checked=body.confirm_remote_checked,
        ctx=ctx,
        runner=runner,
        publishers=publishers,
    )
    publication = get_publication_or_404(session, publication_id)
    return publication_read(session, publication, storage, clock)


@router.get(
    "/publications/{publication_id}/attempts",
    response_model=list[PublicationAttemptRead],
)
def list_attempts(
    publication_id: int, session: SessionDep
) -> list[PublicationAttemptRead]:
    """Every attempt of a publication, newest first."""
    get_publication_or_404(session, publication_id)
    attempts = session.scalars(
        select(PublicationAttempt)
        .where(PublicationAttempt.publication_id == publication_id)
        .order_by(PublicationAttempt.started_at.desc(), PublicationAttempt.id.desc())
    )
    return [attempt_to_read(attempt) for attempt in attempts]
