"""Neutral arming hook (research §20): enabling auto-publish asks the publisher of
the account for local problems (`Publisher.arming_problems`, no network). Creation
for several accounts stays all or nothing."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import Platform, Publication
from app.publishing import PublishProblem
from tests.conftest import (
    create_account,
    in_minutes,
    iso,
    scheduled_publication,
)
from tests.fakes import FakeClock, FakePublisher

PROBLEM = PublishProblem(
    "fake_arming_problem", "Fake @cyber: confirm before enabling auto-publish."
)


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


def _scheduled(
    client: TestClient, db_path: Path, clock: FakeClock
) -> dict[str, object]:
    return scheduled_publication(client, db_path, in_minutes(clock, 30), armed=False)


def test_arming_asks_the_publisher(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    created = _scheduled(client, db_path, fake_clock)
    publication = created["publication"]
    assert isinstance(publication, dict)

    response = client.patch(
        f"/api/publications/{publication['id']}", json={"auto_publish_enabled": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["auto_publish_enabled"] is True
    assert fake_publisher.arming_calls == [publication["id"]]


def test_an_arming_problem_rejects_arming(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    created = _scheduled(client, db_path, fake_clock)
    publication, account = created["publication"], created["account"]
    assert isinstance(publication, dict) and isinstance(account, dict)
    fake_publisher.arming[account["id"]] = [PROBLEM]

    response = client.patch(
        f"/api/publications/{publication['id']}", json={"auto_publish_enabled": True}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "fake_arming_problem"
    assert error["fields"] == [
        {"field": "auto_publish_enabled", "message": PROBLEM.message}
    ]
    current = client.get(f"/api/publications/{publication['id']}").json()
    assert current["auto_publish_enabled"] is False


def test_disarming_never_asks(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    created = _scheduled(client, db_path, fake_clock)
    publication = created["publication"]
    assert isinstance(publication, dict)

    response = client.patch(
        f"/api/publications/{publication['id']}", json={"auto_publish_enabled": False}
    )

    assert response.status_code == 200
    assert fake_publisher.arming_calls == []


def test_batch_creation_is_all_or_nothing(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    created = _scheduled(client, db_path, fake_clock)
    project, content = created["project"], created["content"]
    assert isinstance(project, dict) and isinstance(content, dict)
    first = create_account(client, project["id"], "youtube", "first")
    second = create_account(client, project["id"], "youtube", "second")
    fake_publisher.arming[second["id"]] = [PROBLEM]
    before = len(client.get(f"/api/projects/{project['id']}/publications").json())

    response = client.post(
        f"/api/contents/{content['id']}/publications",
        json={
            "account_ids": [first["id"], second["id"]],
            "scheduled_at": iso(in_minutes(fake_clock, 60)),
            "auto_publish_enabled": True,
        },
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "fake_arming_problem"
    assert error["fields"] == [
        {"field": "account_ids", "message": PROBLEM.message, "account_id": second["id"]}
    ]
    after = len(client.get(f"/api/projects/{project['id']}/publications").json())
    assert after == before


def test_batch_creation_without_auto_publish_never_asks(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    fake_clock: FakeClock,
) -> None:
    created = _scheduled(client, db_path, fake_clock)
    project, content = created["project"], created["content"]
    assert isinstance(project, dict) and isinstance(content, dict)
    other = create_account(client, project["id"], "youtube", "other")
    fake_publisher.arming[other["id"]] = [PROBLEM]

    response = client.post(
        f"/api/contents/{content['id']}/publications",
        json={
            "account_ids": [other["id"]],
            "scheduled_at": iso(in_minutes(fake_clock, 60)),
        },
    )

    assert response.status_code == 201
    assert fake_publisher.arming_calls == []


@pytest.mark.parametrize(
    "platform", [Platform.YOUTUBE, Platform.INSTAGRAM, Platform.THREADS]
)
def test_other_publishers_have_no_arming_problems(
    scheduler_client: TestClient, platform: Platform
) -> None:
    app = scheduler_client.app
    assert isinstance(app, FastAPI)
    publisher = app.state.publishers[platform]
    with app.state.session_factory() as session:
        assert publisher.arming_problems(session, Publication(account_id=1)) == []
