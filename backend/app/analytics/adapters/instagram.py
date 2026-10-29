"""Instagram metrics: the `like_count`/`comments_count` fields of the media.

Insights are declared for a later permissions feature but never read: they need
`instagram_business_manage_insights`, which AutoPublisher does not request.

One call per media (batching with `?ids=` is not confirmed on graph.instagram.com).
Credentials come from `instagram_connections.get_valid_credentials`; failures are
fixed results that never carry tokens or response bodies.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from app.analytics.adapters.base import FetchResult, MetricDef
from app.credential_store import CredentialStore
from app.db import utc_now
from app.errors import AppError
from app.instagram_connections import (
    get_connection,
    get_valid_credentials,
    mark_reconnect_required,
)
from app.instagram_gateway import (
    InstagramGateway,
    MetaError,
    MetaNotFound,
    MetaPermissionDenied,
    MetaRateLimited,
    MetaTokenInvalid,
)
from app.models import MetricOrigin, Platform

# Credential errors that need the user to reconnect; any other one is temporary.
RECONNECT_CODES = {"instagram_not_connected", "instagram_reconnect_required"}

BASIC = "basic"
INSIGHTS = "insights"
BASIC_PERMISSION = "instagram_business_basic"
INSIGHTS_PERMISSION = "instagram_business_manage_insights"


def _insight(name: str, label: str, definition: str, concept: str | None) -> MetricDef:
    return MetricDef(
        name=name,
        label=label,
        definition=definition,
        origin=MetricOrigin.INSIGHT,
        concept=concept,
        group=INSIGHTS,
    )


class InstagramMetricsAdapter:
    platform = Platform.INSTAGRAM
    metrics = (
        MetricDef(
            name="like_count",
            label="Likes",
            definition=(
                "Number of likes on the media. Instagram omits it when the owner "
                "hides like counts."
            ),
            origin=MetricOrigin.PUBLIC_COUNTER,
            concept="likes",
            group=BASIC,
        ),
        MetricDef(
            name="comments_count",
            label="Comments",
            definition="Number of comments on the media.",
            origin=MetricOrigin.PUBLIC_COUNTER,
            concept="comments",
            group=BASIC,
        ),
        _insight("views", "Views", "Number of times the media was viewed.", "views"),
        _insight(
            "reach", "Reach", "Number of unique accounts that saw the media.", None
        ),
        # Likes and comments already align through the basic counters.
        _insight("likes", "Likes (insights)", "Number of likes on the media.", None),
        _insight(
            "comments", "Comments (insights)", "Number of comments on the media.", None
        ),
        _insight("shares", "Shares", "Number of shares of the media.", "shares"),
        _insight("saved", "Saves", "Number of saves of the media.", None),
        _insight(
            "total_interactions",
            "Interactions",
            "Likes, saves, comments and shares of the media, minus unlikes, "
            "unsaves and deleted comments.",
            None,
        ),
    )
    excluded = ()
    groups: Mapping[str, str | None] = {
        BASIC: BASIC_PERMISSION,
        INSIGHTS: INSIGHTS_PERMISSION,
    }
    read_groups = frozenset({BASIC})
    # No views without insights, hence no denominator.
    engagement = None
    source = "instagram.media:fields"
    batch_size = 1

    def __init__(
        self,
        gateway: InstagramGateway | None = None,
        credential_store: CredentialStore | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.clock = clock

    def fetch(
        self, session: Session, account_id: int, remote_ids: Sequence[str]
    ) -> Mapping[str, FetchResult]:
        """Read the basic counters of each media; only the `basic` group. A rate
        limit or a credential problem stops the batch: the rest gets the same
        result. Never raises for platform or credential errors."""
        gateway, store = self.gateway, self.credential_store
        if gateway is None or store is None:
            raise RuntimeError("The Instagram metrics adapter has no gateway.")

        def every(result: FetchResult) -> dict[str, FetchResult]:
            return {remote_id: result for remote_id in remote_ids}

        try:
            token = get_valid_credentials(session, store, gateway, account_id)
        except AppError as error:
            # The connection is already marked when it needs reconnecting.
            if error.code in RECONNECT_CODES:
                return every(FetchResult.unauthorized())
            return every(FetchResult.transient())
        results: dict[str, FetchResult] = {}
        for remote_id in remote_ids:
            try:
                counters = gateway.get_media_counters(token.access_token, remote_id)
            except MetaTokenInvalid:
                connection = get_connection(session, account_id)
                if connection is not None:
                    mark_reconnect_required(session, connection, self.clock())
                return {**every(FetchResult.unauthorized()), **results}
            except MetaRateLimited:
                # retry_at None: refresh.py applies 1 h, doubling up to 24 h.
                return {**every(FetchResult.rate_limited()), **results}
            except MetaPermissionDenied:
                results[remote_id] = FetchResult.permission_missing()
            except MetaNotFound:
                results[remote_id] = FetchResult.not_found()
            except MetaError:
                results[remote_id] = FetchResult.transient()
            else:
                results[remote_id] = FetchResult.ok(counters)
        return results
