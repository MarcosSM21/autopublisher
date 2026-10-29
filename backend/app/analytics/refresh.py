"""Refresh of publication metrics (data-model.md §Refresh rules).

- `remote_link`: the remote id of a published post, only from its succeeded attempt;
  never matched by title, date or search (FR-004). A post published by another
  remote identity than the one connected now is not accessible, never "deleted".
- `request_manual_refresh` / `request_project_refresh`: only enqueue; no network.
- `apply_result`: one fetch result → snapshot and/or refresh state (rule 7).
- `due_publications`: manual requests first, then the automatic ones (rule 2).
- `run_refresh_cycle`: one synchronous pass over the due publications, by account
  and in batches; it yields to publishing before every batch (rule 6). The
  background refresher (`refresher.py`) runs it every few minutes.

Analytics never writes to `publications` or `publication_attempts`.
"""

import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import and_, case, exists, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

from app.analytics.adapters.base import FetchResult, MetricsAdapter
from app.analytics.budget import BudgetExhausted
from app.analytics.capability import Capability, account_capability
from app.automation import publishing_imminent
from app.db import write_transaction
from app.errors import AppError, NotFoundError
from app.models import (
    Account,
    AttemptStatus,
    InstagramConnection,
    MetricRefreshStatus,
    MetricSnapshot,
    MetricTrigger,
    MetricValue,
    Platform,
    Publication,
    PublicationAttempt,
    PublicationMetricState,
    PublicationStatus,
    ThreadsConnection,
    YouTubeConnection,
)

logger = logging.getLogger(__name__)

COOLDOWN = timedelta(minutes=15)
# At most one automatic attempt per publication in this interval, whatever its
# outcome: every attempt moves the next automatic one at least this far (rule 2).
AUTOMATIC_INTERVAL = timedelta(hours=24)
BACKOFF_BASE = timedelta(hours=1)
BACKOFF_MAX = timedelta(hours=24)
# A second absence at least this long after the previous one confirms a deletion.
DELETION_CONFIRMATION = timedelta(hours=1)
MAX_PER_CYCLE = 200
# Only posts published this recently are refreshed automatically (manual: any age).
AUTOMATIC_WINDOW = timedelta(days=90)
# States that wait for a manual request (or, for `reconnect_required`, for the
# connection to be usable again: the capability decides).
NOT_AUTOMATIC = (
    MetricRefreshStatus.PERMISSION_REQUIRED,
    MetricRefreshStatus.REMOTE_DELETED,
)

NOT_FOUND_MESSAGE = "Post not found."
COOLDOWN_MESSAGE = "These metrics were refreshed less than 15 minutes ago."
# Why a publication cannot be refreshed: link reasons, then capability states.
NOT_REFRESHABLE_MESSAGES = {
    "not_published": "Only published posts have metrics.",
    "no_succeeded_attempt": "This post has no successful publication to read.",
    "inbox_upload": (
        "This post was sent to the TikTok inbox: AutoPublisher has no id for it."
    ),
    "remote_identity_unavailable": (
        "The platform did not confirm this post's id, so its metrics can't be read."
    ),
    "remote_id_missing": "AutoPublisher has no remote id for this post.",
    "remote_identity_changed": (
        "This post was published by another account than the one connected now, "
        "so its metrics can't be read."
    ),
    "not_connected": "Connect this account to read its metrics.",
    "reconnect_required": "Reconnect this account to read its metrics again.",
    "permission_required": (
        "These metrics need a permission AutoPublisher does not request yet."
    ),
    "not_supported": "AutoPublisher does not read this platform's metrics yet.",
    "not_available_on_platform": "This platform offers no metrics.",
    "not_applicable": "AutoPublisher does not publish to this platform.",
}

