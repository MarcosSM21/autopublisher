import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import (
    create_account,
    create_project,
    import_one,
    make_image,
    make_mp4,
)


def test_projects_survive_restart(db_path: Path) -> None:
    with TestClient(create_app(db_path)) as client:
        create_project(client, "L4i4")
        create_project(client, "Cybersecurity", "Security content")
        before = client.get("/api/projects").json()

    with TestClient(create_app(db_path)) as client:
        after = client.get("/api/projects").json()

    assert len(after) == 2
    assert after == before


def test_accounts_keep_their_project_after_restart(db_path: Path) -> None:
    with TestClient(create_app(db_path)) as client:
        l4i4 = create_project(client, "L4i4")
        cyber = create_project(client, "Cybersecurity")
        for platform in ["instagram", "tiktok", "x"]:
            create_account(client, l4i4["id"], platform, "l4i4")
        for platform in ["youtube", "instagram", "tiktok"]:
            create_account(client, cyber["id"], platform, "cyber")
        before = {
            project["id"]: client.get(f"/api/projects/{project['id']}/accounts").json()
            for project in (l4i4, cyber)
        }

    with TestClient(create_app(db_path)) as client:
        after = {
            project_id: client.get(f"/api/projects/{project_id}/accounts").json()
            for project_id in before
        }

    assert after == before
    assert all(
        account["project_id"] == project_id
        for project_id, accounts in after.items()
        for account in accounts
    )
    assert sum(len(accounts) for accounts in after.values()) == 6


def test_contents_and_files_survive_restart(db_path: Path, media_dir: Path) -> None:
    image = make_image("PNG")
    video = make_mp4(payload=b"video-bytes")
    with TestClient(create_app(db_path, media_dir)) as client:
        project = create_project(client, "L4i4")
        ids = [
            import_one(client, project["id"], name, data)["content"]["id"]
            for name, data in [("photo.png", image), ("clip.mp4", video)]
        ]
        before = [client.get(f"/api/contents/{id_}").json() for id_ in ids]

    with TestClient(create_app(db_path, media_dir)) as client:
        after = [client.get(f"/api/contents/{id_}").json() for id_ in ids]
        served = {
            item["original_filename"]: client.get(item["file_url"]).content
            for item in after
        }

    assert after == before
    assert len(after) == 2
    assert all(item["project_id"] == project["id"] for item in after)
    assert (
        hashlib.sha256(served["photo.png"]).digest() == hashlib.sha256(image).digest()
    )
    assert served["clip.mp4"] == video


def test_edited_metadata_survives_restart(db_path: Path, media_dir: Path) -> None:
    with TestClient(create_app(db_path, media_dir)) as client:
        project = create_project(client, "L4i4")
        content = import_one(client, project["id"], "photo.png", make_image())[
            "content"
        ]
        edited = client.patch(
            f"/api/contents/{content['id']}",
            json={"title": "T", "description": "D", "hashtags": ["l4i4", "summer"]},
        ).json()

    with TestClient(create_app(db_path, media_dir)) as client:
        after = client.get(f"/api/contents/{content['id']}").json()

    assert after == edited
