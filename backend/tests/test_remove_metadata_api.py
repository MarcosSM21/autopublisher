"""POST /api/contents/{id}/remove-metadata (Feature 016, research §5), with image
contents only: video sanitization is covered in test_video_metadata.py."""

import hashlib
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import asset_library
from app.main import create_app
from app.media import InvalidMediaError
from tests.conftest import (
    create_account,
    create_project,
    create_publications,
    import_one,
    make_image,
    make_mp4,
    run_sql,
    stored_file,
)
from tests.fakes import InMemoryCredentialStore
from tests.test_image_metadata import SENTINELS, dirty_png


def _copy_path(db_path: Path, content_id: int) -> str | None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT sanitized_storage_path FROM contents WHERE id = ?", (content_id,)
        ).fetchone()
    value: str | None = row[0]
    return value


def _clean_files(media_dir: Path) -> list[Path]:
    return sorted(media_dir.glob("projects/*/*.clean.*"))


def _remove(client: TestClient, content_id: int) -> Any:
    return client.post(f"/api/contents/{content_id}/remove-metadata")


@pytest.fixture
def content(client: TestClient) -> dict[str, Any]:
    project = create_project(client, "L4i4")
    result: dict[str, Any] = import_one(
        client, project["id"], "comfy.png", dirty_png()
    )["content"]
    return result


def test_remove_metadata_lifecycle(
    client: TestClient, content: dict[str, Any], media_dir: Path, db_path: Path
) -> None:
    original = stored_file(media_dir, db_path, content["id"])
    original_bytes = original.read_bytes()

    response = _remove(client, content["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata_status"] == "sanitized"
    assert body["publish_file"]["version"] == "clean_copy"
    assert body["publish_file"]["available"] is True
    assert body["checksum"] == content["checksum"]
    assert "projects/" not in response.text and ".clean" not in response.text
    assert original.read_bytes() == original_bytes
    [copy] = _clean_files(media_dir)
    assert (
        body["publish_file"]["checksum"]
        == hashlib.sha256(copy.read_bytes()).hexdigest()
    )
    first_path = _copy_path(db_path, content["id"])

    # A second call does no work.
    assert _remove(client, content["id"]).status_code == 200
    assert _copy_path(db_path, content["id"]) == first_path
    assert _clean_files(media_dir) == [copy]

    # A missing copy is reported and regenerated at a new path.
    copy.unlink()
    detail = client.get(f"/api/contents/{content['id']}").json()
    assert detail["publish_file"]["available"] is False
    regenerated = _remove(client, content["id"])
    assert regenerated.json()["publish_file"]["available"] is True
    assert _copy_path(db_path, content["id"]) != first_path
    assert len(_clean_files(media_dir)) == 1
    assert original.read_bytes() == original_bytes


def test_already_clean_file_is_marked_clean(
    client: TestClient, media_dir: Path
) -> None:
    project = create_project(client, "L4i4")
    clean = import_one(client, project["id"], "clean.png", make_image())["content"]

    response = _remove(client, clean["id"])

    assert response.json()["metadata_status"] == "clean"
    assert response.json()["publish_file"]["version"] == "original"
    assert _clean_files(media_dir) == []


def test_rejected_while_publishing(
    client: TestClient, content: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    account = create_account(client, content["project_id"], "telegram", "tg")
    publication = create_publications(client, content["id"], [account["id"]])[0]
    run_sql(
        db_path,
        "UPDATE publications SET status = 'publishing' WHERE id = ?",
        publication["id"],
    )

    response = _remove(client, content["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "content_publishing"
    assert _clean_files(media_dir) == []


def test_rejected_while_already_removing(
    client: TestClient, content: dict[str, Any]
) -> None:
    app = client.app
    assert isinstance(app, FastAPI)

    with app.state.content_file_guard.sanitizing(content["id"], lambda: None):
        response = _remove(client, content["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "metadata_removal_in_progress"


def test_video_needs_ffmpeg(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "L4i4")
    video = import_one(client, project["id"], "clip.mp4", make_mp4())["content"]
    monkeypatch.setattr(shutil, "which", lambda name: None)

    response = _remove(client, video["id"])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ffmpeg_required"
    assert "ffmpeg" in response.json()["error"]["message"]


def _assert_unchanged(
    client: TestClient, content: dict[str, Any], media_dir: Path
) -> None:
    assert client.get(f"/api/contents/{content['id']}").json()["metadata_status"] == (
        "unknown"
    )
    assert _clean_files(media_dir) == []
    assert list((media_dir / "tmp").iterdir()) == []


def test_sanitizer_failure_changes_nothing(
    client: TestClient,
    content: dict[str, Any],
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise InvalidMediaError

    monkeypatch.setattr(asset_library, "sanitize_image", broken)

    response = _remove(client, content["id"])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_media"
    _assert_unchanged(client, content, media_dir)


def test_database_failure_deletes_the_moved_copy(
    client: TestClient,
    content: dict[str, Any],
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(self: Session) -> None:
        raise OperationalError("COMMIT", {}, Exception("disk I/O error"))

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail)
        response = _remove(client, content["id"])

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "storage_error"
    _assert_unchanged(client, content, media_dir)


def test_start_up_sweeps_orphan_clean_copies(
    client: TestClient, content: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    _remove(client, content["id"])
    [referenced] = _clean_files(media_dir)
    project_dir = referenced.parent
    orphan = project_dir / "0123456789abcdef.clean.png"
    orphan.write_bytes(b"left by a crash")
    original = stored_file(media_dir, db_path, content["id"])

    app = create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
    )
    with TestClient(app):
        pass

    assert not orphan.exists()
    assert referenced.exists()
    assert original.exists()


def test_inspect_metadata_of_a_sanitized_content(
    client: TestClient, content: dict[str, Any]
) -> None:
    _remove(client, content["id"])

    response = client.get(f"/api/contents/{content['id']}/metadata")

    assert response.status_code == 200
    body = response.json()
    categories = {finding["category"] for finding in body["original"]["findings"]}
    assert {"comfyui", "ai_generation"} <= categories
    assert body["publish_copy"] == {"inspected": True, "reason": None, "findings": []}
    for sentinel in SENTINELS:
        assert sentinel.decode() not in response.text
