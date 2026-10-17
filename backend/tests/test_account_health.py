"""Account health: one representative case per state (research.md §8)."""

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_account, create_project, make_scheduler_app
from tests.fakes import FakeClock
from tests.readmodels import connect


@pytest.fixture
def health_client(
    db_path: Path, media_dir: Path, fake_clock: FakeClock
) -> Iterator[TestClient]:
    with TestClient(make_scheduler_app(db_path, media_dir, fake_clock)) as client:
        yield client


@pytest.mark.parametrize(
    ("platform", "connection", "active", "state", "issue", "expiring"),
    [
        ("youtube", {}, True, "ready", None, False),
        ("youtube", {"status": "reconnect_required"}, True, "reconnect_needed",
         "reconnect_required", False),
        ("instagram", {"expires_in": timedelta(days=-1)}, True, "reconnect_needed",
         "credential_expired", False),
        ("telegram", {"channel": False}, True, "setup_required", "channel_required",
         False),
        ("tiktok", None, True, "not_connected", "not_connected", False),
        ("threads", {}, False, "inactive", "account_inactive", False),
        ("instagram", {"expires_in": timedelta(days=3)}, True, "ready",
         "credential_expiring", True),
    ],
)  # fmt: skip
def test_account_health_states(
    health_client: TestClient,
    db_path: Path,
    fake_clock: FakeClock,
    platform: str,
    connection: dict[str, Any] | None,
    active: bool,
    state: str,
    issue: str | None,
    expiring: bool,
) -> None:
    now = fake_clock.now()
    project = create_project(health_client, "Cyber")
    account = create_account(health_client, project["id"], platform, "cyber")
    if connection is not None:
        options = dict(connection)
        expires_in = options.pop("expires_in", None)
        if expires_in is not None:
            options["expires_at"] = now + expires_in
        connect(db_path, account, now, **options)
    if not active:
        health_client.patch(f"/api/accounts/{account['id']}", json={"is_active": False})

    response = health_client.get(f"/api/projects/{project['id']}/account-health")

    assert response.status_code == 200, response.text
    [health] = response.json()
    assert health["state"] == state
    assert (health["issue"] or {}).get("code") == issue
    assert health["expiring"] is expiring
    assert health["can_discard"] is False
    if connection is not None:
        assert health["identity"]["name"]
    # Never platform ids or credential references.
    assert "SENTINEL" not in response.text
    assert "secret-ref" not in response.text


def test_capabilities_and_order(health_client: TestClient) -> None:
    project = create_project(health_client, "Cyber")
    youtube = create_account(health_client, project["id"], "youtube", "cyber")
    create_account(health_client, project["id"], "threads", "cyber")
    health_client.patch(f"/api/accounts/{youtube['id']}", json={"is_active": False})

    body = health_client.get(f"/api/projects/{project['id']}/account-health").json()

    assert [(h["platform"], h["capabilities"]) for h in body] == [
        ("threads", ["text", "images", "videos"]),
        ("youtube", ["videos"]),
    ]


def test_unknown_project_is_not_found(health_client: TestClient) -> None:
    response = health_client.get("/api/projects/999/account-health")

    assert response.status_code == 404
