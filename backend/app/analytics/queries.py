"""Read models of the analytics screens (contracts/analytics-api.md).

Each post row carries its latest **valid** reading (failures never create a
snapshot, so the latest snapshot is the last good one) next to its refresh state.
Every metric the adapter reads is listed: one the platform did not return is
`value: null, available: false`, never 0. Nothing is summed, averaged or compared
across platforms: rankings and content-type medians always stay within one.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.adapters.base import MetricDef, MetricsAdapter
from app.analytics.adapters.registry import ADAPTERS
from app.analytics.catalog import CONCEPTS
from app.analytics.engagement import engagement_of
from app.analytics.refresh import (
    AUTOMATIC_WINDOW,
    COOLDOWN,
    CapabilityCache,
    eligibility,
)
from app.analytics.schemas import (
    AlignedCell,
    AlignedConcept,
    ContentSideBySide,
    ContentTypeSummary,
    EngagementRead,
    MedianRead,
    MetricMedianRead,
    MetricValueRead,
    PostAnalyticsBase,
    PostAnalyticsRow,
    PublicationAnalytics,
    RefreshStateRead,
    SeriesPoint,
    SeriesRead,
    SnapshotRead,
    SnapshotValueRead,
)
from app.errors import AppError, field_errors
from app.models import (
    Account,
    AttemptStatus,
    Content,
    MediaType,
    MetricOrigin,
    MetricRefreshStatus,
    MetricSnapshot,
    MetricValue,
    Platform,
    Publication,
    PublicationAttempt,
    PublicationMetricState,
    PublicationStatus,
)
from app.publications import account_label, effective_metadata

TITLE_MAX = 100
ENGAGEMENT = "engagement"
# Fewer posts with a metric than this and its median is not shown (FR-021).
MIN_SAMPLE = 3
CONTENT_TYPES: tuple[Literal["image", "video", "text"], ...] = (
    "image",
    "video",
    "text",
)
SIDE_BY_SIDE_NOTE = (
    "Not quantitatively equivalent across platforms: each platform counts in its "
    "own way, so these values are shown next to each other, never compared."
)
ALIGNABLE = tuple(concept for concept in CONCEPTS if concept.alignable)
SINGLE_PLATFORM_MESSAGE = (
    "Rankings and summaries stay within one platform: choose a platform, and "
    "optionally one of its accounts."
)


def engagement_for(
    adapter: MetricsAdapter | None, values: dict[str, int]
) -> EngagementRead | None:
    """The adapter's fixed formula on one reading; None without a formula."""
    if adapter is None or adapter.engagement is None:
        return None
    return engagement_of(adapter.engagement, values)


def metrics_for(
    adapter: MetricsAdapter | None, values: dict[str, int]
) -> list[MetricValueRead]:
    """Every metric of the groups this version reads, in declaration order."""
    if adapter is None:
        return []
    rows = []
    for metric in adapter.metrics:
        if metric.group not in adapter.read_groups:
            continue
        value = values.get(metric.name)
        if value is None and not metric.listed_when_absent:
            continue
        rows.append(
            MetricValueRead(
                name=metric.name,
                label=metric.label,
                value=value,
                available=value is not None,
                origin=metric.origin,
                concept=metric.concept,
                definition=metric.definition,
            )
        )
    return rows


def _title(publication: Publication, content: Content | None) -> str | None:
    title, description, _ = effective_metadata(publication, content)
    text = (title or "").strip() or (description or "").strip().split("\n")[0]
    if not text:
        return content.original_filename if content is not None else None
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "…"


def _content_type(content: Content | None) -> Literal["image", "video", "text"]:
    if content is None:
        return "text"
    return "video" if content.media_type == MediaType.VIDEO else "image"


