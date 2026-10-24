import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx2 as httpx
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app import (
    account_discard,
    accounts,
    asset_library,
    auth,
    automation,
    contents,
    distribution_presets,
    instagram_connections,
    instagram_publishing,
    instance_lock,
    overview,
    platform_availability,
    projects,
    publications,
    publishing,
    spa,
    system_status,
    telegram_connections,
    threads_connections,
    threads_publishing,
    tiktok_connections,
    tiktok_inbox,
    tiktok_publishing,
    youtube_connections,
    youtube_publishing,
)
from app.config import get_data_dir, get_db_path, get_media_delivery_file, get_media_dir
from app.content_files import ContentFileGuard, sweep_orphan_clean_copies
from app.credential_store import (
    INSTAGRAM_SERVICE,
    TELEGRAM_SERVICE,
    THREADS_SERVICE,
    TIKTOK_SERVICE,
    CredentialStore,
    CredentialStoreProbe,
    KeyringCredentialStore,
)
from app.db import create_db_engine, run_migrations
from app.deployment import DeploymentSettings
from app.errors import register_error_handlers
from app.guards import install_guards
from app.instagram_gateway import InstagramGateway
from app.instagram_oauth import InstagramAttemptRegistry
from app.instagram_publishing import InstagramPublisher, InstagramPublishSettings
from app.media_delivery import (
    DeliverySettings,
    MediaDeliveryConfig,
    MediaDeliveryProvider,
    TemporaryMediaService,
    install_media_delivery_log_redaction,
    load_media_delivery_config,
)
from app.media_delivery_s3 import S3CompatibleProvider
from app.models import Platform
from app.publishing import (
    PublicationRunner,
    PublishContext,
    PublishingSettings,
    recover_interrupted_attempts,
)
from app.scheduler import Scheduler, SchedulerSettings
from app.storage import MediaStorage
from app.telegram_gateway import TelegramGateway, TelethonGateway
from app.telegram_publishing import TelegramPublisher
from app.threads_gateway import ThreadsGateway
from app.threads_oauth import ThreadsAttemptRegistry
from app.threads_publishing import ThreadsPublisher, ThreadsPublishSettings
from app.tiktok_gateway import TIKTOK_TIMEOUT_SECONDS, TikTokCredential, TikTokGateway
from app.tiktok_oauth import TikTokAttemptRegistry
from app.tiktok_publishing import TikTokPublisher, TikTokPublishSettings
from app.youtube_gateway import GoogleGateway
from app.youtube_oauth import OAuthAttemptRegistry
from app.youtube_publishing import YouTubePublisher
from app.youtube_upload import YouTubeUploadSettings

logger = logging.getLogger(__name__)

GOOGLE_TIMEOUT_SECONDS = 10
META_TIMEOUT_SECONDS = 10


