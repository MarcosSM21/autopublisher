"""Analytics response bodies (contracts/analytics-api.md).

"Not available" is `value: null, available: false`, never a 0.
"""

from datetime import datetime

from pydantic import BaseModel

from app.analytics.capability import CapabilityState, GroupState
from app.models import MetricOrigin, MetricRefreshStatus, Platform


class MetricValueRead(BaseModel):
    name: str
    label: str
    value: int | None
    available: bool
    origin: MetricOrigin
    concept: str | None
    definition: str


class EngagementRead(BaseModel):
    """Only for platforms with a declared formula; computed at read time."""

    available: bool
    value: float | None
    formula: str
    components: dict[str, int | None]


class RefreshStateRead(BaseModel):
    status: MetricRefreshStatus
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    manual_pending: bool
    error_code: str | None
    error_message: str | None
    cooldown_until: datetime | None


class CapabilityGroupRead(BaseModel):
    group: str
    state: GroupState
    missing_permission: str | None


class CapabilityRead(BaseModel):
    state: CapabilityState
    groups: list[CapabilityGroupRead]
    reason: str | None


class AccountCapabilityRead(BaseModel):
    account_id: int
    platform: Platform
    label: str
    capability: CapabilityRead


class ConceptRead(BaseModel):
    key: str
    label: str
    definition: str
    alignable: bool


class MetricDefinitionRead(BaseModel):
    name: str
    label: str
    definition: str
    origin: MetricOrigin
    concept: str | None
    group: str


class ExcludedMetricRead(BaseModel):
    name: str
    reason: str


class EngagementFormulaRead(BaseModel):
    numerator: list[str]
    denominator: str


class PlatformCatalogRead(BaseModel):
    platform: Platform
    metrics: list[MetricDefinitionRead]
    excluded: list[ExcludedMetricRead]
    engagement: EngagementFormulaRead | None


class CatalogRead(BaseModel):
    concepts: list[ConceptRead]
    platforms: list[PlatformCatalogRead]