def _refresh(
    state: PublicationMetricState | None,
    publication: Publication,
    refreshable: bool,
    now: datetime,
) -> RefreshStateRead | None:
    if state is None:
        # A refreshable recent post waits for its first automatic read; any other
        # one has no refresh state until someone asks for it.
        assert publication.published_at is not None
        if refreshable and publication.published_at >= now - AUTOMATIC_WINDOW:
            return RefreshStateRead(
                status=MetricRefreshStatus.PENDING,
                last_success_at=None,
                last_attempt_at=None,
                next_attempt_at=None,
                manual_pending=False,
                error_code=None,
                error_message=None,
                cooldown_until=None,
            )
        return None
    cooldown_until = (
        state.last_attempt_at + COOLDOWN if state.last_attempt_at is not None else None
    )
    return RefreshStateRead(
        status=MetricRefreshStatus(state.status),
        last_success_at=state.last_success_at,
        last_attempt_at=state.last_attempt_at,
        next_attempt_at=state.next_attempt_at,
        manual_pending=state.manual_requested_at is not None,
        error_code=state.error_code,
        error_message=state.error_message,
        cooldown_until=cooldown_until
        if cooldown_until is not None and cooldown_until > now
        else None,
    )


def _latest_readings(
    session: Session, publication_ids: Sequence[int]
) -> dict[int, tuple[datetime, dict[str, int]]]:
    """Latest snapshot of each publication and its values: the newest
    `captured_at`, ties by id, the same order as the post's history."""
    if not publication_ids:
        return {}
    newest_first = (
        func.row_number()
        .over(
            partition_by=MetricSnapshot.publication_id,
            order_by=(MetricSnapshot.captured_at.desc(), MetricSnapshot.id.desc()),
        )
        .label("position")
    )
    ranked = (
        select(MetricSnapshot.id, newest_first)
        .where(MetricSnapshot.publication_id.in_(publication_ids))
        .subquery()
    )
    latest = select(ranked.c.id).where(ranked.c.position == 1)
    snapshots = session.scalars(
        select(MetricSnapshot).where(MetricSnapshot.id.in_(latest))
    ).all()
    values: dict[int, dict[str, int]] = {s.id: {} for s in snapshots}
    for row in session.scalars(
        select(MetricValue).where(MetricValue.snapshot_id.in_(list(values)))
    ):
        values[row.snapshot_id][row.metric_name] = row.value
    return {s.publication_id: (s.captured_at, values[s.id]) for s in snapshots}


def _remote_urls(session: Session, publication_ids: Sequence[int]) -> dict[int, str]:
    rows = session.execute(
        select(PublicationAttempt.publication_id, PublicationAttempt.external_url)
        .where(
            PublicationAttempt.publication_id.in_(publication_ids),
            PublicationAttempt.status == AttemptStatus.SUCCEEDED,
            PublicationAttempt.external_url.is_not(None),
        )
        .order_by(PublicationAttempt.started_at, PublicationAttempt.id)
    ).all()
    # Ordered oldest first: the latest succeeded attempt wins.
    return {publication_id: url for publication_id, url in rows if url}


def _rows(
    session: Session, publications: Sequence[Publication], now: datetime
) -> list[PostAnalyticsRow]:
    ids = [publication.id for publication in publications]
    readings = _latest_readings(session, ids)
    urls = _remote_urls(session, ids) if ids else {}
    states = {
        state.publication_id: state
        for state in session.scalars(
            select(PublicationMetricState).where(
                PublicationMetricState.publication_id.in_(ids)
            )
        )
    }
    cache = CapabilityCache(session)
    rows = []
    for publication in publications:
        account = session.get(Account, publication.account_id)
        assert account is not None and publication.published_at is not None
        content = (
            session.get(Content, publication.content_id)
            if publication.content_id is not None
            else None
        )
        platform = Platform(account.platform)
        adapter = ADAPTERS.get(platform)
        checked = eligibility(session, publication, cache)
        captured_at, values = readings.get(publication.id, (None, {}))
        rows.append(
            PostAnalyticsRow(
                publication_id=publication.id,
                content_id=publication.content_id,
                content_type=_content_type(content),
                title=_title(publication, content),
                platform=platform,
                account_id=account.id,
                account_label=account_label(account),
                published_at=publication.published_at,
                age_days=max((now - publication.published_at).days, 0),
                remote_url=urls.get(publication.id),
                link_state="linked" if checked.link.linked else "not_linked",
                not_linked_reason=checked.link.reason,
                capability_state=checked.capability.state,
                metrics=metrics_for(adapter, values),
                engagement=engagement_for(adapter, values),
                refresh=_refresh(
                    states.get(publication.id), publication, checked.refreshable, now
                ),
                captured_at=captured_at,
            )
        )
    return rows


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time(0), UTC)


