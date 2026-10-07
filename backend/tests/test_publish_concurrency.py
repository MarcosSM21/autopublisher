"""At most one execution per publication, guaranteed by the backend (FR-038, US5)."""

import threading
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    attempt_rows,
    create_publications,
    get_publication,
    import_one,
    make_mp4,
    set_youtube_options,
    setup_publishable,
    wait_idle,
)
from tests.fakes import FakeGoogle, InMemoryCredentialStore


def _ready(client: TestClient, fake_google: FakeGoogle) -> dict[str, Any]:
    created = setup_publishable(client, fake_google)
    set_youtube_options(client, created["publication"]["id"])
    return created


def _publish(client: TestClient, publication_id: int) -> httpx.Response:
    return client.post(f"/api/publications/{publication_id}/publish", json={})


def test_concurrent_publish_now_starts_a_single_upload(
    publishing_client: TestClient, fake_google: FakeGoogle, db_path: Path
) -> None:
    created = _ready(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    # Both requests reach the channel check before either can continue, so both
    # pass the preflight and race for the atomic transition.
    fake_google.channels_barrier = threading.Barrier(2, timeout=5)
    # The winner's upload stays in progress until both requests have answered.
    fake_google.block_uploads(at="start")
    responses: list[httpx.Response] = []

    def publish() -> None:
        responses.append(_publish(publishing_client, publication_id))

    threads = [threading.Thread(target=publish) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    fake_google.channels_barrier = None
    fake_google.release()
    wait_idle(publishing_client)

    codes = sorted(response.status_code for response in responses)
    assert codes == [202, 409]
    rejected = next(r for r in responses if r.status_code == 409)
    assert rejected.json()["error"]["code"] == "publication_in_progress"
    assert len(attempt_rows(db_path)) == 1
    assert len(fake_google.session_starts) == 1
    assert len(fake_google.videos_created) == 1


def test_publish_now_while_publishing_is_rejected(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ready(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    fake_google.block_uploads(at="chunk")
    assert _publish(publishing_client, publication_id).status_code == 202
    assert fake_google.wait_until_blocked()

    response = _publish(publishing_client, publication_id)

    fake_google.release()
    wait_idle(publishing_client)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_in_progress"
    assert len(fake_google.session_starts) == 1


@pytest.mark.parametrize("action", ["authorize", "disconnect"])
def test_connection_cannot_change_while_publishing(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
    action: str,
) -> None:
    created = _ready(publishing_client, fake_google)
    account_id = created["account"]["id"]
    fake_google.block_uploads(at="chunk")
    _publish(publishing_client, created["publication"]["id"])
    assert fake_google.wait_until_blocked()

    response = publishing_client.post(
        f"/api/accounts/{account_id}/youtube-connection/{action}"
    )

    fake_google.release()
    wait_idle(publishing_client)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_in_progress"
    assert len(credential_store.secrets) == 1
    assert get_publication(publishing_client, created["publication"]["id"])[
        "status"
    ] == ("published")


def test_two_publications_of_one_account_can_run_together(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = _ready(publishing_client, fake_google)
    other_content = import_one(
        publishing_client,
        created["project"]["id"],
        "other.mp4",
        make_mp4(payload=b"other" * 1000),
    )["content"]
    publishing_client.patch(
        f"/api/contents/{other_content['id']}", json={"title": "Second video"}
    )
    other = create_publications(
        publishing_client, other_content["id"], [created["account"]["id"]]
    )[0]
    set_youtube_options(publishing_client, other["id"])
    fake_google.block_uploads(at="chunk")
    assert _publish(publishing_client, created["publication"]["id"]).status_code == 202
    assert fake_google.wait_until_blocked()

    assert _publish(publishing_client, other["id"]).status_code == 202

    fake_google.release()
    wait_idle(publishing_client)
    for publication_id in (created["publication"]["id"], other["id"]):
        assert get_publication(publishing_client, publication_id)["status"] == (
            "published"
        )
    assert len(fake_google.videos_created) == 2


@pytest.mark.parametrize("target", ["account", "project"])
def test_deactivating_during_an_upload_does_not_cancel_it(
    publishing_client: TestClient, fake_google: FakeGoogle, target: str
) -> None:
    created = _ready(publishing_client, fake_google)
    other_content = import_one(
        publishing_client,
        created["project"]["id"],
        "other.mp4",
        make_mp4(payload=b"other" * 1000),
    )["content"]
    other = create_publications(
        publishing_client, other_content["id"], [created["account"]["id"]]
    )[0]
    fake_google.block_uploads(at="chunk")
    assert _publish(publishing_client, created["publication"]["id"]).status_code == 202
    assert fake_google.wait_until_blocked()

    path = (
        f"/api/accounts/{created['account']['id']}"
        if target == "account"
        else f"/api/projects/{created['project']['id']}"
    )
    assert publishing_client.patch(path, json={"is_active": False}).status_code == 200
    fake_google.release()
    wait_idle(publishing_client)

    publication = get_publication(publishing_client, created["publication"]["id"])
    assert publication["status"] == "published"
    assert (
        publication["latest_attempt"]["external_id"]
        == (fake_google.videos_created[0]["id"])
    )
    response = _publish(publishing_client, other["id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == f"{target}_inactive"
