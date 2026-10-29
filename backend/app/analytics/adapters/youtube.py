"""YouTube metrics: public counters of `videos.list` (`part=statistics`).

One call reads a batch of videos (1 unit of the general quota bucket, never the
`videos.insert` one). Credentials come from `get_valid_credentials`; error messages
are fixed and never carry tokens or response bodies.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.analytics.adapters.base import (
    EngagementFormula,
    ExcludedMetric,
    FetchResult,
    MetricDef,
)
from app.analytics.budget import QUOTA_TIME_ZONE, BudgetExhausted, DailyUnitBudget
from app.credential_store import CredentialStore
from app.db import utc_now
from app.errors import AppError, ConflictError
from app.models import MetricOrigin, Platform
from app.youtube_connections import (
    get_connection,
    get_valid_credentials,
    mark_reconnect_required,
)
from app.youtube_gateway import (
    MAX_IDS_PER_VIDEOS_LIST,
    GoogleForbidden,
    GoogleGateway,
    GoogleQuotaExceeded,
    GoogleRejected,
    GoogleUnauthorized,
    GoogleUnavailable,
    VideoStatistics,
)

BASIC = "basic"
READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def next_quota_reset(now: datetime) -> datetime:
    local = now.astimezone(QUOTA_TIME_ZONE)
    midnight = datetime.combine(
        local.date() + timedelta(days=1), time(0), QUOTA_TIME_ZONE
    )
    return midnight.astimezone(UTC)


def _counter(
    name: str,
    label: str,
    definition: str,
    concept: str | None,
    *,
    listed_when_absent: bool = True,
) -> MetricDef:
    return MetricDef(
        name=name,
        label=label,
        definition=definition,
        origin=MetricOrigin.PUBLIC_COUNTER,
        concept=concept,
        group=BASIC,
        listed_when_absent=listed_when_absent,
    )


class YouTubeMetricsAdapter:
    platform = Platform.YOUTUBE
    metrics = (
        _counter(
            "viewCount",
            "Views",
            "Number of views YouTube reports for the video. Since 2026-08-24 "
            "YouTube counts a view as soon as playback starts (autoplay and hover "
            "included); an older video's total may span that change. AutoPublisher "
            "keeps the value exactly as returned and never corrects it.",
            "views",
        ),
        _counter(
            "likeCount",
            "Likes",
            "Number of users who liked the video. YouTube omits it when the "
            "channel hides the like count.",
            "likes",
        ),
        _counter(
            "commentCount",
            "Comments",
            "Number of comments on the video. YouTube omits it when comments are "
            "disabled.",
            "comments",
        ),
        _counter(
            "dislikeCount",
            "Dislikes",
            "Number of users who disliked the video. YouTube only returns it to the "
            "channel owner.",
            None,
            listed_when_absent=False,
        ),
    )
    excluded = (
        ExcludedMetric("favoriteCount", "deprecated by YouTube in 2015, always 0"),
    )
    groups: Mapping[str, str | None] = {BASIC: READONLY_SCOPE}
    read_groups = frozenset({BASIC})
    engagement = EngagementFormula(("likeCount", "commentCount"), "viewCount")
    source = "youtube.videos.list:statistics"
    batch_size = MAX_IDS_PER_VIDEOS_LIST

    def __init__(
        self,
        gateway: GoogleGateway | None = None,
        credential_store: CredentialStore | None = None,
        clock: Callable[[], datetime] = utc_now,
        budget: DailyUnitBudget | None = None,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.clock = clock
        # Units of the general quota bucket analytics may still use today.
        self.budget = budget

    def fetch(
        self, session: Session, account_id: int, remote_ids: Sequence[str]
    ) -> Mapping[str, FetchResult]:
        """Read one batch of the account's videos; the same result for every id
        when the whole call fails. Never raises for platform or credential errors;
        raises `BudgetExhausted` before a call that does not fit in the budget."""
        gateway, store = self.gateway, self.credential_store
        if gateway is None or store is None:
            raise RuntimeError("The YouTube metrics adapter has no gateway.")

        if self.budget is not None and self.budget.remaining(self.clock()) <= 0:
            # Nothing is read (not even the credentials) until the daily reset.
            raise BudgetExhausted()

        def every(result: FetchResult) -> dict[str, FetchResult]:
            return {remote_id: result for remote_id in remote_ids}

        try:
            statistics = self._read(session, gateway, store, account_id, remote_ids)
        except ConflictError:
            # not_connected / reconnect_required: the connection is already marked.
            return every(FetchResult.unauthorized())
        except GoogleUnauthorized:
            connection = get_connection(session, account_id)
            if connection is not None:
                mark_reconnect_required(session, connection)
            return every(FetchResult.unauthorized())
        except GoogleForbidden:
            return every(FetchResult.permission_missing())
        except GoogleQuotaExceeded as error:
            retry_at = next_quota_reset(self.clock()) if error.daily else None
            return every(FetchResult.rate_limited(retry_at))
        except (AppError, GoogleUnavailable, GoogleRejected):
            # Unreachable Google, credential store or OAuth client: try again later.
            return every(FetchResult.transient())
        return {
            remote_id: self._result(statistics, remote_id) for remote_id in remote_ids
        }

    def _read(
        self,
        session: Session,
        gateway: GoogleGateway,
        store: CredentialStore,
        account_id: int,
        remote_ids: Sequence[str],
    ) -> VideoStatistics:
        tokens = get_valid_credentials(session, store, gateway, account_id)
        try:
            self._spend()
            return gateway.get_video_statistics(tokens.access_token, remote_ids)
        except GoogleUnauthorized:
            # The token may have been revoked early: refresh once, like uploads do.
            tokens = get_valid_credentials(
                session, store, gateway, account_id, force_refresh=True
            )
            self._spend()
            return gateway.get_video_statistics(tokens.access_token, remote_ids)

    def _spend(self) -> None:
        """One `videos.list` call is 1 unit, spent right before it is made."""
        if self.budget is not None and not self.budget.try_spend(self.clock()):
            raise BudgetExhausted()

    def _result(self, statistics: VideoStatistics, remote_id: str) -> FetchResult:
        if remote_id in statistics.found:
            declared = {metric.name for metric in self.metrics}
            values = statistics.found[remote_id]
            return FetchResult.ok(
                {name: value for name, value in values.items() if name in declared}
            )
        if remote_id in statistics.missing:
            return FetchResult.not_found()
        return FetchResult.transient()