# Fixed, safe failure details (never tokens or remote bodies).
FAILURES: dict[str, tuple[MetricRefreshStatus, str, str]] = {
    "transient": (
        MetricRefreshStatus.STALE,
        "refresh_failed",
        "Could not read the metrics. AutoPublisher will try again later.",
    ),
    "rate_limited": (
        MetricRefreshStatus.RATE_LIMITED,
        "rate_limited",
        "The platform limited requests. AutoPublisher will try again later.",
    ),
    "unauthorized": (
        MetricRefreshStatus.RECONNECT_REQUIRED,
        "reconnect_required",
        "Reconnect the account to read its metrics again.",
    ),
    "permission_missing": (
        MetricRefreshStatus.PERMISSION_REQUIRED,
        "permission_required",
        "The account lacks the permission to read these metrics.",
    ),
}
REMOTE_NOT_FOUND = (
    "remote_not_found",
    "The post was not found on the platform. AutoPublisher will check again.",
)
REMOTE_DELETED = ("remote_deleted", "The post no longer exists on the platform.")


# --- Remote link --------------------------------------------------------------------

# The remote identity each publisher records in the attempt's `submitted` at
# publication time, and the connection columns holding the identity connected now.
REMOTE_IDENTITIES: dict[
    Platform, tuple[str, InstrumentedAttribute[str], InstrumentedAttribute[int]]
] = {
    Platform.YOUTUBE: (
        "channel_id",
        YouTubeConnection.channel_id,
        YouTubeConnection.account_id,
    ),
    Platform.INSTAGRAM: (
        "instagram_user_id",
        InstagramConnection.instagram_user_id,
        InstagramConnection.account_id,
    ),
    Platform.THREADS: (
        "threads_user_id",
        ThreadsConnection.threads_user_id,
        ThreadsConnection.account_id,
    ),
}


def _identity_changed(
    session: Session, publication: Publication, attempt: PublicationAttempt
) -> bool:
    """True only when both identities are known and differ; an unknown one never
    concludes anything."""
    known = REMOTE_IDENTITIES.get(Platform(attempt.platform))
    submitted = attempt.submitted if isinstance(attempt.submitted, dict) else {}
    if known is None or not isinstance(submitted.get(known[0]), str):
        return False
    key, identity, account_id = known
    current = session.scalars(
        select(identity).where(account_id == publication.account_id)
    ).first()
    return current is not None and current != submitted[key]


@dataclass(frozen=True)
class RemoteLink:
    remote_id: str | None
    # Why there is no remote id (None when linked).
    reason: str | None

    @property
    def linked(self) -> bool:
        return self.remote_id is not None


def remote_link(session: Session, publication: Publication) -> RemoteLink:
    if publication.status != PublicationStatus.PUBLISHED:
        return RemoteLink(None, "not_published")
    attempt = session.scalars(
        select(PublicationAttempt)
        .where(
            PublicationAttempt.publication_id == publication.id,
            PublicationAttempt.status == AttemptStatus.SUCCEEDED,
        )
        .order_by(PublicationAttempt.started_at.desc(), PublicationAttempt.id.desc())
    ).first()
    if attempt is None:
        return RemoteLink(None, "no_succeeded_attempt")
    if attempt.external_id:
        if _identity_changed(session, publication, attempt):
            return RemoteLink(None, "remote_identity_changed")
        return RemoteLink(attempt.external_id, None)
    details = attempt.details if isinstance(attempt.details, dict) else {}
    if str(details.get("tiktok_mode", "")).lower() == "inbox_upload":
        return RemoteLink(None, "inbox_upload")
    warnings = attempt.warnings if isinstance(attempt.warnings, list) else []
    codes = {w.get("code") for w in warnings if isinstance(w, dict)}
    if "remote_identity_unavailable" in codes:
        return RemoteLink(None, "remote_identity_unavailable")
    return RemoteLink(None, "remote_id_missing")


@dataclass(frozen=True)
class Eligibility:
    link: RemoteLink
    capability: Capability

    @property
    def refreshable(self) -> bool:
        return self.link.linked and self.capability.is_refreshable

    @property
    def reason(self) -> str | None:
        """The capability state first (it concerns the whole account), else the
        link reason."""
        if not self.capability.is_refreshable:
            return self.capability.state
        return self.link.reason


