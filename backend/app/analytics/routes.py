"""Analytics routes (contracts/analytics-api.md). No route does network work: a
refresh request only enqueues and wakes the background refresher, if any."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.adapters.registry import ADAPTERS
from app.analytics.capability import Capability, account_capability
from app.analytics.catalog import CONCEPTS
from app.analytics.queries import list_posts, publication_analytics
from app.analytics.refresh import request_manual_refresh, request_project_refresh
from app.analytics.schemas import (
    AccountCapabilityRead,
    CapabilityGroupRead,
    CapabilityRead,
    CatalogRead,
    ConceptRead,
    EngagementFormulaRead,
    ExcludedMetricRead,
    MetricDefinitionRead,
    PlatformCatalogRead,
    PostAnalyticsRow,
    PostsQuery,
    ProjectRefreshResult,
    PublicationAnalytics,
    RefreshQueued,
)
from app.db import get_session, get_session_factory, write_transaction
from app.errors import NotFoundError
from app.models import Account, Platform, Publication, PublicationStatus
from app.projects import get_project_or_404
from app.publications import account_label

router = APIRouter(prefix="/api", tags=["analytics"])

SessionDep = Annotated[Session, Depends(get_session)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]


def capability_read(capability: Capability) -> CapabilityRead:
    return CapabilityRead(
        state=capability.state,
        groups=[CapabilityGroupRead(**asdict(group)) for group in capability.groups],
        reason=capability.reason,
    )


@router.get("/analytics/catalog", response_model=CatalogRead)
def get_catalog() -> CatalogRead:
    return CatalogRead(
        concepts=[ConceptRead(**asdict(concept)) for concept in CONCEPTS],
        platforms=[
            PlatformCatalogRead(
                platform=platform,
                metrics=[MetricDefinitionRead(**asdict(m)) for m in adapter.metrics],
                excluded=[ExcludedMetricRead(**asdict(e)) for e in adapter.excluded],
                engagement=(
                    EngagementFormulaRead(
                        numerator=list(adapter.engagement.numerator),
                        denominator=adapter.engagement.denominator,
                    )
                    if adapter.engagement is not None
                    else None
                ),
            )
            for platform, adapter in ADAPTERS.items()
        ],
    )


@router.get(
    "/projects/{project_id}/analytics/accounts",
    response_model=list[AccountCapabilityRead],
)
def list_account_capabilities(
    project_id: int, session: SessionDep
) -> list[AccountCapabilityRead]:
    get_project_or_404(session, project_id)
    accounts = session.scalars(
        select(Account).where(Account.project_id == project_id).order_by(Account.id)
    ).all()
    return [
        AccountCapabilityRead(
            account_id=account.id,
            platform=Platform(account.platform),
            label=account_label(account),
            capability=capability_read(account_capability(session, account)),
        )
        for account in accounts
    ]


@router.get(
    "/projects/{project_id}/analytics/posts", response_model=list[PostAnalyticsRow]
)
def list_post_analytics(
    project_id: int,
    request: Request,
    session: SessionDep,
    query: Annotated[PostsQuery, Query()],
) -> list[PostAnalyticsRow]:
    get_project_or_404(session, project_id)
    return list_posts(
        session,
        project_id,
        request.app.state.clock(),
        platform=query.platform,
        account_id=query.account_id,
        published_from=query.published_from,
        published_to=query.published_to,
    )


@router.get(
    "/publications/{publication_id}/analytics", response_model=PublicationAnalytics
)
def get_publication_analytics(
    publication_id: int, request: Request, session: SessionDep
) -> PostAnalyticsRow:
    publication = session.get(Publication, publication_id)
    if publication is None or publication.status != PublicationStatus.PUBLISHED:
        raise NotFoundError("Post not found.")
    return publication_analytics(session, publication, request.app.state.clock())


def _wake_refresher(request: Request) -> None:
    refresher = getattr(request.app.state, "analytics_refresher", None)
    if refresher is not None:
        refresher.wake()


@router.post(
    "/publications/{publication_id}/analytics/refresh",
    response_model=RefreshQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_publication(
    publication_id: int, request: Request, session_factory: SessionFactoryDep
) -> RefreshQueued:
    with write_transaction(session_factory) as session:
        request_manual_refresh(session, publication_id, request.app.state.clock())
    _wake_refresher(request)
    return RefreshQueued(queued=True)


@router.post(
    "/projects/{project_id}/analytics/refresh",
    response_model=ProjectRefreshResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_project(
    project_id: int, request: Request, session_factory: SessionFactoryDep
) -> ProjectRefreshResult:
    with write_transaction(session_factory) as session:
        get_project_or_404(session, project_id)
        counts = request_project_refresh(session, project_id, request.app.state.clock())
    if counts.queued:
        _wake_refresher(request)
    return ProjectRefreshResult(
        queued=counts.queued,
        in_cooldown=counts.in_cooldown,
        not_eligible=counts.not_eligible,
    )