def require_single_platform(
    session: Session,
    project_id: int,
    platform: Platform | None,
    account_id: int | None,
) -> Platform:
    """The one platform a ranking or summary is about; its account must match."""
    account = session.get(Account, account_id) if account_id is not None else None
    if platform is None or (
        account_id is not None
        and (
            account is None
            or account.project_id != project_id
            or Platform(account.platform) != platform
        )
    ):
        raise AppError(422, "ranking_requires_single_platform", SINGLE_PLATFORM_MESSAGE)
    return platform


def _read_metrics(adapter: MetricsAdapter | None) -> list[MetricDef]:
    if adapter is None:
        return []
    return [m for m in adapter.metrics if m.group in adapter.read_groups]


def _metric(row: PostAnalyticsRow, name: str) -> int | None:
    """The value of one metric in the row's reading; None if absent (never 0)."""
    return next((m.value for m in row.metrics if m.name == name and m.available), None)


def _sort_value(row: PostAnalyticsRow, sort: str) -> float | None:
    if sort == ENGAGEMENT:
        return row.engagement.value if row.engagement is not None else None
    return _metric(row, sort)


def _ranked(
    rows: list[PostAnalyticsRow], sort: str, order: Literal["asc", "desc"]
) -> list[PostAnalyticsRow]:
    """Rows with the metric first, by its value; ties and the unranked rest keep
    the default order (newest publication first, then the highest id)."""
    with_value = [(_sort_value(row, sort), row) for row in rows]
    ranked = sorted(
        ((value, row) for value, row in with_value if value is not None),
        key=lambda item: item[0],
        # `sorted` is stable with `reverse`, so ties keep the default order.
        reverse=order == "desc",
    )
    unranked = [row for value, row in with_value if value is None]
    return [row.model_copy(update={"ranked": True}) for _, row in ranked] + [
        row.model_copy(update={"ranked": False}) for row in unranked
    ]


