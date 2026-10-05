from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app import accounts, contents, projects
from app.config import get_db_path, get_media_dir
from app.db import create_db_engine, run_migrations
from app.errors import register_error_handlers
from app.storage import MediaStorage


def create_app(db_path: Path | None = None, media_dir: Path | None = None) -> FastAPI:
    """Build the application; storage is only touched when it starts up."""
    resolved_path = db_path or get_db_path()
    resolved_media_dir = media_dir or get_media_dir()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        run_migrations(resolved_path)
        engine = create_db_engine(resolved_path)
        app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
        storage = MediaStorage(resolved_media_dir)
        storage.prepare()
        app.state.storage = storage
        yield
        engine.dispose()

    app = FastAPI(title="AutoPublisher", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(projects.router)
    app.include_router(accounts.router)
    app.include_router(contents.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report that the service is running."""
        return {"status": "ok"}

    return app


app = create_app()
