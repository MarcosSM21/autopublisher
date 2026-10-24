"""The compiled frontend in installation mode (Feature 020 T015, api.md §6)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deployment import DeploymentSettings
from app.main import create_app
from tests.conftest import (
    create_project,
    import_one,
    installation_app,
    installation_client,
    installation_settings,
    make_mp4,
    sign_in,
)

INDEX = "<!doctype html><title>AutoPublisher</title>"
ASSET = "console.log('app')"
SECRET = "do-not-serve"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "app-1a2b.js").write_text(ASSET)
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text(SECRET)
    (root / "leak.txt").symlink_to(tmp_path / "secret.txt")
    (root / "assets" / "leak.js").symlink_to(tmp_path / "secret.txt")
    return root


@pytest.fixture
def app(tmp_path: Path, dist: Path) -> FastAPI:
    return installation_app(installation_settings(tmp_path))


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """No lifespan: the shell and the guards need no database."""
    return installation_client(app)


@pytest.fixture
def running(app: FastAPI) -> Iterator[TestClient]:
    with installation_client(app) as client:
        yield client


def _code(response: object) -> str:
    return str(response.json()["error"]["code"])  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/login",
        "/login?next=/posts%3Fview%3Dweek",
        "/calendar/week?d=2026-10-23",
        "/posts/12/edit",
        "/settings#installation",
    ],
)
def test_shell_for_deep_links_without_session(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_assets_are_served_with_a_long_cache(client: TestClient) -> None:
    response = client.get("/assets/app-1a2b.js")
    assert response.status_code == 200
    assert response.text == ASSET
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    head = client.head("/assets/app-1a2b.js")
    assert head.status_code == 200


def test_other_build_files_are_served(client: TestClient) -> None:
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.text == "<svg/>"


def test_missing_asset_is_a_json_404(client: TestClient) -> None:
    response = client.get("/assets/missing.js")
    assert response.status_code == 404
    assert _code(response) == "not_found"


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/health/extra",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
        "/openapi.json",
    ],
)
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_backend_paths_never_get_the_shell(
    client: TestClient, path: str, method: str
) -> None:
    response = client.request(method, path)
    assert response.status_code == 404
    if method == "GET":
        assert _code(response) == "not_found"
        assert INDEX not in response.text


def test_unknown_api_route(running: TestClient, app: FastAPI) -> None:
    # Without a session the guard answers first; with one, the backend's 404.
    assert _code(running.get("/api/nope")) == "auth_required"
    sign_in(running, app)
    response = running.get("/api/nope")
    assert response.status_code == 404
    assert _code(response) == "not_found"
    assert running.get("/api").status_code == 404


def test_health_is_not_shadowed(running: TestClient) -> None:
    assert running.get("/health").json() == {"status": "ok"}


def test_other_methods_on_the_shell_are_json(client: TestClient) -> None:
    response = client.post("/calendar")
    assert response.status_code == 405
    assert _code(response) == "method_not_allowed"


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "/assets/..%2f..%2fsecret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/leak.txt",
        "/assets/leak.js",
    ],
)
def test_nothing_outside_dist_is_served(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert SECRET not in response.text
    assert response.status_code in {200, 404}


def test_shell_is_public_but_media_is_not(
    running: TestClient, app: FastAPI, tmp_path: Path
) -> None:
    assert running.get("/").status_code == 200
    sign_in(running, app)
    project = create_project(running, "Cyber")
    data = make_mp4(payload=b"0123456789" * 50)
    content = import_one(running, project["id"], "clip.mp4", data)["content"]
    url = f"/api/contents/{content['id']}/file"

    # Range regression (L7): authenticated media streams to <video> on phones.
    partial = running.get(url, headers={"Range": "bytes=0-1"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == f"bytes 0-1/{len(data)}"
    assert partial.headers["accept-ranges"] == "bytes"
    assert partial.content == data[:2]

    anonymous = installation_client(app)
    for headers in ({}, {"Range": "bytes=0-1"}):
        response = anonymous.get(url, headers=headers)
        assert response.status_code == 401
        assert _code(response) == "auth_required"
    assert anonymous.get("/").status_code == 200


def test_missing_build_never_falls_back(tmp_path: Path) -> None:
    app = installation_app(installation_settings(tmp_path))  # no dist at all
    response = installation_client(app).get("/calendar")
    assert response.status_code == 404
    assert _code(response) == "not_found"


def test_development_serves_no_frontend(tmp_path: Path, dist: Path) -> None:
    app = create_app(
        tmp_path / "db.sqlite",
        tmp_path / "media",
        deployment=DeploymentSettings.development(),
    )
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1))
    response = client.get("/")
    assert response.status_code == 404
    assert _code(response) == "not_found"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 200
