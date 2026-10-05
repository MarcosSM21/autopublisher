from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import create_account, create_project


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
