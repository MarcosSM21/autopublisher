"""Publications: the intent to publish a content on an account (see contracts/api.md).

Nothing here publishes anything or reacts to the passing of time: a status only changes
when the user asks for it. Real executions live in `app.publishing`.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.automation import (
    Clock,
    auto_publish_state,
    clear_auto_publish_error,
    disarm,
    get_clock,
    is_paused,
    window_ends_at,
)
from app.contents import StorageDep, file_available, get_content_or_404
from app.db import get_session, utc_now
from app.errors import AppError, ConflictError, NotFoundError, field_errors
from app.models import (
    Account,
    AttemptStage,
    AttemptStatus,
    AttemptTrigger,
    Content,
    MediaType,
    Platform,
    Project,
    Publication,
    PublicationAttempt,
)
from app.models import PublicationStatus as Status
from app.post_state import (
    needs_manual_review,
    post_display_state,
    requires_remote_check,
)
from app.projects import get_project_or_404
from app.schemas import (
    AutoPublishErrorRead,
    PublicationAccountSummary,
    PublicationAttemptErrorRead,
    PublicationAttemptRead,
    PublicationContentSummary,
    PublicationCreate,
    PublicationRead,
    PublicationUpdate,
    PublicationWarningRead,
    TextPublicationCreate,
)
from app.storage import MediaStorage

router = APIRouter(prefix="/api", tags=["publications"])

SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]

MEDIA_UNAVAILABLE_MESSAGE = "The media file of this content is not available."

# Statuses that are history: they never block a new publication of the same pair.
HISTORY_STATUSES = (Status.CANCELLED, Status.PUBLISHED)

AttemptInfo = tuple[PublicationAttempt, int]

PLATFORM_LABELS = {
    Platform.YOUTUBE: "YouTube",
    Platform.INSTAGRAM: "Instagram",
    Platform.TIKTOK: "TikTok",
    Platform.X: "X",
    Platform.THREADS: "Threads",
    Platform.TELEGRAM: "Telegram",
}


def effective_metadata(
    publication: Publication, content: Content | None
) -> tuple[str | None, str | None, list[str]]:
    """Title, description and hashtags: the overrides, else the content's (only the
    overrides for a publication without content)."""
    title = (
        publication.title_override
        if publication.title_override is not None or content is None
        else content.title
    )
    description = (
        publication.description_override
        if publication.description_override is not None or content is None
        else content.description
    )
    hashtags = (
        publication.hashtags_override
        if publication.hashtags_override is not None or content is None
        else content.hashtags
    )
    return title, description, list(hashtags or [])


def description_with_hashtags(description: str | None, hashtags: list[str]) -> str:
    """Effective description, then a blank line and the hashtags as `#a #b`."""
    tags = " ".join(f"#{tag}" for tag in hashtags)
    parts = [part for part in (description or "", tags) if part]
    return "\n\n".join(parts)


def ensure_not_publishing(session: Session, account_id: int) -> None:
    """A connection cannot change while one of its publications is running."""
    running = session.scalars(
        select(Publication.id).where(
            Publication.account_id == account_id,
            Publication.status == Status.PUBLISHING,
        )
    ).first()
    if running is not None:
        raise ConflictError(
            "publication_in_progress",
            "A publication of this account is being uploaded. Wait until it "
            "finishes before changing the connection.",
        )


def account_label(account: Account) -> str:
    """Name an account the way the user sees it, e.g. "Instagram @l4i4"; a
    provisional account (identity not known yet) is "Instagram account", with its
    display name when it has one."""
    platform = PLATFORM_LABELS[Platform(account.platform)]
    if account.handle is not None:
        return f"{platform} @{account.handle}"
    if account.display_name:
        return f"{platform} account · {account.display_name}"
    return f"{platform} account"


def account_reference(account: Account) -> str:
    """The "@handle" for messages that already name the platform, else the label."""
    return (
        f"@{account.handle}" if account.handle is not None else account_label(account)
    )


def get_publication_or_404(session: Session, publication_id: int) -> Publication:
    publication = session.get(Publication, publication_id)
    if publication is None:
        raise NotFoundError("Publication not found.")
    return publication


# Highest progress shown for an attempt that has not succeeded: 1.0 means published.
MAX_UNFINISHED_PROGRESS = 0.99


def attempt_to_read(attempt: PublicationAttempt) -> PublicationAttemptRead:
    if attempt.status == AttemptStatus.SUCCEEDED:
        progress = 1.0
    elif attempt.total_bytes:
        progress = min(
            attempt.bytes_sent / attempt.total_bytes, MAX_UNFINISHED_PROGRESS
        )
    else:
        progress = 0.0
    error = None
    if attempt.error_code is not None:
        error = PublicationAttemptErrorRead(
            code=attempt.error_code, message=attempt.error_message or ""
        )
    return PublicationAttemptRead(
        id=attempt.id,
        publication_id=attempt.publication_id,
        platform=attempt.platform,  # type: ignore[arg-type]
        trigger=AttemptTrigger(attempt.trigger),
        status=AttemptStatus(attempt.status),
        stage=AttemptStage(attempt.stage),
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        bytes_sent=attempt.bytes_sent,
        total_bytes=attempt.total_bytes,
        progress=round(progress, 4),
        error=error,
        outcome_determined=attempt.outcome_determined,
        requires_manual_review=needs_manual_review(attempt),
        external_id=attempt.external_id,
        external_url=attempt.external_url,
        submitted=dict(attempt.submitted or {}),
        details=dict(attempt.details or {}),
        warnings=[PublicationWarningRead(**w) for w in attempt.warnings or []],
    )


def latest_attempts(
    session: Session, publication_ids: Sequence[int]
) -> dict[int, tuple[PublicationAttempt, int]]:
    """Latest attempt and attempt count per publication, in two queries."""
    if not publication_ids:
        return {}
    rows = session.execute(
        select(
            PublicationAttempt.publication_id,
            func.max(PublicationAttempt.id),
            func.count(PublicationAttempt.id),
        )
        .where(PublicationAttempt.publication_id.in_(publication_ids))
        .group_by(PublicationAttempt.publication_id)
    ).all()
    if not rows:
        return {}
    counts = {publication_id: count for publication_id, _, count in rows}
    attempts = session.scalars(
        select(PublicationAttempt).where(
            PublicationAttempt.id.in_([latest for _, latest, _ in rows])
        )
    )
    return {a.publication_id: (a, counts[a.publication_id]) for a in attempts}


def publication_to_read(
    publication: Publication,
    content: Content | None,
    account: Account,
    project: Project,
    storage: MediaStorage,
    available: bool | None = None,
    attempt_info: AttemptInfo | None = None,
    *,
    now: datetime,
    paused: bool,
) -> PublicationRead:
    """Serialize a publication with its effective metadata, related summaries,
    latest execution attempt and derived automation state.

    The only mapper of publications: every endpoint goes through it, so the derived
    fields are always computed from the same clock (`now`) and pause flag.
    """
    if available is None and content is not None:
        available = file_available(storage, content)
    latest, attempt_count = attempt_info if attempt_info is not None else (None, 0)
    auto_error = None
    if (
        publication.auto_publish_error_code is not None
        and publication.auto_publish_failed_at is not None
    ):
        auto_error = AutoPublishErrorRead(
            code=publication.auto_publish_error_code,
            message=publication.auto_publish_error_message or "",
            failed_at=publication.auto_publish_failed_at,
        )
    window_end = None
    if publication.status == Status.SCHEDULED and publication.scheduled_at is not None:
        window_end = window_ends_at(publication.scheduled_at)
    title, description, hashtags = effective_metadata(publication, content)
    content_summary = None
    if content is not None:
        content_summary = PublicationContentSummary(
            id=content.id,
            title=content.title,
            original_filename=content.original_filename,
            media_type=MediaType(content.media_type),
            file_url=f"/api/contents/{content.id}/file",
            file_available=bool(available),
        )
    return PublicationRead(
        id=publication.id,
        project_id=publication.project_id,
        content_id=publication.content_id,
        account_id=publication.account_id,
        status=Status(publication.status),
        scheduled_at=publication.scheduled_at,
        title_override=publication.title_override,
        description_override=publication.description_override,
        hashtags_override=publication.hashtags_override,
        title=title,
        description=description,
        hashtags=hashtags,
        content=content_summary,
        account=PublicationAccountSummary(
            id=account.id,
            platform=Platform(account.platform),
            handle=account.handle,
            display_name=account.display_name,
            is_active=account.is_active,
        ),
        project_active=project.is_active,
        published_at=publication.published_at,
        latest_attempt=attempt_to_read(latest) if latest is not None else None,
        attempt_count=attempt_count,
        auto_publish_enabled=publication.auto_publish_enabled,
        auto_publish_state=auto_publish_state(
            publication.status,
            publication.auto_publish_enabled,
            publication.scheduled_at,
            paused,
            now,
        ),
        auto_publish_window_ends_at=window_end,
        auto_publish_error=auto_error,
        display_state=post_display_state(
            publication.status,
            publication.auto_publish_enabled,
            publication.scheduled_at,
            paused,
            latest,
            now,
        ),
        created_at=publication.created_at,
        updated_at=publication.updated_at,
    )


def ensure_can_prepare(
    project: Project, account: Account, content: Content | None, storage: MediaStorage
) -> None:
    """Rules for operations that prepare a future publication (create, schedule,
    reactivate). Unscheduling, editing overrides and cancelling never call this. A
    publication without content has no file to check."""
    if not project.is_active:
        raise ConflictError(
            "project_inactive",
            "Reactivate the project before scheduling publications.",
        )
    if not account.is_active:
        raise ConflictError(
            "account_inactive",
            "Reactivate the account before scheduling publications.",
        )
    if content is not None and not file_available(storage, content):
        raise ConflictError("media_unavailable", MEDIA_UNAVAILABLE_MESSAGE)


CHECK_RESULT_FIRST_MESSAGE = "Check the result first."


def ensure_editable(
    publication: Publication,
    *,
    schedule_change: bool = False,
    session: Session | None = None,
) -> None:
    """Which changes each status allows (research.md §13). A failed publication can
    be rescheduled or moved back to drafts (Feature 019, R6) unless the remote
    outcome of the latest attempt is uncertain: then it must be checked first, so
    a scheduling change needs the `session` to look at that attempt."""
    status = publication.status
    if status == Status.CANCELLED:
        raise ConflictError(
            "publication_cancelled", "Reactivate the publication before editing it."
        )
    if status == Status.PUBLISHING:
        raise ConflictError(
            "publication_not_editable",
            "This publication is being published and cannot be changed.",
        )
    if status == Status.PUBLISHED:
        raise ConflictError(
            "publication_not_editable",
            "This publication was already published; it is kept as a record of the "
            "upload and cannot be changed.",
        )
    if status == Status.AWAITING_USER_ACTION:
        raise ConflictError(
            "publication_not_editable",
            "This publication was already sent and is waiting for you to finish it "
            "on the platform; it cannot be changed.",
        )
    if status == Status.FAILED and schedule_change:
        if session is None or requires_remote_check(session, publication):
            raise ConflictError(
                "check_result_first",
                CHECK_RESULT_FIRST_MESSAGE,
                fields=[
                    {"field": "scheduled_at", "message": CHECK_RESULT_FIRST_MESSAGE}
                ],
            )


def ensure_future(value: datetime, field: str = "scheduled_at") -> None:
    if value <= utc_now():
        raise field_errors([(field, "Choose a date and time in the future.")])


def find_active(
    session: Session,
    content_id: int,
    account_ids: Sequence[int],
    exclude_id: int | None = None,
) -> list[Publication]:
    """Active publications (neither cancelled nor published) of a content for the
    given accounts."""
    query = select(Publication).where(
        Publication.content_id == content_id,
        Publication.account_id.in_(account_ids),
        Publication.status.not_in(HISTORY_STATUSES),
    )
    if exclude_id is not None:
        query = query.where(Publication.id != exclude_id)
    return list(session.scalars(query))


# Severity order of per-account problems when creating publications (research.md §6).
_INVALID, _INACTIVE, _DUPLICATE = 0, 1, 2


@router.get("/projects/{project_id}/publications", response_model=list[PublicationRead])
def list_publications(
    project_id: int, session: SessionDep, storage: StorageDep, clock: ClockDep
) -> list[PublicationRead]:
    """The project's queue (research.md §14): publishing, awaiting user action,
    failed, scheduled by date, unscheduled, published (newest first), then
    cancelled."""
    project = get_project_or_404(session, project_id)
    status_rank = case(
        (Publication.status == Status.PUBLISHING, 0),
        (Publication.status == Status.AWAITING_USER_ACTION, 1),
        (Publication.status == Status.FAILED, 2),
        (Publication.status == Status.SCHEDULED, 3),
        (Publication.status == Status.UNSCHEDULED, 4),
        (Publication.status == Status.PUBLISHED, 5),
        else_=6,
    )
    query = (
        select(Publication, Content, Account)
        .outerjoin(Content, Publication.content_id == Content.id)
        .join(Account, Publication.account_id == Account.id)
        .where(Publication.project_id == project_id)
        .order_by(
            status_rank,
            case(
                (Publication.status == Status.SCHEDULED, Publication.scheduled_at),
                else_=None,
            ),
            case(
                (Publication.status == Status.UNSCHEDULED, Publication.created_at),
                else_=None,
            ),
            case(
                (Publication.status == Status.PUBLISHED, Publication.published_at),
                else_=None,
            ).desc(),
            case(
                (Publication.status == Status.CANCELLED, Publication.updated_at),
                else_=None,
            ).desc(),
            Publication.id,
        )
    )
    rows = session.execute(query).all()
    attempts = latest_attempts(session, [publication.id for publication, _, _ in rows])
    availability: dict[int, bool] = {}
    now, paused = clock(), is_paused(session)
    items: list[PublicationRead] = []
    for publication, content, account in rows:
        available = None
        if content is not None:
            if content.id not in availability:
                availability[content.id] = file_available(storage, content)
            available = availability[content.id]
        items.append(
            publication_to_read(
                publication,
                content,
                account,
                project,
                storage,
                available,
                attempts.get(publication.id),
                now=now,
                paused=paused,
            )
        )
    return items


@router.post(
    "/contents/{content_id}/publications",
    response_model=list[PublicationRead],
    status_code=status.HTTP_201_CREATED,
)
def create_publications(
    content_id: int,
    body: PublicationCreate,
    request: Request,
    session: SessionDep,
    storage: StorageDep,
    clock: ClockDep,
) -> list[PublicationRead]:
    """Create one publication per account, all or nothing."""
    content = get_content_or_404(session, content_id)
    project = get_project_or_404(session, content.project_id)
    if not project.is_active:
        raise ConflictError(
            "project_inactive",
            "Reactivate the project before preparing publications.",
        )
    if not file_available(storage, content):
        raise ConflictError("media_unavailable", MEDIA_UNAVAILABLE_MESSAGE)
    if body.scheduled_at is not None:
        ensure_future(body.scheduled_at)
    elif body.auto_publish_enabled:
        raise field_errors([("auto_publish_enabled", NEEDS_DATE_MESSAGE)])

    account_ids = list(dict.fromkeys(body.account_ids))
    unselected = [key for key in body.targets or {} if key not in account_ids]
    if unselected:
        raise field_errors(
            [(f"targets.{key}", UNSELECTED_TARGET_MESSAGE) for key in unselected]
        )
    found = {
        account.id: account
        for account in session.scalars(
            select(Account).where(Account.id.in_(account_ids))
        )
    }
    active = {p.account_id for p in find_active(session, content.id, account_ids)}
    problems: list[tuple[int, int, str]] = []
    for account_id in account_ids:
        account = found.get(account_id)
        if account is None:
            problems.append((_INVALID, account_id, f"Account {account_id} not found."))
        elif account.project_id != content.project_id:
            problems.append(
                (
                    _INVALID,
                    account_id,
                    f"Account {account_id} does not belong to this project.",
                )
            )
        elif not account.is_active:
            problems.append(
                (_INACTIVE, account_id, f"{account_label(account)} is inactive.")
            )
        elif account_id in active:
            problems.append((_DUPLICATE, account_id, _duplicate_message(account)))
    if problems:
        _raise_account_problems(problems)

    now = utc_now()
    if body.auto_publish_enabled:
        # All or nothing: an account whose publisher cannot be armed yet stops the
        # whole batch, and each such account is named in `fields`.
        arming = [
            (account_id, problem)
            for account_id in account_ids
            for problem in _arming_problems(
                request,
                session,
                Publication(
                    project_id=project.id,
                    content_id=content.id,
                    account_id=account_id,
                    status=Status.SCHEDULED,
                    scheduled_at=body.scheduled_at,
                    auto_publish_enabled=True,
                ),
                found[account_id],
            )[:1]
        ]
        if arming:
            raise AppError(
                409,
                arming[0][1].code,
                ARMING_PROBLEMS_MESSAGE,
                fields=[
                    {
                        "field": "account_ids",
                        "message": problem.message,
                        "account_id": account_id,
                    }
                    for account_id, problem in arming
                ],
            )
    created = [
        Publication(
            project_id=project.id,
            content_id=content.id,
            account_id=account_id,
            status=(
                Status.SCHEDULED
                if body.scheduled_at is not None
                else Status.UNSCHEDULED
            ),
            scheduled_at=body.scheduled_at,
            auto_publish_enabled=body.auto_publish_enabled,
            created_at=now,
            updated_at=now,
            **resolve_overrides(body, account_id),
        )
        for account_id in account_ids
    ]
    session.add_all(created)
    _commit_or_conflict(
        session,
        "Some accounts already have an active publication of this content.",
    )
    available = file_available(storage, content)
    now, paused = clock(), is_paused(session)
    return [
        publication_to_read(
            publication,
            content,
            found[publication.account_id],
            project,
            storage,
            available,
            now=now,
            paused=paused,
        )
        for publication in created
    ]


UNSELECTED_TARGET_MESSAGE = "This destination is not selected."

_OVERRIDE_FIELDS = ("title_override", "description_override", "hashtags_override")


def resolve_overrides(body: PublicationCreate, account_id: int) -> dict[str, Any]:
    """Per field: the destination's value, else the common one, else None (the
    publication inherits the content's metadata). "" and [] are explicit values."""
    target = (body.targets or {}).get(account_id)
    resolved: dict[str, Any] = {}
    for field in _OVERRIDE_FIELDS:
        value = getattr(target, field) if target is not None else None
        resolved[field] = value if value is not None else getattr(body, field)
    return resolved


