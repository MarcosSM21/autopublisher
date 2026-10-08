"""Automatic executions keep every secret out of SQLite, responses and logs
(Feature 007, FR-038, FR-039, SC-012)."""

import logging
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    in_minutes,
    run_tick,
    scheduled_publication,
    wait_idle,
)
from tests.fakes import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_UPLOAD_ID,
    FAKE_VIDEO_ID,
    FakeClock,
    FakeGoogle,
)

SECRETS = [
    FAKE_UPLOAD_ID,
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    "Bearer ",
    "Authorization",
]


def test_no_secret_from_automatic_executions(
    scheduler_client: TestClient,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    at = in_minutes(fake_clock, 5)
    published = scheduled_publication(
        scheduler_client, db_path, at, fake_google=fake_google
    )
    failing = scheduled_publication(
        scheduler_client,
        db_path,
        at + timedelta(minutes=1),
        fake_google=fake_google,
        project_name="Other",
    )
    fake_clock.set(at)
    run_tick(scheduler_client)
    wait_idle(scheduler_client)
    # The second one fails its automatic preflight (YouTube unreachable).
    fake_google.channels_outcome = "server_error"
    fake_clock.set(at + timedelta(minutes=1))
    report = run_tick(scheduler_client)
    assert report.failed == [failing["publication"]["id"]]

    bodies = [scheduler_client.get("/api/automation").text]
    for setup in (published, failing):
        publication_id = setup["publication"]["id"]
        for path in (
            f"/api/publications/{publication_id}",
            f"/api/publications/{publication_id}/attempts",
            f"/api/projects/{setup['project']['id']}/publications",
        ):
            response = scheduler_client.get(path)
            assert response.status_code == 200, response.text
            bodies.append(response.text)
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
        messages = [
            row[0]
            for row in connection.execute(
                "SELECT auto_publish_error_message FROM publications "
                "WHERE auto_publish_error_message IS NOT NULL"
            )
        ]

    assert fake_google.session_starts, "the scenario must reach YouTube"
    for secret in SECRETS:
        assert secret not in dump
        assert all(secret not in body for body in bodies)
        assert secret not in caplog.text
    assert FAKE_VIDEO_ID not in caplog.text
    # Only the safe message that "Publish now" gives for the same problem.
    manual = scheduler_client.post(
        f"/api/publications/{failing['publication']['id']}/publish", json={}
    )
    assert messages == [manual.json()["error"]["message"]]