def create_app(
    db_path: Path | None = None,
    media_dir: Path | None = None,
    *,
    credential_store: CredentialStore | None = None,
    google_transport: httpx.BaseTransport | None = None,
    instagram_credential_store: CredentialStore | None = None,
    instagram_transport: httpx.BaseTransport | None = None,
    threads_credential_store: CredentialStore | None = None,
    threads_transport: httpx.BaseTransport | None = None,
    tiktok_credential_store: CredentialStore | None = None,
    tiktok_transport: httpx.BaseTransport | None = None,
    telegram_credential_store: CredentialStore | None = None,
    telegram_gateway: TelegramGateway | None = None,
    publishing_settings: PublishingSettings | None = None,
    youtube_upload_settings: YouTubeUploadSettings | None = None,
    media_delivery_provider: MediaDeliveryProvider | None = None,
    instagram_publish_settings: InstagramPublishSettings | None = None,
    threads_publish_settings: ThreadsPublishSettings | None = None,
    tiktok_publish_settings: TikTokPublishSettings | None = None,
    scheduler_settings: SchedulerSettings | None = None,
    clock: Callable[[], datetime] | None = None,
    deployment: DeploymentSettings | None = None,
    credential_probe: CredentialStoreProbe | None = None,
) -> FastAPI:
    """Build the application; storage is only touched when it starts up.

    This is the composition root: platform publishers receive their own dependencies
    here, while the publishing core only gets generic ones. Tests inject in-memory
    credential stores, fake Google and Meta transports, a fake media delivery
    provider, settings that never really wait and a fake clock shared by the
    scheduler and the API.

    `deployment` selects the mode and its guards (Feature 020, research §4): the
    module app below is development, `serve` builds installation. Without it (the
    existing tests) the app behaves exactly as before, with no guards.
    """
    layout = deployment.layout if deployment is not None else None
    resolved_path = db_path or (layout.db_path if layout else get_db_path())
    resolved_data_dir = layout.data_dir if layout else get_data_dir()
    resolved_media_dir = media_dir or (layout.media_dir if layout else get_media_dir())
    resolved_scheduler_settings = scheduler_settings or SchedulerSettings()
    resolved_clock = clock or resolved_scheduler_settings.clock
    resolved_publishing_settings = publishing_settings or PublishingSettings()
    s3_providers: dict[MediaDeliveryConfig, S3CompatibleProvider] = {}

    def delivery_provider() -> tuple[MediaDeliveryProvider, MediaDeliveryConfig]:
        """Read on every use, like the other local configuration files."""
        config = load_media_delivery_config(get_media_delivery_file())
        if media_delivery_provider is not None:
            return media_delivery_provider, config
        provider = s3_providers.get(config)
        if provider is None:
            provider = s3_providers.setdefault(config, S3CompatibleProvider(config))
        return provider, config

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Before migrations: two servers never share a data directory or an
        # effective database (Feature 020, research §9).
        with instance_lock.hold(
            instance_lock.server_locks(resolved_data_dir, resolved_path),
            retry_seconds=instance_lock.SERVER_RETRY_SECONDS,
        ):
            async with serve(app):
                yield

    @asynccontextmanager
    async def serve(app: FastAPI) -> AsyncIterator[None]:
        run_migrations(resolved_path)
        engine = create_db_engine(resolved_path)
        session_factory = sessionmaker(engine, expire_on_commit=False)
        app.state.session_factory = session_factory
        with session_factory() as session:
            auth.purge_expired_sessions(session, resolved_clock())
        storage = MediaStorage(resolved_media_dir)
        storage.prepare()
        # Before the scheduler starts: no publication can use a copy yet.
        with session_factory() as session:
            sweep_orphan_clean_copies(session, storage)
        app.state.storage = storage
        app.state.content_file_guard = ContentFileGuard()
        app.state.credential_store = credential_store or KeyringCredentialStore()
        app.state.oauth_attempts = OAuthAttemptRegistry()
        # Instagram has its own secure-storage service and attempts.
        app.state.instagram_credential_store = (
            instagram_credential_store or KeyringCredentialStore(INSTAGRAM_SERVICE)
        )
        app.state.instagram_attempts = InstagramAttemptRegistry(resolved_clock)
        # Threads is independent from Instagram: own service, attempts and client.
        app.state.threads_credential_store = (
            threads_credential_store or KeyringCredentialStore(THREADS_SERVICE)
        )
        app.state.threads_attempts = ThreadsAttemptRegistry(resolved_clock)
        # TikTok has its own secure-storage service (Feature 012).
        app.state.tiktok_credential_store = (
            tiktok_credential_store or KeyringCredentialStore(TIKTOK_SERVICE)
        )

        def discard_tiktok_credential(
            credential: TikTokCredential, account_id: int
        ) -> None:
            tiktok_connections.discard_credential(
                app.state.tiktok_gateway, credential, account_id
            )

        # A cancelled or expired account change discards its pending credential.
        app.state.tiktok_attempts = TikTokAttemptRegistry(
            resolved_clock, discard=discard_tiktok_credential
        )
        # Telegram (Feature 015): own service; the session never leaves it.
        app.state.telegram_credential_store = (
            telegram_credential_store or KeyringCredentialStore(TELEGRAM_SERVICE)
        )
        app.state.telegram_gateway = telegram_gateway or TelethonGateway()
        app.state.telegram_logins = telegram_connections.TelegramLoginRegistry(
            resolved_clock
        )
        with (
            httpx.Client(
                transport=google_transport, timeout=GOOGLE_TIMEOUT_SECONDS
            ) as google_client,
            httpx.Client(
                transport=instagram_transport, timeout=META_TIMEOUT_SECONDS
            ) as meta_client,
            httpx.Client(
                transport=threads_transport, timeout=META_TIMEOUT_SECONDS
            ) as threads_client,
            httpx.Client(
                transport=tiktok_transport, timeout=TIKTOK_TIMEOUT_SECONDS
            ) as tiktok_client,
        ):
            app.state.google_gateway = GoogleGateway(google_client)
            app.state.instagram_gateway = InstagramGateway(meta_client, resolved_clock)
            app.state.threads_gateway = ThreadsGateway(threads_client, resolved_clock)
            app.state.tiktok_gateway = TikTokGateway(tiktok_client, resolved_clock)
            publish_context = PublishContext(
                session_factory,
                storage,
                resolved_publishing_settings,
                file_guard=app.state.content_file_guard,
            )
            temporary_media = TemporaryMediaService(
                session_factory,
                delivery_provider,
                DeliverySettings(sleep=resolved_publishing_settings.sleep),
                clock=resolved_clock,
            )
            app.state.temporary_media = temporary_media
            app.state.publish_context = publish_context
            runner = PublicationRunner(publish_context)
            app.state.publication_runner = runner
            app.state.publishers = {
                Platform.YOUTUBE: YouTubePublisher(
                    gateway=app.state.google_gateway,
                    credential_store=app.state.credential_store,
                    upload_settings=youtube_upload_settings or YouTubeUploadSettings(),
                ),
                Platform.INSTAGRAM: InstagramPublisher(
                    gateway=app.state.instagram_gateway,
                    credential_store=app.state.instagram_credential_store,
                    delivery=temporary_media,
                    settings=instagram_publish_settings,
                ),
                Platform.THREADS: ThreadsPublisher(
                    gateway=app.state.threads_gateway,
                    credential_store=app.state.threads_credential_store,
                    delivery=temporary_media,
                    settings=threads_publish_settings,
                ),
                Platform.TELEGRAM: TelegramPublisher(
                    gateway=app.state.telegram_gateway,
                    credential_store=app.state.telegram_credential_store,
                    clock=resolved_clock,
                ),
                Platform.TIKTOK: TikTokPublisher(
                    gateway=app.state.tiktok_gateway,
                    credential_store=app.state.tiktok_credential_store,
                    settings=app.state.tiktok_publish_settings,
                ),
            }
            # Start-up order (research.md §2): migrations, publishers, recovery of
            # executions left running by a previous process (closed, never resumed),
            # and only then the scheduler, so they never compete.
            recover_interrupted_attempts(session_factory)
            # TikTok secrets left behind by an interrupted reconnection (best-effort).
            with session_factory() as session:
                tiktok_connections.cleanup_orphans(
                    session, app.state.tiktok_credential_store
                )
            # Temporary media left by a previous process is deleted in the
            # background: it may need the network and must not delay start-up.
            sweeper = threading.Thread(
                target=_sweep, args=(temporary_media,), name="media-sweep", daemon=True
            )
            sweeper.start()
            app.state.media_sweeper = sweeper
            scheduler = Scheduler(
                session_factory,
                publish_context,
                runner,
                app.state.publishers,
                resolved_scheduler_settings,
            )
            app.state.scheduler = scheduler
            if resolved_scheduler_settings.autostart:
                scheduler.start()
            try:
                yield
            finally:
                # Nothing new starts while running uploads are being stopped.
                scheduler.stop()
                runner.stop()
        engine.dispose()

    youtube_connections.install_log_redaction()
    instagram_connections.install_log_redaction()
    threads_connections.install_log_redaction()
    tiktok_connections.install_log_redaction()
    install_media_delivery_log_redaction()
    if deployment is not None and deployment.is_installation:
        # No public API schema in installation mode (contracts/api.md §6).
        app = FastAPI(
            title="AutoPublisher",
            lifespan=lifespan,
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
    else:
        app = FastAPI(title="AutoPublisher", lifespan=lifespan)
    app.state.deployment = deployment
    if deployment is not None:
        install_guards(app, deployment)
    app.state.clock = resolved_clock
    app.state.tiktok_publish_settings = tiktok_publish_settings or (
        TikTokPublishSettings(clock=resolved_clock)
    )
    app.state.login_limiter = auth.LoginRateLimiter(resolved_clock)
    app.state.credential_probe = credential_probe or CredentialStoreProbe()
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(accounts.router)
    app.include_router(account_discard.router)
    app.include_router(contents.router)
    app.include_router(asset_library.router)
    app.include_router(publications.router)
    app.include_router(distribution_presets.router)
    app.include_router(publishing.router)
    app.include_router(youtube_connections.router)
    app.include_router(youtube_publishing.router)
    app.include_router(instagram_connections.router)
    app.include_router(instagram_publishing.router)
    app.include_router(threads_connections.router)
    app.include_router(threads_publishing.router)
    app.include_router(tiktok_connections.router)
    app.include_router(tiktok_publishing.router)
    app.include_router(tiktok_inbox.router)
    app.include_router(telegram_connections.router)
    app.include_router(automation.router)
    app.include_router(overview.router)
    app.include_router(platform_availability.router)
    app.include_router(system_status.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Public liveness: `ok` or `degraded`, nothing else (contracts/api.md §2)."""
        return {"status": system_status.health_status(app)}

    if deployment is not None and deployment.is_installation:
        # Last: the SPA catch-all must never shadow a backend route.
        assert deployment.frontend_dist is not None
        spa.register_spa(app, deployment.frontend_dist)
    return app


def _sweep(service: TemporaryMediaService) -> None:
    try:
        service.sweep()
    except Exception as exc:  # Best effort: the next sweep tries again.
        logger.warning("Temporary media sweep failed (%s).", type(exc).__name__)


# `uvicorn app.main:app --reload` is development mode: loopback clients only.
app = create_app(deployment=DeploymentSettings.development())
