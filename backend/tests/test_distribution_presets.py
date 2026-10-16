from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import (
    create_account,
    create_project,
    create_publications,
    setup_project,
)


def _presets(client: TestClient, project_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/distribution-presets")
    assert response.status_code == 200, response.text
    presets: list[dict[str, Any]] = response.json()
    return presets


def _create(client: TestClient, project_id: int, body: dict[str, Any]) -> Any:
    return client.post(f"/api/projects/{project_id}/distribution-presets", json=body)


def test_preset_lifecycle(client: TestClient) -> None:
    project, content, accounts = setup_project(client)
    a, b, c = (account["id"] for account in accounts)
    create_publications(client, content["id"], [a])
    accounts_before = client.get(f"/api/projects/{project['id']}/accounts").json()
    publications_before = client.get(
        f"/api/projects/{project['id']}/publications"
    ).json()

    response = _create(
        client, project["id"], {"name": "  Short video ", "account_ids": [c, a]}
    )
    assert response.status_code == 201, response.text
    preset = response.json()
    assert preset["name"] == "Short video"
    assert preset["account_ids"] == sorted([a, c])
    assert _presets(client, project["id"]) == [preset]

    response = client.patch(
        f"/api/distribution-presets/{preset['id']}",
        json={"name": "Shorts", "account_ids": [b]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Shorts"
    assert response.json()["account_ids"] == [b]

    response = client.delete(f"/api/distribution-presets/{preset['id']}")
    assert response.status_code == 204
    assert _presets(client, project["id"]) == []
    assert (
        client.patch(f"/api/distribution-presets/{preset['id']}", json={"name": "X"})
    ).status_code == 404
    # Presets never touch accounts or publications.
    assert (
        client.get(f"/api/projects/{project['id']}/accounts").json() == accounts_before
    )
    assert (
        client.get(f"/api/projects/{project['id']}/publications").json()
        == publications_before
    )


def test_preset_names_are_unique_per_project_ignoring_case(
    client: TestClient,
) -> None:
    project, _, accounts = setup_project(client)
    ids = [accounts[0]["id"]]
    assert _create(client, project["id"], {"name": "Shorts", "account_ids": ids})

    response = _create(client, project["id"], {"name": "SHORTS", "account_ids": ids})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate"
    assert [field["field"] for field in error["fields"]] == ["name"]
    assert len(_presets(client, project["id"])) == 1


def test_accounts_of_another_project_are_rejected(client: TestClient) -> None:
    project, _, accounts = setup_project(client)
    other = create_project(client, "Cybersecurity")
    foreign = create_account(client, other["id"], "instagram", "cyber")

    response = _create(
        client,
        project["id"],
        {"name": "Mixed", "account_ids": [accounts[0]["id"], foreign["id"]]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [
        {
            "field": "account_ids",
            "message": f"Account {foreign['id']} does not belong to this project.",
            "account_id": foreign["id"],
        }
    ]
    assert _presets(client, project["id"]) == []