TEXT_NOT_SUPPORTED_MESSAGE = "Some accounts cannot publish posts without media."


ARMING_PROBLEMS_MESSAGE = "Some destinations need action before enabling auto-publish."


def _arming_problems(
    request: Request, session: Session, publication: Publication, account: Account
) -> list[Any]:
    """Local problems the platform's registered publisher reports before arming
    (each with `code` and `message`), read from the app state like
    `accepts_text_only`. No network."""
    publisher = request.app.state.publishers.get(Platform(account.platform))
    check = getattr(publisher, "arming_problems", None)
    return list(check(session, publication)) if check is not None else []


def _accepts_text_only(request: Request, platform: str) -> bool:
    """The capability declared by the platform's registered publisher, read from
    the app state (the execution core imports this module, not the reverse)."""
    publisher = request.app.state.publishers.get(Platform(platform))
    return bool(getattr(publisher, "accepts_text_only", False))


@router.post(
    "/projects/{project_id}/text-publications",
    response_model=list[PublicationRead],
    status_code=status.HTTP_201_CREATED,
)
def create_text_publications(
    project_id: int,
    body: TextPublicationCreate,
    request: Request,
    session: SessionDep,
    storage: StorageDep,
    clock: ClockDep,
) -> list[PublicationRead]:
    """Create one publication without content per account, all or nothing."""
    project = get_project_or_404(session, project_id)
    if not project.is_active:
        raise ConflictError(
            "project_inactive",
            "Reactivate the project before preparing publications.",
        )
    if body.scheduled_at is not None:
        ensure_future(body.scheduled_at)
    elif body.auto_publish_enabled:
        raise field_errors([("auto_publish_enabled", NEEDS_DATE_MESSAGE)])

    account_ids = list(dict.fromkeys(body.account_ids))
    found = {
        account.id: account
        for account in session.scalars(
            select(Account).where(Account.id.in_(account_ids))
        )
    }
    problems: list[tuple[int, int, str]] = []
    unsupported: list[str] = []
    for account_id in account_ids:
        account = found.get(account_id)
        if account is None:
            problems.append((_INVALID, account_id, f"Account {account_id} not found."))
        elif account.project_id != project.id:
            problems.append(
                (
                    _INVALID,
                    account_id,
                    f"Account {account_id} does not belong to this project.",
                )
            )
        elif not account.is_active:
            problems.append(
                (_INACTIVE, account_id, f"{account_label(account)} is inactive.")
            )
        elif not _accepts_text_only(request, account.platform):
            unsupported.append(
                f"{account_label(account)} cannot publish posts without media."
            )
    if problems:
        _raise_account_problems(problems)
    if unsupported:
        raise AppError(
            422,
            "text_publication_not_supported",
            TEXT_NOT_SUPPORTED_MESSAGE,
            fields=[{"field": "account_ids", "message": m} for m in unsupported],
        )

    now = utc_now()
    created = [
        Publication(
            project_id=project.id,
            content_id=None,
            account_id=account_id,
            status=(
                Status.SCHEDULED
                if body.scheduled_at is not None
                else Status.UNSCHEDULED
            ),
            scheduled_at=body.scheduled_at,
            description_override=body.description,
            hashtags_override=body.hashtags,
            auto_publish_enabled=body.auto_publish_enabled,
            created_at=now,
            updated_at=now,
        )
        for account_id in account_ids
    ]
    session.add_all(created)
    session.commit()
    now, paused = clock(), is_paused(session)
    return [
        publication_to_read(
            publication,
            None,
            found[publication.account_id],
            project,
            storage,
            now=now,
            paused=paused,
        )
        for publication in created
    ]


