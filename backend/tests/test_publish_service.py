"""The execution service is reusable without HTTP (FR-013) and the API never waits for
an upload to finish (SC-002)."""

import inspect
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.models import Publication
from app.publishing import PublishOutcome, UserActionCompleted, start_publication
from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    publish_and_wait,
    run_sql,
    scheduled_publication,
    set_youtube_options,
    setup_publishable,
    wait_idle,
)
from tests.fakes import FakeClock, FakeGoogle, FakePublisher


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def test_start_publication_runs_without_http(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    set_youtube_options(publishing_client, publication_id)
    state = _app(publishing_client).state

    with state.publish_context.session_factory() as session:
        attempt_id = start_publication(
            session,
            publication_id,
            confirm_remote_checked=False,
            ctx=state.publish_context,
            runner=state.publication_runner,
            publishers=state.publishers,
        )
        assert session.get_one(Publication, publication_id).status in {
            "publishing",
            "published",
        }

    assert isinstance(attempt_id, int)
    assert state.publication_runner.wait_idle(timeout=10)
    publication = get_publication(publishing_client, publication_id)
    assert publication["status"] == "published"
    assert publication["attempt_count"] == 1
    assert publication["latest_attempt"]["id"] == attempt_id


def test_start_publication_does_not_depend_on_fastapi() -> None:
    parameters = inspect.signature(start_publication).parameters.values()

    assert all(parameter.annotation is not Request for parameter in parameters)
    assert "request" not in {parameter.name for parameter in parameters}


def test_publish_now_answers_while_the_upload_is_still_running(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    set_youtube_options(publishing_client, publication_id)
    fake_google.block_uploads(at="chunk")

    response = publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "publishing"
    assert fake_google.wait_until_blocked()
    during = get_publication(publishing_client, publication_id)
    assert during["status"] == "publishing"
    assert during["latest_attempt"]["status"] == "running"

    fake_google.release()
    wait_idle(publishing_client)
    assert get_publication(publishing_client, publication_id)["status"] == "published"


# --- Posts deleted while starting (Feature 021, research §5) -----------------------


def _delete_post(db_path: Path, publication_id: int) -> None:
    """What a Delete Post commits: the post and its dependants, by raw SQL."""
    for table, column in (
        ("youtube_publication_options", "publication_id"),
        ("publication_attempts", "publication_id"),
        ("publications", "id"),
    ):
        run_sql(db_path, f"DELETE FROM {table} WHERE {column} = ?", publication_id)


def test_a_post_deleted_during_the_preflight_is_not_found(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 60), armed=False
    )
    publication_id = setup["publication"]["id"]
    fake_publisher.prepare_hook = lambda pid: _delete_post(db_path, pid)

    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    assert fake_publisher.prepare_calls == [publication_id]
    # Nothing was claimed nor recreated.
    assert attempt_rows(db_path) == []
    assert fake_publisher.upload_calls == []
    assert (
        fake_scheduler_client.get(f"/api/publications/{publication_id}").status_code
        == 404
    )


def test_a_post_deleted_during_a_follow_up_is_not_found(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    setup = scheduled_publication(
        fake_scheduler_client, db_path, in_minutes(fake_clock, 60), armed=False
    )
    publication_id = setup["publication"]["id"]
    fake_publisher.outcomes[publication_id] = PublishOutcome(
        external_id=None,
        external_url=None,
        details={"delivered": True},
        awaiting_user_action=True,
    )
    assert publish_and_wait(fake_scheduler_client, publication_id)["status"] == (
        "awaiting_user_action"
    )
    fake_publisher.follow_ups[publication_id] = UserActionCompleted(
        datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
    )
    fake_publisher.follow_up_hook = lambda pid: _delete_post(db_path, pid)

    response = fake_scheduler_client.post(
        f"/api/publications/{publication_id}/check-status"
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    assert attempt_rows(db_path) == []
