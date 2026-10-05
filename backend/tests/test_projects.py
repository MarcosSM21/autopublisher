from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_project


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def field_errors(response_json: dict[str, object]) -> dict[str, str]:
    error = response_json["error"]
    assert isinstance(error, dict)
    return {item["field"]: item["message"] for item in error["fields"]}


def test_list_is_empty_initially(client: TestClient) -> None:
    response = client.get("/api/projects")

    assert response.status_code == 200
    assert response.json() == []


def test_create_project_returns_active_project(client: TestClient) -> None:
    response = client.post("/api/projects", json={"name": "  L4i4  "})

    assert response.status_code == 201
    project = response.json()
    assert isinstance(project["id"], int)
    assert project["name"] == "L4i4"
    assert project["description"] is None
    assert project["is_active"] is True
    assert project["created_at"] == project["updated_at"]
    assert project["created_at"].endswith("Z")
    assert datetime.fromisoformat(project["created_at"]).tzinfo is not None


def test_create_project_keeps_trimmed_description(client: TestClient) -> None:
    project = create_project(client, "Cybersecurity", "  Security content  ")

    assert project["description"] == "Security content"


def test_blank_description_is_stored_as_null(client: TestClient) -> None:
    project = create_project(client, "Cybersecurity", "   ")

    assert project["description"] is None


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": None}])
def test_create_project_requires_a_name(
    client: TestClient, body: dict[str, object]
) -> None:
    response = client.post("/api/projects", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "name" in field_errors(response.json())


def test_create_project_rejects_long_name_with_maximum_in_message(
    client: TestClient,
) -> None:
    response = client.post("/api/projects", json={"name": "a" * 101})

    assert response.status_code == 422
    assert "100" in field_errors(response.json())["name"]


def test_create_project_accepts_name_of_maximum_length(client: TestClient) -> None:
    create_project(client, "a" * 100)


def test_create_project_rejects_long_description(client: TestClient) -> None:
    response = client.post(
        "/api/projects", json={"name": "L4i4", "description": "a" * 1001}
    )

    assert response.status_code == 422
    assert "1000" in field_errors(response.json())["description"]


def test_create_project_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/api/projects", json={"name": "L4i4", "is_active": False})

    assert response.status_code == 422
    assert "is_active" in field_errors(response.json())


@pytest.mark.parametrize(
    ("existing", "duplicate"),
    [("L4i4", "l4i4"), ("Straße", "STRASSE"), ("Café", "café")],
)
def test_create_project_rejects_duplicate_names(
    client: TestClient, existing: str, duplicate: str
) -> None:
    create_project(client, existing)

    response = client.post("/api/projects", json={"name": duplicate})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert "name" in field_errors(response.json())
    assert len(client.get("/api/projects").json()) == 1


def test_list_includes_all_projects_ordered_by_name(client: TestClient) -> None:
    create_project(client, "cybersecurity")
    create_project(client, "L4i4")
    create_project(client, "Art")

    names = [project["name"] for project in client.get("/api/projects").json()]

    assert names == ["Art", "cybersecurity", "L4i4"]


def test_get_project_returns_it(client: TestClient) -> None:
    project = create_project(client, "L4i4", "Main brand")

    response = client.get(f"/api/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json() == project


def test_get_unknown_project_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/projects/9999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_projects_cannot_be_deleted(client: TestClient) -> None:
    project = create_project(client, "L4i4")

    response = client.delete(f"/api/projects/{project['id']}")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert client.get(f"/api/projects/{project['id']}").status_code == 200


def patch_project(client: TestClient, project_id: int, body: object) -> Any:
    return client.patch(f"/api/projects/{project_id}", json=body)


def test_edit_project_updates_values_and_updated_at(client: TestClient) -> None:
    project = create_project(client, "L4i4")

    response = patch_project(
        client, project["id"], {"name": " L4i4 Studio ", "description": "Art"}
    )

    assert response.status_code == 200
    edited = response.json()
    assert edited["name"] == "L4i4 Studio"
    assert edited["description"] == "Art"
    assert edited["created_at"] == project["created_at"]
    assert ts(edited["updated_at"]) > ts(project["updated_at"])
    assert client.get(f"/api/projects/{project['id']}").json() == edited


def test_edit_with_same_values_keeps_updated_at(client: TestClient) -> None:
    project = create_project(client, "L4i4", "Art")

    response = patch_project(
        client, project["id"], {"name": "  L4i4 ", "description": " Art "}
    )

    assert response.status_code == 200
    assert response.json() == project


def test_changing_only_the_case_of_own_name_is_allowed(client: TestClient) -> None:
    project = create_project(client, "l4i4")

    response = patch_project(client, project["id"], {"name": "L4i4"})

    assert response.status_code == 200
    assert response.json()["name"] == "L4i4"
    assert ts(response.json()["updated_at"]) > ts(project["updated_at"])


@pytest.mark.parametrize("new_name", ["cybersecurity", "CYBERSECURITY "])
def test_renaming_to_another_project_name_is_rejected(
    client: TestClient, new_name: str
) -> None:
    create_project(client, "Cybersecurity")
    project = create_project(client, "L4i4")

    response = patch_project(client, project["id"], {"name": new_name})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert client.get(f"/api/projects/{project['id']}").json() == project


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": None},
        {"id": 5},
        {"created_at": "2026-01-01T00:00:00Z"},
        {"is_active": "maybe"},
    ],
)
def test_invalid_project_edits_are_rejected(
    client: TestClient, body: dict[str, object]
) -> None:
    project = create_project(client, "L4i4")

    response = patch_project(client, project["id"], body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get(f"/api/projects/{project['id']}").json() == project


def test_description_can_be_cleared(client: TestClient) -> None:
    project = create_project(client, "L4i4", "Art")

    response = patch_project(client, project["id"], {"description": None})

    assert response.json()["description"] is None


def test_project_can_be_deactivated_and_reactivated(client: TestClient) -> None:
    project = create_project(client, "L4i4", "Art")

    deactivated = patch_project(client, project["id"], {"is_active": False}).json()
    reactivated = patch_project(client, project["id"], {"is_active": True}).json()

    assert deactivated["is_active"] is False
    assert ts(deactivated["updated_at"]) > ts(project["updated_at"])
    assert reactivated["is_active"] is True
    assert ts(reactivated["updated_at"]) > ts(deactivated["updated_at"])
    assert reactivated["name"] == "L4i4"
    assert reactivated["description"] == "Art"
    assert reactivated["created_at"] == project["created_at"]


def test_inactive_projects_stay_listed(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    patch_project(client, project["id"], {"is_active": False})

    projects = client.get("/api/projects").json()

    assert [p["is_active"] for p in projects] == [False]


@pytest.mark.parametrize("state", [True, False])
def test_repeating_the_current_state_keeps_updated_at(
    client: TestClient, state: bool
) -> None:
    project = create_project(client, "L4i4")
    current = patch_project(client, project["id"], {"is_active": state}).json()

    response = patch_project(client, project["id"], {"is_active": state})

    assert response.status_code == 200
    assert response.json() == current


def test_editing_unknown_project_returns_not_found(client: TestClient) -> None:
    response = patch_project(client, 9999, {"name": "Ghost"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