def list_posts(
    session: Session,
    project_id: int,
    now: datetime,
    *,
    platform: Platform | None = None,
    account_id: int | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    sort: str | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> list[PostAnalyticsRow]:
    """Published posts of the project, newest first; dates are inclusive UTC days
    of publication.

    With `sort` (a metric this version reads for `platform`, or `engagement` if
    the platform declares a formula) the posts are ranked by it, within that one
    platform only."""
    if sort is not None:
        platform = require_single_platform(session, project_id, platform, account_id)
        adapter = ADAPTERS.get(platform)
        sortable = {m.name for m in _read_metrics(adapter)}
        if adapter is not None and adapter.engagement is not None:
            sortable.add(ENGAGEMENT)
        if sort not in sortable:
            raise field_errors([("sort", "Choose a metric of this platform.")])
    rows = _filtered_rows(
        session,
        project_id,
        now,
        platform=platform,
        account_id=account_id,
        published_from=published_from,
        published_to=published_to,
    )
    return _ranked(rows, sort, order) if sort is not None else rows


def _filtered_rows(
    session: Session,
    project_id: int,
    now: datetime,
    *,
    platform: Platform | None,
    account_id: int | None,
    published_from: date | None,
    published_to: date | None,
) -> list[PostAnalyticsRow]:
    query = (
        select(Publication)
        .join(Account, Account.id == Publication.account_id)
        .where(
            Publication.project_id == project_id,
            Publication.status == PublicationStatus.PUBLISHED,
        )
        .order_by(Publication.published_at.desc(), Publication.id.desc())
    )
    if platform is not None:
        query = query.where(Account.platform == platform)
    if account_id is not None:
        query = query.where(Publication.account_id == account_id)
    if published_from is not None:
        query = query.where(Publication.published_at >= _day_start(published_from))
    if published_to is not None:
        end = _day_start(published_to) + timedelta(days=1)
        query = query.where(Publication.published_at < end)
    return _rows(session, session.scalars(query).all(), now)


def _median(values: list[float]) -> MedianRead:
    insufficient = len(values) < MIN_SAMPLE
    return MedianRead(
        count=len(values),
        insufficient_sample=insufficient,
        value=None if insufficient else float(median(values)),
    )


def content_type_summary(
    session: Session,
    project_id: int,
    now: datetime,
    *,
    platform: Platform,
    account_id: int | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
) -> list[ContentTypeSummary]:
    """Per content type of one platform: how many posts have a valid reading and
    the median of each metric over the posts that have it (a real 0 counts, a
    missing metric does not). Below 3 posts the median is withheld."""
    require_single_platform(session, project_id, platform, account_id)
    adapter = ADAPTERS.get(platform)
    rows = _filtered_rows(
        session,
        project_id,
        now,
        platform=platform,
        account_id=account_id,
        published_from=published_from,
        published_to=published_to,
    )
    summaries = []
    for content_type in CONTENT_TYPES:
        of_type = [row for row in rows if row.content_type == content_type]
        if not of_type:
            continue
        with_data = [row for row in of_type if row.captured_at is not None]
        medians = []
        for metric in _read_metrics(adapter):
            read = (_metric(row, metric.name) for row in with_data)
            values = [float(value) for value in read if value is not None]
            # A metric only some callers get (e.g. dislikes) is listed only if read.
            if not values and not metric.listed_when_absent:
                continue
            medians.append(
                MetricMedianRead(
                    name=metric.name,
                    label=metric.label,
                    concept=metric.concept,
                    **_median(values).model_dump(),
                )
            )
        engagement_median = None
        if adapter is not None and adapter.engagement is not None:
            engagement_median = _median(
                [
                    row.engagement.value
                    for row in with_data
                    if row.engagement is not None and row.engagement.value is not None
                ]
            )
        summaries.append(
            ContentTypeSummary(
                content_type=content_type,
                posts_total=len(of_type),
                posts_with_data=len(with_data),
                insufficient_sample=len(with_data) < MIN_SAMPLE,
                median_age_days=(
                    float(median(row.age_days for row in with_data))
                    if with_data
                    else None
                ),
                medians=medians,
                engagement_median=engagement_median,
            )
        )
    return summaries


def content_side_by_side(
    session: Session, content: Content, now: datetime
) -> ContentSideBySide:
    """The published posts of one media, linked only by `content_id` (never by
    title, date or text), in account order.

    Alignable concepts (likes, comments) line up each platform's own metric,
    with its original name and definition; every other metric stays with its
    publication. Nothing is summed, averaged, ordered or marked as best."""
    publications = session.scalars(
        select(Publication)
        .join(Account, Account.id == Publication.account_id)
        .where(
            Publication.content_id == content.id,
            Publication.status == PublicationStatus.PUBLISHED,
        )
        .order_by(Account.id, Publication.id)
    ).all()
    rows = _rows(session, publications, now)
    aligned = []
    for concept in ALIGNABLE:
        cells = []
        for row in rows:
            metric = next(
                (
                    m
                    for m in _read_metrics(ADAPTERS.get(row.platform))
                    if m.concept == concept.key
                ),
                None,
            )
            value = _metric(row, metric.name) if metric is not None else None
            cells.append(
                AlignedCell(
                    publication_id=row.publication_id,
                    platform=row.platform,
                    account_id=row.account_id,
                    metric_name=metric.name if metric is not None else None,
                    value=value,
                    available=value is not None,
                    definition=metric.definition if metric is not None else None,
                )
            )
        if any(cell.metric_name is not None for cell in cells):
            aligned.append(
                AlignedConcept(
                    concept=concept.key,
                    label=concept.label,
                    definition=concept.definition,
                    cells=cells,
                )
            )
    alignable = {concept.key for concept in ALIGNABLE}
    per_platform = [
        PostAnalyticsBase.model_validate(
            {
                **row.model_dump(exclude={"ranked", "metrics"}),
                "metrics": [m for m in row.metrics if m.concept not in alignable],
            }
        )
        for row in rows
    ]
    return ContentSideBySide(
        content_id=content.id,
        aligned=aligned,
        per_platform=per_platform,
        note=SIDE_BY_SIDE_NOTE,
    )


def publication_history(
    session: Session, publication: Publication, adapter: MetricsAdapter | None
) -> tuple[list[SnapshotRead], list[SeriesRead]]:
    """Every real reading of the post, oldest first (ties by id), and one series
    per metric seen at least once. A reading without a metric adds no point to
    its series: nothing is filled, interpolated or read as 0. Engagement uses
    only the components of its own reading."""
    snapshots = session.scalars(
        select(MetricSnapshot)
        .where(MetricSnapshot.publication_id == publication.id)
        .order_by(MetricSnapshot.captured_at, MetricSnapshot.id)
    ).all()
    values: dict[int, dict[str, MetricValue]] = {s.id: {} for s in snapshots}
    for row in session.scalars(
        select(MetricValue).where(MetricValue.snapshot_id.in_(list(values)))
    ):
        values[row.snapshot_id][row.metric_name] = row
    declared = {m.name: m for m in adapter.metrics} if adapter is not None else {}
    history = []
    points: dict[str, list[SeriesPoint]] = {}
    engagement_points: list[SeriesPoint] = []
    for reading, snapshot in enumerate(snapshots):
        read = values[snapshot.id]
        plain = {name: row.value for name, row in read.items()}
        engagement = engagement_for(adapter, plain)
        history.append(
            SnapshotRead(
                snapshot_id=snapshot.id,
                captured_at=snapshot.captured_at,
                trigger=snapshot.trigger,
                source=snapshot.source,
                remote_id=snapshot.remote_id,
                values=[
                    SnapshotValueRead(
                        name=name,
                        value=row.value,
                        origin=MetricOrigin(row.origin),
                        concept=declared[name].concept if name in declared else None,
                    )
                    for name, row in sorted(read.items())
                ],
                engagement=engagement,
            )
        )
        for name, value in plain.items():
            points.setdefault(name, []).append(
                SeriesPoint(
                    snapshot_id=snapshot.id,
                    reading=reading,
                    captured_at=snapshot.captured_at,
                    value=value,
                )
            )
        if engagement is not None and engagement.value is not None:
            engagement_points.append(
                SeriesPoint(
                    snapshot_id=snapshot.id,
                    reading=reading,
                    captured_at=snapshot.captured_at,
                    value=engagement.value,
                )
            )
    # Declared metrics in declaration order, then any other stored name.
    names = [name for name in declared if name in points] + sorted(
        name for name in points if name not in declared
    )
    series = [
        SeriesRead(
            name=name,
            label=declared[name].label if name in declared else name,
            concept=declared[name].concept if name in declared else None,
            definition=declared[name].definition if name in declared else "",
            derived=False,
            points=points[name],
        )
        for name in names
    ]
    if adapter is not None and adapter.engagement is not None and engagement_points:
        series.append(
            SeriesRead(
                name=ENGAGEMENT,
                label="Engagement",
                concept=None,
                definition=(
                    "Calculated by AutoPublisher for each reading with "
                    f"{adapter.engagement.expression}, using only that reading."
                ),
                derived=True,
                points=engagement_points,
            )
        )
    return history, series


def publication_analytics(
    session: Session, publication: Publication, now: datetime
) -> PublicationAnalytics:
    """The row of one published post with its real reading history."""
    row = _rows(session, [publication], now)[0]
    history, series = publication_history(
        session, publication, ADAPTERS.get(row.platform)
    )
    return PublicationAnalytics(
        **row.model_dump(exclude={"ranked"}), history=history, series=series
    )
