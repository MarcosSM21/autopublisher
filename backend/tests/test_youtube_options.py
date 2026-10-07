"""YouTube options of a publication (US2, FR-018–FR-022)."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import (
    create_account,
    create_publications,
    get_publication,
    publish_and_wait,
    run_sql,
    set_youtube_options,
    setup_publishable,
)
from tests.fakes import FakeGoogle, InMemoryCredentialStore

DEFAULTS = {
    "privacy_status": "private",
    "made_for_kids": None,
    "contains_synthetic_media": None,
    "notify_subscribers": False,
    "complete": False,
    "editable": True,
}


def _url(publication_id: int) -> str:
    return f"/api/publications/{publication_id}/youtube-options"


def test_defaults_without_stored_options(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = setup_publishable(publishing_client, fake_google)

    response = publishing_client.get(_url(created["publication"]["id"]))

    assert response.status_code == 200
    assert response.json() == DEFAULTS


def test_options_are_saved_idempotently(
    publishing_client: TestClient, fake_google: FakeGoogle, db_path: Path
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    body = {
        "privacy_status": "unlisted",
        "made_for_kids": False,
        "contains_synthetic_media": True,
        "notify_subscribers": True,
    }

    first = publishing_client.put(_url(publication_id), json=body).json()
    second = publishing_client.put(_url(publication_id), json=body).json()

    assert first == second == {**body, "complete": True, "editable": True}
    assert publishing_client.get(_url(publication_id)).json() == first


def test_null_resets_a_declaration(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    set_youtube_options(publishing_client, publication_id)

    options = set_youtube_options(publishing_client, publication_id, made_for_kids=None)

    assert options["made_for_kids"] is None
    assert options["complete"] is False


def test_options_belong_to_one_publication(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    other_account = create_account(
        publishing_client, created["project"]["id"], "youtube", "second"
    )
    other = create_publications(
        publishing_client, created["content"]["id"], [other_account["id"]]
    )[0]

    set_youtube_options(
        publishing_client, created["publication"]["id"], privacy_status="public"
    )

    assert publishing_client.get(_url(other["id"])).json() == DEFAULTS


@pytest.mark.parametrize(
    "body",
    [
        {"privacy_status": "friends"},
        {"made_for_kids": "maybe"},
        {"extra": True},
        {},
    ],
    ids=["privacy", "declaration", "extra", "missing"],
)
def test_invalid_bodies_are_rejected(
    publishing_client: TestClient, fake_google: FakeGoogle, body: dict[str, Any]
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    complete = {
        "privacy_status": "private",
        "made_for_kids": False,
        "contains_synthetic_media": False,
        "notify_subscribers": False,
    }
    payload = {} if body == {} else {**complete, **body}

    response = publishing_client.put(_url(created["publication"]["id"]), json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_non_youtube_publications_have_no_options(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    instagram = create_account(
        publishing_client, created["project"]["id"], "instagram", "cyber"
    )
    publication = create_publications(
        publishing_client, created["content"]["id"], [instagram["id"]]
    )[0]

    response = publishing_client.get(_url(publication["id"]))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_not_supported"
    assert publishing_client.get(_url(999)).status_code == 404


@pytest.mark.parametrize(
    ("status", "editable"),
    [
        ("unscheduled", True),
        ("scheduled", True),
        ("failed", True),
        ("publishing", False),
        ("published", False),
        ("cancelled", False),
    ],
)
def test_options_are_editable_only_before_publishing(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    status: str,
    editable: bool,
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    scheduled_at = "2100-01-01 10:00:00" if status == "scheduled" else None
    published_at = "2026-10-07 10:00:00" if status == "published" else None
    run_sql(
        db_path,
        "UPDATE publications SET status = ?, scheduled_at = ?, published_at = ?",
        status,
        scheduled_at,
        published_at,
    )

    read = publishing_client.get(_url(publication_id)).json()
    response = publishing_client.put(
        _url(publication_id),
        json={
            "privacy_status": "public",
            "made_for_kids": False,
            "contains_synthetic_media": False,
            "notify_subscribers": False,
        },
    )

    assert read["editable"] is editable
    if editable:
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "publication_not_editable"


def test_options_survive_a_restart(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    media_dir: Path,
    credential_store: InMemoryCredentialStore,
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    saved = set_youtube_options(
        publishing_client, publication_id, privacy_status="unlisted"
    )

    app = create_app(db_path, media_dir, credential_store=credential_store)
    with TestClient(app) as restarted:
        assert restarted.get(_url(publication_id)).json() == saved


@pytest.mark.parametrize("missing", ["made_for_kids", "contains_synthetic_media"])
def test_missing_declarations_block_publishing(
    publishing_client: TestClient, fake_google: FakeGoogle, missing: str
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    set_youtube_options(publishing_client, publication_id, **{missing: None})

    response = publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "youtube_options_incomplete"
    assert [entry["field"] for entry in error["fields"]] == [missing]
    assert fake_google.upload_requests == []
    assert get_publication(publishing_client, publication_id)["status"] == (
        "unscheduled"
    )


@pytest.mark.parametrize("value", [True, False])
def test_declarations_are_sent_to_youtube(
    publishing_client: TestClient, fake_google: FakeGoogle, value: bool
) -> None:
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    set_youtube_options(
        publishing_client,
        publication_id,
        made_for_kids=value,
        contains_synthetic_media=not value,
        notify_subscribers=value,
    )

    publish_and_wait(publishing_client, publication_id)

    start = fake_google.session_starts[0]
    status = json.loads(start.content)["status"]
    assert status["selfDeclaredMadeForKids"] is value
    assert status["containsSyntheticMedia"] is (not value)
    params = parse_qs(urlsplit(start.url).query)
    assert params["notifySubscribers"] == ["true" if value else "false"]
