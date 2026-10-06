"""Publications: the intent to publish a content on an account (see contracts/api.md).

Nothing here publishes anything or reacts to the passing of time: a status only changes
when the user asks for it.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contents import StorageDep, file_available, get_content_or_404
from app.db import get_session, utc_now
from app.errors import ConflictError, NotFoundError, field_errors
from app.models import Account, Content, MediaType, Platform, Project, Publication
from app.models import PublicationStatus as Status
from app.projects import get_project_or_404
from app.schemas import (
    PublicationAccountSummary,
    PublicationContentSummary,
    PublicationCreate,
    PublicationRead,
    PublicationUpdate,
)
from app.storage import MediaStorage

router = APIRouter(prefix="/api", tags=["publications"])

SessionDep = Annotated[Session, Depends(get_session)]

MEDIA_UNAVAILABLE_MESSAGE = "The media file of this content is not available."

PLATFORM_LABELS = {
    Platform.YOUTUBE: "YouTube",
    Platform.INSTAGRAM: "Instagram",
    Platform.TIKTOK: "TikTok",
    Platform.X: "X",
    Platform.THREADS: "Threads",
    Platform.TELEGRAM: "Telegram",
}


def account_label(account: Account) -> str:
    """Name an account the way the user sees it, e.g. "Instagram @l4i4"."""
    return f"{PLATFORM_LABELS[Platform(account.platform)]} @{account.handle}"


def get_publication_or_404(session: Session, publication_id: int) -> Publication:
    publication = session.get(Publication, publication_id)
    if publication is None:
        raise NotFoundError("Publication not found.")
    return publication


def publication_to_read(
    publication: Publication,
    content: Content,
    account: Account,
    project: Project,
    storage: MediaStorage,
    available: bool | None = None,
) -> PublicationRead:
    """Serialize a publication with its effective metadata and related summaries."""
    if available is None:
        available = file_available(storage, content)
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
        title=(
            publication.title_override
            if publication.title_override is not None
            else content.title
        ),
        description=(
            publication.description_override
            if publication.description_override is not None
            else content.description
        ),
        hashtags=list(
            publication.hashtags_override
            if publication.hashtags_override is not None
            else content.hashtags
        ),
        content=PublicationContentSummary(
            id=content.id,
            title=content.title,
            original_filename=content.original_filename,
            media_type=MediaType(content.media_type),
            file_url=f"/api/contents/{content.id}/file",
            file_available=available,
        ),
        account=PublicationAccountSummary(
            id=account.id,
            platform=Platform(account.platform),
            handle=account.handle,
            display_name=account.display_name,
            is_active=account.is_active,
        ),
        project_active=project.is_active,
        created_at=publication.created_at,
        updated_at=publication.updated_at,
    )


def ensure_can_prepare(
    project: Project, account: Account, content: Content, storage: MediaStorage
) -> None:
    """Rules for operations that prepare a future publication (create, schedule,
    reactivate). Unscheduling, editing overrides and cancelling never call this."""
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
    if not file_available(storage, content):
        raise ConflictError("media_unavailable", MEDIA_UNAVAILABLE_MESSAGE)


def ensure_future(value: datetime, field: str = "scheduled_at") -> None:
    if value <= utc_now():
        raise field_errors([(field, "Choose a date and time in the future.")])


def find_active(
    session: Session,
    content_id: int,
    account_ids: Sequence[int],
    exclude_id: int | None = None,
) -> list[Publication]:
    """Active (not cancelled) publications of a content for the given accounts."""
    query = select(Publication).where(
        Publication.content_id == content_id,
        Publication.account_id.in_(account_ids),
        Publication.status != Status.CANCELLED,
    )
    if exclude_id is not None:
        query = query.where(Publication.id != exclude_id)
    return list(session.scalars(query))


# Severity order of per-account problems when creating publications (research.md §6).
_INVALID, _INACTIVE, _DUPLICATE = 0, 1, 2


@router.get("/projects/{project_id}/publications", response_model=list[PublicationRead])
def list_publications(
    project_id: int, session: SessionDep, storage: StorageDep
) -> list[PublicationRead]:
    """The project's queue: scheduled by date, then unscheduled, then cancelled."""
    project = get_project_or_404(session, project_id)
    status_rank = case(
        (Publication.status == Status.SCHEDULED, 0),
        (Publication.status == Status.UNSCHEDULED, 1),
        else_=2,
    )
    query = (
        select(Publication, Content, Account)
        .join(Content, Publication.content_id == Content.id)
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
                (Publication.status == Status.CANCELLED, Publication.updated_at),
                else_=None,
            ).desc(),
            Publication.id,
        )
    )
    availability: dict[int, bool] = {}
    items: list[PublicationRead] = []
    for publication, content, account in session.execute(query):
        if content.id not in availability:
            availability[content.id] = file_available(storage, content)
        items.append(
            publication_to_read(
                publication,
                content,
                account,
                project,
                storage,
                availability[content.id],
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
    session: SessionDep,
    storage: StorageDep,
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

    account_ids = list(dict.fromkeys(body.account_ids))
    found = {
        account.id: account
        for account in session.scalars(
            select(Account).where(Account.id.in_(account_ids))
        )
    }
    active = {p.account_id for p in find_active(session, content.id, account_ids)}
    problems: list[tuple[int, str]] = []
    for account_id in account_ids:
        account = found.get(account_id)
        if account is None:
            problems.append((_INVALID, f"Account {account_id} not found."))
        elif account.project_id != content.project_id:
            problems.append(
                (_INVALID, f"Account {account_id} does not belong to this project.")
            )
        elif not account.is_active:
            problems.append((_INACTIVE, f"{account_label(account)} is inactive."))
        elif account_id in active:
            problems.append((_DUPLICATE, _duplicate_message(account)))
    if problems:
        _raise_account_problems(problems)

    now = utc_now()
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
            created_at=now,
            updated_at=now,
        )
        for account_id in account_ids
    ]
    session.add_all(created)
    _commit_or_conflict(
        session,
        "Some accounts already have an active publication of this content.",
    )
    available = file_available(storage, content)
    return [
        publication_to_read(
            publication,
            content,
            found[publication.account_id],
            project,
            storage,
            available,
        )
        for publication in created
    ]


