"""Threads options and the exact text (contracts/api.md §2); no network."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TH_TEXT,
    create_account,
    create_publications,
    import_one,
    make_image,
    make_threads_publishing_app,
    run_sql,
    threads_image_publication,
    threads_text_publication,
    threads_video_publication,
)
from tests.fakes import (
    FAKE_DELIVERY_ACCESS_KEY,
    FAKE_DELIVERY_SECRET,
    FAKE_TH_LONG_TOKEN,
    FakeClock,
    FakeMediaDeliveryProvider,
    FakeThreads,
    InMemoryCredentialStore,
)

CONNECTION_CODES = {"threads_not_connected", "threads_reconnect_required"}


def _get(client: TestClient, publication_id: int) -> Any:
    return client.get(f"/api/publications/{publication_id}/threads-options")


def _put(client: TestClient, publication_id: int, alt_text: str | None) -> Any:
    return client.put(
        f"/api/publications/{publication_id}/threads-options",
        json={"alt_text": alt_text},
    )


def _assert_no_secrets(response: Any) -> None:
    for secret in (
        FAKE_DELIVERY_SECRET,
        FAKE_DELIVERY_ACCESS_KEY,
        FAKE_TH_LONG_TOKEN,
        "r2.cloudflarestorage.com",
        "X-Amz",
    ):
        assert secret not in response.text


def test_text_options(threads_publishing_client: TestClient) -> None:
    publication = threads_text_publication(threads_publishing_client)["publication"]

    response = _get(threads_publishing_client, publication["id"])

    assert response.status_code == 200, response.text
    assert response.json() == {
        "media_kind": "text",
        "text": TH_TEXT,
        "text_length": len(TH_TEXT) + 3,  # the rocket emoji counts 4
        "text_links": 1,
        "alt_text": None,
        "editable": True,
        "media_delivery_required": False,
        "media_delivery_configured": True,
        "problems": [],
        "limits": {
            "text_characters": 500,
            "text_links": 5,
            "alt_text_characters": 1000,
        },
    }
    _assert_no_secrets(response)


def test_problems_never_include_connection_codes(
    threads_publishing_client: TestClient,
) -> None:
    publication = threads_text_publication(
        threads_publishing_client, connect=False, description="x" * 501, hashtags=[]
    )["publication"]

    body = _get(threads_publishing_client, publication["id"]).json()

    codes = [p["code"] for p in body["problems"]]
    assert codes == ["threads_text_invalid"]
    assert not CONNECTION_CODES & set(codes)


def test_alt_text_does_not_apply_to_text(threads_publishing_client: TestClient) -> None:
    publication = threads_text_publication(threads_publishing_client)["publication"]

    response = _put(threads_publishing_client, publication["id"], "Alt")
    cleared = _put(threads_publishing_client, publication["id"], None)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "threads_option_not_applicable"
    assert error["fields"][0]["field"] == "alt_text"
    assert cleared.status_code == 200
    assert cleared.json()["alt_text"] is None


def test_image_alt_text(threads_publishing_client: TestClient) -> None:
    publication = threads_image_publication(threads_publishing_client)["publication"]

    saved = _put(threads_publishing_client, publication["id"], "  A red square  ")
    emptied = _put(threads_publishing_client, publication["id"], "   ")

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["media_kind"] == "image"
    assert body["alt_text"] == "A red square"
    assert body["text"] == "Summer drop.\n\n#cyber"
    assert body["media_delivery_required"] is True
    assert emptied.json()["alt_text"] is None
    _assert_no_secrets(saved)


def test_video_alt_text(
    threads_publishing_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = threads_video_publication(
        threads_publishing_client, monkeypatch, alt_text="A clip"
    )["publication"]

    body = _get(threads_publishing_client, publication["id"]).json()

    assert body["media_kind"] == "video"
    assert body["alt_text"] == "A clip"


def test_alt_text_limit(threads_publishing_client: TestClient) -> None:
    publication = threads_image_publication(threads_publishing_client)["publication"]

    accepted = _put(threads_publishing_client, publication["id"], "a" * 1000)
    rejected = _put(threads_publishing_client, publication["id"], "a" * 1001)

    assert accepted.status_code == 200
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "threads_alt_text_invalid"
    assert _get(threads_publishing_client, publication["id"]).json()["alt_text"] == (
        "a" * 1000
    )


def test_not_editable_statuses(
    threads_publishing_client: TestClient, db_path: Path
) -> None:
    published = threads_image_publication(threads_publishing_client)["publication"]
    cancelled = threads_image_publication(
        threads_publishing_client, project_name="Other"
    )["publication"]
    run_sql(
        db_path,
        "UPDATE publications SET status = 'published', "
        "published_at = '2026-10-13 10:00:00' WHERE id = ?",
        published["id"],
    )
    threads_publishing_client.post(f"/api/publications/{cancelled['id']}/cancel")

    for publication_id, code in (
        (published["id"], "publication_not_editable"),
        (cancelled["id"], "publication_cancelled"),
    ):
        response = _put(threads_publishing_client, publication_id, "Alt")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == code
        assert _get(threads_publishing_client, publication_id).json()["editable"] is (
            False
        )


def test_other_platforms_have_no_threads_options(
    threads_publishing_client: TestClient,
) -> None:
    publication = threads_text_publication(threads_publishing_client)["publication"]
    project_id = publication["project_id"]
    instagram = create_account(threads_publishing_client, project_id, "instagram", "ig")
    content = import_one(threads_publishing_client, project_id, "a.png", make_image())[
        "content"
    ]
    [other] = create_publications(
        threads_publishing_client, content["id"], [instagram["id"]]
    )

    responses = [
        _get(threads_publishing_client, other["id"]),
        _put(threads_publishing_client, other["id"], "Alt"),
    ]

    for response in responses:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "platform_not_supported"


def test_media_delivery_is_only_required_for_media(
    threads_publishing_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = threads_text_publication(threads_publishing_client)["publication"]
    image = threads_image_publication(threads_publishing_client, project_name="Other")[
        "publication"
    ]
    monkeypatch.setenv(
        "AUTOPUBLISHER_MEDIA_DELIVERY_FILE", str(tmp_path / "missing.json")
    )

    text_body = _get(threads_publishing_client, text["id"]).json()
    image_body = _get(threads_publishing_client, image["id"]).json()

    assert text_body["media_delivery_configured"] is False
    assert text_body["problems"] == []
    assert image_body["media_delivery_configured"] is False
    assert "media_delivery_not_configured" in {
        p["code"] for p in image_body["problems"]
    }


def test_options_survive_a_restart(
    threads_publishing_client: TestClient,
    db_path: Path,
    media_dir: Path,
    fake_clock: FakeClock,
) -> None:
    publication = threads_image_publication(threads_publishing_client)["publication"]
    _put(threads_publishing_client, publication["id"], "Kept")

    app = make_threads_publishing_app(
        db_path,
        media_dir,
        InMemoryCredentialStore(),
        FakeThreads(),
        FakeMediaDeliveryProvider(),
        fake_clock,
        [],
    )
    with TestClient(app) as restarted:
        assert _get(restarted, publication["id"]).json()["alt_text"] == "Kept"


def test_unknown_publication(threads_publishing_client: TestClient) -> None:
    assert _get(threads_publishing_client, 999).status_code == 404
