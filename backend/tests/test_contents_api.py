from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.db import database_url
from tests.conftest import (
    create_project,
    import_files,
    import_one,
    make_image,
    make_mov,
    make_mp4,
    make_webm,
)


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "L4i4")


@pytest.fixture
def content(client: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    result = import_one(client, project["id"], "photo.png", make_image())
    imported: dict[str, Any] = result["content"]
    return imported


# --- User Story 1: read a content and its file ----------------------------------


def test_get_content(client: TestClient, content: dict[str, Any]) -> None:
    response = client.get(f"/api/contents/{content['id']}")

    assert response.status_code == 200
    assert response.json() == content
    assert "storage_path" not in response.json()


def test_get_unknown_content(client: TestClient) -> None:
    response = client.get("/api/contents/9999")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Content not found.",
        "fields": [],
    }


@pytest.mark.parametrize(
    ("name", "data", "mime"),
    [
        ("photo.png", make_image("PNG"), "image/png"),
        ("photo.jpg", make_image("JPEG"), "image/jpeg"),
        ("photo.webp", make_image("WEBP"), "image/webp"),
        ("clip.mp4", make_mp4(), "video/mp4"),
        ("clip.mov", make_mov(), "video/quicktime"),
        ("clip.webm", make_webm(), "video/webm"),
    ],
)
def test_file_is_served_unchanged(
    client: TestClient, project: dict[str, Any], name: str, data: bytes, mime: str
) -> None:
    content = import_one(client, project["id"], name, data)["content"]

    response = client.get(content["file_url"])

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == mime


def test_file_supports_range_requests(
    client: TestClient, content: dict[str, Any]
) -> None:
    full = client.get(content["file_url"]).content

    response = client.get(content["file_url"], headers={"Range": "bytes=0-9"})

    assert response.status_code == 206
    assert response.content == full[:10]


def test_file_of_unknown_content(client: TestClient) -> None:
    response = client.get("/api/contents/9999/file")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_contents_cannot_be_deleted(
    client: TestClient, content: dict[str, Any]
) -> None:
    response = client.delete(f"/api/contents/{content['id']}")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert client.get(f"/api/contents/{content['id']}").status_code == 200


# --- User Story 4: library ---------------------------------------------------------


