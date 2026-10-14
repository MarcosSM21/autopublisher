"""`POST /api/publications/{id}/tiktok-consent` (contracts §4) and the invalidation of
a consent by any material change (research §6). No network."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    LATER,
    TT_OPTIONS,
    run_sql,
    tiktok_publication,
    tiktok_ready,
)
from tests.fakes import FakeClock, FakeTikTok


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


@pytest.fixture
def created(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    return tiktok_publication(client, fake_tiktok, monkeypatch)


def _options(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/tiktok-options")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _consent(client: TestClient, publication_id: int, **body: Any) -> Any:
    return client.post(f"/api/publications/{publication_id}/tiktok-consent", json=body)


def test_consent_is_stored_when_it_matches(
    client: TestClient,
    created: dict[str, Any],
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id = created["publication"]["id"]

    body = tiktok_ready(client, publication_id)

    assert body["consent"]["state"] == "valid"
    assert body["consent"]["consented_at"] is not None
    assert body["problems"] == []
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT consent_fingerprint, consent_declaration_version, consented_at "
            "FROM tiktok_publication_options"
        ).fetchone()
    assert row[0] == body["fingerprint"]
    assert row[1] == "music-usage-2026-10-14"
    assert row[2] is not None
    assert fake_tiktok.requests == []


def test_a_different_fingerprint_or_version_is_stale(
    client: TestClient, created: dict[str, Any]
) -> None:
    publication_id = created["publication"]["id"]
    saved = client.put(
        f"/api/publications/{publication_id}/tiktok-options", json=TT_OPTIONS
    ).json()

    wrong_fingerprint = _consent(
        client,
        publication_id,
        fingerprint="0" * 64,
        declaration_version=saved["declaration"]["version"],
    )
    wrong_version = _consent(
        client,
        publication_id,
        fingerprint=saved["fingerprint"],
        declaration_version="branded-music-usage-2026-10-14",
    )

    for response in (wrong_fingerprint, wrong_version):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "tiktok_consent_stale"
    assert _options(client, publication_id)["consent"]["state"] == "missing"


@pytest.mark.parametrize(
    "values",
    [
        {"privacy_level": None},
        {"is_aigc": None},
        {"commercial_disclosure_enabled": True},
    ],
)
def test_incomplete_options_cannot_be_consented(
    client: TestClient, created: dict[str, Any], values: dict[str, Any]
) -> None:
    publication_id = created["publication"]["id"]
    client.put(
        f"/api/publications/{publication_id}/tiktok-options",
        json={**TT_OPTIONS, **values},
    )

    response = _consent(
        client,
        publication_id,
        fingerprint="0" * 64,
        declaration_version="music-usage-2026-10-14",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_options_incomplete"


def test_no_options_row_cannot_be_consented(
    client: TestClient, created: dict[str, Any]
) -> None:
    response = _consent(
        client,
        created["publication"]["id"],
        fingerprint="0" * 64,
        declaration_version="music-usage-2026-10-14",
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_options_incomplete"


def test_consent_needs_a_connected_account(
    client: TestClient, created: dict[str, Any], db_path: Path
) -> None:
    publication_id = created["publication"]["id"]
    saved = client.put(
        f"/api/publications/{publication_id}/tiktok-options", json=TT_OPTIONS
    ).json()
    run_sql(db_path, "UPDATE tiktok_connections SET status = 'reconnect_required'")

    response = _consent(
        client,
        publication_id,
        fingerprint=saved["fingerprint"],
        declaration_version=saved["declaration"]["version"],
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_reconnect_required"


def test_consent_is_rejected_while_publishing(
    client: TestClient, created: dict[str, Any], db_path: Path
) -> None:
    publication_id = created["publication"]["id"]
    saved = client.put(
        f"/api/publications/{publication_id}/tiktok-options", json=TT_OPTIONS
    ).json()
    run_sql(db_path, "UPDATE publications SET status = 'publishing'")

    response = _consent(
        client,
        publication_id,
        fingerprint=saved["fingerprint"],
        declaration_version=saved["declaration"]["version"],
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"


def _put_options(**values: Any) -> Callable[[TestClient, dict[str, Any], Path], None]:
    def change(client: TestClient, created: dict[str, Any], db_path: Path) -> None:
        response = client.put(
            f"/api/publications/{created['publication']['id']}/tiktok-options",
            json={**TT_OPTIONS, **values},
        )
        assert response.status_code == 200, response.text

    return change


def _patch_publication(
    **values: Any,
) -> Callable[[TestClient, dict[str, Any], Path], None]:
    def change(client: TestClient, created: dict[str, Any], db_path: Path) -> None:
        response = client.patch(
            f"/api/publications/{created['publication']['id']}", json=values
        )
        assert response.status_code == 200, response.text

    return change


def _patch_content(**values: Any) -> Callable[[TestClient, dict[str, Any], Path], None]:
    def change(client: TestClient, created: dict[str, Any], db_path: Path) -> None:
        response = client.patch(
            f"/api/contents/{created['content']['id']}", json=values
        )
        assert response.status_code == 200, response.text

    return change


def _sql(statement: str) -> Callable[[TestClient, dict[str, Any], Path], None]:
    def change(client: TestClient, created: dict[str, Any], db_path: Path) -> None:
        run_sql(db_path, statement)

    return change


MATERIAL_CHANGES = {
    "description_override": _patch_publication(description_override="Other text"),
    "hashtags_override": _patch_publication(hashtags_override=["other"]),
    "content_description": _patch_content(description="New content text"),
    "content_hashtags": _patch_content(hashtags=["new"]),
    "privacy": _put_options(privacy_level="FOLLOWER_OF_CREATOR"),
    "allow_comment": _put_options(allow_comment=True),
    "allow_duet": _put_options(allow_duet=True),
    "allow_stitch": _put_options(allow_stitch=True),
    "your_brand": _put_options(
        commercial_disclosure_enabled=True, brand_organic_toggle=True
    ),
    "branded_content": _put_options(
        privacy_level="FOLLOWER_OF_CREATOR",
        commercial_disclosure_enabled=True,
        brand_content_toggle=True,
    ),
    "aigc": _put_options(is_aigc=True),
    "open_id": _sql("UPDATE tiktok_connections SET open_id = 'another-open-id'"),
    "video_checksum": _sql(f"UPDATE contents SET checksum = '{'b' * 64}'"),
}


@pytest.mark.parametrize("change", MATERIAL_CHANGES.values(), ids=MATERIAL_CHANGES)
def test_material_changes_make_the_consent_stale(
    client: TestClient,
    created: dict[str, Any],
    db_path: Path,
    change: Callable[[TestClient, dict[str, Any], Path], None],
) -> None:
    publication_id = created["publication"]["id"]
    tiktok_ready(client, publication_id)

    change(client, created, db_path)

    body = _options(client, publication_id)
    assert body["consent"]["state"] == "stale"


def test_overridden_content_metadata_does_not_matter(
    client: TestClient, created: dict[str, Any], db_path: Path
) -> None:
    publication_id = created["publication"]["id"]
    _patch_publication(description_override="Fixed", hashtags_override=["fixed"])(
        client, created, db_path
    )
    tiktok_ready(client, publication_id)

    _patch_content(description="Not used anymore", hashtags=["unused"])(
        client, created, db_path
    )

    assert _options(client, publication_id)["consent"]["state"] == "valid"


@pytest.mark.parametrize(
    "change",
    [
        _patch_publication(scheduled_at=LATER),
        _patch_publication(title_override="Another generic title"),
        _patch_content(title="Another content title"),
    ],
    ids=["scheduled_at", "title_override", "content_title"],
)
def test_date_and_title_keep_the_consent(
    client: TestClient,
    created: dict[str, Any],
    db_path: Path,
    change: Callable[[TestClient, dict[str, Any], Path], None],
) -> None:
    publication_id = created["publication"]["id"]
    tiktok_ready(client, publication_id)

    change(client, created, db_path)

    assert _options(client, publication_id)["consent"]["state"] == "valid"


def test_reconfirming_makes_it_valid_again(
    client: TestClient, created: dict[str, Any], db_path: Path, fake_tiktok: FakeTikTok
) -> None:
    publication_id = created["publication"]["id"]
    first = tiktok_ready(client, publication_id)
    _put_options(allow_comment=True)(client, created, db_path)
    assert _options(client, publication_id)["consent"]["state"] == "stale"

    second = tiktok_ready(client, publication_id, allow_comment=True)

    assert second["consent"]["state"] == "valid"
    assert second["fingerprint"] != first["fingerprint"]
    assert fake_tiktok.requests == []
