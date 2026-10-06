from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FUTURE,
    create_publications,
    run_sql,
    setup_project,
    stored_file,
)


def _cancel(client: TestClient, publication_id: int) -> Any:
    return client.post(f"/api/publications/{publication_id}/cancel")


def _reactivate(client: TestClient, publication_id: int) -> Any:
    return client.post(f"/api/publications/{publication_id}/reactivate")


@pytest.fixture
def pair(client: TestClient) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project, content, accounts = setup_project(client, ("instagram",))
    return project, content, accounts[0]


def test_cancel_keeps_date_and_overrides(client: TestClient, pair: Any) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]], FUTURE)
    client.patch(
        f"/api/publications/{publication['id']}",
        json={"description_override": "Custom"},
    )

    response = _cancel(client, publication["id"])

    cancelled = response.json()
    assert response.status_code == 200
    assert cancelled["status"] == "cancelled"
    assert cancelled["scheduled_at"] == "2100-01-01T10:00:00Z"
    assert cancelled["description_override"] == "Custom"
    assert cancelled["updated_at"] >= publication["updated_at"]

    again = _cancel(client, publication["id"])
    assert again.status_code == 200
    assert again.json() == cancelled


def test_cancel_unscheduled(client: TestClient, pair: Any) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]])

    assert _cancel(client, publication["id"]).json()["status"] == "cancelled"


@pytest.mark.parametrize("blocker", ["project", "account", "file"])
def test_cancel_is_always_allowed(
    client: TestClient,
    pair: Any,
    media_dir: Path,
    db_path: Path,
    blocker: str,
) -> None:
    project, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]])
    _block(client, blocker, project, content, account, media_dir, db_path)

    assert _cancel(client, publication["id"]).json()["status"] == "cancelled"


def test_cancelled_publication_cannot_be_edited(client: TestClient, pair: Any) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]])
    _cancel(client, publication["id"])

    response = client.patch(
        f"/api/publications/{publication['id']}", json={"scheduled_at": None}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_cancelled"


def test_cancelled_publication_does_not_block_a_new_one(
    client: TestClient, pair: Any
) -> None:
    project, content, account = pair
    [old] = create_publications(client, content["id"], [account["id"]])
    _cancel(client, old["id"])

    [new] = create_publications(client, content["id"], [account["id"]])

    assert new["id"] != old["id"]
    queue = client.get(f"/api/projects/{project['id']}/publications").json()
    assert [p["status"] for p in queue] == ["unscheduled", "cancelled"]


def test_reactivate_with_future_date(client: TestClient, pair: Any) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]], FUTURE)
    _cancel(client, publication["id"])

    reactivated = _reactivate(client, publication["id"]).json()

    assert reactivated["status"] == "scheduled"
    assert reactivated["scheduled_at"] == "2100-01-01T10:00:00Z"


def test_reactivate_without_date(client: TestClient, pair: Any) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]])
    _cancel(client, publication["id"])

    reactivated = _reactivate(client, publication["id"]).json()

    assert reactivated["status"] == "unscheduled"
    assert reactivated["scheduled_at"] is None


def test_reactivate_drops_a_past_date(
    client: TestClient, pair: Any, db_path: Path
) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]], FUTURE)
    _cancel(client, publication["id"])
    run_sql(
        db_path,
        "UPDATE publications SET scheduled_at = '2000-01-01 10:00:00' WHERE id = ?",
        publication["id"],
    )

    reactivated = _reactivate(client, publication["id"]).json()

    assert reactivated["status"] == "unscheduled"
    assert reactivated["scheduled_at"] is None


def test_reactivate_conflicts_with_another_active_publication(
    client: TestClient, pair: Any
) -> None:
    _, content, account = pair
    [old] = create_publications(client, content["id"], [account["id"]])
    _cancel(client, old["id"])
    [new] = create_publications(client, content["id"], [account["id"]])

    response = _reactivate(client, old["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate"
    assert error["message"] == (
        "Instagram @l4i4 already has an active publication of this content."
    )

    _cancel(client, new["id"])
    assert _reactivate(client, old["id"]).json()["status"] == "unscheduled"


@pytest.mark.parametrize(
    ("blocker", "code"),
    [
        ("project", "project_inactive"),
        ("account", "account_inactive"),
        ("file", "media_unavailable"),
    ],
)
def test_reactivate_requires_active_project_account_and_file(
    client: TestClient,
    pair: Any,
    media_dir: Path,
    db_path: Path,
    blocker: str,
    code: str,
) -> None:
    project, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]])
    _cancel(client, publication["id"])
    _block(client, blocker, project, content, account, media_dir, db_path)

    response = _reactivate(client, publication["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


def test_reactivate_requires_a_cancelled_publication(
    client: TestClient, pair: Any
) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]])

    response = _reactivate(client, publication["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_cancelled"


def test_unknown_publication_and_no_delete(client: TestClient, pair: Any) -> None:
    _, content, account = pair
    [publication] = create_publications(client, content["id"], [account["id"]])

    assert _cancel(client, 9999).status_code == 404
    assert _reactivate(client, 9999).status_code == 404
    response = client.delete(f"/api/publications/{publication['id']}")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def _block(
    client: TestClient,
    blocker: str,
    project: dict[str, Any],
    content: dict[str, Any],
    account: dict[str, Any],
    media_dir: Path,
    db_path: Path,
) -> None:
    if blocker == "project":
        client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    elif blocker == "account":
        client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})
    else:
        stored_file(media_dir, db_path, content["id"]).unlink()
