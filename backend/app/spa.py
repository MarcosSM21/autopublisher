"""The compiled frontend, served by FastAPI in installation mode (research §2, §3).

One process and one port serve the UI and the API. Development keeps Vite.

- `/assets/*`: hashed build files, cached for a year; a missing one is a JSON 404.
- Catch-all `GET|HEAD /{path}`, registered last: backend paths (`/api`, `/health`,
  docs) answer the JSON 404 and never the shell; a regular file inside `dist` is
  served; anything else gets `index.html` (deep links), never cached.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.deployment import EXIT_CONFIG
from app.guards import SPA_SHELL_ROUTE, is_backend_path

INDEX_FILE = "index.html"
ASSETS_CACHE = "public, max-age=31536000, immutable"
SHELL_CACHE = "no-cache"


class FrontendBuildMissing(Exception):
    exit_code = EXIT_CONFIG


def check_build(dist: Path) -> None:
    """Installation never falls back to Vite: without a build it does not start."""
    if not (dist / INDEX_FILE).is_file():
        raise FrontendBuildMissing(
            f"Frontend build not found at {dist}. Run `npm ci && npm run build` in "
            "frontend/ or copy a build there (see docs/deployment.md)."
        )


class _AssetFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = ASSETS_CACHE
        return response


def register_spa(app: FastAPI, dist: Path) -> None:
    """Call last in `create_app`, after every API route."""
    root = dist.resolve()
    index = root / INDEX_FILE
    # StaticFiles refuses paths outside its directory and does not follow symlinks.
    app.mount(
        "/assets", _AssetFiles(directory=root / "assets", check_dir=False), "assets"
    )

    @app.api_route(SPA_SHELL_ROUTE[1], methods=["GET", "HEAD"], include_in_schema=False)
    def spa_shell(path: str) -> FileResponse:
        if is_backend_path(f"/{path}") or not index.is_file():
            raise StarletteHTTPException(404)
        try:
            candidate = (root / path).resolve()
            regular_file = (
                bool(path)
                and candidate != index
                and candidate.is_relative_to(root)
                and candidate.is_file()
            )
        except (OSError, ValueError):  # e.g. an embedded NUL byte
            regular_file = False
        if regular_file:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": SHELL_CACHE})
