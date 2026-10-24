"""Library folders (Feature 021 T025–T029, US3/US5, research §12–§14).

Folders are logical only: creating, renaming or deleting one never moves, copies or
deletes a file, a media item or a post. "Unsorted" and "All media" are views, not
rows. Races with an import are forced from inside the import (a patched step),
never with `sleep`.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import contents, deletion
from app.content_files import ContentFileGuard
from app.schemas import DeletionKind
from tests.conftest import (
    create_account,
    create_project,
    import_files,
    make_image,
    run_sql,
)
from tests.test_contents_import import content_rows, stored_files, tmp_files
from tests.test_delete_media import media_post
from tests.test_delete_post import CHANGED, count

NAME_TAKEN = "A folder with this name already exists here."
TOO_DEEP = "Folders can be nested up to 5 levels."


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


def post_folder(
    client: TestClient, project_id: int, name: str, parent_id: int | None = None
) -> Any:
    return client.post(
        f"/api/projects/{project_id}/library-folders",
        json={"name": name, "parent_id": parent_id},
    )


def new_folder(
    client: TestClient, project_id: int, name: str, parent_id: int | None = None
) -> dict[str, Any]:
    response = post_folder(client, project_id, name, parent_id)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def tree(client: TestClient, project_id: int) -> dict[str, Any]:
    response = client.get(f"/api/projects/{project_id}/library-folders")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def import_into(
    client: TestClient, project_id: int, folder_id: int | None, n: int = 1
) -> list[dict[str, Any]]:
    params = {"folder_id": folder_id} if folder_id is not None else {}
    response = client.post(
        f"/api/projects/{project_id}/contents",
        params=params,
        files=[("files", (f"m{i}.png", make_image())) for i in range(n)],
    )
    assert response.status_code == 200, response.text
    return [item["content"] for item in response.json()["results"]]


def listed(client: TestClient, project_id: int, folder: str | int | None) -> Any:
    params = {"folder": folder} if folder is not None else {}
    return client.get(f"/api/projects/{project_id}/contents", params=params)


def listed_ids(
    client: TestClient, project_id: int, folder: str | int | None
) -> set[int]:
    response = listed(client, project_id, folder)
    assert response.status_code == 200, response.text
    return {content["id"] for content in response.json()}


def preview(client: TestClient, folder_id: int) -> dict[str, Any]:
    response = client.get(f"/api/library-folders/{folder_id}/deletion-preview")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def delete(client: TestClient, folder_id: int, confirmation: str) -> Any:
    return client.delete(
        f"/api/library-folders/{folder_id}", params={"confirmation": confirmation}
    )


def move(
    client: TestClient, project_id: int, ids: list[int], folder_id: int | None
) -> Any:
    return client.post(
        f"/api/projects/{project_id}/contents/move",
        json={"content_ids": ids, "folder_id": folder_id},
    )


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _files(media_dir: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in stored_files(media_dir)}


# --- Hierarchy and names ------------------------------------------------------------


def test_root_and_child_folders(client: TestClient, project: dict[str, Any]) -> None:
    root = new_folder(client, project["id"], "  Cybersecurity  ")
    child = new_folder(client, project["id"], "DDoS", root["id"])

    assert (root["name"], root["parent_id"], root["depth"]) == (
        "Cybersecurity",
        None,
        1,
    )
    assert (child["parent_id"], child["depth"], child["media_count"]) == (
        root["id"],
        2,
        0,
    )
    assert child["project_id"] == project["id"]
    assert tree(client, project["id"]) == {
        "folders": [
            {
                "id": root["id"],
                "parent_id": None,
                "name": "Cybersecurity",
                "depth": 1,
                "media_count": 0,
            },
            {
                "id": child["id"],
                "parent_id": root["id"],
                "name": "DDoS",
                "depth": 2,
                "media_count": 0,
            },
        ],
        "unsorted_count": 0,
        "total_count": 0,
    }


def test_depth_five_is_the_limit(
    client: TestClient, project: dict[str, Any], db_path: Path
) -> None:
    parent_id = None
    for level in range(1, 6):
        folder = new_folder(client, project["id"], f"Level {level}", parent_id)
        assert folder["depth"] == level
        parent_id = folder["id"]

    response = post_folder(client, project["id"], "Level 6", parent_id)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "folder_too_deep",
        "message": TOO_DEEP,
        "fields": [],
    }
    assert count(db_path, "library_folders") == 5


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Lux", "lux"),
        ("Lux", "LUX"),
        ("Straße", "STRASSE"),  # casefold
        ("Lux", "Ｌｕｘ"),  # fullwidth letters (NFKC)
        ("ﬁles", "files"),  # ligature (NFKC)
    ],
)
@pytest.mark.parametrize("nested", [False, True], ids=["root", "child"])
def test_sibling_names_are_unique_ignoring_case_and_unicode_forms(
    client: TestClient, project: dict[str, Any], first: str, second: str, nested: bool
) -> None:
    parent_id = new_folder(client, project["id"], "Parent")["id"] if nested else None
    new_folder(client, project["id"], first, parent_id)

    response = post_folder(client, project["id"], second, parent_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "folder_name_taken"
    assert response.json()["error"]["message"] == NAME_TAKEN
    assert "UNIQUE" not in response.text


def test_same_name_under_different_parents_or_projects_is_allowed(
    client: TestClient, project: dict[str, Any]
) -> None:
    first = new_folder(client, project["id"], "Cyber")
    second = new_folder(client, project["id"], "Infra")
    other = create_project(client, "Other")

    new_folder(client, project["id"], "Lux")
    new_folder(client, project["id"], "Lux", first["id"])
    new_folder(client, project["id"], "Lux", second["id"])
    new_folder(client, other["id"], "Lux")

    names = [f["name"] for f in tree(client, project["id"])["folders"]]
    assert names.count("Lux") == 3


@pytest.mark.parametrize("name", ["Unsorted", "All media", "unsorted"])
def test_virtual_entry_names_are_ordinary_folder_names(
    client: TestClient, project: dict[str, Any], name: str
) -> None:
    folder = new_folder(client, project["id"], name)
    [content] = import_into(client, project["id"], folder["id"])

    assert listed_ids(client, project["id"], folder["id"]) == {content["id"]}
    assert listed_ids(client, project["id"], "unsorted") == set()
    listing = tree(client, project["id"])
    assert listing["unsorted_count"] == 0
    assert listing["total_count"] == 1


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_invalid_names_are_rejected(
    client: TestClient, project: dict[str, Any], db_path: Path, name: str
) -> None:
    response = post_folder(client, project["id"], name)

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "name"
    assert count(db_path, "library_folders") == 0


def test_folders_can_be_created_in_an_inactive_project(
    client: TestClient, project: dict[str, Any]
) -> None:
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    assert post_folder(client, project["id"], "Archive").status_code == 201


def test_rename_changes_only_the_name(
    client: TestClient, project: dict[str, Any], media_dir: Path
) -> None:
    parent = new_folder(client, project["id"], "Cyber")
    folder = new_folder(client, project["id"], "Lux", parent["id"])
    new_folder(client, project["id"], "MFA", parent["id"])
    [content] = import_into(client, project["id"], folder["id"])
    files = _files(media_dir)

    same_key = client.patch(
        f"/api/library-folders/{folder['id']}", json={"name": "LUX"}
    )
    taken = client.patch(f"/api/library-folders/{folder['id']}", json={"name": "mfa"})
    renamed = client.patch(
        f"/api/library-folders/{folder['id']}", json={"name": " Phishing "}
    )

    assert same_key.status_code == 200
    assert same_key.json()["name"] == "LUX"
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "folder_name_taken"
    assert renamed.status_code == 200
    body = renamed.json()
    assert (body["name"], body["parent_id"], body["depth"], body["media_count"]) == (
        "Phishing",
        parent["id"],
        2,
        1,
    )
    assert [f["name"] for f in tree(client, project["id"])["folders"]] == [
        "Cyber",
        "MFA",
        "Phishing",
    ]
    assert listed_ids(client, project["id"], folder["id"]) == {content["id"]}
    assert _files(media_dir) == files
    # The freed name can be used again.
    assert post_folder(client, project["id"], "Lux", parent["id"]).status_code == 201


def test_rename_of_a_missing_folder_is_not_found(client: TestClient) -> None:
    response = client.patch("/api/library-folders/999", json={"name": "X"})

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Folder not found."


# --- Isolation between projects -----------------------------------------------------


def test_other_projects_folders_are_not_found(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    other = create_project(client, "Other")
    foreign = new_folder(client, other["id"], "Theirs")

    as_parent = post_folder(client, project["id"], "Mine", foreign["id"])
    as_view = listed(client, project["id"], foreign["id"])
    as_upload = client.post(
        f"/api/projects/{project['id']}/contents",
        params={"folder_id": foreign["id"]},
        files=[("files", ("a.png", make_image()))],
    )

    for response in (as_parent, as_view, as_upload):
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "not_found",
            "message": "Folder not found.",
            "fields": [],
        }
    assert count(db_path, "library_folders") == 1
    assert content_rows(db_path) == []
    assert stored_files(media_dir) == []


def test_missing_project_and_folder_are_not_found(
    client: TestClient, project: dict[str, Any]
) -> None:
    assert client.get("/api/projects/999/library-folders").status_code == 404
    assert post_folder(client, 999, "X").status_code == 404
    assert post_folder(client, project["id"], "X", 999).status_code == 404
    assert listed(client, project["id"], 999).status_code == 404
    assert client.get("/api/library-folders/999/deletion-preview").status_code == 404
    assert delete(client, 999, "v1:x").status_code == 404


@pytest.mark.parametrize("value", ["all", "0", "-1", "1.5", ""])
def test_unknown_view_is_invalid(
    client: TestClient, project: dict[str, Any], value: str
) -> None:
    assert listed(client, project["id"], value).status_code == 422


# --- Views ------------------------------------------------------------------------


def test_views_and_counts(client: TestClient, project: dict[str, Any]) -> None:
    parent = new_folder(client, project["id"], "Cyber")
    child = new_folder(client, project["id"], "DDoS", parent["id"])
    unsorted = import_into(client, project["id"], None)
    in_parent = import_into(client, project["id"], parent["id"], 2)
    in_child = import_into(client, project["id"], child["id"])
    every = {c["id"] for c in unsorted + in_parent + in_child}

    assert listed_ids(client, project["id"], None) == every
    assert listed_ids(client, project["id"], "unsorted") == {unsorted[0]["id"]}
    # A folder shows its own media only, never those of its subfolders.
    assert listed_ids(client, project["id"], parent["id"]) == {
        c["id"] for c in in_parent
    }
    assert listed_ids(client, project["id"], child["id"]) == {in_child[0]["id"]}
    folder_of = {
        c["id"]: c["folder_id"] for c in listed(client, project["id"], None).json()
    }
    assert folder_of[in_child[0]["id"]] == child["id"]
    assert folder_of[unsorted[0]["id"]] is None

    listing = tree(client, project["id"])
    assert [(f["name"], f["media_count"]) for f in listing["folders"]] == [
        ("Cyber", 2),
        ("DDoS", 1),
    ]
    assert (listing["unsorted_count"], listing["total_count"]) == (1, 4)


def test_views_keep_the_current_order(
    client: TestClient, project: dict[str, Any]
) -> None:
    folder = new_folder(client, project["id"], "Cyber")
    first, second = import_into(client, project["id"], folder["id"], 2)

    ids = [c["id"] for c in listed(client, project["id"], folder["id"]).json()]

    assert ids == [second["id"], first["id"]]  # newest first, as All media


# --- Upload into a folder -----------------------------------------------------------


def test_upload_goes_to_the_current_folder_without_moving_files(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    folder = new_folder(client, project["id"], "Cyber")

    [inside] = import_into(client, project["id"], folder["id"])
    [outside] = import_into(client, project["id"], None)

    assert inside["folder_id"] == folder["id"]
    assert outside["folder_id"] is None
    paths = {row["storage_path"] for row in content_rows(db_path)}
    # The folder never appears on disk: every file stays under projects/{id}/.
    assert all(path.startswith(f"projects/{project['id']}/") for path in paths)
    assert all("Cyber" not in path for path in paths)
    assert len(stored_files(media_dir)) == 2


def test_a_duplicate_is_not_moved_by_an_upload(
    client: TestClient, project: dict[str, Any]
) -> None:
    folder = new_folder(client, project["id"], "Cyber")
    data = make_image()
    response = import_files(client, project["id"], [("a.png", data)])
    original = response.json()["results"][0]["content"]

    again = client.post(
        f"/api/projects/{project['id']}/contents",
        params={"folder_id": folder["id"]},
        files=[("files", ("a.png", data))],
    ).json()["results"][0]

    assert again["status"] == "duplicate"
    assert again["existing_content"]["id"] == original["id"]
    assert again["existing_content"]["folder_id"] is None


def _context(client: TestClient) -> deletion.DeletionContext:
    state = _app(client).state
    return deletion.DeletionContext(
        session_factory=state.session_factory,
        file_guard=state.content_file_guard,
        storage=state.storage,
        credential_targets=state.credential_targets,
        probe_status=lambda: "available",
        invalidate_attempts=lambda account_id: None,
    )


def _delete_now(client: TestClient, kind: DeletionKind, target: int) -> None:
    """A real delete, run from inside the import (between two of its files)."""
    state = _app(client).state
    guard: ContentFileGuard = state.content_file_guard
    with state.session_factory() as session:
        token = deletion.preview(session, kind, target, guard).confirmation
    deletion.execute(_context(client), kind, target, token)


def _on_file(monkeypatch: pytest.MonkeyPatch, number: int, action: Any) -> None:
    """Run `action` when the import reads the header of its `number`-th file, i.e.
    after the request was validated and before that file's row is written."""
    real = contents._read_header
    calls = {"n": 0}

    def read_header(path: Path) -> bytes:
        calls["n"] += 1
        if calls["n"] == number:
            action()
        return real(path)

    monkeypatch.setattr(contents, "_read_header", read_header)


