"""Which platforms can be connected and published to (contracts/api.md §3).

Aggregates the existing local configuration loaders, read on every call. The answer
is written by us: never file paths, environment variable names, file contents,
client ids, secrets or exception text.
"""

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Request

from app import (
    instagram_connections,
    telegram_connections,
    threads_connections,
    tiktok_connections,
    youtube_connections,
)
from app.models import Platform
from app.publications import PLATFORM_LABELS
from app.schemas import PlatformAvailabilityRead

router = APIRouter(prefix="/api", tags=["platforms"])

# Platforms whose posts need the temporary media delivery (Threads only for media).
NEEDS_MEDIA_DELIVERY = {Platform.INSTAGRAM, Platform.THREADS}

APP_CONFIGURED: dict[Platform, Callable[[], bool]] = {
    Platform.YOUTUBE: youtube_connections.oauth_configured,
    Platform.INSTAGRAM: instagram_connections.oauth_configured,
    Platform.THREADS: threads_connections.oauth_configured,
    Platform.TIKTOK: tiktok_connections.oauth_configured,
    Platform.TELEGRAM: telegram_connections.configured,
}

MEDIA_DELIVERY_MESSAGES = {
    Platform.INSTAGRAM: (
        "Media delivery is not configured: Instagram posts can't be published yet."
    ),
    Platform.THREADS: (
        "Media delivery is not configured: Threads can publish text posts, "
        "but not images or videos."
    ),
}


def _availability(
    platform: Platform, media_delivery: Callable[[], bool]
) -> PlatformAvailabilityRead:
    label = PLATFORM_LABELS[platform]
    app_configured = APP_CONFIGURED.get(platform)
    if app_configured is None:
        return PlatformAvailabilityRead(
            platform=platform,
            label=label,
            integration_available=False,
            status="coming_soon",
            can_connect=False,
            missing=[],
            message=None,
        )
    if not app_configured():
        return PlatformAvailabilityRead(
            platform=platform,
            label=label,
            integration_available=True,
            status="not_configured",
            can_connect=False,
            missing=["app_credentials"],
            message=f"The {label} app credentials are missing or invalid.",
        )
    status: Literal["configured", "partial"] = "configured"
    missing: list[Literal["app_credentials", "media_delivery"]] = []
    message = None
    if platform in NEEDS_MEDIA_DELIVERY and not media_delivery():
        status, missing, message = (
            "partial",
            ["media_delivery"],
            MEDIA_DELIVERY_MESSAGES[platform],
        )
    return PlatformAvailabilityRead(
        platform=platform,
        label=label,
        integration_available=True,
        status=status,
        can_connect=True,
        missing=missing,
        message=message,
    )


@router.get("/platforms", response_model=list[PlatformAvailabilityRead])
def list_platforms(request: Request) -> list[PlatformAvailabilityRead]:
    """Read only: local configuration files, no network."""
    media_delivery: Callable[[], bool] = request.app.state.temporary_media.configured
    return [_availability(platform, media_delivery) for platform in Platform]