def test_list_contents_of_empty_project(
    client: TestClient, project: dict[str, Any]
) -> None:
    response = client.get(f"/api/projects/{project['id']}/contents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_contents_of_unknown_project(client: TestClient) -> None:
    response = client.get("/api/projects/9999/contents")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_contents_newest_first_and_only_own(
    client: TestClient, project: dict[str, Any]
) -> None:
    other = create_project(client, "Cybersecurity")
    first = import_one(client, project["id"], "a.png", make_image())["content"]
    import_one(client, other["id"], "other.png", make_image())
    second = import_one(client, project["id"], "b.mp4", make_mp4())["content"]

    listed = client.get(f"/api/projects/{project['id']}/contents").json()

    assert [item["id"] for item in listed] == [second["id"], first["id"]]
    assert all(item["project_id"] == project["id"] for item in listed)


def test_list_contents_of_inactive_project(
    client: TestClient, project: dict[str, Any], content: dict[str, Any]
) -> None:
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    listed = client.get(f"/api/projects/{project['id']}/contents").json()

    assert [item["id"] for item in listed] == [content["id"]]


def test_missing_file_is_reported(
    client: TestClient, content: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    engine = create_engine(database_url(db_path))
    with engine.connect() as connection:
        storage_path = connection.execute(
            text("SELECT storage_path FROM contents WHERE id = :id"),
            {"id": content["id"]},
        ).scalar_one()
    engine.dispose()
    (media_dir / storage_path).unlink()

    listed = client.get(f"/api/projects/{content['project_id']}/contents").json()
    response = client.get(content["file_url"])

    assert listed[0]["file_available"] is False
    assert client.get(f"/api/contents/{content['id']}").json()["file_available"] is (
        False
    )
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "The media file is not available.",
        "fields": [],
    }


def test_library_with_two_hundred_contents(
    client: TestClient, project: dict[str, Any]
) -> None:
    """Functional volume check (SC-007); real timing is checked in the quickstart."""
    for batch in range(2):
        files = [(f"{batch}-{i}.png", make_image(size=(1, 1))) for i in range(100)]
        body = import_files(client, project["id"], files).json()
        assert body["summary"]["imported"] == 100

    listed = client.get(f"/api/projects/{project['id']}/contents").json()

    assert len(listed) == 200
    assert all(item["file_available"] for item in listed)
    ids = [item["id"] for item in listed]
    assert ids == sorted(ids, reverse=True)


# --- User Story 5: metadata ----------------------------------------------------------


def patch(client: TestClient, content_id: int, body: Any) -> Any:
    return client.patch(f"/api/contents/{content_id}", json=body)


def test_edit_metadata(client: TestClient, content: dict[str, Any]) -> None:
    file_before = client.get(content["file_url"]).content

    response = patch(
        client,
        content["id"],
        {
            "title": "Summer teaser",
            "description": "First reel",
            "hashtags": ["l4i4", "summer"],
        },
    )

    assert response.status_code == 200
    edited = response.json()
    assert edited["title"] == "Summer teaser"
    assert edited["description"] == "First reel"
    assert edited["hashtags"] == ["l4i4", "summer"]
    assert edited["updated_at"] > content["updated_at"]
    assert edited["created_at"] == content["created_at"]
    assert edited["checksum"] == content["checksum"]
    assert client.get(content["file_url"]).content == file_before
    assert client.get(f"/api/contents/{content['id']}").json() == edited


def test_metadata_is_normalized(client: TestClient, content: dict[str, Any]) -> None:
    edited = patch(
        client,
        content["id"],
        {
            "title": "   ",
            "description": "  text  ",
            "hashtags": ["#L4i4", " summer ", "l4i4", "#Summer"],
        },
    ).json()

    assert edited["title"] is None
    assert edited["description"] == "text"
    assert edited["hashtags"] == ["L4i4", "summer"]


def test_null_hashtags_clear_the_list(
    client: TestClient, content: dict[str, Any]
) -> None:
    patch(client, content["id"], {"hashtags": ["a"]})

    edited = patch(client, content["id"], {"hashtags": None}).json()

    assert edited["hashtags"] == []


def test_values_can_be_cleared(client: TestClient, content: dict[str, Any]) -> None:
    patch(client, content["id"], {"title": "T", "description": "D", "hashtags": ["h"]})

    edited = patch(
        client, content["id"], {"title": "", "description": None, "hashtags": []}
    ).json()

    assert (edited["title"], edited["description"], edited["hashtags"]) == (
        None,
        None,
        [],
    )


def test_same_normalized_values_keep_updated_at(
    client: TestClient, content: dict[str, Any]
) -> None:
    first = patch(
        client, content["id"], {"title": "Same", "hashtags": ["l4i4", "summer"]}
    ).json()

    again = patch(
        client, content["id"], {"title": "  Same  ", "hashtags": ["#l4i4", "summer"]}
    ).json()

    assert again["updated_at"] == first["updated_at"]
    assert again == first


@pytest.mark.parametrize("hashtags", [["summer", "l4i4"], ["L4I4", "summer"]])
def test_hashtag_order_or_case_is_a_change(
    client: TestClient, content: dict[str, Any], hashtags: list[str]
) -> None:
    first = patch(client, content["id"], {"hashtags": ["l4i4", "summer"]}).json()

    edited = patch(client, content["id"], {"hashtags": hashtags}).json()

    assert edited["hashtags"] == hashtags
    assert edited["updated_at"] > first["updated_at"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"title": "x" * 201}, "title"),
        ({"description": "x" * 5001}, "description"),
        ({"hashtags": ["has space"]}, "hashtags"),
        ({"hashtags": ["#"]}, "hashtags"),
        ({"hashtags": ["x" * 101]}, "hashtags"),
        ({"hashtags": [f"tag{i}" for i in range(31)]}, "hashtags"),
        ({"hashtags": "l4i4"}, "hashtags"),
        ({"hashtags": [1]}, "hashtags"),
        ({"project_id": 2}, "project_id"),
        ({"checksum": "abc"}, "checksum"),
        ({"media_type": "video"}, "media_type"),
    ],
)
def test_invalid_metadata_is_rejected(
    client: TestClient, content: dict[str, Any], body: dict[str, Any], field: str
) -> None:
    response = patch(client, content["id"], body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert field in [item["field"] for item in error["fields"]]
    assert client.get(f"/api/contents/{content['id']}").json() == content


def test_hashtag_messages(client: TestClient, content: dict[str, Any]) -> None:
    def message(hashtags: Any) -> str:
        fields = patch(client, content["id"], {"hashtags": hashtags}).json()["error"][
            "fields"
        ]
        return str(fields[0]["message"])

    assert message(["a b"]) == "Hashtags cannot be empty or contain spaces."
    assert message(["x" * 101]) == "Each hashtag must be at most 100 characters."
    assert message([f"t{i}" for i in range(31)]) == "At most 30 hashtags are allowed."


def test_thirty_distinct_hashtags_after_dedupe_are_accepted(
    client: TestClient, content: dict[str, Any]
) -> None:
    hashtags = [f"tag{i}" for i in range(30)] + ["#TAG0"]

    edited = patch(client, content["id"], {"hashtags": hashtags}).json()

    assert len(edited["hashtags"]) == 30


def test_empty_patch_is_rejected(client: TestClient, content: dict[str, Any]) -> None:
    response = patch(client, content["id"], {})

    assert response.status_code == 422


def test_patch_unknown_content(client: TestClient) -> None:
    response = patch(client, 9999, {"title": "x"})

    assert response.status_code == 404


def test_patch_allowed_on_inactive_project(
    client: TestClient, project: dict[str, Any], content: dict[str, Any]
) -> None:
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = patch(client, content["id"], {"title": "Still editable"})

    assert response.status_code == 200
    assert response.json()["title"] == "Still editable"
