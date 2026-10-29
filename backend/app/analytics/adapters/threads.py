"""Threads metrics: declared only.

The Threads media object exposes no counters; every metric is an insight that needs
`threads_manage_insights`, which AutoPublisher does not request. The adapter never
calls the network.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy.orm import Session

from app.analytics.adapters.base import FetchResult, MetricDef
from app.models import MetricOrigin, Platform

INSIGHTS = "insights"
INSIGHTS_PERMISSION = "threads_manage_insights"


def _insight(name: str, label: str, definition: str, concept: str | None) -> MetricDef:
    return MetricDef(
        name=name,
        label=label,
        definition=definition,
        origin=MetricOrigin.INSIGHT,
        concept=concept,
        group=INSIGHTS,
    )


class ThreadsMetricsAdapter:
    platform = Platform.THREADS
    metrics = (
        _insight("views", "Views", "Number of times the post was viewed.", "views"),
        _insight("likes", "Likes", "Number of likes on the post.", "likes"),
        _insight(
            "replies",
            "Replies",
            "Number of replies to the post. Shown under Comments for alignment "
            "only: on a root post Threads counts every reply, but nested replies "
            "are not included.",
            "comments",
        ),
        _insight("reposts", "Reposts", "Number of reposts of the post.", None),
        _insight("quotes", "Quotes", "Number of quotes of the post.", None),
        _insight("shares", "Shares", "Number of shares of the post.", "shares"),
    )
    excluded = ()
    groups: Mapping[str, str | None] = {INSIGHTS: INSIGHTS_PERMISSION}
    read_groups: frozenset[str] = frozenset()
    engagement = None
    source = "threads.media:insights"
    batch_size = 1

    def fetch(
        self, session: Session, account_id: int, remote_ids: Sequence[str]
    ) -> Mapping[str, FetchResult]:
        raise RuntimeError("Threads metrics are never read.")
