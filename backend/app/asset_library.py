"""Asset Library: derived usage of contents and their metadata (Feature 016).

Usage is never stored: it is computed from the publications with two aggregate
queries per project (research §1), so listings never grow with N+1 queries.
"""

from collections.abc import Collection
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from app.contents import get_content_or_404
from app.db import UTCDateTime, get_session
from app.models import Account, Platform, Publication
from app.models import PublicationStatus as Status
from app.publications import latest_attempts, needs_manual_review
from app.schemas import AssetPublicationRead, AssetUsageRead, ContentUsageRead

router = APIRouter(prefix="/api", tags=["asset-library"])

SessionDep = Annotated[Session, Depends(get_session)]

# Statuses that count as "used": a confirmed publication, or a post handed to the
# platform that waits for the user there (never reported as published).
USED_STATUSES = (Status.PUBLISHED.value, Status.AWAITING_USER_ACTION.value)


def _count(status: Status) -> ColumnElement[int]:
    return func.sum(case((Publication.status == status.value, 1), else_=0))


def usage_by_content(
    session: Session, project_id: int, content_ids: Collection[int] | None = None
) -> dict[int, ContentUsageRead]:
    """Usage summary per content of the project; contents without publications are
    absent (their usage is the empty default)."""
    conditions = [
        Publication.project_id == project_id,
        Publication.content_id.is_not(None),
    ]
    if content_ids is not None:
        conditions.append(Publication.content_id.in_(content_ids))
    totals = session.execute(
        select(
            Publication.content_id,
            func.count(Publication.id),
            _count(Status.PUBLISHED),
            _count(Status.AWAITING_USER_ACTION),
            _count(Status.SCHEDULED),
            func.max(
                case(
                    (
                        Publication.status == Status.PUBLISHED.value,
                        Publication.published_at,
                    )
                ),
                type_=UTCDateTime(),
            ),
        )
        .where(*conditions)
        .group_by(Publication.content_id)
    ).all()
    platforms: dict[int, set[str]] = {}
    for content_id, platform in session.execute(
        select(Publication.content_id, Account.platform)
        .join(Account, Account.id == Publication.account_id)
        .where(*conditions, Publication.status.in_(USED_STATUSES))
        .distinct()
    ):
        platforms.setdefault(content_id, set()).add(platform)
    usage: dict[int, ContentUsageRead] = {}
    for content_id, total, published, awaiting, scheduled, last in totals:
        usage[content_id] = ContentUsageRead(
            used=published + awaiting > 0,
            publication_count=total,
            published_count=published,
            awaiting_count=awaiting,
            scheduled_count=scheduled,
            platforms=[Platform(p) for p in sorted(platforms.get(content_id, ()))],
            last_published_at=last,
        )
    return usage


@router.get("/contents/{content_id}/usage", response_model=AssetUsageRead)
def get_content_usage(content_id: int, session: SessionDep) -> AssetUsageRead:
    """Every publication of the content, most recently changed first."""
    content = get_content_or_404(session, content_id)
    rows = session.execute(
        select(Publication, Account)
        .join(Account, Account.id == Publication.account_id)
        .where(Publication.content_id == content.id)
        .order_by(Publication.updated_at.desc(), Publication.id.desc())
    ).all()
    attempts = latest_attempts(session, [publication.id for publication, _ in rows])
    publications = []
    for publication, account in rows:
        latest = attempts.get(publication.id)
        attempt = latest[0] if latest is not None else None
        publications.append(
            AssetPublicationRead(
                publication_id=publication.id,
                platform=Platform(account.platform),
                account_id=account.id,
                account_name=account.display_name or account.handle,
                status=Status(publication.status),
                scheduled_at=publication.scheduled_at,
                published_at=publication.published_at,
                created_at=publication.created_at,
                updated_at=publication.updated_at,
                uncertain=attempt is not None and needs_manual_review(attempt),
                external_url=attempt.external_url if attempt is not None else None,
            )
        )
    usage = usage_by_content(session, content.project_id, [content.id])
    return AssetUsageRead(
        usage=usage.get(content.id, ContentUsageRead()), publications=publications
    )