@router.get("/publications/{publication_id}", response_model=PublicationRead)
def get_publication(
    publication_id: int, session: SessionDep, storage: StorageDep, clock: ClockDep
) -> PublicationRead:
    publication = get_publication_or_404(session, publication_id)
    return publication_read(session, publication, storage, clock)


@router.patch("/publications/{publication_id}", response_model=PublicationRead)
def update_publication(
    publication_id: int,
    body: PublicationUpdate,
    request: Request,
    session: SessionDep,
    storage: StorageDep,
    clock: ClockDep,
) -> PublicationRead:
    """Change the date, the consent to publish automatically or the metadata
    overrides; only effective changes count."""
    publication = get_publication_or_404(session, publication_id)
    fields = body.model_fields_set
    arming = "auto_publish_enabled" in fields and body.auto_publish_enabled
    # A failed publication leaves `failed` whenever the request says when it should
    # happen, even with the same value: `{scheduled_at: null}` moves a failed
    # "Publish now" (whose date is already null) back to drafts (Feature 019, R6).
    failed_rescheduling = publication.status == Status.FAILED and (
        "scheduled_at" in fields
    )
    ensure_editable(
        publication,
        schedule_change=arming
        or failed_rescheduling
        or ("scheduled_at" in fields and body.scheduled_at != publication.scheduled_at),
        session=session,
    )
    if publication.status == Status.FAILED and arming and not failed_rescheduling:
        # Only a new time takes a failed publication back to `scheduled`.
        raise field_errors(
            [("scheduled_at", "Choose a time to schedule this post again.")]
        )
    content, account, project = _related(session, publication)
    changed = False

    if "scheduled_at" in fields and (
        failed_rescheduling or body.scheduled_at != publication.scheduled_at
    ):
        if body.scheduled_at is not None:
            ensure_future(body.scheduled_at)
            ensure_can_prepare(project, account, content, storage)
        publication.scheduled_at = body.scheduled_at
        publication.status = (
            Status.SCHEDULED if body.scheduled_at is not None else Status.UNSCHEDULED
        )
        # A new date never inherits the previous consent (Feature 007).
        disarm(publication)
        changed = True
    if "auto_publish_enabled" in fields:
        changed = (
            _set_consent(publication, arming, project, account, content, storage)
            or changed
        )

    # None means "use the content's value"; "" and [] are explicit empty overrides.
    if "title_override" in fields and body.title_override != publication.title_override:
        publication.title_override = body.title_override
        changed = True
    if (
        "description_override" in fields
        and body.description_override != publication.description_override
    ):
        publication.description_override = body.description_override
        changed = True
    if (
        "hashtags_override" in fields
        and body.hashtags_override != publication.hashtags_override
    ):
        publication.hashtags_override = body.hashtags_override
        changed = True

    if arming:
        # Checked on the final values of this request, before anything is saved.
        found = _arming_problems(request, session, publication, account)
        if found:
            first = found[0]
            raise AppError(
                409,
                first.code,
                first.message,
                fields=[{"field": "auto_publish_enabled", "message": first.message}],
            )
    if changed:
        publication.updated_at = utc_now()
        session.commit()
    return publication_read(session, publication, storage, clock)


