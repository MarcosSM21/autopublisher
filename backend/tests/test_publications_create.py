from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import publications
from tests.conftest import (
    FUTURE,
    PAST,
    create_account,
    create_project,
    create_publications,
    make_image,
    setup_project,
    stored_file,
)


def _publications(client: TestClient, project_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/publications")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items


def _post(client: TestClient, content_id: int, body: dict[str, Any]) -> Any:
    return client.post(f"/api/contents/{content_id}/publications", json=body)


def test_create_one_publication(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram",))

    [publication] = create_publications(client, content["id"], [accounts[0]["id"]])

    assert publication["status"] == "unscheduled"
    assert publication["scheduled_at"] is None
    assert publication["project_id"] == project["id"]
    assert publication["content_id"] == content["id"]
    assert publication["account_id"] == accounts[0]["id"]
    assert publication["title_override"] is None
    assert publication["description_override"] is None
    assert publication["hashtags_override"] is None
    assert publication["title"] == content["title"]
    assert publication["hashtags"] == content["hashtags"]
    assert publication["account"]["platform"] == "instagram"
    assert publication["content"]["file_available"] is True
    assert publication["project_active"] is True
    assert publication["created_at"] == publication["updated_at"]


def test_create_publications_for_several_accounts(client: TestClient) -> None:
    _, content, accounts = setup_project(client)
    ids = [account["id"] for account in accounts]

    created = create_publications(client, content["id"], ids)

    assert [p["account_id"] for p in created] == ids
    assert {p["content_id"] for p in created} == {content["id"]}
    assert len({p["id"] for p in created}) == 3


def test_repeated_account_ids_count_once(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram", "x"))
    a, b = accounts[0]["id"], accounts[1]["id"]

    created = create_publications(client, content["id"], [a, a, b])

    assert [p["account_id"] for p in created] == [a, b]


def test_create_scheduled_publications(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram", "x"))

    created = create_publications(
        client, content["id"], [a["id"] for a in accounts], FUTURE
    )

    assert {p["status"] for p in created} == {"scheduled"}
    assert {p["scheduled_at"] for p in created} == {"2100-01-01T10:00:00Z"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2100-01-01T12:00:00+02:00", "2100-01-01T10:00:00Z"),
        ("2100-01-01T10:00:42.5Z", "2100-01-01T10:00:00Z"),
    ],
)
def test_scheduled_at_is_utc_and_truncated_to_the_minute(
    client: TestClient, value: str, expected: str
) -> None:
    _, content, accounts = setup_project(client, ("instagram",))

    [publication] = create_publications(
        client, content["id"], [accounts[0]["id"]], value
    )

    assert publication["scheduled_at"] == expected


def test_creating_publications_does_not_copy_the_file(
    client: TestClient, media_dir: Path
) -> None:
    project, content, accounts = setup_project(client)
    project_dir = media_dir / "projects" / str(project["id"])
    before = sorted(project_dir.iterdir())

    create_publications(client, content["id"], [a["id"] for a in accounts])

    assert sorted(project_dir.iterdir()) == before


def test_unknown_content_is_not_found(client: TestClient) -> None:
    response = _post(client, 9999, {"account_ids": [1]})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("count", [0, 51])
def test_account_ids_must_have_between_1_and_50_items(
    client: TestClient, count: int
) -> None:
    project, content, _ = setup_project(client, ("instagram",))

    response = _post(client, content["id"], {"account_ids": list(range(1, count + 1))})

    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "account_ids"
    assert _publications(client, project["id"]) == []


def test_account_of_another_project_is_rejected(client: TestClient) -> None:
    project, content, _ = setup_project(client, ("instagram",))
    other = create_project(client, "Cybersecurity")
    foreign = create_account(client, other["id"], "instagram", "cyber")

    response = _post(client, content["id"], {"account_ids": [foreign["id"]]})

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [
        {
            "field": "account_ids",
            "message": f"Account {foreign['id']} does not belong to this project.",
        }
    ]
    assert _publications(client, project["id"]) == []


def test_unknown_account_is_reported_as_not_found(client: TestClient) -> None:
    project, content, _ = setup_project(client, ("instagram",))
    other = create_project(client, "Cybersecurity")
    foreign = create_account(client, other["id"], "x", "cyber")

    response = _post(client, content["id"], {"account_ids": [9999, foreign["id"]]})

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [
        {"field": "account_ids", "message": "Account 9999 not found."},
        {
            "field": "account_ids",
            "message": f"Account {foreign['id']} does not belong to this project.",
        },
    ]
    assert _publications(client, project["id"]) == []


def test_inactive_account_is_rejected(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    client.patch(f"/api/accounts/{accounts[0]['id']}", json={"is_active": False})

    response = _post(client, content["id"], {"account_ids": [accounts[0]["id"]]})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "account_inactive"
    assert error["fields"] == [
        {"field": "account_ids", "message": "Instagram @l4i4 is inactive."}
    ]
    assert _publications(client, project["id"]) == []


def test_creation_is_atomic(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram", "x"))
    client.patch(f"/api/accounts/{accounts[1]['id']}", json={"is_active": False})

    response = _post(
        client, content["id"], {"account_ids": [a["id"] for a in accounts]}
    )

    assert response.status_code == 409
    assert _publications(client, project["id"]) == []


def test_inactive_project_is_rejected(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = _post(client, content["id"], {"account_ids": [accounts[0]["id"]]})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_inactive"
    assert _publications(client, project["id"]) == []


def test_past_date_is_rejected(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram",))

    response = _post(
        client,
        content["id"],
        {"account_ids": [accounts[0]["id"]], "scheduled_at": PAST},
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [
        {"field": "scheduled_at", "message": "Choose a date and time in the future."}
    ]
    assert _publications(client, project["id"]) == []


def test_date_without_time_zone_is_rejected(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram",))

    response = _post(
        client,
        content["id"],
        {"account_ids": [accounts[0]["id"]], "scheduled_at": "2100-01-01T10:00"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == [
        {"field": "scheduled_at", "message": "Include a time zone."}
    ]


def test_missing_media_file_is_rejected(
    client: TestClient, media_dir: Path, db_path: Path
) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    stored_file(media_dir, db_path, content["id"]).unlink()

    response = _post(client, content["id"], {"account_ids": [accounts[0]["id"]]})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "media_unavailable"
    assert error["message"] == "The media file of this content is not available."
    assert _publications(client, project["id"]) == []


@pytest.mark.parametrize("field", ["status", "project_id"])
def test_unknown_fields_are_rejected(client: TestClient, field: str) -> None:
    _, content, accounts = setup_project(client, ("instagram",))

    response = _post(
        client, content["id"], {"account_ids": [accounts[0]["id"]], field: "x"}
    )

    assert response.status_code == 422


# Duplicate prevention (User Story 2).


def test_active_publication_for_the_same_pair_is_a_conflict(
    client: TestClient,
) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    create_publications(client, content["id"], [accounts[0]["id"]])

    response = _post(client, content["id"], {"account_ids": [accounts[0]["id"]]})

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate"
    assert error["fields"] == [
        {
            "field": "account_ids",
            "message": "Instagram @l4i4 already has an active publication of this "
            "content.",
        }
    ]
    assert len(_publications(client, project["id"])) == 1


def test_scheduled_publication_also_blocks_the_pair(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram",))
    create_publications(client, content["id"], [accounts[0]["id"]], FUTURE)

    response = _post(client, content["id"], {"account_ids": [accounts[0]["id"]]})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"


def test_one_conflict_blocks_the_whole_request(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram", "tiktok"))
    create_publications(client, content["id"], [accounts[0]["id"]])

    response = _post(
        client, content["id"], {"account_ids": [a["id"] for a in accounts]}
    )

    assert response.status_code == 409
    assert len(_publications(client, project["id"])) == 1


def test_most_severe_problem_decides_the_code(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram", "tiktok"))
    other = create_project(client, "Cybersecurity")
    foreign = create_account(client, other["id"], "x", "cyber")
    create_publications(client, content["id"], [accounts[0]["id"]])
    client.patch(f"/api/accounts/{accounts[1]['id']}", json={"is_active": False})

    response = _post(
        client,
        content["id"],
        {"account_ids": [foreign["id"], accounts[1]["id"], accounts[0]["id"]]},
    )

    assert response.status_code == 422
    assert len(response.json()["error"]["fields"]) == 3


def test_same_account_with_another_content_is_allowed(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    create_publications(client, content["id"], [accounts[0]["id"]])
    response = client.post(
        f"/api/projects/{project['id']}/contents",
        files=[("files", ("other.png", make_image()))],
    )
    other_content = response.json()["results"][0]["content"]

    create_publications(client, other_content["id"], [accounts[0]["id"]])

    assert len(_publications(client, project["id"])) == 2


def test_race_is_caught_by_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    create_publications(client, content["id"], [accounts[0]["id"]])
    monkeypatch.setattr(publications, "find_active", lambda *args, **kwargs: [])

    response = _post(client, content["id"], {"account_ids": [accounts[0]["id"]]})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert len(_publications(client, project["id"])) == 1