class CapabilityCache:
    """Capabilities computed once per account within one operation."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.values: dict[int, Capability] = {}

    def of(self, account_id: int) -> Capability:
        if account_id not in self.values:
            account = self.session.get(Account, account_id)
            assert account is not None  # RESTRICT foreign key
            self.values[account_id] = account_capability(self.session, account)
        return self.values[account_id]


def eligibility(
    session: Session, publication: Publication, cache: CapabilityCache | None = None
) -> Eligibility:
    capabilities = cache or CapabilityCache(session)
    return Eligibility(
        remote_link(session, publication), capabilities.of(publication.account_id)
    )


# --- Manual requests ----------------------------------------------------------------


def _not_refreshable(reason: str) -> AppError:
    return AppError(
        409,
        "analytics_not_refreshable",
        NOT_REFRESHABLE_MESSAGES.get(reason, NOT_REFRESHABLE_MESSAGES["not_supported"]),
        details={"reason": reason},
    )


def _cooldown_until(
    state: PublicationMetricState | None, now: datetime
) -> datetime | None:
    if state is None or state.last_attempt_at is None:
        return None
    available_at = state.last_attempt_at + COOLDOWN
    return available_at if available_at > now else None


def _enqueue(
    session: Session,
    publication_id: int,
    state: PublicationMetricState | None,
    now: datetime,
) -> None:
    """Accept a manual request: `pending`, keeping the last data and error detail."""
    if state is None:
        state = PublicationMetricState(publication_id=publication_id, failure_count=0)
        session.add(state)
    state.status = MetricRefreshStatus.PENDING
    if state.manual_requested_at is None:
        state.manual_requested_at = now


def request_manual_refresh(
    session: Session, publication_id: int, now: datetime
) -> None:
    """Enqueue one publication, at any age (rule 3). Raises 404, 409
    `analytics_not_refreshable` or 409 `refresh_cooldown`; a refused request is
    never queued. Runs inside the caller's write transaction."""
    publication = session.get(Publication, publication_id)
    if publication is None:
        raise NotFoundError(NOT_FOUND_MESSAGE)
    checked = eligibility(session, publication)
    if not checked.refreshable:
        raise _not_refreshable(checked.reason or "not_supported")
    state = session.get(PublicationMetricState, publication_id)
    available_at = _cooldown_until(state, now)
    if available_at is not None:
        raise AppError(
            409,
            "refresh_cooldown",
            COOLDOWN_MESSAGE,
            details={"available_at": available_at.isoformat()},
        )
    _enqueue(session, publication_id, state, now)


@dataclass
class ProjectRefreshCounts:
    queued: int = 0
    in_cooldown: int = 0
    not_eligible: int = 0


def request_project_refresh(
    session: Session, project_id: int, now: datetime
) -> ProjectRefreshCounts:
    """Enqueue every refreshable published post of the project not in cooldown
    (rule 4). Each post is judged on its own; one never blocks the others."""
    publications = session.scalars(
        select(Publication)
        .where(
            Publication.project_id == project_id,
            Publication.status == PublicationStatus.PUBLISHED,
        )
        .order_by(Publication.id)
    ).all()
    cache = CapabilityCache(session)
    counts = ProjectRefreshCounts()
    for publication in publications:
        if not eligibility(session, publication, cache).refreshable:
            counts.not_eligible += 1
            continue
        state = session.get(PublicationMetricState, publication.id)
        if _cooldown_until(state, now) is not None:
            counts.in_cooldown += 1
            continue
        _enqueue(session, publication.id, state, now)
        counts.queued += 1
    return counts


