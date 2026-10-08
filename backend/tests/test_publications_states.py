"""Editing rules for the execution states and independence of the publishing core."""

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR
from tests.conftest import FUTURE, create_publications, run_sql, setup_project

APP_DIR = BACKEND_DIR / "app"
PUBLISHED_AT = "2026-10-07 10:00:00"


def _setup(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    _, content, accounts = setup_project(client, platforms=("instagram",))
    publication = create_publications(client, content["id"], [accounts[0]["id"]])[0]
    return content, publication


def _set_status(db_path: Path, publication_id: int, status: str) -> None:
    published_at = PUBLISHED_AT if status == "published" else None
    run_sql(
        db_path,
        "UPDATE publications SET status = ?, published_at = ? WHERE id = ?",
        status,
        published_at,
        publication_id,
    )


@pytest.mark.parametrize("status", ["publishing", "published"])
@pytest.mark.parametrize(
    "body",
    [{"scheduled_at": FUTURE}, {"title_override": "New"}, {"hashtags_override": []}],
)
def test_executing_or_published_publications_cannot_be_edited(
    client: TestClient, db_path: Path, status: str, body: dict[str, Any]
) -> None:
    _, publication = _setup(client)
    _set_status(db_path, publication["id"], status)

    response = client.patch(f"/api/publications/{publication['id']}", json=body)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    assert client.get(f"/api/publications/{publication['id']}").json()["status"] == (
        status
    )


def test_failed_publications_accept_overrides_but_not_dates(
    client: TestClient, db_path: Path
) -> None:
    _, publication = _setup(client)
    _set_status(db_path, publication["id"], "failed")
    url = f"/api/publications/{publication['id']}"

    response = client.patch(url, json={"title_override": "Fixed title"})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Fixed title"
    assert response.json()["status"] == "failed"

    response = client.patch(url, json={"scheduled_at": FUTURE})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"


@pytest.mark.parametrize("status", ["publishing", "published"])
def test_executing_or_published_publications_cannot_be_cancelled(
    client: TestClient, db_path: Path, status: str
) -> None:
    _, publication = _setup(client)
    _set_status(db_path, publication["id"], status)

    response = client.post(f"/api/publications/{publication['id']}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"


def test_failed_publications_can_be_cancelled(
    client: TestClient, db_path: Path
) -> None:
    _, publication = _setup(client)
    _set_status(db_path, publication["id"], "failed")

    response = client.post(f"/api/publications/{publication['id']}/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("publishing", 409), ("failed", 409), ("published", 201)],
)
def test_duplicates_consider_execution_states(
    client: TestClient, db_path: Path, status: str, expected: int
) -> None:
    content, publication = _setup(client)
    _set_status(db_path, publication["id"], status)

    response = client.post(
        f"/api/contents/{content['id']}/publications",
        json={"account_ids": [publication["account_id"]]},
    )

    assert response.status_code == expected, response.text
    if expected == 409:
        assert response.json()["error"]["code"] == "duplicate"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("publishing", 409), ("failed", 409), ("published", 200)],
)
def test_reactivation_considers_execution_states(
    client: TestClient, db_path: Path, status: str, expected: int
) -> None:
    content, publication = _setup(client)
    client.post(f"/api/publications/{publication['id']}/cancel")
    other = create_publications(client, content["id"], [publication["account_id"]])[0]
    _set_status(db_path, other["id"], status)

    response = client.post(f"/api/publications/{publication['id']}/reactivate")

    assert response.status_code == expected, response.text


def test_publication_read_includes_execution_fields(
    client: TestClient, db_path: Path
) -> None:
    _, publication = _setup(client)

    body = client.get(f"/api/publications/{publication['id']}").json()

    assert body["published_at"] is None
    assert body["latest_attempt"] is None
    assert body["attempt_count"] == 0

    _set_status(db_path, publication["id"], "published")
    body = client.get(f"/api/publications/{publication['id']}").json()
    assert body["status"] == "published"
    assert body["published_at"].startswith("2026-10-07T10:00:00")


# --- Architecture of the generic publishing core -------------------------------------

FORBIDDEN_PREFIXES = ("app.youtube_", "app.credential_store", "httpx", "keyring")


def _imported_modules(module: str) -> set[str]:
    tree = ast.parse((APP_DIR / f"{module}.py").read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize(
    "module", ["publishing", "publications", "scheduler", "automation"]
)
def test_core_modules_do_not_depend_on_youtube(module: str) -> None:
    imported = _imported_modules(module)

    offending = {
        name
        for name in imported
        if name.startswith(FORBIDDEN_PREFIXES) or name.startswith("app.youtube")
    }
    assert offending == set()


def test_publish_context_only_holds_generic_dependencies() -> None:
    from app import publishing

    fields = {field.name for field in dataclasses.fields(publishing.PublishContext)}

    assert fields == {"session_factory", "storage", "settings"}
    assert publishing.PublishingSettings.__module__ == "app.publishing"


def test_youtube_upload_settings_live_in_the_youtube_module() -> None:
    defining = [
        path.name
        for path in sorted(APP_DIR.glob("*.py"))
        if "class YouTubeUploadSettings" in path.read_text()
    ]

    assert defining == ["youtube_upload.py"]
