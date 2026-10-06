from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FUTURE,
    LATER,
    PAST,
    create_publications,
    run_sql,
    setup_project,
    stored_file,
)


def _patch(client: TestClient, publication_id: int, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/publications/{publication_id}", json=body)


def _get(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}")
    assert response.status_code == 200, response.text
    publication: dict[str, Any] = response.json()
    return publication


@pytest.fixture
def three(
    client: TestClient,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    project, content, accounts = setup_project(client)
    created = create_publications(client, content["id"], [a["id"] for a in accounts])
    return project, content, created


# Scheduling (User Story 3).


def test_schedule_and_unschedule(client: TestClient, three: Any) -> None:
    _, _, (instagram, tiktok, x) = three

    scheduled = _patch(client, instagram["id"], {"scheduled_at": FUTURE}).json()
    assert scheduled["status"] == "scheduled"
    assert scheduled["scheduled_at"] == "2100-01-01T10:00:00Z"
    assert scheduled["updated_at"] >= instagram["updated_at"]

    other = _patch(client, tiktok["id"], {"scheduled_at": LATER}).json()
    assert other["scheduled_at"] == "2100-02-01T18:30:00Z"
    assert _get(client, x["id"])["status"] == "unscheduled"
    assert _get(client, instagram["id"])["scheduled_at"] == "2100-01-01T10:00:00Z"

    changed = _patch(client, tiktok["id"], {"scheduled_at": FUTURE}).json()
    assert changed["status"] == "scheduled"
    assert changed["scheduled_at"] == "2100-01-01T10:00:00Z"

    unscheduled = _patch(client, tiktok["id"], {"scheduled_at": None}).json()
    assert unscheduled["status"] == "unscheduled"
    assert unscheduled["scheduled_at"] is None


def test_date_is_normalised_to_utc_minutes(client: TestClient, three: Any) -> None:
    _, _, (instagram, _, _) = three

    response = _patch(
        client, instagram["id"], {"scheduled_at": "2100-01-01T12:00:59+02:00"}
    )

    assert response.json()["scheduled_at"] == "2100-01-01T10:00:00Z"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (PAST, "Choose a date and time in the future."),
        ("2100-01-01T10:00", "Include a time zone."),
        ("tomorrow", None),
    ],
)
def test_invalid_dates_are_rejected(
    client: TestClient, three: Any, value: str, message: str | None
) -> None:
    _, _, (instagram, _, _) = three

    response = _patch(client, instagram["id"], {"scheduled_at": value})

    assert response.status_code == 422
    [field] = response.json()["error"]["fields"]
    assert field["field"] == "scheduled_at"
    if message:
        assert field["message"] == message
    assert _get(client, instagram["id"]) == instagram


def test_resending_the_same_date_is_idempotent(client: TestClient, three: Any) -> None:
    _, _, (instagram, _, _) = three
    first = _patch(client, instagram["id"], {"scheduled_at": FUTURE}).json()

    again = _patch(client, instagram["id"], {"scheduled_at": FUTURE}).json()

    assert again == first


def test_overdue_date_can_be_resent_unchanged(
    client: TestClient, three: Any, db_path: Path
) -> None:
    _, _, (instagram, _, _) = three
    _patch(client, instagram["id"], {"scheduled_at": FUTURE})
    run_sql(
        db_path,
        "UPDATE publications SET scheduled_at = '2000-01-01 10:00:00' WHERE id = ?",
        instagram["id"],
    )
    overdue = _get(client, instagram["id"])

    response = _patch(client, instagram["id"], {"scheduled_at": PAST})

    assert response.status_code == 200
    assert response.json()["updated_at"] == overdue["updated_at"]


def test_overdue_publication_stays_scheduled(
    client: TestClient, three: Any, db_path: Path
) -> None:
    project, _, (instagram, _, _) = three
    _patch(client, instagram["id"], {"scheduled_at": FUTURE})
    run_sql(
        db_path,
        "UPDATE publications SET scheduled_at = '2000-01-01 10:00:00' WHERE id = ?",
        instagram["id"],
    )

    assert _get(client, instagram["id"])["status"] == "scheduled"
    queue = client.get(f"/api/projects/{project['id']}/publications").json()
    assert queue[0]["id"] == instagram["id"]
    assert queue[0]["status"] == "scheduled"


@pytest.mark.parametrize("blocker", ["project", "account", "file"])
def test_scheduling_requires_active_project_account_and_file(
    client: TestClient,
    three: Any,
    media_dir: Path,
    db_path: Path,
    blocker: str,
) -> None:
    project, content, (instagram, tiktok, _) = three
    _patch(client, tiktok["id"], {"scheduled_at": FUTURE})
    if blocker == "project":
        client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
        code = "project_inactive"
    elif blocker == "account":
        for publication in (instagram, tiktok):
            client.patch(
                f"/api/accounts/{publication['account_id']}",
                json={"is_active": False},
            )
        code = "account_inactive"
    else:
        stored_file(media_dir, db_path, content["id"]).unlink()
        code = "media_unavailable"

    response = _patch(client, instagram["id"], {"scheduled_at": FUTURE})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert _get(client, instagram["id"])["status"] == "unscheduled"
    # Removing a date never prepares a future publication, so it is allowed.
    removed = _patch(client, tiktok["id"], {"scheduled_at": None})
    assert removed.status_code == 200
    assert removed.json()["status"] == "unscheduled"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"content_id": 1},
        {"account_id": 1},
        {"project_id": 1},
        {"status": "scheduled"},
    ],
)
def test_only_schedule_and_overrides_are_editable(
    client: TestClient, three: Any, body: dict[str, Any]
) -> None:
    _, _, (instagram, _, _) = three

    response = _patch(client, instagram["id"], body)

    assert response.status_code == 422