def due_publications(session: Session, now: datetime) -> list[int]:
    """Publications that may be refreshed now (rule 5 order): manual requests
    (oldest first), then automatic candidates (rule 2: published in the last 90
    days, with a remote id, not waiting for a manual request and due), `pending`
    or never read first, then the oldest `last_success_at`. Link and capability
    are checked by the caller."""
    manual = list(
        session.scalars(
            select(PublicationMetricState.publication_id)
            .where(PublicationMetricState.manual_requested_at.is_not(None))
            .order_by(
                PublicationMetricState.manual_requested_at,
                PublicationMetricState.publication_id,
            )
        )
    )
    state = PublicationMetricState
    no_state = state.publication_id.is_(None)
    with_remote_id = exists().where(
        PublicationAttempt.publication_id == Publication.id,
        PublicationAttempt.status == AttemptStatus.SUCCEEDED,
        PublicationAttempt.external_id.is_not(None),
    )
    automatic = session.scalars(
        select(Publication.id)
        .outerjoin(state, state.publication_id == Publication.id)
        .where(
            Publication.status == PublicationStatus.PUBLISHED,
            Publication.published_at >= now - AUTOMATIC_WINDOW,
            with_remote_id,
            or_(
                no_state,
                and_(
                    state.manual_requested_at.is_(None),
                    state.status.not_in(NOT_AUTOMATIC),
                    or_(state.next_attempt_at.is_(None), state.next_attempt_at <= now),
                ),
            ),
        )
        .order_by(
            case(
                (or_(no_state, state.status == MetricRefreshStatus.PENDING), 0),
                else_=1,
            ),
            state.last_success_at.asc().nulls_first(),
            Publication.id,
        )
    )
    queued = set(manual)
    return manual + [id_ for id_ in automatic if id_ not in queued]


# --- Transitions --------------------------------------------------------------------


def backoff(failures: int) -> timedelta:
    """1 h × 2^(failures − 1), at most 24 h."""
    # 2^5 h already exceeds the cap; a larger power would overflow timedelta.
    doublings: int = 2 ** min(max(failures - 1, 0), 5)
    return min(BACKOFF_BASE * doublings, BACKOFF_MAX)


def apply_result(
    session: Session,
    adapter: MetricsAdapter,
    publication: Publication,
    remote_id: str,
    result: FetchResult,
    now: datetime,
) -> PublicationMetricState:
    """Record one attempt (rule 7). Only a success creates a snapshot, with one row
    per declared metric returned (a 0 is stored, an absent metric is not); earlier
    snapshots and `last_success_at` are never touched by a failure."""
    state = session.get(PublicationMetricState, publication.id)
    if state is None:
        # The first automatic read: accepted, now attempted.
        state = PublicationMetricState(
            publication_id=publication.id,
            status=MetricRefreshStatus.PENDING,
            failure_count=0,
        )
        session.add(state)
    previous_attempt_at, previous_error = state.last_attempt_at, state.error_code
    trigger = (
        MetricTrigger.MANUAL
        if state.manual_requested_at is not None
        else MetricTrigger.AUTOMATIC
    )
    state.last_attempt_at = now
    state.manual_requested_at = None

    if result.kind == "ok":
        snapshot = MetricSnapshot(
            publication_id=publication.id,
            platform=adapter.platform,
            remote_id=remote_id,
            captured_at=now,
            source=adapter.source,
            trigger=trigger,
        )
        session.add(snapshot)
        session.flush()
        origins = {metric.name: metric.origin for metric in adapter.metrics}
        excluded = {metric.name for metric in adapter.excluded}
        for name, value in result.values.items():
            if name in origins and name not in excluded and value >= 0:
                session.add(
                    MetricValue(
                        snapshot_id=snapshot.id,
                        metric_name=name,
                        value=value,
                        origin=origins[name],
                    )
                )
        state.status = MetricRefreshStatus.OK
        state.last_success_at = now
        state.next_attempt_at = now + AUTOMATIC_INTERVAL
        state.failure_count = 0
        state.error_code = state.error_message = None
        return state

    state.failure_count += 1
    _record_failure(state, result, now, previous_attempt_at, previous_error)
    if state.next_attempt_at is not None:
        # A longer backoff or pause wins; a shorter one never brings it closer.
        state.next_attempt_at = max(state.next_attempt_at, now + AUTOMATIC_INTERVAL)
    return state


