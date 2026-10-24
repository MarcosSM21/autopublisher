"""Move media between folders (Feature 021 T027/T030, US4).

One request moves one or many media to a folder or to Unsorted, all of them or
none. Only `contents.folder_id` changes: no file moves and no post changes, so it
is allowed while a post of the media is being published.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import readmodels
from tests.conftest import create_account, create_project
from tests.test_contents_import import content_rows
from tests.test_library_folders import (
    _files,
    import_into,
    listed_ids,
    move,
    new_folder,
    tree,
)


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


def _folders(db_path: Path) -> dict[int, int | None]:
    return {row["id"]: row["folder_id"] for row in content_rows(db_path)}


def test_move_one_media_to_a_folder_and_back_to_unsorted(
    client: TestClient, project: dict[str, Any]
) -> None:
    folder = new_folder(client, project["id"], "Lux")
    [media] = import_into(client, project["id"], None)

    response = move(client, project["id"], [media["id"]], folder["id"])

    assert response.status_code == 200
    assert response.json() == {"moved": 1}
    assert listed_ids(client, project["id"], folder["id"]) == {media["id"]}
    assert listed_ids(client, project["id"], "unsorted") == set()
    assert (
        client.get(f"/api/contents/{media['id']}").json()["folder_id"] == folder["id"]
    )

    assert move(client, project["id"], [media["id"]], None).json() == {"moved": 1}
    assert listed_ids(client, project["id"], "unsorted") == {media["id"]}
    assert tree(client, project["id"])["folders"][0]["media_count"] == 0


def test_move_several_media_at_once(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    source = new_folder(client, project["id"], "Inbox")
    target = new_folder(client, project["id"], "Lux")
    media = import_into(client, project["id"], None, 2) + import_into(
        client, project["id"], source["id"]
    )
    ids = [m["id"] for m in media]
    paths = {row["id"]: row["storage_path"] for row in content_rows(db_path)}
    files = _files(media_dir)

    response = move(client, project["id"], ids, target["id"])

    assert response.json() == {"moved": 3}
    assert listed_ids(client, project["id"], target["id"]) == set(ids)
    assert listed_ids(client, project["id"], source["id"]) == set()
    # Nothing moves on disk.
    assert {row["id"]: row["storage_path"] for row in content_rows(db_path)} == paths
    assert _files(media_dir) == files


@pytest.mark.parametrize("bad", ["foreign", "missing"])
def test_one_bad_media_id_moves_nothing(
    client: TestClient, project: dict[str, Any], db_path: Path, bad: str
) -> None:
    folder = new_folder(client, project["id"], "Lux")
    mine = import_into(client, project["id"], None, 2)
    other = create_project(client, "Other")
    [theirs] = import_into(client, other["id"], None)
    bad_id = theirs["id"] if bad == "foreign" else 999
    before = _folders(db_path)

    response = move(
        client, project["id"], [mine[0]["id"], bad_id, mine[1]["id"]], folder["id"]
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Media not found.",
        "fields": [],
    }
    assert _folders(db_path) == before


@pytest.mark.parametrize("bad", ["foreign", "missing"])
def test_a_bad_destination_moves_nothing(
    client: TestClient, project: dict[str, Any], db_path: Path, bad: str
) -> None:
    media = import_into(client, project["id"], None, 2)
    other = create_project(client, "Other")
    foreign = new_folder(client, other["id"], "Theirs")
    destination = foreign["id"] if bad == "foreign" else 999
    before = _folders(db_path)

    response = move(client, project["id"], [m["id"] for m in media], destination)

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Folder not found."
    assert _folders(db_path) == before


def test_a_missing_project_is_not_found(client: TestClient) -> None:
    assert move(client, 999, [1], None).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"content_ids": [], "folder_id": None},
        {"content_ids": [1, 1], "folder_id": None},
        {"content_ids": list(range(1, 502)), "folder_id": None},
        {"content_ids": [1]},  # the destination is always explicit
        {"content_ids": [1], "folder_id": None, "extra": 1},
    ],
    ids=["empty", "repeated", "too-many", "no-destination", "extra-field"],
)
def test_invalid_requests_are_rejected(
    client: TestClient, project: dict[str, Any], body: dict[str, Any]
) -> None:
    response = client.post(f"/api/projects/{project['id']}/contents/move", json=body)

    assert response.status_code == 422


def test_media_can_move_while_its_post_is_publishing(
    client: TestClient, project: dict[str, Any], db_path: Path
) -> None:
    folder = new_folder(client, project["id"], "Lux")
    [media] = import_into(client, project["id"], None)
    account = create_account(client, project["id"], "youtube", "cyber")
    now = datetime.now(UTC)
    post_id = readmodels.insert(
        db_path,
        "publications",
        project_id=project["id"],
        account_id=account["id"],
        content_id=media["id"],
        status="publishing",
        auto_publish_enabled=False,
        created_at=now,
        updated_at=now,
    )
    with sqlite3.connect(db_path) as connection:
        post_before = connection.execute(
            "SELECT * FROM publications WHERE id = ?", (post_id,)
        ).fetchone()

    response = move(client, project["id"], [media["id"]], folder["id"])

    assert response.json() == {"moved": 1}
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT * FROM publications WHERE id = ?", (post_id,)
            ).fetchone()
            == post_before
        )
    assert listed_ids(client, project["id"], folder["id"]) == {media["id"]}