@router.get("/publications/{publication_id}", response_model=PublicationRead)
def get_publication(
    publication_id: int, session: SessionDep, storage: StorageDep
) -> PublicationRead:
    publication = get_publication_or_404(session, publication_id)
    return _to_read(session, publication, storage)


@router.patch("/publications/{publication_id}", response_model=PublicationRead)
def update_publication(
    publication_id: int,
    body: PublicationUpdate,
    session: SessionDep,
    storage: StorageDep,
) -> PublicationRead:
    """Change the date or the metadata overrides; only effective changes count."""
    publication = get_publication_or_404(session, publication_id)
    if publication.status == Status.CANCELLED:
        raise ConflictError(
            "publication_cancelled", "Reactivate the publication before editing it."
        )
    content, account, project = _related(session, publication)
    fields = body.model_fields_set
    changed = False

    if "scheduled_at" in fields and body.scheduled_at != publication.scheduled_at:
        if body.scheduled_at is not None:
            ensure_future(body.scheduled_at)
            ensure_can_prepare(project, account, content, storage)
        publication.scheduled_at = body.scheduled_at
        publication.status = (
            Status.SCHEDULED if body.scheduled_at is not None else Status.UNSCHEDULED
        )
        changed = True
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

    if changed:
        publication.updated_at = utc_now()
        session.commit()
    return publication_to_read(publication, content, account, project, storage)


@router.post("/publications/{publication_id}/cancel", response_model=PublicationRead)
def cancel_publication(
    publication_id: int, session: SessionDep, storage: StorageDep
) -> PublicationRead:
    """Cancel without losing history; the date and overrides are kept."""
    publication = get_publication_or_404(session, publication_id)
    if publication.status != Status.CANCELLED:
        publication.status = Status.CANCELLED
        publication.updated_at = utc_now()
        session.commit()
    return _to_read(session, publication, storage)


@router.post(
    "/publications/{publication_id}/reactivate", response_model=PublicationRead
)
def reactivate_publication(
    publication_id: int, session: SessionDep, storage: StorageDep
) -> PublicationRead:
    """Back to scheduled if its date is still ahead, otherwise unscheduled."""
    publication = get_publication_or_404(session, publication_id)
    if publication.status != Status.CANCELLED:
        raise ConflictError(
            "publication_not_cancelled", "This publication is not cancelled."
        )
    content, account, project = _related(session, publication)
    ensure_can_prepare(project, account, content, storage)
    if find_active(session, content.id, [account.id], exclude_id=publication.id):
        raise ConflictError("duplicate", _duplicate_message(account))

    if publication.scheduled_at is not None and publication.scheduled_at > utc_now():
        publication.status = Status.SCHEDULED
    else:
        # A date that has already passed is dropped; the user picks a new one.
        publication.scheduled_at = None
        publication.status = Status.UNSCHEDULED
    publication.updated_at = utc_now()
    _commit_or_conflict(session, _duplicate_message(account))
    return publication_to_read(publication, content, account, project, storage)


def _to_read(
    session: Session, publication: Publication, storage: MediaStorage
) -> PublicationRead:
    content, account, project = _related(session, publication)
    return publication_to_read(publication, content, account, project, storage)


def _related(
    session: Session, publication: Publication
) -> tuple[Content, Account, Project]:
    content = session.get_one(Content, publication.content_id)
    account = session.get_one(Account, publication.account_id)
    project = session.get_one(Project, publication.project_id)
    return content, account, project


def _duplicate_message(account: Account) -> str:
    return (
        f"{account_label(account)} already has an active publication of this content."
    )


def _raise_account_problems(problems: list[tuple[int, str]]) -> None:
    """Report every problematic account under the most severe error code."""
    entries = [("account_ids", message) for _, message in problems]
    worst = min(severity for severity, _ in problems)
    if worst == _INVALID:
        raise field_errors(entries)
    fields = [{"field": field, "message": message} for field, message in entries]
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
