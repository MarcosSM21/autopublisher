"""The caption shown in `tiktok-options` is exactly what would be sent (contracts §1,
spec US3): publication overrides, else the content metadata; never the title; never
truncated."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import run_sql, tiktok_publication
from tests.fakes import FakeTikTok


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _options(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/tiktok-options")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_caption_follows_the_content_and_never_the_title(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(
        client, fake_tiktok, monkeypatch, description="Hello 😀", hashtags=["a", "b"]
    )

    body = _options(client, created["publication"]["id"])

    assert body["caption"] == "Hello 😀\n\n#a #b"
    assert body["caption_length"] == 15
    assert "Not sent to TikTok" not in body["caption"]


def test_publication_overrides_change_the_caption(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]

    response = client.patch(
        f"/api/publications/{publication_id}",
        json={
            "description_override": "Only for TikTok",
            "hashtags_override": [],
            "title_override": "Still not sent",
        },
    )
    assert response.status_code == 200, response.text

    body = _options(client, publication_id)
    assert body["caption"] == "Only for TikTok"
    assert body["caption_length"] == len("Only for TikTok")


def test_empty_caption(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(
        client, fake_tiktok, monkeypatch, description=None, hashtags=[]
    )

    body = _options(client, created["publication"]["id"])

    assert body["caption"] == ""
    assert body["caption_length"] == 0
    assert "tiktok_caption_invalid" not in [p["code"] for p in body["problems"]]


def test_too_long_caption_is_reported_never_truncated(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    caption = "😀" * 1100 + "a"
    client.patch(
        f"/api/publications/{publication_id}",
        json={"description_override": caption, "hashtags_override": []},
    )

    body = _options(client, publication_id)

    assert body["caption"] == caption
    assert body["caption_length"] == 2201
    [problem] = [p for p in body["problems"] if p["code"] == "tiktok_caption_invalid"]
    assert "2201" in problem["message"]
    assert "2200" in problem["message"]
    assert problem["field"] == "caption"


@pytest.mark.parametrize("status", ["publishing", "published"])
def test_caption_cannot_be_edited_while_publishing_or_published(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    status: str,
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    run_sql(
        db_path,
        "UPDATE publications SET status = ?, published_at = ? WHERE id = ?",
        status,
        "2026-10-14 10:00:00" if status == "published" else None,
        publication_id,
    )

    response = client.patch(
        f"/api/publications/{publication_id}", json={"description_override": "x"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    assert _options(client, publication_id)["caption"] != "x"
