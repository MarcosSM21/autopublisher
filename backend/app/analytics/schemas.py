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


class PostAnalyticsBase(BaseModel):
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


class PostAnalyticsRow(PostAnalyticsBase):
    # Only in a ranking (`sort`): False when the post lacks the sorted metric, so
    # it is listed after the ranked ones instead of counting as 0.
    ranked: bool | None = None


class SnapshotValueRead(BaseModel):
    name: str
    value: int
    origin: MetricOrigin
    concept: str | None


class SnapshotRead(BaseModel):
    """One real reading, with only the metrics the platform returned in it."""

    snapshot_id: int
    captured_at: datetime
    trigger: str
    source: str
    remote_id: str
    values: list[SnapshotValueRead]
    # From this reading's own components only; None without a formula.
    engagement: EngagementRead | None


class SeriesPoint(BaseModel):
    snapshot_id: int
    # Position of the reading in `history`: consecutive points are consecutive
    # readings, so a skipped index is a reading without this metric (a gap).
    reading: int
    captured_at: datetime
    value: float


class SeriesRead(BaseModel):
    """One metric over time: real readings that contain it, oldest first.

    A reading without the metric has no point (never 0, never interpolated)."""

    name: str
    label: str
    concept: str | None
    definition: str
    derived: bool
    points: list[SeriesPoint]


class PublicationAnalytics(PostAnalyticsBase):
    """One post with every real reading, oldest first (contracts §One publication)."""

    history: list[SnapshotRead]
    # Only metrics observed at least once; `engagement` only where computable.
    series: list[SeriesRead]


class PostsQuery(BaseModel):
    platform: Platform | None = None
    account_id: int | None = None
    published_from: date | None = None
    published_to: date | None = None
    # A metric name of `platform`, or `engagement`: a ranking within one platform.
    sort: str | None = None
    order: Literal["asc", "desc"] = "desc"


class ContentTypesQuery(BaseModel):
    platform: Platform
    account_id: int | None = None
    published_from: date | None = None
    published_to: date | None = None


class MedianRead(BaseModel):
    """The median of one metric over the posts of a type that have it.

    `count` is how many posts have the metric; with fewer than 3 the sample is
    insufficient and `value` is null."""

    count: int
    insufficient_sample: bool
    value: float | None


class MetricMedianRead(MedianRead):
    name: str
    label: str
    concept: str | None


class ContentTypeSummary(BaseModel):
    """One content type of one platform (contracts §Content-type summary)."""

    content_type: Literal["image", "video", "text"]
    posts_total: int
    # Posts with a valid reading.
    posts_with_data: int
    insufficient_sample: bool
    median_age_days: float | None
    medians: list[MetricMedianRead]
    # None for a platform without an engagement formula.
    engagement_median: MedianRead | None


class AlignedCell(BaseModel):
    """One publication's own metric under a common concept (never comparable)."""

    publication_id: int
    platform: Platform
    account_id: int
    # The platform's original metric, or None if the platform has none for it.
    metric_name: str | None
    value: int | None
    available: bool
    definition: str | None


class AlignedConcept(BaseModel):
    """A row that only lines up metrics visually; nothing is summed or ranked."""

    concept: str
    label: str
    definition: str
    cells: list[AlignedCell]


class ContentSideBySide(BaseModel):
    """One content's publications, side by side (contracts §Side by side).

    `per_platform` keeps each publication apart, with the metrics that are not
    aligned. There are no totals, averages, differences, ordering or "best"."""

    content_id: int
    aligned: list[AlignedConcept]
    per_platform: list[PostAnalyticsBase]
    note: str
