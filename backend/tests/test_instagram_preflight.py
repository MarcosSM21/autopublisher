"""Every detectable problem fails before any publishing or media delivery effect;
only safe reads (credential, identity, quota, previous container) are allowed
(US4, FR-031-FR-035, research.md §10)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.media import StreamInfo, VideoStreams
from tests.conftest import (
    VALID_REEL_STREAMS,
    allow_reels,
    get_publication,
    instagram_publication,
    run_sql,
    stored_file,
)
from tests.fakes import FakeMediaDeliveryProvider, FakeMeta, InMemoryCredentialStore


def _publish(client: TestClient, publication_id: int, **body: Any) -> Any:
    return client.post(f"/api/publications/{publication_id}/publish", json=body)


def _assert_no_effects(
    client: TestClient,
    publication_id: int,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    assert get_publication(client, publication_id)["status"] != "publishing"
    assert get_publication(client, publication_id)["attempt_count"] == 0
    assert fake_delivery.put_calls == []
    assert fake_meta.requests_for("create") == []
    assert fake_meta.requests_for("publish") == []


def _rejected(response: Any, code: str, status: int = 409) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


# --- Local problems ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        ({"is_ai_generated": None}, "instagram_options_incomplete"),
        ({"kind": "wide"}, "instagram_image_incompatible"),
        ({"kind": "webm"}, "instagram_video_incompatible"),
        ({"kind": "reel"}, "instagram_media_unverifiable"),
        ({"connect": False}, "instagram_not_connected"),
    ],
)
def test_local_problems_block_publishing(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    setup: dict[str, Any],
    code: str,
) -> None:
    created = instagram_publication(ig_client, **setup)
    publication_id = created["publication"]["id"]

    response = _publish(ig_client, publication_id)

    _rejected(response, code)
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


def test_invalid_caption_blocks_publishing(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    created = instagram_publication(ig_client, description="x" * 2201, hashtags=[])
    publication_id = created["publication"]["id"]

    response = _publish(ig_client, publication_id)

    _rejected(response, "instagram_caption_invalid")
    assert response.json()["error"]["fields"][0]["field"] == "caption"
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


def test_missing_file_blocks_publishing(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
    media_dir: Path,
) -> None:
    created = instagram_publication(ig_client)
    stored_file(media_dir, db_path, created["content"]["id"]).unlink()
    publication_id = created["publication"]["id"]

    _rejected(_publish(ig_client, publication_id), "media_unavailable")
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


def test_delivery_not_configured_blocks_publishing(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    media_delivery_file: Path,
) -> None:
    created = instagram_publication(ig_client)
    media_delivery_file.unlink()
    publication_id = created["publication"]["id"]

    response = _publish(ig_client, publication_id)

    _rejected(response, "media_delivery_not_configured", 503)
    assert "docs/instagram-publishing.md" in response.json()["error"]["message"]
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


@pytest.mark.parametrize(
    ("statement", "code"),
    [
        ("UPDATE projects SET is_active = 0", "project_inactive"),
        ("UPDATE accounts SET is_active = 0", "account_inactive"),
        (
            "UPDATE instagram_connections SET status = 'reconnect_required'",
            "instagram_reconnect_required",
        ),
    ],
)
def test_inactive_or_disconnected_blocks_publishing(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
    statement: str,
    code: str,
) -> None:
    created = instagram_publication(ig_client)
    run_sql(db_path, statement)
    publication_id = created["publication"]["id"]

    _rejected(_publish(ig_client, publication_id), code)
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


# --- Reels ---------------------------------------------------------------------------


def _stream(**values: Any) -> VideoStreams:
    video = StreamInfo(**{**VALID_REEL_STREAMS.streams[0].__dict__, **values})
    return VideoStreams(
        format_names=VALID_REEL_STREAMS.format_names,
        duration_seconds=VALID_REEL_STREAMS.duration_seconds,
        size_bytes=VALID_REEL_STREAMS.size_bytes,
        bit_rate=VALID_REEL_STREAMS.bit_rate,
        streams=(video, VALID_REEL_STREAMS.streams[1]),
    )


@pytest.mark.parametrize(
    ("streams", "fragment"),
    [
        (_stream(codec_name="vp9"), "H.264 or HEVC"),
        (_stream(frame_rate=15.0), "23 and 60 FPS"),
        (_stream(field_order="tt"), "progressive"),
        (_stream(width=3840, height=2160), "1920 pixels"),
    ],
)
def test_incompatible_reels_fail_before_any_upload(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    monkeypatch: pytest.MonkeyPatch,
    streams: VideoStreams,
    fragment: str,
) -> None:
    allow_reels(monkeypatch, streams)
    created = instagram_publication(ig_client, kind="reel")
    publication_id = created["publication"]["id"]

    response = _publish(ig_client, publication_id)

    _rejected(response, "instagram_video_incompatible")
    assert fragment in response.json()["error"]["message"]
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


def test_reel_without_fast_start_is_rejected(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allow_reels(monkeypatch)
    from app import media

    monkeypatch.setattr(media, "moov_before_mdat", lambda path: False)
    created = instagram_publication(ig_client, kind="reel")

    response = _publish(ig_client, created["publication"]["id"])

    _rejected(response, "instagram_video_incompatible")
    assert "moov" in response.json()["error"]["message"]
    assert fake_delivery.put_calls == []


# --- Reads allowed during preflight --------------------------------------------------


def test_quota_reached_blocks_before_any_effect(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    fake_meta.quota = (50, 50)
    created = instagram_publication(ig_client)
    publication_id = created["publication"]["id"]

    response = _publish(ig_client, publication_id)

    _rejected(response, "instagram_publishing_limit_reached")
    assert len(fake_meta.requests_for("limit")) == 1
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


def test_meta_quota_value_is_the_source_of_truth(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    fake_meta.quota = (99, 100)  # Not the 50 of some documentation pages.
    created = instagram_publication(ig_client)

    response = _publish(ig_client, created["publication"]["id"])

    assert response.status_code == 202


@pytest.mark.parametrize("fault", ["server_error", "bad_json"])
def test_unreadable_quota_does_not_block(
    ig_client: TestClient, fake_meta: FakeMeta, fault: str
) -> None:
    fake_meta.faults["limit"] = fault
    created = instagram_publication(ig_client)
    publication_id = created["publication"]["id"]

    response = _publish(ig_client, publication_id)

    assert response.status_code == 202
    from tests.conftest import wait_idle

    wait_idle(ig_client)
    attempt = get_publication(ig_client, publication_id)["latest_attempt"]
    assert attempt["submitted"]["quota_checked"] is False


def test_unexpected_quota_shape_is_not_checked(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    fake_meta.quota = None
    created = instagram_publication(ig_client)

    assert _publish(ig_client, created["publication"]["id"]).status_code == 202


def test_identity_mismatch_blocks_publishing(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    created = instagram_publication(ig_client)
    fake_meta.set_identity(user_id="17841499999999999", username="other")
    publication_id = created["publication"]["id"]

    _rejected(_publish(ig_client, publication_id), "instagram_identity_mismatch")
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


def test_missing_credential_requires_reconnection(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    instagram_credential_store: InMemoryCredentialStore,
) -> None:
    created = instagram_publication(ig_client)
    instagram_credential_store.secrets.clear()
    publication_id = created["publication"]["id"]

    _rejected(_publish(ig_client, publication_id), "instagram_reconnect_required")
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)


def test_meta_unavailable_during_preflight_has_no_effects(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    created = instagram_publication(ig_client)
    fake_meta.faults["me"] = "server_error"
    publication_id = created["publication"]["id"]

    _rejected(_publish(ig_client, publication_id), "instagram_unavailable", 503)
    _assert_no_effects(ig_client, publication_id, fake_meta, fake_delivery)
    connection = ig_client.get(
        f"/api/accounts/{created['account']['id']}/instagram-connection"
    ).json()
    assert connection["status"] == "connected"


def test_execution_already_running_is_rejected(
    ig_client: TestClient, db_path: Path
) -> None:
    created = instagram_publication(ig_client)
    publication_id = created["publication"]["id"]
    run_sql(db_path, "UPDATE publications SET status = 'publishing'")

    _rejected(_publish(ig_client, publication_id), "publication_in_progress")


# --- publish-check -------------------------------------------------------------------


def test_publish_check_lists_problems_without_network(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    created = instagram_publication(ig_client, kind="wide", is_ai_generated=None)
    before = len(fake_meta.requests)

    check = ig_client.get(
        f"/api/publications/{created['publication']['id']}/publish-check"
    ).json()

    codes = {p["code"] for p in check["problems"]}
    assert codes == {"instagram_image_incompatible", "instagram_options_incomplete"}
    labels = [item["label"] for item in check["summary"]]
    assert labels[:4] == ["Post type", "Instagram account", "Caption", "AI-generated"]
    assert len(fake_meta.requests) == before