@router.post("/publications/{publication_id}/cancel", response_model=PublicationRead)
def cancel_publication(
    publication_id: int, session: SessionDep, storage: StorageDep, clock: ClockDep
) -> PublicationRead:
    """Cancel without losing history; the date and overrides are kept. Executing,
    published and awaiting user action publications cannot be cancelled."""
    publication = get_publication_or_404(session, publication_id)
    if publication.status in (
        Status.PUBLISHING,
        Status.PUBLISHED,
        Status.AWAITING_USER_ACTION,
    ):
        ensure_editable(publication)
    if publication.status != Status.CANCELLED:
        publication.status = Status.CANCELLED
        disarm(publication)
        publication.updated_at = utc_now()
        session.commit()
    return publication_read(session, publication, storage, clock)


@router.post(
    "/publications/{publication_id}/reactivate", response_model=PublicationRead
)
def reactivate_publication(
    publication_id: int, session: SessionDep, storage: StorageDep, clock: ClockDep
) -> PublicationRead:
    """Back to scheduled if its date is still ahead, otherwise unscheduled."""
    publication = get_publication_or_404(session, publication_id)
    if publication.status != Status.CANCELLED:
        raise ConflictError(
            "publication_not_cancelled", "This publication is not cancelled."
        )
    content, account, project = _related(session, publication)
    ensure_can_prepare(project, account, content, storage)
    # Publications without content are each a different post: never duplicates.
    if content is not None and find_active(
        session, content.id, [account.id], exclude_id=publication.id
    ):
        raise ConflictError("duplicate", _duplicate_message(account))

    # Reactivated publications are always disarmed (cancelling already disarmed them).
    disarm(publication)
    if publication.scheduled_at is not None and publication.scheduled_at > utc_now():
        publication.status = Status.SCHEDULED
    else:
        # A date that has already passed is dropped; the user picks a new one.
        publication.scheduled_at = None
        publication.status = Status.UNSCHEDULED
    publication.updated_at = utc_now()
    _commit_or_conflict(session, _duplicate_message(account))
    return publication_read(session, publication, storage, clock)


