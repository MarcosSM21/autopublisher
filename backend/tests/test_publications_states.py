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

FORBIDDEN_PREFIXES = (
    "app.youtube_",
    "app.instagram_",
    "app.media_delivery",
    "app.credential_store",
    "httpx",
    "keyring",
    "boto3",
    "botocore",
)


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


@pytest.mark.parametrize(
    "module", ["publishing", "publications", "scheduler", "automation"]
)
def test_core_modules_have_no_instagram_code(module: str) -> None:
    # Platform display names (e.g. "Instagram") are generic data; code is not.
    source = (APP_DIR / f"{module}.py").read_text().lower()

    assert "instagram_" not in source
    assert "media_delivery" not in source


@pytest.mark.parametrize(
    "module", ["publishing", "publications", "scheduler", "automation"]
)
def test_core_modules_have_no_threads_code(module: str) -> None:
    source = (APP_DIR / f"{module}.py").read_text().lower()

    assert "threads_" not in source
    assert not any(name.startswith("app.threads") for name in _imported_modules(module))


def test_threads_and_instagram_do_not_depend_on_each_other() -> None:
    """Threads is an independent integration (spec FR-005)."""
    threads_modules = [
        "threads_oauth",
        "threads_gateway",
        "threads_connections",
        "threads_publishing",
        "threads_media",
    ]
    instagram_modules = [path.stem for path in APP_DIR.glob("instagram_*.py")]
    assert instagram_modules
    for module in threads_modules:
        assert not any(
            name.startswith("app.instagram") for name in _imported_modules(module)
        ), module
    for module in instagram_modules:
        assert not any(
            name.startswith("app.threads") for name in _imported_modules(module)
        ), module


@pytest.mark.parametrize(
    "module", ["publishing", "publications", "scheduler", "automation", "accounts"]
)
def test_core_modules_have_no_tiktok_code(module: str) -> None:
    """The generic core and the accounts core know nothing of TikTok: its publisher
    is only registered by `main.py` (Feature 013, FR-003)."""
    source = (APP_DIR / f"{module}.py").read_text().lower()

    assert "tiktok_" not in source
    assert not any(name.startswith("app.tiktok") for name in _imported_modules(module))


def test_tiktok_and_other_platforms_do_not_depend_on_each_other() -> None:
    tiktok_modules = [path.stem for path in APP_DIR.glob("tiktok_*.py")]
    assert set(tiktok_modules) == {
        "tiktok_oauth",
        "tiktok_gateway",
        "tiktok_connections",
        "tiktok_media",
        "tiktok_publishing",
        "tiktok_transfer",
        "tiktok_inbox",
    }
    other_modules = [
        path.stem
        for prefix in ("youtube_", "instagram_", "threads_")
        for path in APP_DIR.glob(f"{prefix}*.py")
    ]
    assert other_modules
    for module in tiktok_modules:
        assert not any(
            name.startswith(("app.youtube", "app.instagram", "app.threads"))
            for name in _imported_modules(module)
        ), module
    for module in other_modules:
        assert not any(
            name.startswith("app.tiktok") for name in _imported_modules(module)
        ), module


@pytest.mark.parametrize(
    "module", ["tiktok_media", "tiktok_publishing", "tiktok_transfer", "tiktok_inbox"]
)
def test_tiktok_publishing_never_uses_media_delivery(module: str) -> None:
    """FILE_UPLOAD only: no media delivery, R2 or signed URLs (FR-007)."""
    imported = _imported_modules(module)

    assert not any(
        name.startswith(
            (
                "app.media_delivery",
                "app.media_delivery_s3",
                "app.instagram",
                "app.threads",
                "boto3",
                "botocore",
            )
        )
        for name in imported
    ), imported
    assert "media_delivery" not in (APP_DIR / f"{module}.py").read_text()


def test_tiktok_media_rules_need_no_network() -> None:
    imported = _imported_modules("tiktok_media")

    assert not any(
        name.split(".")[0] in ("httpx", "httpx2", "httpcore", "httpcore2", "requests")
        or name.startswith(("app.tiktok_gateway", "app.tiktok_connections"))
        for name in imported
    ), imported


def test_publications_do_not_depend_on_the_publishing_core() -> None:
    """Text publications read the publisher capability from the app state, never by
    importing the execution core (it imports `publications`)."""
    assert not any(
        name.startswith("app.publishing") for name in _imported_modules("publications")
    )


def test_media_delivery_does_not_depend_on_any_platform() -> None:
    imported = _imported_modules("media_delivery") | _imported_modules(
        "media_delivery_s3"
    )

    assert {
        name
        for name in imported
        if name.startswith(("app.instagram", "app.youtube", "app.publishing"))
    } == set()


def test_publish_context_only_holds_generic_dependencies() -> None:
    from app import publishing

    fields = {field.name for field in dataclasses.fields(publishing.PublishContext)}

    assert fields == {"session_factory", "storage", "settings", "file_guard"}
    assert publishing.PublishingSettings.__module__ == "app.publishing"
    # The guard shared with Remove metadata is platform-neutral too.
    from app.content_files import ContentFileGuard

    guard = next(
        f
        for f in dataclasses.fields(publishing.PublishContext)
        if f.name == "file_guard"
    )
    assert guard.default_factory is ContentFileGuard


def test_youtube_upload_settings_live_in_the_youtube_module() -> None:
    defining = [
        path.name
        for path in sorted(APP_DIR.glob("*.py"))
        if "class YouTubeUploadSettings" in path.read_text()
    ]

    assert defining == ["youtube_upload.py"]


def test_tiktok_transfer_knows_no_mode() -> None:
    """The FILE_UPLOAD transfer is shared by both modes: what differs (init call,
    status meaning) is injected (Feature 014, research §4)."""
    source = (APP_DIR / "tiktok_transfer.py").read_text()

    assert "init_video_post" not in source
    assert "init_inbox_video" not in source
    assert "INBOX_UPLOAD" not in source
    assert "DIRECT_POST" not in source
    assert not any(
        name.startswith(("app.tiktok_publishing", "app.tiktok_inbox"))
        for name in _imported_modules("tiktok_transfer")
    )


def test_tiktok_inbox_does_not_depend_on_direct_post() -> None:
    """Upload to Inbox reuses the transfer, never the Direct Post publisher."""
    assert not any(
        name.startswith("app.tiktok_publishing")
        for name in _imported_modules("tiktok_inbox")
    )
