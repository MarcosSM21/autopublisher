"""`GET`/`PUT /api/publications/{id}/tiktok-options` (contracts §1–§2): no network,
nothing preselected, full replacement, structural rules and editability."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FUTURE,
    TT_CAPTION,
    TT_OPTIONS,
    create_publications,
    import_one,
    make_image,
    run_sql,
    setup_project,
    tiktok_publication,
)
from tests.fakes import FAKE_TT_ACCESS_TOKEN, FAKE_TT_UPLOAD_TOKEN, FakeTikTok

pytestmark = pytest.mark.usefixtures("tiktok_publishing_client")


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _options(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/tiktok-options")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _put(client: TestClient, publication_id: int, **values: Any) -> Any:
    return client.put(
        f"/api/publications/{publication_id}/tiktok-options",
        json={**TT_OPTIONS, **values},
    )


def test_initial_values_without_a_row(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]

    body = _options(client, publication["id"])

    assert body["privacy_level"] is None
    assert body["is_aigc"] is None
    assert body["allow_comment"] is body["allow_duet"] is body["allow_stitch"] is False
    assert body["commercial_disclosure_enabled"] is False
    assert body["brand_organic_toggle"] is body["brand_content_toggle"] is False
    assert body["client_audited"] is False
    assert body["allowed_privacy_levels"] == ["SELF_ONLY"]
    assert body["caption"] == TT_CAPTION
    assert body["caption_length"] == len(TT_CAPTION)
    assert body["caption_max_length"] == 2200
    assert body["declaration"]["version"] == "music-usage-2026-10-14"
    assert body["declaration"]["text"] == (
        "By posting, you agree to TikTok's Music Usage Confirmation."
    )
    assert body["declaration"]["links"][0]["label"] == "Music Usage Confirmation"
    assert body["labels"] == []
    assert body["fingerprint"] is None
    assert body["consent"] == {"state": "missing", "consented_at": None}
    assert body["integrity_warning"] is None
    assert [p["code"] for p in body["problems"]] == [
        "tiktok_privacy_required",
        "tiktok_aigc_required",
    ]
    assert body["video"] == {
        "format": "mp4",
        "size_bytes": body["video"]["size_bytes"],
        "duration_seconds": 12.4,
        "width": 1080,
        "height": 1920,
        "frame_rate": 30.0,
        "delegated_checks": [],
        "chunk_count": 1,
    }
    assert body["editable"] is True
    assert fake_tiktok.requests == []


def test_put_replaces_every_option(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]

    response = _put(client, publication["id"], allow_comment=True, is_aigc=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["privacy_level"] == "SELF_ONLY"
    assert body["allow_comment"] is True
    assert body["is_aigc"] is True
    assert body["problems"] == [
        {
            "code": "tiktok_consent_required",
            "message": body["problems"][0]["message"],
            "field": "consent",
        }
    ]
    assert body["fingerprint"] is not None and len(body["fingerprint"]) == 64
    assert body["consent"]["state"] == "missing"

    second = _put(client, publication["id"], privacy_level=None, is_aigc=None)

    assert second.status_code == 200
    assert second.json()["privacy_level"] is None
    assert second.json()["allow_comment"] is False
    assert second.json()["fingerprint"] is None
    assert _options(client, publication["id"]) == second.json()
    assert fake_tiktok.requests == []


def test_every_field_is_required(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]
    body = dict(TT_OPTIONS)
    del body["allow_duet"]

    response = client.put(
        f"/api/publications/{publication['id']}/tiktok-options", json=body
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "values",
    [
        {"brand_organic_toggle": True},
        {"brand_content_toggle": True, "privacy_level": "FOLLOWER_OF_CREATOR"},
        {"privacy_level": "EVERYONE"},
    ],
)
def test_structural_errors(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, Any],
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]

    response = _put(client, publication["id"], **values)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_branded_content_cannot_be_private(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]

    response = _put(
        client,
        publication["id"],
        commercial_disclosure_enabled=True,
        brand_content_toggle=True,
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "tiktok_branded_content_private"
    assert error["message"] == "Branded content visibility cannot be set to private."
    assert error["fields"][0]["field"] == "brand_content_toggle"


def test_disclosure_without_toggle_is_saved_but_not_publishable(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]

    response = _put(client, publication["id"], commercial_disclosure_enabled=True)

    assert response.status_code == 200
    body = response.json()
    assert body["commercial_disclosure_enabled"] is True
    assert [p["code"] for p in body["problems"]] == ["tiktok_disclosure_incomplete"]
    assert body["fingerprint"] is None


def test_labels_and_branded_declaration(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]

    your_brand = _put(
        client,
        publication["id"],
        commercial_disclosure_enabled=True,
        brand_organic_toggle=True,
    ).json()
    branded = _put(
        client,
        publication["id"],
        privacy_level="FOLLOWER_OF_CREATOR",
        commercial_disclosure_enabled=True,
        brand_content_toggle=True,
    ).json()

    assert your_brand["labels"] == [
        "Your video will be labeled as 'Promotional content'"
    ]
    assert your_brand["declaration"]["version"] == "music-usage-2026-10-14"
    assert branded["labels"] == ["Your video will be labeled as 'Paid partnership'"]
    assert branded["declaration"]["version"] == "branded-music-usage-2026-10-14"
    assert [p["code"] for p in branded["problems"]] == ["tiktok_privacy_not_allowed"]


@pytest.mark.parametrize("status", ["publishing", "published"])
def test_not_editable_while_publishing_or_published(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Any,
    status: str,
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]
    run_sql(
        db_path,
        "UPDATE publications SET status = ?, published_at = ? WHERE id = ?",
        status,
        "2026-10-14 10:00:00" if status == "published" else None,
        publication["id"],
    )

    response = _put(client, publication["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    assert _options(client, publication["id"])["editable"] is False


def test_editable_when_scheduled_or_failed(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(
        client, fake_tiktok, monkeypatch, scheduled_at=FUTURE
    )["publication"]

    assert _put(client, publication["id"]).status_code == 200


def test_other_platforms_are_rejected(client: TestClient) -> None:
    _, content, accounts = setup_project(client, platforms=("x",))
    publication = create_publications(client, content["id"], [accounts[0]["id"]])[0]

    for response in (
        client.get(f"/api/publications/{publication['id']}/tiktok-options"),
        _put(client, publication["id"]),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "platform_not_supported"


def test_photos_are_rejected(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    project_id = created["account"]["project_id"]
    image = import_one(client, project_id, "photo.png", make_image())["content"]
    publication = create_publications(client, image["id"], [created["account"]["id"]])[
        0
    ]

    response = client.get(f"/api/publications/{publication['id']}/tiktok-options")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_video_required"


def test_unknown_publication(client: TestClient) -> None:
    assert client.get("/api/publications/999/tiktok-options").status_code == 404


def test_no_secret_nor_publish_id_in_responses(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]

    text = (
        _put(client, publication["id"]).text
        + client.get(f"/api/publications/{publication['id']}/tiktok-options").text
    )

    for forbidden in (
        "publish_id",
        "upload_url",
        FAKE_TT_UPLOAD_TOKEN,
        FAKE_TT_ACCESS_TOKEN,
    ):
        assert forbidden not in text