def test_folder_deleted_during_a_multi_file_import_sends_the_rest_to_unsorted(
    client: TestClient,
    project: dict[str, Any],
    db_path: Path,
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = new_folder(client, project["id"], "Cyber")
    _on_file(monkeypatch, 2, lambda: _delete_now(client, "folder", folder["id"]))

    response = client.post(
        f"/api/projects/{project['id']}/contents",
        params={"folder_id": folder["id"]},
        files=[("files", (f"m{i}.png", make_image())) for i in range(3)],
    )

    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [r["status"] for r in results] == ["imported"] * 3
    assert [r["content"]["folder_id"] for r in results] == [folder["id"], None, None]
    # Every media is now in Unsorted (the first one was moved by the delete).
    assert {row["folder_id"] for row in content_rows(db_path)} == {None}
    assert len(stored_files(media_dir)) == 3
    assert tmp_files(media_dir) == []


@pytest.mark.parametrize("number", [1, 2], ids=["first-file", "second-file"])
def test_project_deleted_during_an_import_leaves_no_file(
    client: TestClient,
    project: dict[str, Any],
    db_path: Path,
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    number: int,
) -> None:
    _on_file(monkeypatch, number, lambda: _delete_now(client, "project", project["id"]))

    response = client.post(
        f"/api/projects/{project['id']}/contents",
        files=[("files", (f"m{i}.png", make_image())) for i in range(3)],
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Project not found."
    assert content_rows(db_path) == []
    assert stored_files(media_dir) == []
    assert tmp_files(media_dir) == []
    assert count(db_path, "pending_file_deletions") == 0


def test_project_deleted_after_validation_never_leaks_an_integrity_error(
    client: TestClient,
    project: dict[str, Any],
    db_path: Path,
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plain-SQL form of the race: the row disappears behind the API."""
    _on_file(
        monkeypatch,
        1,
        lambda: run_sql(db_path, "DELETE FROM projects WHERE id = ?", project["id"]),
    )

    response = import_files(client, project["id"], [("a.png", make_image())])

    assert response.status_code == 404
    assert "IntegrityError" not in response.text
    assert stored_files(media_dir) == []
    assert tmp_files(media_dir) == []


# --- Delete a folder ----------------------------------------------------------------


def _posts(db_path: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT id, content_id, status, updated_at FROM publications ORDER BY id"
        ).fetchall()


def test_delete_folder_moves_its_subtree_media_to_unsorted(
    client: TestClient, project: dict[str, Any], db_path: Path, media_dir: Path
) -> None:
    folder = new_folder(client, project["id"], "Cybersecurity")
    sub = new_folder(client, project["id"], "DDoS", folder["id"])
    sibling = new_folder(client, project["id"], "Infra")
    direct = import_into(client, project["id"], folder["id"], 5)
    nested = import_into(client, project["id"], sub["id"], 3)
    [kept] = import_into(client, project["id"], sibling["id"])
    account = create_account(client, project["id"], "youtube", "cyber")
    media_post(db_path, account, direct[0]["id"], datetime.now(UTC))
    media_post(db_path, account, nested[0]["id"], datetime.now(UTC), status="published")
    posts, files = _posts(db_path), _files(media_dir)

    body = preview(client, folder["id"])

    assert body["kind"] == "folder"
    assert body["name"] == "Cybersecurity"
    assert body["summary"] == [
        "1 subfolder will also be removed.",
        "8 media items will move to Unsorted.",
        "No media is deleted.",
    ]
    assert body["counts"] == {
        "unpublished_posts": 0,
        "remote_posts": 0,
        "needs_review_posts": 0,
        "accounts": 0,
        "posts": 0,
        "media": 0,
        "subfolders": 1,
        "media_to_unsorted": 8,
    }
    assert body["blocker"] is None

    assert delete(client, folder["id"], body["confirmation"]).status_code == 204

    moved = {c["id"] for c in direct + nested}
    assert listed_ids(client, project["id"], "unsorted") == moved
    assert listed_ids(client, project["id"], None) == moved | {kept["id"]}
    assert listed_ids(client, project["id"], sibling["id"]) == {kept["id"]}
    assert count(db_path, "contents") == 9
    assert _posts(db_path) == posts
    assert _files(media_dir) == files
    assert count(db_path, "pending_file_deletions") == 0
    assert tree(client, project["id"])["folders"] == [
        {
            "id": sibling["id"],
            "parent_id": None,
            "name": "Infra",
            "depth": 1,
            "media_count": 1,
        }
    ]
    for gone in (folder["id"], sub["id"]):
        assert listed(client, project["id"], gone).status_code == 404
        assert (
            client.get(f"/api/library-folders/{gone}/deletion-preview").status_code
            == 404
        )
        assert (
            client.patch(f"/api/library-folders/{gone}", json={"name": "X"}).status_code
            == 404
        )
    assert delete(client, folder["id"], body["confirmation"]).status_code == 404


def test_delete_covers_the_whole_depth_and_stays_in_its_project(
    client: TestClient, project: dict[str, Any], db_path: Path
) -> None:
    parent_id = None
    chain = []
    for level in range(1, 6):
        parent_id = new_folder(client, project["id"], f"L{level}", parent_id)["id"]
        chain.append(parent_id)
    [deepest] = import_into(client, project["id"], chain[-1])
    other = create_project(client, "Other")
    theirs = new_folder(client, other["id"], "L1")
    [their_media] = import_into(client, other["id"], theirs["id"])

    body = preview(client, chain[0])
    assert body["counts"]["subfolders"] == 4
    assert body["summary"] == [
        "4 subfolders will also be removed.",
        "1 media item will move to Unsorted.",
        "No media is deleted.",
    ]
    assert delete(client, chain[0], body["confirmation"]).status_code == 204

    assert tree(client, project["id"])["folders"] == []
    assert listed_ids(client, project["id"], "unsorted") == {deepest["id"]}
    assert listed_ids(client, other["id"], theirs["id"]) == {their_media["id"]}


def test_empty_folder_has_a_plain_confirmation(
    client: TestClient, project: dict[str, Any]
) -> None:
    folder = new_folder(client, project["id"], "Empty")

    body = preview(client, folder["id"])

    assert body["summary"] == []
    assert body["counts"]["subfolders"] == body["counts"]["media_to_unsorted"] == 0
    assert delete(client, folder["id"], body["confirmation"]).status_code == 204


def test_subfolders_without_media_still_say_no_media_is_deleted(
    client: TestClient, project: dict[str, Any]
) -> None:
    folder = new_folder(client, project["id"], "Cyber")
    new_folder(client, project["id"], "A", folder["id"])
    new_folder(client, project["id"], "B", folder["id"])

    assert preview(client, folder["id"])["summary"] == [
        "2 subfolders will also be removed.",
        "No media is deleted.",
    ]


def test_folder_ids_are_never_reused(
    client: TestClient, project: dict[str, Any]
) -> None:
    first = new_folder(client, project["id"], "Cyber")
    delete(client, first["id"], preview(client, first["id"])["confirmation"])

    again = new_folder(client, project["id"], "Cyber")

    assert again["id"] > first["id"]


@pytest.mark.parametrize("change", ["new-subfolder", "media-in", "media-out"])
def test_a_changed_subtree_rejects_the_delete(
    client: TestClient, project: dict[str, Any], db_path: Path, change: str
) -> None:
    folder = new_folder(client, project["id"], "Cyber")
    sub = new_folder(client, project["id"], "DDoS", folder["id"])
    [inside] = import_into(client, project["id"], sub["id"])
    [outside] = import_into(client, project["id"], None)
    token = preview(client, folder["id"])["confirmation"]

    if change == "new-subfolder":
        new_folder(client, project["id"], "Botnets", sub["id"])
    elif change == "media-in":
        assert (
            move(client, project["id"], [outside["id"]], sub["id"]).status_code == 200
        )
    else:
        assert move(client, project["id"], [inside["id"]], None).status_code == 200
    folders, assignments = count(db_path, "library_folders"), content_rows(db_path)

    response = delete(client, folder["id"], token)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "deletion_changed",
        "message": CHANGED,
        "fields": [],
    }
    assert count(db_path, "library_folders") == folders
    assert content_rows(db_path) == assignments
    assert preview(client, folder["id"])["confirmation"] != token


def test_token_ignores_names(client: TestClient, project: dict[str, Any]) -> None:
    folder = new_folder(client, project["id"], "Cyber")
    token = preview(client, folder["id"])["confirmation"]

    client.patch(f"/api/library-folders/{folder['id']}", json={"name": "Security"})

    assert preview(client, folder["id"])["confirmation"] == token
    assert delete(client, folder["id"], token).status_code == 204
