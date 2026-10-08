"""Explicit consent for automatic publishing (User Story 2): only what the user arms
runs by itself, and every way out of `scheduled` disarms."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FUTURE,
    LATER,
    attempt_rows,
    create_publications,
    get_publication,
    in_minutes,
    iso,
    run_sql,
    run_tick,
    scheduled_publication,
    setup_project,
    stored_file,
    wait_idle,
)
from tests.fakes import FakeClock, FakePublisher


def _patch(client: TestClient, publication_id: int, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/publications/{publication_id}", json=body)


def _field_error(response: Any, field: str = "auto_publish_enabled") -> str:
    assert response.status_code == 422, response.text
    [error] = response.json()["error"]["fields"]
    assert error["field"] == field
    message: str = error["message"]
    return message


@pytest.fixture
def one(client: TestClient) -> tuple[dict[str, Any], dict[str, Any]]:
    """A project with an image and one Instagram publication (unscheduled)."""
    project, content, accounts = setup_project(client, ("instagram",))
    [publication] = create_publications(client, content["id"], [accounts[0]["id"]])
    return project, publication


# --- Creating --------------------------------------------------------------------


def test_create_armed(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram", "tiktok"))
    response = client.post(
        f"/api/contents/{content['id']}/publications",
        json={
            "account_ids": [a["id"] for a in accounts],
            "scheduled_at": FUTURE,
            "auto_publish_enabled": True,
        },
    )

    assert response.status_code == 201, response.text
    for publication in response.json():
        assert publication["auto_publish_enabled"] is True
        assert publication["auto_publish_state"] == "waiting"
        assert publication["auto_publish_window_ends_at"] == "2100-01-01T10:10:00Z"
        assert publication["auto_publish_error"] is None


def test_create_is_disarmed_by_default(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram",))
    [publication] = create_publications(
        client, content["id"], [accounts[0]["id"]], FUTURE
    )

    assert publication["auto_publish_enabled"] is False
    assert publication["auto_publish_state"] == "disabled"


def test_create_armed_requires_a_date(client: TestClient) -> None:
    _, content, accounts = setup_project(client, ("instagram",))
    response = client.post(
        f"/api/contents/{content['id']}/publications",
        json={"account_ids": [accounts[0]["id"]], "auto_publish_enabled": True},
    )

    assert "date" in _field_error(response)


# --- PATCH -----------------------------------------------------------------------


def test_arm_and_disarm_a_scheduled_publication(client: TestClient, one: Any) -> None:
    _, publication = one
    _patch(client, publication["id"], {"scheduled_at": FUTURE})

    armed = _patch(client, publication["id"], {"auto_publish_enabled": True})
    assert armed.status_code == 200, armed.text
    assert armed.json()["auto_publish_enabled"] is True
    assert armed.json()["auto_publish_state"] == "waiting"

    disarmed = _patch(client, publication["id"], {"auto_publish_enabled": False})
    assert disarmed.json()["auto_publish_enabled"] is False
    assert disarmed.json()["auto_publish_state"] == "disabled"


@pytest.mark.parametrize("armed", [True, False])
def test_schedule_and_choose_consent_together(
    client: TestClient, one: Any, armed: bool
) -> None:
    _, publication = one

    response = _patch(
        client,
        publication["id"],
        {"scheduled_at": FUTURE, "auto_publish_enabled": armed},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "scheduled"
    assert response.json()["auto_publish_enabled"] is armed


def test_rescheduling_without_consent_disarms(client: TestClient, one: Any) -> None:
    _, publication = one
    _patch(
        client,
        publication["id"],
        {"scheduled_at": FUTURE, "auto_publish_enabled": True},
    )

    moved = _patch(client, publication["id"], {"scheduled_at": LATER}).json()

    assert moved["scheduled_at"] == "2100-02-01T18:30:00Z"
    assert moved["auto_publish_enabled"] is False


def test_rescheduling_with_consent_keeps_it_armed(client: TestClient, one: Any) -> None:
    _, publication = one
    _patch(
        client,
        publication["id"],
        {"scheduled_at": FUTURE, "auto_publish_enabled": True},
    )

    moved = _patch(
        client, publication["id"], {"scheduled_at": LATER, "auto_publish_enabled": True}
    ).json()

    assert moved["auto_publish_enabled"] is True
    assert moved["auto_publish_window_ends_at"] == "2100-02-01T18:40:00Z"


def test_removing_the_date_disarms(client: TestClient, one: Any) -> None:
    _, publication = one
    _patch(
        client,
        publication["id"],
        {"scheduled_at": FUTURE, "auto_publish_enabled": True},
    )

    unscheduled = _patch(client, publication["id"], {"scheduled_at": None}).json()

    assert unscheduled["status"] == "unscheduled"
    assert unscheduled["auto_publish_enabled"] is False
    assert unscheduled["auto_publish_state"] is None


def test_removing_the_date_while_arming_is_rejected(
    client: TestClient, one: Any
) -> None:
    _, publication = one
    _patch(client, publication["id"], {"scheduled_at": FUTURE})

    response = _patch(
        client,
        publication["id"],
        {"scheduled_at": None, "auto_publish_enabled": True},
    )

    _field_error(response)


def test_arming_an_unscheduled_publication_is_rejected(
    client: TestClient, one: Any
) -> None:
    _, publication = one

    response = _patch(client, publication["id"], {"auto_publish_enabled": True})

    assert "date" in _field_error(response)


def test_arming_a_past_date_is_rejected(
    client: TestClient, one: Any, db_path: Path
) -> None:
    _, publication = one
    _patch(client, publication["id"], {"scheduled_at": FUTURE})
    run_sql(
        db_path,
        "UPDATE publications SET scheduled_at = '2000-01-01 10:00:00' WHERE id = ?",
        publication["id"],
    )

    response = _patch(client, publication["id"], {"auto_publish_enabled": True})

    assert "future" in _field_error(response)


@pytest.mark.parametrize("target", ["project", "account", "media"])
def test_arming_requires_active_project_account_and_media(
    client: TestClient,
    one: Any,
    target: str,
    db_path: Path,
    media_dir: Path,
) -> None:
    project, publication = one
    _patch(client, publication["id"], {"scheduled_at": FUTURE})
    if target == "project":
        client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    elif target == "account":
        client.patch(
            f"/api/accounts/{publication['account_id']}", json={"is_active": False}
        )
    else:
        stored_file(media_dir, db_path, publication["content_id"]).unlink()

    response = _patch(client, publication["id"], {"auto_publish_enabled": True})

    assert response.status_code == 409
    assert (
        response.json()["error"]["code"]
        == {
            "project": "project_inactive",
            "account": "account_inactive",
            "media": "media_unavailable",
        }[target]
    )


def test_disarming_is_allowed_with_inactive_project(
    client: TestClient, one: Any
) -> None:
    project, publication = one
    _patch(
        client,
        publication["id"],
        {"scheduled_at": FUTURE, "auto_publish_enabled": True},
    )
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = _patch(client, publication["id"], {"auto_publish_enabled": False})

    assert response.status_code == 200, response.text
    assert response.json()["auto_publish_enabled"] is False


@pytest.mark.parametrize("status", ["failed", "cancelled", "publishing", "published"])
def test_arming_is_rejected_outside_scheduled(
    client: TestClient, one: Any, db_path: Path, status: str
) -> None:
    _, publication = one
    published_at = "'2026-10-07 10:00:00'" if status == "published" else "NULL"
    run_sql(
        db_path,
        f"UPDATE publications SET status = ?, scheduled_at = '2100-01-01 10:00:00', "
        f"published_at = {published_at} WHERE id = ?",
        status,
        publication["id"],
    )

    response = _patch(client, publication["id"], {"auto_publish_enabled": True})

    assert response.status_code == 409


def test_editing_overrides_keeps_consent(client: TestClient, one: Any) -> None:
    _, publication = one
    _patch(
        client,
        publication["id"],
        {"scheduled_at": FUTURE, "auto_publish_enabled": True},
    )

    edited = _patch(client, publication["id"], {"title_override": "New"}).json()

    assert edited["auto_publish_enabled"] is True


# --- Cancel / reactivate ---------------------------------------------------------


def test_cancel_and_reactivate_leave_it_disarmed(client: TestClient, one: Any) -> None:
    _, publication = one
    _patch(
        client,
        publication["id"],
        {"scheduled_at": FUTURE, "auto_publish_enabled": True},
    )

    cancelled = client.post(f"/api/publications/{publication['id']}/cancel").json()
    assert cancelled["auto_publish_enabled"] is False
    reactivated = client.post(
        f"/api/publications/{publication['id']}/reactivate"
    ).json()

    assert reactivated["status"] == "scheduled"
    assert reactivated["auto_publish_enabled"] is False
    assert reactivated["auto_publish_state"] == "disabled"


# --- With the scheduler ----------------------------------------------------------


def test_publish_now_disarms(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 60)
    )
    publication_id = setup["publication"]["id"]

    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 202, response.text
    assert response.json()["auto_publish_enabled"] is False
    wait_idle(fake_scheduler_client)
    assert [row["trigger"] for row in attempt_rows(db_path)] == ["manual"]


def test_only_armed_publications_start(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    armed = scheduled_publication(fake_scheduler_client, db_path, at)
    disarmed = scheduled_publication(
        fake_scheduler_client, db_path, at, project_name="Other", armed=False
    )
    fake_clock.set(at)

    report = run_tick(fake_scheduler_client)

    assert report.started == [armed["publication"]["id"]]
    wait_idle(fake_scheduler_client)
    later = get_publication(fake_scheduler_client, disarmed["publication"]["id"])
    assert later["status"] == "scheduled"
    assert disarmed["publication"]["id"] not in fake_publisher.prepare_calls


def test_armed_through_the_api_starts(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(fake_scheduler_client, db_path, at, armed=False)
    publication_id = setup["publication"]["id"]
    response = _patch(
        fake_scheduler_client, publication_id, {"auto_publish_enabled": True}
    )
    assert response.status_code == 200, response.text
    fake_clock.set(at)

    assert run_tick(fake_scheduler_client).started == [publication_id]


def test_pre_existing_scheduled_publication_never_starts(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    """A row written without the new column, as before the migration."""
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 5), armed=False
    )
    publication = setup["publication"]
    run_sql(db_path, "DELETE FROM publications WHERE id = ?", publication["id"])
    at = in_minutes(fake_clock, 5)
    run_sql(
        db_path,
        "INSERT INTO publications (project_id, content_id, account_id, status, "
        "scheduled_at, created_at, updated_at) VALUES (?, ?, ?, 'scheduled', ?, "
        "'2026-10-06 10:00:00', '2026-10-06 10:00:00')",
        publication["project_id"],
        publication["content_id"],
        publication["account_id"],
        iso(at).replace("T", " ").replace("Z", ""),
    )

    for minutes in (0, 1, 5, 9):
        fake_clock.set(at + timedelta(minutes=minutes))
        assert run_tick(fake_scheduler_client).started == []
    assert attempt_rows(db_path) == []
