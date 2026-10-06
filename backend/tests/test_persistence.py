import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import (
    FUTURE,
    create_account,
    create_project,
    create_publications,
    import_one,
    make_image,
    make_mp4,
    setup_project,
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


def test_publications_survive_restart(db_path: Path, media_dir: Path) -> None:
    with TestClient(create_app(db_path, media_dir)) as client:
        project, content, accounts = setup_project(client)
        create_publications(client, content["id"], [accounts[0]["id"]], FUTURE)
        _, tiktok = create_publications(
            client, content["id"], [a["id"] for a in accounts[1:]]
        )
        client.patch(
            f"/api/publications/{tiktok['id']}",
            json={"description_override": "Custom", "hashtags_override": []},
        )
        before = client.get(f"/api/projects/{project['id']}/publications").json()

    with TestClient(create_app(db_path, media_dir)) as client:
        after = client.get(f"/api/projects/{project['id']}/publications").json()

    assert len(after) == 3
    assert after == before
    assert [p["status"] for p in after] == ["scheduled", "unscheduled", "unscheduled"]
    assert {p["content_id"] for p in after} == {content["id"]}
    assert [p["account_id"] for p in after] == [a["id"] for a in accounts]
    assert after[2]["description_override"] == "Custom"
    assert after[2]["hashtags_override"] == []
    assert after[1]["hashtags_override"] is None


def test_scheduled_at_keeps_the_same_utc_instant_after_restart(
    db_path: Path, media_dir: Path
) -> None:
    sent = "2100-03-15T18:45:00+02:00"
    with TestClient(create_app(db_path, media_dir)) as client:
        _, content, accounts = setup_project(client, ("instagram",))
        [publication] = create_publications(
            client, content["id"], [accounts[0]["id"]], sent
        )

    with TestClient(create_app(db_path, media_dir)) as client:
        stored = client.get(f"/api/publications/{publication['id']}").json()

    assert stored["scheduled_at"] == "2100-03-15T16:45:00Z"
    received = datetime.fromisoformat(stored["scheduled_at"])
    assert received == datetime.fromisoformat(sent)
    assert received.utcoffset() == timedelta(0)
