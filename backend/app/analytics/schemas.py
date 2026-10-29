"""Analytics response bodies (contracts/analytics-api.md).

"Not available" is `value: null, available: false`, never a 0.
"""

from datetime import date, datetime
from typing import Literal

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


class RefreshQueued(BaseModel):
    queued: bool


class ProjectRefreshResult(BaseModel):
    queued: int
    in_cooldown: int
    not_eligible: int


class PostAnalyticsRow(BaseModel):
    """One published post with its latest valid reading (contracts §Posts list).

    There are no totals, averages or cross-platform aggregates."""

    publication_id: int
    content_id: int | None
    content_type: Literal["image", "video", "text"]
    title: str | None
    platform: Platform
    account_id: int
    account_label: str
    published_at: datetime
    age_days: int
    remote_url: str | None
    link_state: Literal["linked", "not_linked"]
    not_linked_reason: str | None
    capability_state: CapabilityState
    metrics: list[MetricValueRead]
    engagement: EngagementRead | None
    refresh: RefreshStateRead | None
    # When the latest valid reading was received (None: never read).
    captured_at: datetime | None


class PublicationAnalytics(PostAnalyticsRow):
    """One post; its reading history comes in a later checkpoint."""


class PostsQuery(BaseModel):
    platform: Platform | None = None
    account_id: int | None = None
    published_from: date | None = None
    published_to: date | None = None