def _record_failure(
    state: PublicationMetricState,
    result: FetchResult,
    now: datetime,
    previous_attempt_at: datetime | None,
    previous_error: str | None,
) -> None:
    if result.kind == "not_found":
        confirmed = (
            previous_error == REMOTE_NOT_FOUND[0]
            and previous_attempt_at is not None
            and now - previous_attempt_at >= DELETION_CONFIRMATION
        )
        if confirmed:
            state.status = MetricRefreshStatus.REMOTE_DELETED
            state.error_code, state.error_message = REMOTE_DELETED
            state.next_attempt_at = None
        else:
            state.status = MetricRefreshStatus.REMOTE_NOT_FOUND
            state.error_code, state.error_message = REMOTE_NOT_FOUND
            state.next_attempt_at = now + DELETION_CONFIRMATION
        return

    status, code, message = FAILURES[result.kind]
    state.status, state.error_code, state.error_message = status, code, message
    if result.kind == "transient":
        state.next_attempt_at = now + backoff(state.failure_count)
    elif result.kind == "rate_limited":
        state.next_attempt_at = result.retry_at or now + backoff(state.failure_count)
    elif result.kind == "unauthorized":
        # Retried automatically once the connection is usable again, never sooner
        # than the automatic interval.
        state.next_attempt_at = now
    else:
        # permission_required: no automatic retry.
        state.next_attempt_at = None


# --- One refresh cycle --------------------------------------------------------------


@dataclass
class PlatformPauses:
    """In-memory pause of a platform after a rate limit, kept across cycles."""

    until: dict[Platform, datetime] = field(default_factory=dict)
    strikes: dict[Platform, int] = field(default_factory=dict)

    def paused(self, platform: Platform, now: datetime) -> bool:
        end = self.until.get(platform)
        return end is not None and end > now

    def pause(self, platform: Platform, now: datetime, until: datetime | None) -> None:
        self.strikes[platform] = self.strikes.get(platform, 0) + 1
        self.until[platform] = until or now + backoff(self.strikes[platform])

    def clear(self, platform: Platform) -> None:
        self.until.pop(platform, None)
        self.strikes.pop(platform, None)


@dataclass
class CycleReport:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    # Left for later: platform paused, budget spent, no runnable adapter or
    # publishing priority. Manual requests among them stay queued.
    deferred: int = 0
    # Dropped requests: the publication is no longer refreshable.
    not_refreshable: int = 0
    # The cycle stopped because a publication is running or due soon.
    yielded_to_publishing: bool = False


@dataclass(frozen=True)
class _Due:
    publication_id: int
    account_id: int
    platform: Platform
    remote_id: str


def _close_unrefreshable(
    session: Session, publication_id: int, checked: Eligibility
) -> None:
    """A queued request whose publication can no longer be refreshed: drop the
    request, and show a connection or permission problem in the state."""
    state = session.get(PublicationMetricState, publication_id)
    if state is None:
        return
    state.manual_requested_at = None
    capability = checked.capability.state
    if capability in ("not_connected", "reconnect_required"):
        status, code, message = FAILURES["unauthorized"]
    elif capability == "permission_required":
        status, code, message = FAILURES["permission_missing"]
    else:
        return
    state.status, state.error_code, state.error_message = status, code, message
    state.next_attempt_at = None


def _collect(
    session_factory: sessionmaker[Session],
    adapters: Mapping[Platform, MetricsAdapter],
    pauses: PlatformPauses,
    now: datetime,
    limit: int,
    report: CycleReport,
) -> list[_Due]:
    """Read-only selection; only queued requests that can no longer run are
    written (dropped), in a short transaction of their own."""
    due: list[_Due] = []
    closed: list[tuple[int, Eligibility]] = []
    with session_factory() as session:
        cache = CapabilityCache(session)
        for publication_id in due_publications(session, now):
            if len(due) >= limit:
                break
            publication = session.get(Publication, publication_id)
            if publication is None:
                continue
            checked = eligibility(session, publication, cache)
            if not checked.refreshable or checked.link.remote_id is None:
                state = session.get(PublicationMetricState, publication_id)
                if state is not None and state.manual_requested_at is not None:
                    closed.append((publication_id, checked))
                    report.not_refreshable += 1
                continue
            account = session.get(Account, publication.account_id)
            assert account is not None  # RESTRICT foreign key
            platform = Platform(account.platform)
            if platform not in adapters or pauses.paused(platform, now):
                report.deferred += 1
                continue
            due.append(
                _Due(
                    publication_id,
                    publication.account_id,
                    platform,
                    checked.link.remote_id,
                )
            )
    if closed:
        with write_transaction(session_factory) as session:
            for publication_id, checked in closed:
                _close_unrefreshable(session, publication_id, checked)
    return due


