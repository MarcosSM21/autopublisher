"""YouTube metrics: public counters of `videos.list` (`part=statistics`).

Only the declaration lives here for now; the read is not implemented yet.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy.orm import Session

from app.analytics.adapters.base import (
    EngagementFormula,
    ExcludedMetric,
    FetchResult,
    MetricDef,
)
from app.models import MetricOrigin, Platform

BASIC = "basic"
READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


def _counter(name: str, label: str, definition: str, concept: str | None) -> MetricDef:
    return MetricDef(
        name=name,
        label=label,
        definition=definition,
        origin=MetricOrigin.PUBLIC_COUNTER,
        concept=concept,
        group=BASIC,
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
        ),
    )
    excluded = (
        ExcludedMetric("favoriteCount", "deprecated by YouTube in 2015, always 0"),
    )
    groups: Mapping[str, str | None] = {BASIC: READONLY_SCOPE}
    read_groups = frozenset({BASIC})
    engagement = EngagementFormula(("likeCount", "commentCount"), "viewCount")
    batch_size = 50

    def fetch(
        self, session: Session, account_id: int, remote_ids: Sequence[str]
    ) -> Mapping[str, FetchResult]:
        raise NotImplementedError("YouTube metrics are not read yet.")
