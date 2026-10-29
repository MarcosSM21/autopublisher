"""Analytics routes (contracts/analytics-api.md). Read-only so far; no network."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.adapters.registry import ADAPTERS
from app.analytics.capability import Capability, account_capability
from app.analytics.catalog import CONCEPTS
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
)
from app.db import get_session
from app.models import Account, Platform
from app.projects import get_project_or_404
from app.publications import account_label

router = APIRouter(prefix="/api", tags=["analytics"])

SessionDep = Annotated[Session, Depends(get_session)]


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
