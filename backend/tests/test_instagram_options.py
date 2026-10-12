"""Instagram options API (contracts/api.md): defaults, exact caption, applicability,
editability, problems and absence of provider details. No network."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    IG_CAPTION,
    allow_reels,
    create_account,
    create_project,
    import_one,
    instagram_media,
    instagram_publication,
    run_sql,
)
from tests.fakes import (
    FAKE_DELIVERY_ACCESS_KEY,
    FAKE_DELIVERY_SECRET,
    FakeMeta,
)


def _options(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/instagram-options")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _save(client: TestClient, publication_id: int, **body: Any) -> Any:
    return client.put(
        f"/api/publications/{publication_id}/instagram-options", json=body
    )


def test_defaults_and_exact_caption(ig_client: TestClient, fake_meta: FakeMeta) -> None:
    created = instagram_publication(ig_client, is_ai_generated=None)
    requests_before = len(fake_meta.requests)

    body = _options(ig_client, created["publication"]["id"])

    assert body["media_kind"] == "image"
    assert body["caption"] == IG_CAPTION
    assert "Not sent to Instagram" not in body["caption"]
    assert (body["caption_length"], body["caption_hashtags"]) == (len(IG_CAPTION), 2)
    assert body["is_ai_generated"] is None
    assert body["complete"] is False
    assert body["share_to_feed"] is None
    assert body["alt_text"] is None
    assert body["editable"] is True
    assert body["media_delivery_configured"] is True
    assert [p["code"] for p in body["problems"]] == ["instagram_options_incomplete"]
    assert body["limits"]["caption_characters"] == 2200
    assert len(fake_meta.requests) == requests_before


def test_reel_defaults_share_to_feed(
    ig_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_reels(monkeypatch)
    created = instagram_publication(ig_client, kind="reel")

    body = _options(ig_client, created["publication"]["id"])

    assert body["media_kind"] == "reel"
    assert body["share_to_feed"] is True
    assert body["alt_text"] is None


def test_save_image_options(ig_client: TestClient) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]

    response = _save(
        ig_client, publication_id, is_ai_generated=True, alt_text="  A neon sign  "
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_ai_generated"] is True
    assert body["alt_text"] == "A neon sign"
    assert body["complete"] is True
    assert (
        _save(ig_client, publication_id, is_ai_generated=True, alt_text=" ").json()[
            "alt_text"
        ]
        is None
    )


def test_save_reel_options(
    ig_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_reels(monkeypatch)
    publication_id = instagram_publication(ig_client, kind="reel")["publication"]["id"]

    body = _save(
        ig_client, publication_id, is_ai_generated=False, share_to_feed=False
    ).json()

    assert body["share_to_feed"] is False
    assert _options(ig_client, publication_id)["share_to_feed"] is False


@pytest.mark.parametrize("share_to_feed", [True, False])
def test_first_save_of_reel_options_includes_share_to_feed(
    ig_client: TestClient, monkeypatch: pytest.MonkeyPatch, share_to_feed: bool
) -> None:
    """Regression: the first save of a Reel (no stored options yet) used to pass
    share_to_feed twice and fail with 500 (found during T065)."""
    allow_reels(monkeypatch)
    publication_id = instagram_publication(
        ig_client, kind="reel", is_ai_generated=None
    )["publication"]["id"]

    response = _save(
        ig_client, publication_id, is_ai_generated=True, share_to_feed=share_to_feed
    )

    assert response.status_code == 200, response.text
    body = _options(ig_client, publication_id)
    assert (body["is_ai_generated"], body["share_to_feed"]) == (True, share_to_feed)


def test_options_not_applicable(
    ig_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_reels(monkeypatch)
    image_id = instagram_publication(ig_client)["publication"]["id"]
    reel_id = instagram_publication(ig_client, kind="reel", project_name="Reels")[
        "publication"
    ]["id"]

    share = _save(ig_client, image_id, is_ai_generated=True, share_to_feed=True)
    alt = _save(ig_client, reel_id, is_ai_generated=True, alt_text="Text")

    assert share.status_code == 422
    assert share.json()["error"]["code"] == "instagram_option_not_applicable"
    assert share.json()["error"]["fields"][0]["field"] == "share_to_feed"
    assert alt.status_code == 422
    assert alt.json()["error"]["fields"][0]["field"] == "alt_text"


@pytest.mark.parametrize(
    "body",
    [
        {"is_ai_generated": True, "alt_text": "a" * 1001},
        {"is_ai_generated": "maybe"},
        {"is_ai_generated": True, "extra": 1},
        {},
    ],
)
def test_invalid_bodies(ig_client: TestClient, body: dict[str, Any]) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]

    response = _save(ig_client, publication_id, **body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("publishing", "publication_not_editable"),
        ("published", "publication_not_editable"),
        ("cancelled", "publication_cancelled"),
    ],
)
def test_not_editable(
    ig_client: TestClient, db_path: Path, status: str, code: str
) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]
    published_at = "'2026-10-09 10:00:00'" if status == "published" else "NULL"
    run_sql(
        db_path,
        f"UPDATE publications SET status = ?, published_at = {published_at} "
        "WHERE id = ?",
        status,
        publication_id,
    )

    response = _save(ig_client, publication_id, is_ai_generated=True)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert _options(ig_client, publication_id)["editable"] is False


def test_other_platforms_have_no_instagram_options(ig_client: TestClient) -> None:
    project = create_project(ig_client, "Tube")
    account = create_account(ig_client, project["id"], "youtube", "tube")
    name, data = instagram_media("jpeg")
    content = import_one(ig_client, project["id"], name, data)["content"]
    publication = ig_client.post(
        f"/api/contents/{content['id']}/publications",
        json={"account_ids": [account["id"]]},
    ).json()[0]

    response = ig_client.get(f"/api/publications/{publication['id']}/instagram-options")
    saved = _save(ig_client, publication["id"], is_ai_generated=True)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "platform_not_supported"
    assert saved.status_code == 409
    assert ig_client.get("/api/publications/999/instagram-options").status_code == 404


def test_problems_list_local_issues(ig_client: TestClient) -> None:
    # 30 hashtags in the content plus one in the description: 31 in the caption.
    created = instagram_publication(
        ig_client,
        kind="wide",
        description="Summer #extra",
        hashtags=[f"t{i}" for i in range(30)],
    )

    codes = {
        p["code"] for p in _options(ig_client, created["publication"]["id"])["problems"]
    }

    assert codes == {"instagram_image_incompatible", "instagram_caption_invalid"}


def test_delivery_not_configured_is_reported(
    ig_client: TestClient, media_delivery_file: Path
) -> None:
    media_delivery_file.unlink()
    publication_id = instagram_publication(ig_client)["publication"]["id"]

    body = _options(ig_client, publication_id)

    assert body["media_delivery_configured"] is False
    assert "media_delivery_not_configured" in {p["code"] for p in body["problems"]}


def test_no_provider_configuration_in_responses(ig_client: TestClient) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]

    text = ig_client.get(f"/api/publications/{publication_id}/instagram-options").text

    for secret in (FAKE_DELIVERY_SECRET, FAKE_DELIVERY_ACCESS_KEY, "r2.cloudflare"):
        assert secret not in text


def test_options_persist_after_restart(
    ig_client: TestClient,
    db_path: Path,
    media_dir: Path,
) -> None:
    publication_id = instagram_publication(ig_client)["publication"]["id"]
    _save(ig_client, publication_id, is_ai_generated=True, alt_text="Persisted")

    from app.main import create_app
    from tests.fakes import InMemoryCredentialStore

    with TestClient(
        create_app(
            db_path, media_dir, instagram_credential_store=InMemoryCredentialStore()
        )
    ) as restarted:
        body = _options(restarted, publication_id)

    assert (body["is_ai_generated"], body["alt_text"]) == (True, "Persisted")
