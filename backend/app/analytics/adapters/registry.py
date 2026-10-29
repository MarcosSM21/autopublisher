"""Platform → metrics adapter, and the static capability of adapterless platforms."""

from dataclasses import dataclass
from typing import Literal

from app.analytics.adapters.base import MetricsAdapter
from app.analytics.adapters.instagram import InstagramMetricsAdapter
from app.analytics.adapters.threads import ThreadsMetricsAdapter
from app.analytics.adapters.youtube import YouTubeMetricsAdapter
from app.models import Platform

StaticState = Literal["not_supported", "not_available_on_platform", "not_applicable"]


@dataclass(frozen=True)
class StaticCapability:
    state: StaticState
    reason: str


ADAPTERS: dict[Platform, MetricsAdapter] = {
    Platform.YOUTUBE: YouTubeMetricsAdapter(),
    Platform.INSTAGRAM: InstagramMetricsAdapter(),
    Platform.THREADS: ThreadsMetricsAdapter(),
}

STATIC_CAPABILITIES: dict[Platform, StaticCapability] = {
    Platform.TIKTOK: StaticCapability(
        "not_supported",
        "TikTok metrics need the video.list permission, which AutoPublisher does "
        "not request, and posts published from AutoPublisher have no public post id.",
    ),
    # The MTProto API AutoPublisher uses offers channel post metrics
    # (`messages.getMessagesViews`); there is no adapter for it yet.
    Platform.TELEGRAM: StaticCapability(
        "not_supported",
        "Telegram metrics are not supported by AutoPublisher in this version.",
    ),
    Platform.X: StaticCapability(
        "not_applicable",
        "AutoPublisher does not publish to X.",
    ),
}
