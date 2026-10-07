from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2 as httpx
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app import (
    accounts,
    contents,
    projects,
    publications,
    publishing,
    youtube_connections,
    youtube_publishing,
)
from app.config import get_db_path, get_media_dir
from app.credential_store import CredentialStore, KeyringCredentialStore
from app.db import create_db_engine, run_migrations
from app.errors import register_error_handlers
from app.models import Platform
from app.publishing import (
    PublicationRunner,
    PublishContext,
    PublishingSettings,
    recover_interrupted_attempts,
)
from app.storage import MediaStorage
from app.youtube_gateway import GoogleGateway
from app.youtube_oauth import OAuthAttemptRegistry
from app.youtube_publishing import YouTubePublisher
from app.youtube_upload import YouTubeUploadSettings

GOOGLE_TIMEOUT_SECONDS = 10


def create_app(
    db_path: Path | None = None,
    media_dir: Path | None = None,
    *,
    credential_store: CredentialStore | None = None,
    google_transport: httpx.BaseTransport | None = None,
    publishing_settings: PublishingSettings | None = None,
    youtube_upload_settings: YouTubeUploadSettings | None = None,
) -> FastAPI:
    """Build the application; storage is only touched when it starts up.

    This is the composition root: platform publishers receive their own dependencies
    here, while the publishing core only gets generic ones. Tests inject an in-memory
    credential store, a fake Google transport and settings that never really wait.
    """
    resolved_path = db_path or get_db_path()
    resolved_media_dir = media_dir or get_media_dir()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        run_migrations(resolved_path)
        engine = create_db_engine(resolved_path)
        session_factory = sessionmaker(engine, expire_on_commit=False)
        app.state.session_factory = session_factory
        # Executions left running by a previous process are closed, never resumed.
        recover_interrupted_attempts(session_factory)
        storage = MediaStorage(resolved_media_dir)
        storage.prepare()
        app.state.storage = storage
        app.state.credential_store = credential_store or KeyringCredentialStore()
        app.state.oauth_attempts = OAuthAttemptRegistry()
        with httpx.Client(
            transport=google_transport, timeout=GOOGLE_TIMEOUT_SECONDS
        ) as google_client:
            app.state.google_gateway = GoogleGateway(google_client)
            publish_context = PublishContext(
                session_factory, storage, publishing_settings or PublishingSettings()
            )
            app.state.publish_context = publish_context
            runner = PublicationRunner(publish_context)
            app.state.publication_runner = runner
            app.state.publishers = {
                Platform.YOUTUBE: YouTubePublisher(
                    gateway=app.state.google_gateway,
                    credential_store=app.state.credential_store,
                    upload_settings=youtube_upload_settings or YouTubeUploadSettings(),
                )
            }
            try:
                yield
            finally:
                runner.stop()
        engine.dispose()

    youtube_connections.install_log_redaction()
    app = FastAPI(title="AutoPublisher", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(projects.router)
    app.include_router(accounts.router)
    app.include_router(contents.router)
    app.include_router(publications.router)
    app.include_router(publishing.router)
    app.include_router(youtube_connections.router)
    app.include_router(youtube_publishing.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the service is running."""
        return {"status": "ok"}

    return app


app = create_app()
