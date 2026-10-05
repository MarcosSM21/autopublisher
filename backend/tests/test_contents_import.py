import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import contents, media
from app.db import database_url
from app.storage import MediaStorage
from tests.conftest import (
    create_project,
    import_files,
    import_one,
    make_image,
    make_mov,
    make_mp4,
    make_webm,
)


def stored_files(media_dir: Path) -> list[Path]:
    return sorted(
        path for path in (media_dir / "projects").rglob("*") if path.is_file()
    )


def tmp_files(media_dir: Path) -> list[Path]:
    return list((media_dir / "tmp").iterdir())


def content_rows(db_path: Path) -> list[dict[str, Any]]:
    engine = create_engine(database_url(db_path))
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM contents ORDER BY id"))
        result = [dict(row._mapping) for row in rows]
    engine.dispose()
    return result


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "L4i4")


def assert_nothing_stored(db_path: Path, media_dir: Path) -> None:
    assert content_rows(db_path) == []
    assert stored_files(media_dir) == []
    assert tmp_files(media_dir) == []


# --- User Story 1: single imports -------------------------------------------------


def test_import_valid_image(
    client: TestClient, project: dict[str, Any], media_dir: Path
) -> None:
    data = make_image("PNG", size=(32, 20))

    response = import_files(client, project["id"], [("photo.png", data)])

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"imported": 1, "duplicates": 0, "rejected": 0}
    result = body["results"][0]
    assert result["status"] == "imported"
    assert result["filename"] == "photo.png"
    assert result["error"] is None
    content = result["content"]
    assert content["project_id"] == project["id"]
    assert content["media_type"] == "image"
    assert content["media_format"] == "png"
    assert (content["width"], content["height"]) == (32, 20)
    assert content["duration_seconds"] is None
    assert content["size_bytes"] == len(data)
    assert content["checksum"] == hashlib.sha256(data).hexdigest()
    assert content["original_filename"] == "photo.png"
    assert content["created_at"] == content["updated_at"]
    assert content["hashtags"] == []
    assert content["title"] is None
    assert content["description"] is None
    assert content["file_available"] is True
    assert "storage_path" not in content
    [stored] = stored_files(media_dir)
    assert stored.parent == media_dir / "projects" / str(project["id"])
    assert stored.suffix == ".png"
    assert stored.read_bytes() == data
    assert tmp_files(media_dir) == []


def test_import_valid_video_without_metadata(
    client: TestClient, project: dict[str, Any]
) -> None:
    result = import_one(client, project["id"], "clip.mp4", make_mp4())

    assert result["status"] == "imported"
    content = result["content"]
    assert content["media_type"] == "video"
    assert content["media_format"] == "mp4"
    assert content["width"] is None
    assert content["height"] is None
    assert content["duration_seconds"] is None


def test_import_video_stores_probed_metadata(
    client: TestClient, project: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        media, "probe_video", lambda path: media.VideoInfo(1080, 1920, 14.5)
    )

    content = import_one(client, project["id"], "reel.mov", make_mov())["content"]

    assert content["media_format"] == "mov"
    assert (content["width"], content["height"]) == (1080, 1920)
    assert content["duration_seconds"] == 14.5


def test_import_webm(client: TestClient, project: dict[str, Any]) -> None:
    content = import_one(client, project["id"], "clip.webm", make_webm())["content"]

    assert content["media_format"] == "webm"


def test_extension_case_and_mismatch_do_not_matter(
    client: TestClient, project: dict[str, Any], media_dir: Path
) -> None:
    jpeg = import_one(client, project["id"], "FOTO.JPG", make_image("JPEG"))
    png_named_jpg = import_one(client, project["id"], "photo.jpg", make_image("PNG"))

    assert jpeg["content"]["media_format"] == "jpeg"
    assert png_named_jpg["content"]["media_format"] == "png"
    assert png_named_jpg["content"]["original_filename"] == "photo.jpg"
    assert sorted(path.suffix for path in stored_files(media_dir)) == [".jpg", ".png"]


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("notes.txt", b"Some notes, not an image.", "unsupported_format"),
        ("fake.mp4", b"Plain text renamed to look like a video.", "unsupported_format"),
        ("fake.jpg", b"Plain text renamed to look like a photo.", "unsupported_format"),
        ("empty.jpg", b"", "empty_file"),
        ("broken.jpg", b"\xff\xd8\xff" + b"garbage" * 50, "invalid_file"),
    ],
)
def test_invalid_files_are_rejected_without_residue(
    client: TestClient,
    project: dict[str, Any],
    db_path: Path,
    media_dir: Path,
    name: str,
    data: bytes,
    code: str,
) -> None:
    result = import_one(client, project["id"], name, data)

    assert result["status"] == "rejected"
    assert result["content"] is None
    assert result["error"]["code"] == code
    assert result["error"]["message"]
    assert_nothing_stored(db_path, media_dir)