def publication_read(
    session: Session, publication: Publication, storage: MediaStorage, clock: Clock
) -> PublicationRead:
    """Serialize one publication, loading its relations, latest attempt and the
    automation state; used by every endpoint that returns a single publication."""
    content, account, project = _related(session, publication)
    attempts = latest_attempts(session, [publication.id])
    return publication_to_read(
        publication,
        content,
        account,
        project,
        storage,
        attempt_info=attempts.get(publication.id),
        now=clock(),
        paused=is_paused(session),
    )


NEEDS_DATE_MESSAGE = "Choose a date and time to enable auto-publish."
PAST_DATE_MESSAGE = "Reschedule to a future time to enable auto-publish."


def _set_consent(
    publication: Publication,
    enabled: bool,
    project: Project,
    account: Account,
    content: Content | None,
    storage: MediaStorage,
) -> bool:
    """Arm or disarm explicitly (Feature 007); arming prepares a future execution,
    so it follows the same rules as scheduling. Returns whether anything changed."""
    if not enabled:
        if not publication.auto_publish_enabled:
            return False
        disarm(publication)
        return True
    if publication.scheduled_at is None:
        raise field_errors([("auto_publish_enabled", NEEDS_DATE_MESSAGE)])
    if publication.scheduled_at <= utc_now():
        raise field_errors([("auto_publish_enabled", PAST_DATE_MESSAGE)])
    ensure_can_prepare(project, account, content, storage)
    publication.auto_publish_enabled = True
    clear_auto_publish_error(publication)
    return True