def test_unknown_publication_is_not_found(client: TestClient) -> None:
    assert client.get("/api/publications/9999").status_code == 404
    response = _patch(client, 9999, {"scheduled_at": None})
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Publication not found."


# Metadata overrides (User Story 5).


@pytest.fixture
def described(
    client: TestClient,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """A content with global metadata and publications on Instagram and TikTok."""
    _, content, accounts = setup_project(client, ("instagram", "tiktok"))
    client.patch(
        f"/api/contents/{content['id']}",
        json={
            "title": "What is a DDoS attack?",
            "description": "Global description",
            "hashtags": ["cybersecurity", "ddos"],
        },
    )
    instagram, tiktok = create_publications(
        client, content["id"], [a["id"] for a in accounts]
    )
    return content, instagram, tiktok


def test_metadata_is_inherited_by_default(described: Any) -> None:
    _, instagram, _ = described

    assert instagram["title"] == "What is a DDoS attack?"
    assert instagram["description"] == "Global description"
    assert instagram["hashtags"] == ["cybersecurity", "ddos"]
    assert instagram["title_override"] is None
    assert instagram["description_override"] is None
    assert instagram["hashtags_override"] is None


def test_override_affects_only_that_publication(
    client: TestClient, described: Any
) -> None:
    content, instagram, tiktok = described

    updated = _patch(client, instagram["id"], {"description_override": "Custom"})

    assert updated.json()["description"] == "Custom"
    assert updated.json()["description_override"] == "Custom"
    stored = client.get(f"/api/contents/{content['id']}").json()
    assert stored["description"] == "Global description"
    assert _get(client, tiktok["id"])["description"] == "Global description"


def test_global_change_reaches_publications_without_override(
    client: TestClient, described: Any
) -> None:
    content, instagram, tiktok = described
    _patch(client, instagram["id"], {"description_override": "Custom"})

    client.patch(
        f"/api/contents/{content['id']}",
        json={"title": "New title", "description": "New description"},
    )

    assert _get(client, instagram["id"])["title"] == "New title"
    assert _get(client, tiktok["id"])["title"] == "New title"
    assert _get(client, instagram["id"])["description"] == "Custom"
    assert _get(client, tiktok["id"])["description"] == "New description"


def test_empty_overrides_differ_from_inheriting(
    client: TestClient, described: Any
) -> None:
    _, instagram, _ = described

    updated = _patch(
        client, instagram["id"], {"title_override": "   ", "hashtags_override": []}
    ).json()

    assert updated["title_override"] == ""
    assert updated["title"] == ""
    assert updated["hashtags_override"] == []
    assert updated["hashtags"] == []


def test_null_goes_back_to_the_content_value(
    client: TestClient, described: Any
) -> None:
    _, instagram, _ = described
    _patch(
        client,
        instagram["id"],
        {"description_override": "Custom", "hashtags_override": []},
    )

    updated = _patch(
        client,
        instagram["id"],
        {"description_override": None, "hashtags_override": None},
    ).json()

    assert updated["description_override"] is None
    assert updated["description"] == "Global description"
    assert updated["hashtags"] == ["cybersecurity", "ddos"]


def test_hashtags_override_is_normalised(client: TestClient, described: Any) -> None:
    _, instagram, _ = described

    updated = _patch(client, instagram["id"], {"hashtags_override": ["#A", "a", "b"]})

    assert updated.json()["hashtags_override"] == ["A", "b"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"hashtags_override": ["has space"]}, "hashtags_override"),
        ({"title_override": "x" * 201}, "title_override"),
        ({"description_override": "x" * 5001}, "description_override"),
    ],
)
def test_invalid_overrides_are_rejected(
    client: TestClient, described: Any, body: dict[str, Any], field: str
) -> None:
    _, instagram, _ = described

    response = _patch(client, instagram["id"], body)

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == field


def test_override_equal_to_global_value_stays_an_override(
    client: TestClient, described: Any
) -> None:
    content, instagram, _ = described
    _patch(client, instagram["id"], {"title_override": "What is a DDoS attack?"})

    client.patch(f"/api/contents/{content['id']}", json={"title": "New title"})

    publication = _get(client, instagram["id"])
    assert publication["title_override"] == "What is a DDoS attack?"
    assert publication["title"] == "What is a DDoS attack?"


def test_identical_overrides_do_not_touch_updated_at(
    client: TestClient, described: Any
) -> None:
    _, instagram, _ = described
    first = _patch(
        client,
        instagram["id"],
        {"title_override": "Custom", "hashtags_override": ["a"]},
    ).json()

    again = _patch(
        client,
        instagram["id"],
        {"title_override": "  Custom  ", "hashtags_override": ["#a"]},
    ).json()

    assert again["updated_at"] == first["updated_at"]
    assert first["updated_at"] > instagram["updated_at"]


@pytest.mark.parametrize("blocker", ["project", "account", "file"])
def test_overrides_are_editable_when_scheduling_is_blocked(
    client: TestClient,
    described: Any,
    media_dir: Path,
    db_path: Path,
    blocker: str,
) -> None:
    content, instagram, _ = described
    if blocker == "project":
        client.patch(
            f"/api/projects/{instagram['project_id']}", json={"is_active": False}
        )
    elif blocker == "account":
        client.patch(
            f"/api/accounts/{instagram['account_id']}", json={"is_active": False}
        )
    else:
        stored_file(media_dir, db_path, content["id"]).unlink()

    response = _patch(client, instagram["id"], {"description_override": "Custom"})

    assert response.status_code == 200
    assert response.json()["description"] == "Custom"
