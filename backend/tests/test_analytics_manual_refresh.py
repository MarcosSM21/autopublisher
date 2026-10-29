"""Manual refresh requests (Feature 027 T031, data-model rules 3 and 4).

A request only enqueues: it never contacts a platform. A request inside the
15-minute cooldown is refused and never queued.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analytics.adapters.youtube import YouTubeMetricsAdapter
from app.youtube_gateway import GoogleGateway
from tests import analytics_support as scene
from tests import readmodels
from tests.conftest import create_account, create_project
from tests.fakes import FakeClock


@pytest.fixture
def client(
    fake_scheduler_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("a refresh request must not contact any platform")

    monkeypatch.setattr(YouTubeMetricsAdapter, "fetch", no_network)
    monkeypatch.setattr(GoogleGateway, "get_video_statistics", no_network)
    return fake_scheduler_client


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


def connected(
    client: TestClient, db_path: Path, project: dict[str, Any], platform: str
) -> dict[str, Any]:
    account = create_account(client, project["id"], platform, f"{platform}-cyber")
    readmodels.connect(db_path, account, scene.NOW)
    return account


def refresh(client: TestClient, post_id: int) -> Any:
    return client.post(f"/api/publications/{post_id}/analytics/refresh")


def last_attempt(db_path: Path, post_id: int, when: datetime) -> None:
    """The publication was attempted at `when` (any outcome)."""
    readmodels.insert(
        db_path,
        "publication_metric_states",
        publication_id=post_id,
        status="ok",
        last_success_at=when,
        last_attempt_at=when,
        next_attempt_at=when + timedelta(hours=24),
        failure_count=0,
    )


def test_an_accepted_request_is_pending(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    post_id = scene.published(db_path, connected(client, db_path, project, "youtube"))

    response = refresh(client, post_id)

    assert response.status_code == 202, response.text
    assert response.json() == {"queued": True}
    state = scene.state(db_path, post_id)
    assert state is not None
    assert state["status"] == "pending"
    assert state["manual_requested_at"] is not None
    assert scene.values(db_path, post_id) == []


def test_a_post_older_than_90_days_can_be_refreshed_manually(
    client: TestClient, db_path: Path, project: dict[str, Any], fake_clock: FakeClock
) -> None:
    owner = connected(client, db_path, project, "youtube")
    old = fake_clock.now() - timedelta(days=400)
    post_id = scene.published(db_path, owner, published_at=old)

    assert refresh(client, post_id).status_code == 202


def test_a_request_inside_the_cooldown_is_refused_and_not_queued(
    client: TestClient, db_path: Path, project: dict[str, Any], fake_clock: FakeClock
) -> None:
    post_id = scene.published(db_path, connected(client, db_path, project, "youtube"))
    attempted = fake_clock.now() - timedelta(minutes=5)
    last_attempt(db_path, post_id, attempted)

    response = refresh(client, post_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "refresh_cooldown"
    available_at = datetime.fromisoformat(error["available_at"])
    assert available_at == attempted + timedelta(minutes=15)
    state = scene.state(db_path, post_id)
    assert state is not None
    assert (state["status"], state["manual_requested_at"]) == ("ok", None)

    fake_clock.set(available_at)
    assert refresh(client, post_id).status_code == 202


def test_a_failed_state_is_requeued_keeping_its_detail(
    client: TestClient, db_path: Path, project: dict[str, Any], fake_clock: FakeClock
) -> None:
    post_id = scene.published(db_path, connected(client, db_path, project, "youtube"))
    readmodels.insert(
        db_path,
        "publication_metric_states",
        publication_id=post_id,
        status="remote_not_found",
        last_attempt_at=fake_clock.now() - timedelta(hours=2),
        failure_count=1,
        error_code="remote_not_found",
        error_message="The post was not found on the platform.",
    )

    assert refresh(client, post_id).status_code == 202

    state = scene.state(db_path, post_id)
    assert state is not None
    assert (state["status"], state["error_code"]) == ("pending", "remote_not_found")


@pytest.mark.parametrize(
    ("platform", "external_id", "reason"),
    [
        ("youtube", None, "remote_id_missing"),
        ("tiktok", "REMOTE-1", "not_supported"),
        ("telegram", "42", "not_supported"),
        ("threads", "REMOTE-1", "permission_required"),
    ],
)
def test_a_post_that_cannot_be_refreshed_is_refused_with_its_reason(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    platform: str,
    external_id: str | None,
    reason: str,
) -> None:
    owner = connected(client, db_path, project, platform)
    post_id = scene.published(db_path, owner, external_id)

    response = refresh(client, post_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["reason"]) == ("analytics_not_refreshable", reason)
    assert scene.state(db_path, post_id) is None


def test_a_disconnected_account_is_refused(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    owner = create_account(client, project["id"], "youtube", "loose")
    post_id = scene.published(db_path, owner)

    error = refresh(client, post_id).json()["error"]

    assert error["reason"] == "not_connected"


def test_an_unknown_post_is_404(client: TestClient) -> None:
    assert refresh(client, 999).status_code == 404


def test_a_project_refresh_counts_each_post(
    client: TestClient, db_path: Path, project: dict[str, Any], fake_clock: FakeClock
) -> None:
    youtube = connected(client, db_path, project, "youtube")
    telegram = connected(client, db_path, project, "telegram")
    queued = [scene.published(db_path, youtube, f"V{i}") for i in range(2)]
    cooling = scene.published(db_path, youtube, "V-COOL")
    last_attempt(db_path, cooling, fake_clock.now() - timedelta(minutes=1))
    not_eligible = [
        scene.published(db_path, youtube, None),
        scene.published(db_path, telegram, "42"),
    ]
    # Not published: not counted at all.
    readmodels.post(db_path, youtube, fake_clock.now(), status="unscheduled")
    other = create_project(client, "Other")
    elsewhere = scene.published(db_path, connected(client, db_path, other, "youtube"))

    response = client.post(f"/api/projects/{project['id']}/analytics/refresh")

    assert response.status_code == 202, response.text
    assert response.json() == {"queued": 2, "in_cooldown": 1, "not_eligible": 2}
    for post_id in queued:
        assert scene.state(db_path, post_id)["status"] == "pending"  # type: ignore[index]
    cooled = scene.state(db_path, cooling)
    assert cooled is not None and cooled["manual_requested_at"] is None
    for post_id in [*not_eligible, elsewhere]:
        assert scene.state(db_path, post_id) is None


def test_a_project_refresh_of_an_unknown_project_is_404(client: TestClient) -> None:
    assert client.post("/api/projects/999/analytics/refresh").status_code == 404


def test_a_request_wakes_the_refresher_when_there_is_one(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    woken: list[bool] = []

    class Refresher:
        def wake(self) -> None:
            woken.append(True)

    client.app.state.analytics_refresher = Refresher()  # type: ignore[attr-defined]
    post_id = scene.published(db_path, connected(client, db_path, project, "youtube"))

    refresh(client, post_id)
    client.post(f"/api/projects/{project['id']}/analytics/refresh")

    assert woken == [True, True]
