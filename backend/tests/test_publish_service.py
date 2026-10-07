"""The execution service is reusable without HTTP (FR-013) and the API never waits for
an upload to finish (SC-002)."""

import inspect

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.models import Publication
from app.publishing import start_publication
from tests.conftest import (
    get_publication,
    set_youtube_options,
    setup_publishable,
    wait_idle,
)
from tests.fakes import FakeGoogle


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
