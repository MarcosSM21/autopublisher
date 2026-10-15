"""The TikTok mode of a publication (Feature 014): `DIRECT_POST`, `INBOX_UPLOAD` or
undecided (`null`). New publications have no default; publications created before
Feature 014 are Direct Post and keep their Feature 013 readiness."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TT_INITIAL_OPTIONS,
    TT_OPTIONS,
    get_tiktok_connection,
    in_minutes,
    iso,
    run_sql,
    set_tiktok_granted_scopes,
    tiktok_inbox_publication,
    tiktok_publication,
    tiktok_ready_publication,
)
from tests.fakes import (
    TT_BASIC,
    TT_PUBLISH,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)

pytestmark = pytest.mark.usefixtures("tiktok_publishing_client")

MODE_REQUIRED = "tiktok_mode_required"


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


def _codes(problems: list[dict[str, Any]]) -> list[str]:
    return [problem["code"] for problem in problems]


def _undecided(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: Any,
) -> int:
    created = tiktok_publication(client, fake_tiktok, monkeypatch, mode=None, **kwargs)
    publication_id: int = created["publication"]["id"]
    return publication_id


def test_new_publication_has_no_mode(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _undecided(client, fake_tiktok, monkeypatch)

    body = _options(client, publication_id)

    assert body["mode"] is None
    [problem] = [p for p in body["problems"] if p["code"] == MODE_REQUIRED]
    assert problem["field"] == "mode"
    assert problem["message"] == "Choose how to send this video to TikTok."
    assert fake_tiktok.requests == []


@pytest.mark.parametrize("mode", [None, "DIRECT_POST", "INBOX_UPLOAD"])
def test_mode_is_saved_and_returned(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    mode: str | None,
) -> None:
    publication_id = _undecided(client, fake_tiktok, monkeypatch)

    response = _put(client, publication_id, mode=mode)

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == mode
    assert _options(client, publication_id)["mode"] == mode


def test_mode_is_a_required_field(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _undecided(client, fake_tiktok, monkeypatch)
    body = {key: value for key, value in TT_OPTIONS.items() if key != "mode"}

    response = client.put(
        f"/api/publications/{publication_id}/tiktok-options", json=body
    )

    assert response.status_code == 422


def test_unknown_mode_is_rejected(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _undecided(client, fake_tiktok, monkeypatch)

    response = _put(client, publication_id, mode="DRAFT")

    assert response.status_code == 422
    assert _options(client, publication_id)["mode"] is None


def test_publish_check_requires_a_mode(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _undecided(client, fake_tiktok, monkeypatch)

    response = client.get(f"/api/publications/{publication_id}/publish-check")

    assert response.status_code == 200, response.text
    assert response.json()["eligible"] is False
    assert MODE_REQUIRED in _codes(response.json()["problems"])
    assert fake_tiktok.requests == []


def test_publish_without_a_mode_sends_nothing(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _undecided(client, fake_tiktok, monkeypatch)

    response = client.post(f"/api/publications/{publication_id}/publish", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == MODE_REQUIRED
    assert fake_tiktok.requests == []


def test_arming_requires_a_mode(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    at = in_minutes(fake_clock, 5)
    publication_id = _undecided(client, fake_tiktok, monkeypatch, scheduled_at=iso(at))

    response = client.patch(
        f"/api/publications/{publication_id}", json={"auto_publish_enabled": True}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == MODE_REQUIRED
    assert error["fields"][0]["field"] == "auto_publish_enabled"
    assert fake_tiktok.requests == []


@pytest.mark.parametrize("status", ["publishing", "awaiting_user_action", "published"])
def test_mode_is_not_editable_after_sending(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    status: str,
) -> None:
    publication_id = _undecided(client, fake_tiktok, monkeypatch)
    _put(client, publication_id, mode="DIRECT_POST")
    run_sql(
        db_path,
        "UPDATE publications SET status = ?, published_at = ? WHERE id = ?",
        status,
        "2026-10-15 10:00:00" if status == "published" else None,
        publication_id,
    )

    response = _put(client, publication_id, mode="INBOX_UPLOAD")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_editable"
    assert _options(client, publication_id)["mode"] == "DIRECT_POST"


def test_migrated_direct_post_keeps_its_feature_013_problems(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    """A row inserted by migration 0013: initial values with `DIRECT_POST`."""
    migrated = tiktok_publication(client, fake_tiktok, monkeypatch)["publication"]
    undecided = _undecided(client, fake_tiktok, monkeypatch, project_name="Other")
    _put(client, undecided, **TT_INITIAL_OPTIONS, mode=None)

    migrated_problems = _codes(_options(client, migrated["id"])["problems"])

    assert MODE_REQUIRED not in migrated_problems
    # The Direct Post rules of Feature 013 still apply as before.
    assert "tiktok_privacy_required" in migrated_problems
    assert MODE_REQUIRED in _codes(_options(client, undecided)["problems"])


def test_ready_direct_post_publication_stays_eligible(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)

    response = client.get(
        f"/api/publications/{created['publication']['id']}/publish-check"
    )

    assert response.json()["eligible"] is True, response.text
    assert created["options"]["mode"] == "DIRECT_POST"
    assert created["options"]["consent"]["state"] == "valid"


# --- Upload to Inbox -----------------------------------------------------------------

INBOX_PERMISSION_MESSAGE = (
    "Upload to Inbox needs the video.upload permission. Reconnect the TikTok account."
)


def _without_video_upload(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    store: InMemoryCredentialStore,
    db_path: Path,
) -> dict[str, Any]:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    set_tiktok_granted_scopes(
        store, db_path, created["account"]["id"], [TT_BASIC, TT_PUBLISH]
    )
    return created


def test_inbox_without_video_upload_is_not_available(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    created = _without_video_upload(
        client, fake_tiktok, monkeypatch, tiktok_credential_store, db_path
    )
    publication_id = created["publication"]["id"]

    body = _options(client, publication_id)
    check = client.get(f"/api/publications/{publication_id}/publish-check").json()

    assert body["modes"] == {
        "DIRECT_POST": {"available": True, "reason": None},
        "INBOX_UPLOAD": {"available": False, "reason": INBOX_PERMISSION_MESSAGE},
    }
    [problem] = [
        p for p in body["problems"] if p["code"] == "tiktok_upload_permission_missing"
    ]
    assert problem["field"] == "mode"
    assert problem["message"] == INBOX_PERMISSION_MESSAGE
    assert check["eligible"] is False
    assert "tiktok_upload_permission_missing" in _codes(check["problems"])
    # A capability, never a connection problem.
    connection = get_tiktok_connection(client, created["account"]["id"])
    assert connection["status"] == "connected"
    assert "tiktok_reconnect_required" not in _codes(check["problems"])
    assert fake_tiktok.requests == []


def test_inbox_needs_no_post_options_caption_nor_consent(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No privacy, no AIGC answer, an empty caption and no consent.
    created = tiktok_inbox_publication(
        client, fake_tiktok, monkeypatch, description=None, hashtags=[]
    )
    publication_id = created["publication"]["id"]

    body = _options(client, publication_id)
    check = client.get(f"/api/publications/{publication_id}/publish-check").json()

    assert body["mode"] == "INBOX_UPLOAD"
    assert body["modes"]["INBOX_UPLOAD"] == {"available": True, "reason": None}
    assert body["problems"] == []
    assert check["eligible"] is True, check
    assert check["problems"] == []


def test_inbox_keeps_direct_post_options(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]

    _put(client, publication_id, mode="INBOX_UPLOAD", privacy_level="SELF_ONLY")
    body = _put(client, publication_id, mode="DIRECT_POST").json()

    # Switching modes never deletes the Direct Post options.
    assert body["privacy_level"] == "SELF_ONLY"
    assert body["mode"] == "DIRECT_POST"


def test_consent_does_not_apply_to_inbox(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    options = _options(client, publication_id)

    response = client.post(
        f"/api/publications/{publication_id}/tiktok-consent",
        json={
            "fingerprint": options["fingerprint"] or "0" * 64,
            "declaration_version": options["declaration"]["version"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_consent_not_applicable"
    assert _options(client, publication_id)["consent"]["state"] == "missing"
