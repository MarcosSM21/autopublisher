"""Instagram metrics: the `like_count`/`comments_count` fields of the media.

Insights are declared for a later permissions feature but never read: they need
`instagram_business_manage_insights`, which AutoPublisher does not request. Only the
declaration lives here for now; the read is not implemented yet.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy.orm import Session

from app.analytics.adapters.base import FetchResult, MetricDef
from app.models import MetricOrigin, Platform

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

    def fetch(
        self, session: Session, account_id: int, remote_ids: Sequence[str]
    ) -> Mapping[str, FetchResult]:
        raise NotImplementedError("Instagram metrics are not read yet.")
