from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_account, create_project


def field_errors(response_json: dict[str, Any]) -> dict[str, str]:
    return {item["field"]: item["message"] for item in response_json["error"]["fields"]}


def list_accounts(client: TestClient, project_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/accounts")
    assert response.status_code == 200
    accounts: list[dict[str, Any]] = response.json()
    return accounts


def test_create_account_returns_active_account(client: TestClient) -> None:
    project = create_project(client, "L4i4")

    response = client.post(
        f"/api/projects/{project['id']}/accounts",
        json={"platform": "instagram", "handle": " @l4i4 ", "display_name": "  "},
    )

    assert response.status_code == 201
    account = response.json()
    assert account["project_id"] == project["id"]
    assert account["platform"] == "instagram"
    assert account["handle"] == "l4i4"
    assert account["display_name"] is None
    assert account["is_active"] is True
    assert account["created_at"] == account["updated_at"]


def test_project_can_have_accounts_on_several_platforms(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    for platform in ["instagram", "tiktok", "x"]:
        create_account(client, project["id"], platform, "l4i4", "L4i4 Official")

    accounts = list_accounts(client, project["id"])

    assert [account["platform"] for account in accounts] == ["instagram", "tiktok", "x"]
    assert all(account["display_name"] == "L4i4 Official" for account in accounts)


def test_project_can_have_several_accounts_on_the_same_platform(
    client: TestClient,
) -> None:
    project = create_project(client, "Cybersecurity")
    create_account(client, project["id"], "youtube", "cyber")
    create_account(client, project["id"], "youtube", "cyber_shorts")

    assert len(list_accounts(client, project["id"])) == 2


@pytest.mark.parametrize("duplicate", ["@L4I4", "l4i4", " L4i4 "])
def test_duplicate_handle_in_same_project_is_rejected(
    client: TestClient, duplicate: str
) -> None:
    project = create_project(client, "L4i4")
    create_account(client, project["id"], "instagram", "l4i4")

    response = client.post(
        f"/api/projects/{project['id']}/accounts",
        json={"platform": "instagram", "handle": duplicate},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert "handle" in field_errors(response.json())
    assert len(list_accounts(client, project["id"])) == 1


def test_same_handle_is_allowed_in_another_project(client: TestClient) -> None:
    first = create_project(client, "L4i4")
    second = create_project(client, "Cybersecurity")
    create_account(client, first["id"], "instagram", "shared")

    create_account(client, second["id"], "instagram", "shared")


def test_same_handle_is_allowed_on_another_platform(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    create_account(client, project["id"], "instagram", "l4i4")

    create_account(client, project["id"], "tiktok", "l4i4")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"handle": "l4i4"}, "platform"),
        ({"platform": "myspace", "handle": "l4i4"}, "platform"),
        ({"platform": "instagram"}, "handle"),
        ({"platform": "instagram", "handle": "   "}, "handle"),
        ({"platform": "instagram", "handle": "@"}, "handle"),
        ({"platform": "instagram", "handle": "l4i4", "project_id": 2}, "project_id"),
    ],
)
def test_invalid_account_is_rejected(
    client: TestClient, body: dict[str, Any], field: str
) -> None:
    project = create_project(client, "L4i4")

    response = client.post(f"/api/projects/{project['id']}/accounts", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert field in field_errors(response.json())
    assert list_accounts(client, project["id"]) == []


@pytest.mark.parametrize("field", ["handle", "display_name"])
def test_too_long_values_are_rejected_with_maximum_in_message(
    client: TestClient, field: str
) -> None:
    project = create_project(client, "L4i4")
    body = {"platform": "instagram", "handle": "l4i4", field: "a" * 101}

    response = client.post(f"/api/projects/{project['id']}/accounts", json=body)

    assert response.status_code == 422
    assert "100" in field_errors(response.json())[field]


def test_account_for_unknown_project_is_rejected(client: TestClient) -> None:
    project = create_project(client, "L4i4")

    response = client.post(
        "/api/projects/9999/accounts", json={"platform": "instagram", "handle": "x"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert list_accounts(client, project["id"]) == []


def test_listing_accounts_of_unknown_project_returns_not_found(
    client: TestClient,
) -> None:
    response = client.get("/api/projects/9999/accounts")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_accounts_are_listed_only_in_their_project_and_ordered(
    client: TestClient,
) -> None:
    l4i4 = create_project(client, "L4i4")
    cyber = create_project(client, "Cybersecurity")
    create_account(client, l4i4["id"], "x", "l4i4")
    create_account(client, l4i4["id"], "instagram", "zeta")
    create_account(client, l4i4["id"], "instagram", "Alpha")
    create_account(client, cyber["id"], "youtube", "cyber")

    l4i4_accounts = list_accounts(client, l4i4["id"])
    cyber_accounts = list_accounts(client, cyber["id"])

    assert [(a["platform"], a["handle"]) for a in l4i4_accounts] == [
        ("instagram", "Alpha"),
        ("instagram", "zeta"),
        ("x", "l4i4"),
    ]
    assert [a["handle"] for a in cyber_accounts] == ["cyber"]
    assert all(a["project_id"] == l4i4["id"] for a in l4i4_accounts)


def test_deactivating_a_project_keeps_its_accounts_unchanged(
    client: TestClient,
) -> None:
    project = create_project(client, "Cybersecurity")
    create_account(client, project["id"], "youtube", "cyber")
    create_account(client, project["id"], "instagram", "cyber")
    before = list_accounts(client, project["id"])

    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    after_deactivation = list_accounts(client, project["id"])
    client.patch(f"/api/projects/{project['id']}", json={"is_active": True})
    after_reactivation = list_accounts(client, project["id"])

    assert after_deactivation == before
    assert after_reactivation == before
    assert len(before) == 2


def test_accounts_cannot_be_added_to_inactive_project(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = client.post(
        f"/api/projects/{project['id']}/accounts",
        json={"platform": "instagram", "handle": "l4i4"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_inactive"
    assert list_accounts(client, project["id"]) == []

    client.patch(f"/api/projects/{project['id']}", json={"is_active": True})
    create_account(client, project["id"], "instagram", "l4i4")


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def patch_account(client: TestClient, account_id: int, body: object) -> Any:
    return client.patch(f"/api/accounts/{account_id}", json=body)


def test_edit_account_updates_values_and_updated_at(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(
        client, account["id"], {"handle": "@l4i4_art", "display_name": "L4i4 Art"}
    )

    assert response.status_code == 200
    edited = response.json()
    assert edited["handle"] == "l4i4_art"
    assert edited["display_name"] == "L4i4 Art"
    assert edited["platform"] == "instagram"
    assert edited["project_id"] == project["id"]
    assert edited["created_at"] == account["created_at"]
    assert ts(edited["updated_at"]) > ts(account["updated_at"])
    assert list_accounts(client, project["id"]) == [edited]


def test_equivalent_handle_is_not_a_change(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], {"handle": " @l4i4 "})

    assert response.status_code == 200
    assert response.json() == account


def test_changing_only_the_case_of_own_handle_is_allowed(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], {"handle": "L4i4"})

    assert response.status_code == 200
    assert response.json()["handle"] == "L4i4"
    assert ts(response.json()["updated_at"]) > ts(account["updated_at"])


@pytest.mark.parametrize("other_active", [True, False])
def test_handle_of_another_account_is_rejected(
    client: TestClient, other_active: bool
) -> None:
    project = create_project(client, "L4i4")
    other = create_account(client, project["id"], "instagram", "taken")
    patch_account(client, other["id"], {"is_active": other_active})
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], {"handle": "@TAKEN"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert "handle" in field_errors(response.json())


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"platform": "x"}, "platform"),
        ({"project_id": 2}, "project_id"),
        ({"handle": ""}, "handle"),
        ({"handle": None}, "handle"),
        ({"is_active": None}, "is_active"),
        ({}, None),
    ],
)
def test_invalid_account_edits_are_rejected(
    client: TestClient, body: dict[str, Any], field: str | None
) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    if field:
        assert field in field_errors(response.json())
    assert list_accounts(client, project["id"]) == [account]


def test_display_name_can_be_cleared(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4", "L4i4")

    response = patch_account(client, account["id"], {"display_name": None})

    assert response.json()["display_name"] is None


def test_account_can_be_deactivated_and_reactivated(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4", "L4i4")

    deactivated = patch_account(client, account["id"], {"is_active": False}).json()
    listed = list_accounts(client, project["id"])
    reactivated = patch_account(client, account["id"], {"is_active": True}).json()

    assert deactivated["is_active"] is False
    assert listed == [deactivated]
    assert ts(deactivated["updated_at"]) > ts(account["updated_at"])
    assert reactivated["is_active"] is True
    assert {k: v for k, v in reactivated.items() if k != "updated_at"} == {
        k: v for k, v in account.items() if k != "updated_at"
    }


@pytest.mark.parametrize("state", [True, False])
def test_repeating_the_current_account_state_keeps_updated_at(
    client: TestClient, state: bool
) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4")
    current = patch_account(client, account["id"], {"is_active": state}).json()

    response = patch_account(client, account["id"], {"is_active": state})

    assert response.status_code == 200
    assert response.json() == current


def test_accounts_of_inactive_project_can_be_edited(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4")
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    edited = patch_account(client, account["id"], {"handle": "l4i4_new"})
    toggled = patch_account(client, account["id"], {"is_active": False})

    assert edited.status_code == 200
    assert toggled.json()["is_active"] is False


def test_deactivating_a_project_keeps_individual_account_states(
    client: TestClient,
) -> None:
    project = create_project(client, "Cybersecurity")
    create_account(client, project["id"], "youtube", "cyber")
    inactive = create_account(client, project["id"], "instagram", "cyber")
    patch_account(client, inactive["id"], {"is_active": False})
    before = list_accounts(client, project["id"])

    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    client.patch(f"/api/projects/{project['id']}", json={"is_active": True})

    assert list_accounts(client, project["id"]) == before
    assert [a["is_active"] for a in before] == [False, True]


def test_editing_unknown_account_returns_not_found(client: TestClient) -> None:
    response = patch_account(client, 9999, {"handle": "ghost"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_accounts_cannot_be_deleted(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4")

    response = client.delete(f"/api/accounts/{account['id']}")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert list_accounts(client, project["id"]) == [account]


ACCOUNT_FIELDS = {
    "id",
    "project_id",
    "platform",
    "handle",
    "display_name",
    "is_active",
    "created_at",
    "updated_at",
}


def test_account_responses_have_no_platform_connection_fields(
    client: TestClient,
) -> None:
    project = create_project(client, "Cyber")
    youtube = create_account(client, project["id"], "youtube", "cyber")
    instagram = create_account(client, project["id"], "instagram", "cyber")

    assert set(youtube) == ACCOUNT_FIELDS
    assert set(instagram) == ACCOUNT_FIELDS
    for account in list_accounts(client, project["id"]):
        assert set(account) == ACCOUNT_FIELDS


def test_accounts_core_does_not_depend_on_platforms() -> None:
    """Constitution III: platform-specific code never leaks into the accounts core."""
    import ast
    import inspect

    from app import accounts, models

    tree = ast.parse(inspect.getsource(accounts))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any("youtube" in name for name in imported)
    assert not any("instagram" in name for name in imported)
    assert not hasattr(models.Account, "youtube_connection")
    assert not hasattr(models.Account, "instagram_connection")
    assert not hasattr(models.Account, "instagram_connections")