def _batches(
    due: Sequence[_Due], adapters: Mapping[Platform, MetricsAdapter]
) -> list[list[_Due]]:
    by_account: dict[tuple[Platform, int], list[_Due]] = defaultdict(list)
    for item in due:
        by_account[(item.platform, item.account_id)].append(item)
    batches: list[list[_Due]] = []
    for (platform, _), items in by_account.items():
        size = max(adapters[platform].batch_size, 1)
        batches.extend(items[i : i + size] for i in range(0, len(items), size))
    return batches


def _fetch(
    session_factory: sessionmaker[Session],
    adapter: MetricsAdapter,
    batch: Sequence[_Due],
) -> Mapping[str, FetchResult] | None:
    """The adapter's results, or None when its budget is spent (nothing called)."""
    remote_ids = list(dict.fromkeys(item.remote_id for item in batch))
    try:
        with session_factory() as session:
            return adapter.fetch(session, batch[0].account_id, remote_ids)
    except BudgetExhausted:
        return None
    except Exception as exc:
        # A failing adapter never stops the cycle; its batch is retried later.
        logger.error(
            "Analytics fetch failed for %s (%s).", adapter.platform, type(exc).__name__
        )
        return {remote_id: FetchResult.transient() for remote_id in remote_ids}


def _publishing_imminent(session_factory: sessionmaker[Session], now: datetime) -> bool:
    with session_factory() as session:
        return publishing_imminent(session, now)


def run_refresh_cycle(
    session_factory: sessionmaker[Session],
    adapters: Mapping[Platform, MetricsAdapter],
    now: datetime,
    *,
    pauses: PlatformPauses | None = None,
    limit: int = MAX_PER_CYCLE,
) -> CycleReport:
    """Refresh the due publications once, synchronously (rules 5–7).

    Before each batch it yields to publishing: if an attempt is running or an armed
    publication is due soon, it stops and everything left stays as it was. Grouped
    by account in batches of the adapter's `batch_size`; a rate limit pauses its
    platform and a spent budget stops it for this cycle, skipping the rest of that
    platform's batches, whose requests stay queued. Other platforms go on."""
    pauses = pauses if pauses is not None else PlatformPauses()
    report = CycleReport()
    if _publishing_imminent(session_factory, now):
        report.yielded_to_publishing = True
        return report
    due = _collect(session_factory, adapters, pauses, now, limit, report)
    stopped: set[Platform] = set()
    batches = _batches(due, adapters)
    for index, batch in enumerate(batches):
        platform = batch[0].platform
        if platform in stopped or pauses.paused(platform, now):
            report.deferred += len(batch)
            continue
        if _publishing_imminent(session_factory, now):
            report.yielded_to_publishing = True
            report.deferred += sum(len(rest) for rest in batches[index:])
            break
        adapter = adapters[platform]
        results = _fetch(session_factory, adapter, batch)
        if results is None:
            stopped.add(platform)
            report.deferred += len(batch)
            continue
        limited = [r for r in results.values() if r.kind == "rate_limited"]
        if limited:
            pauses.pause(platform, now, limited[0].retry_at)
        elif any(r.kind == "ok" for r in results.values()):
            pauses.clear(platform)
        with write_transaction(session_factory) as session:
            for item in batch:
                publication = session.get(Publication, item.publication_id)
                if publication is None:  # deleted meanwhile
                    continue
                result = results.get(item.remote_id, FetchResult.transient())
                apply_result(session, adapter, publication, item.remote_id, result, now)
                report.attempted += 1
                if result.kind == "ok":
                    report.succeeded += 1
                else:
                    report.failed += 1
    return report
