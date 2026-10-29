"""Read models of the analytics screens (contracts/analytics-api.md).

Each post row carries its latest **valid** reading (failures never create a
snapshot, so the latest snapshot is the last good one) next to its refresh state.
Every metric the adapter reads is listed: one the platform did not return is
`value: null, available: false`, never 0. Nothing is summed, averaged or compared
across posts or platforms.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.adapters.base import MetricsAdapter
from app.analytics.adapters.registry import ADAPTERS
from app.analytics.engagement import engagement_of
from app.analytics.refresh import (
    AUTOMATIC_WINDOW,
    COOLDOWN,
    CapabilityCache,
    eligibility,
)
from app.analytics.schemas import (
    EngagementRead,
    MetricValueRead,
    PostAnalyticsRow,
    RefreshStateRead,
)
from app.models import (
    Account,
    AttemptStatus,
    Content,
    MediaType,
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
    """Latest snapshot of each publication (ids grow with time) and its values."""
    if not publication_ids:
        return {}
    latest = (
        select(func.max(MetricSnapshot.id))
        .where(MetricSnapshot.publication_id.in_(publication_ids))
        .group_by(MetricSnapshot.publication_id)
    )
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


def list_posts(
    session: Session,
    project_id: int,
    now: datetime,
    *,
    platform: Platform | None = None,
    account_id: int | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
) -> list[PostAnalyticsRow]:
    """Published posts of the project, newest first; dates are inclusive UTC days."""
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


def publication_analytics(
    session: Session, publication: Publication, now: datetime
) -> PostAnalyticsRow:
    """The row of one published post."""
    return _rows(session, [publication], now)[0]