def test_unsupported_format_message_lists_formats(
    client: TestClient, project: dict[str, Any]
) -> None:
    result = import_one(client, project["id"], "notes.txt", b"text")

    assert result["error"]["message"] == (
        "Unsupported file format. Supported: JPEG, PNG, WebP, MP4, MOV, WebM."
    )


def test_unknown_project_is_rejected(
    client: TestClient, db_path: Path, media_dir: Path
) -> None:
    response = import_files(client, 9999, [("photo.png", make_image())])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert_nothing_stored(db_path, media_dir)


def test_inactive_project_is_rejected(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = import_files(client, project["id"], [("photo.png", make_image())])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_inactive"
    assert_nothing_stored(db_path, media_dir)


def test_original_file_is_untouched(
    client: TestClient, project: dict[str, Any], tmp_path: Path
) -> None:
    original = tmp_path / "originals" / "photo.png"
    original.parent.mkdir()
    original.write_bytes(make_image())
    checksum = hashlib.sha256(original.read_bytes()).hexdigest()
    mtime = os.stat(original).st_mtime_ns

    with original.open("rb") as handle:
        response = client.post(
            f"/api/projects/{project['id']}/contents",
            files=[("files", ("photo.png", handle))],
        )

    assert response.json()["results"][0]["status"] == "imported"
    assert original.exists()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == checksum
    assert os.stat(original).st_mtime_ns == mtime


def test_original_filename_is_never_used_as_a_path(
    client: TestClient, project: dict[str, Any], media_dir: Path, tmp_path: Path
) -> None:
    result = import_one(client, project["id"], "../../evil.png", make_image())

    assert result["filename"] == "evil.png"
    assert result["content"]["original_filename"] == "evil.png"
    [stored] = stored_files(media_dir)
    assert stored.parent == media_dir / "projects" / str(project["id"])
    assert stored.name != "evil.png"
    assert not (tmp_path / "evil.png").exists()


def test_long_original_filename_is_truncated(
    client: TestClient, project: dict[str, Any]
) -> None:
    name = "a" * 300 + ".png"

    content = import_one(client, project["id"], name, make_image())["content"]

    assert len(content["original_filename"]) == 255
    assert content["original_filename"].endswith(".png")


def test_storage_error_leaves_no_residue(
    client: TestClient,
    project: dict[str, Any],
    db_path: Path,
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_commit(self: MediaStorage, temp_path: Path, relative: str) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(MediaStorage, "commit", broken_commit)

    result = import_one(client, project["id"], "photo.png", make_image())

    assert result["status"] == "rejected"
    assert result["error"]["code"] == "storage_error"
    assert "disk" not in result["error"]["message"]
    assert_nothing_stored(db_path, media_dir)


@pytest.fixture
def failing_db_commit(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original_commit = Session.commit
    calls = {"failed": False}

    def commit(self: Session) -> None:
        if not calls["failed"]:
            calls["failed"] = True
            raise OperationalError("COMMIT", {}, Exception("database is locked"))
        original_commit(self)

    monkeypatch.setattr(Session, "commit", commit)
    yield


def test_database_failure_after_move_removes_final_file(
    client: TestClient,
    project: dict[str, Any],
    db_path: Path,
    media_dir: Path,
    failing_db_commit: None,
) -> None:
    result = import_one(client, project["id"], "photo.png", make_image())

    assert result["status"] == "rejected"
    assert result["error"]["code"] == "storage_error"
    assert_nothing_stored(db_path, media_dir)


# --- User Story 2: batches ---------------------------------------------------------


def test_import_several_files_in_one_request(
    client: TestClient, project: dict[str, Any]
) -> None:
    files = [
        ("a.png", make_image("PNG")),
        ("b.jpg", make_image("JPEG")),
        ("c.mp4", make_mp4()),
    ]

    response = import_files(client, project["id"], files)

    body = response.json()
    assert [result["filename"] for result in body["results"]] == [
        "a.png",
        "b.jpg",
        "c.mp4",
    ]
    assert all(result["status"] == "imported" for result in body["results"])
    assert body["summary"] == {"imported": 3, "duplicates": 0, "rejected": 0}


def test_mixed_batch_keeps_valid_files(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    files = [
        ("a.png", make_image("PNG")),
        ("notes.txt", b"not media"),
        ("empty.jpg", b""),
        ("clip.webm", make_webm()),
        ("broken.jpg", b"\xff\xd8\xff" + b"garbage" * 50),
    ]

    body = import_files(client, project["id"], files).json()

    assert [(r["filename"], r["status"]) for r in body["results"]] == [
        ("a.png", "imported"),
        ("notes.txt", "rejected"),
        ("empty.jpg", "rejected"),
        ("clip.webm", "imported"),
        ("broken.jpg", "rejected"),
    ]
    assert [r["error"]["code"] for r in body["results"] if r["error"]] == [
        "unsupported_format",
        "empty_file",
        "invalid_file",
    ]
    assert body["summary"] == {"imported": 2, "duplicates": 0, "rejected": 3}
    assert len(content_rows(db_path)) == 2
    assert len(stored_files(media_dir)) == 2
    assert tmp_files(media_dir) == []


def test_storage_failure_only_affects_one_file(
    client: TestClient,
    project: dict[str, Any],
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_commit = MediaStorage.commit
    calls = {"count": 0}

    def flaky_commit(self: MediaStorage, temp_path: Path, relative: str) -> Path:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("disk error")
        return original_commit(self, temp_path, relative)

    monkeypatch.setattr(MediaStorage, "commit", flaky_commit)
    files = [(f"{i}.png", make_image()) for i in range(3)]

    body = import_files(client, project["id"], files).json()

    assert [r["status"] for r in body["results"]] == [
        "imported",
        "rejected",
        "imported",
    ]
    assert body["results"][1]["error"]["code"] == "storage_error"
    assert len(stored_files(media_dir)) == 2
    assert tmp_files(media_dir) == []


def test_request_without_files_is_rejected(
    client: TestClient, project: dict[str, Any]
) -> None:
    response = client.post(f"/api/projects/{project['id']}/contents")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert [field["field"] for field in error["fields"]] == ["files"]


def test_too_many_files_are_rejected_as_a_whole(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    files = [(f"{i}.png", make_image(size=(1, 1))) for i in range(101)]

    response = import_files(client, project["id"], files)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["fields"] == [
        {"field": "files", "message": "At most 100 files can be imported at once."}
    ]
    assert_nothing_stored(db_path, media_dir)


def test_one_hundred_files_are_accepted(
    client: TestClient, project: dict[str, Any]
) -> None:
    files = [(f"{i}.png", make_image(size=(1, 1))) for i in range(100)]

    body = import_files(client, project["id"], files).json()

    assert body["summary"] == {"imported": 100, "duplicates": 0, "rejected": 0}


# --- User Story 3: duplicates -------------------------------------------------------


def test_reimporting_the_same_file_is_a_duplicate(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    data = make_image()
    original = import_one(client, project["id"], "photo.png", data)["content"]

    result = import_one(client, project["id"], "photo.png", data)

    assert result["status"] == "duplicate"
    assert result["content"] is None
    assert result["error"] is None
    assert result["existing_content"]["id"] == original["id"]
    assert len(content_rows(db_path)) == 1
    assert len(stored_files(media_dir)) == 1
    assert tmp_files(media_dir) == []


def test_renamed_copy_is_a_duplicate(
    client: TestClient, project: dict[str, Any]
) -> None:
    data = make_image()
    original = import_one(client, project["id"], "photo.png", data)["content"]

    result = import_one(client, project["id"], "renamed-copy.png", data)

    assert result["status"] == "duplicate"
    assert result["existing_content"]["id"] == original["id"]


def test_duplicate_within_the_same_batch(
    client: TestClient, project: dict[str, Any], db_path: Path
) -> None:
    data = make_image()

    body = import_files(
        client, project["id"], [("a.png", data), ("b.png", data)]
    ).json()

    first, second = body["results"]
    assert first["status"] == "imported"
    assert second["status"] == "duplicate"
    assert second["existing_content"]["id"] == first["content"]["id"]
    assert body["summary"] == {"imported": 1, "duplicates": 1, "rejected": 0}
    assert len(content_rows(db_path)) == 1


def test_same_file_in_another_project_is_imported(
    client: TestClient, project: dict[str, Any]
) -> None:
    other = create_project(client, "Cybersecurity")
    data = make_image()
    import_one(client, project["id"], "photo.png", data)

    result = import_one(client, other["id"], "photo.png", data)

    assert result["status"] == "imported"
    assert result["content"]["project_id"] == other["id"]


def test_different_files_with_the_same_name_are_both_imported(
    client: TestClient, project: dict[str, Any]
) -> None:
    first = import_one(client, project["id"], "photo.png", make_image())
    second = import_one(client, project["id"], "photo.png", make_image())

    assert first["status"] == second["status"] == "imported"
    assert first["content"]["id"] != second["content"]["id"]


def test_unique_constraint_still_reports_a_duplicate(
    client: TestClient,
    project: dict[str, Any],
    db_path: Path,
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = make_image()
    original = import_one(client, project["id"], "photo.png", data)["content"]
    # Simulate a concurrent import that the pre-check could not see yet.
    real_find_duplicate = contents.find_duplicate
    calls = {"count": 0}

    def find_duplicate(*args: Any) -> Any:
        calls["count"] += 1
        return None if calls["count"] == 1 else real_find_duplicate(*args)

    monkeypatch.setattr(contents, "find_duplicate", find_duplicate)

    result = import_one(client, project["id"], "copy.png", data)

    assert result["status"] == "duplicate"
    assert result["existing_content"]["id"] == original["id"]
    assert len(content_rows(db_path)) == 1
    assert len(stored_files(media_dir)) == 1
    assert tmp_files(media_dir) == []