def _related(
    session: Session, publication: Publication
) -> tuple[Content | None, Account, Project]:
    content = (
        session.get_one(Content, publication.content_id)
        if publication.content_id is not None
        else None
    )
    account = session.get_one(Account, publication.account_id)
    project = session.get_one(Project, publication.project_id)
    return content, account, project


def _duplicate_message(account: Account) -> str:
    return (
        f"{account_label(account)} already has an active publication of this content."
    )


def _raise_account_problems(problems: list[tuple[int, int, str]]) -> None:
    """Report every problematic account under the most severe error code; each
    entry names its account (`account_id`)."""
    worst = min(severity for severity, _, _ in problems)
    if worst == _INVALID:
        raise field_errors(
            [
                ("account_ids", message, account_id)
                for _, account_id, message in problems
            ]
        )
    fields: list[dict[str, Any]] = [
        {"field": "account_ids", "message": message, "account_id": account_id}
        for _, account_id, message in problems
    ]
    if worst == _INACTIVE:
        raise ConflictError(
            "account_inactive", "Some accounts are inactive.", fields=fields
        )
    raise ConflictError(
        "duplicate",
        "Some accounts already have an active publication of this content.",
        fields=fields,
    )


def _commit_or_conflict(session: Session, message: str) -> None:
    """Commit; a concurrent active publication for the same pair is a conflict."""
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("duplicate", message) from exc
