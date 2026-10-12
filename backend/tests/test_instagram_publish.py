"""Publishing images and Reels on Instagram end to end with the fake Meta and the fake
media delivery provider (US1, US2, US3; research.md §1-§8, §13-§14)."""

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import (
    IG_CAPTION,
    allow_reels,
    attempt_rows,
    get_publication,
    instagram_publication,
    instagram_run_rows,
    publish_and_wait,
    stored_file,
    temporary_media_rows,
)
from tests.fakes import FAKE_SIGNATURE, IG_USER_ID, FakeMediaDeliveryProvider, FakeMeta


def _publish(client: TestClient, created: dict[str, Any]) -> dict[str, Any]:
    return publish_and_wait(client, created["publication"]["id"])


# --- US1: images ---------------------------------------------------------------------


def test_jpeg_is_published_end_to_end(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
    media_dir: Path,
) -> None:
    created = instagram_publication(ig_client)
    original = stored_file(media_dir, db_path, created["content"]["id"])
    digest = hashlib.sha256(original.read_bytes()).hexdigest()

    publication = _publish(ig_client, created)

    assert publication["status"] == "published"
    attempt = publication["latest_attempt"]
    assert attempt["status"] == "succeeded"
    assert attempt["trigger"] == "manual"
    assert attempt["stage"] == "done"
    assert attempt["outcome_determined"] is True
    assert attempt["progress"] == 1
    assert attempt["external_id"] == "18000000000001"
    assert attempt["external_url"] == "https://www.instagram.com/p/18000000000001/"
    assert attempt["warnings"] == []
    submitted = attempt["submitted"]
    assert submitted["media_kind"] == "image"
    assert submitted["caption"] == IG_CAPTION
    assert submitted["converted"] is False
    assert submitted["container_reused"] is False
    assert submitted["quota_checked"] is True
    # One container, one media_publish, both with the token in the body.
    assert len(fake_meta.containers) == 1
    assert len(fake_meta.published) == 1
    create = fake_meta.requests_for("create")[0]
    assert create.url.endswith(f"/{IG_USER_ID}/media")
    assert create.form["image_url"].startswith("https://fake-account.r2")
    assert FAKE_SIGNATURE in create.form["image_url"]
    assert all(FAKE_SIGNATURE not in r.url for r in fake_meta.requests)
    # The temporary copy was uploaded as the exact file, then deleted.
    [row] = temporary_media_rows(db_path)
    assert row["deleted_at"] is not None
    assert fake_delivery.objects == {}
    assert fake_delivery.content_types[row["object_key"]] == "image/jpeg"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    [run] = instagram_run_rows(db_path)
    assert run["phase"] == "succeeded"
    assert run["container_status"] == "PUBLISHED"
    assert run["publish_started_at"] is not None


@pytest.mark.parametrize("kind", ["png", "webp"])
def test_png_and_webp_are_sent_as_jpeg(
    ig_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
    media_dir: Path,
    kind: str,
) -> None:
    created = instagram_publication(ig_client, kind=kind)
    original = stored_file(media_dir, db_path, created["content"]["id"])
    before = original.read_bytes()
    uploaded: list[bytes] = []
    real_put = fake_delivery.put

    def capture(key: str, source: Any, *args: Any) -> None:
        uploaded.append(source if isinstance(source, bytes) else source.read_bytes())
        real_put(key, source, *args)

    fake_delivery.put = capture  # type: ignore[method-assign,assignment]

    publication = _publish(ig_client, created)

    assert publication["status"] == "published"
    assert publication["latest_attempt"]["submitted"]["converted"] is True
    with Image.open(io.BytesIO(uploaded[0])) as image:
        assert image.format == "JPEG"
    assert original.read_bytes() == before
    assert [p.name for p in original.parent.iterdir()] == [original.name]


def test_image_options_are_sent(ig_client: TestClient, fake_meta: FakeMeta) -> None:
    created = instagram_publication(ig_client, is_ai_generated=None)
    ig_client.put(
        f"/api/publications/{created['publication']['id']}/instagram-options",
        json={"is_ai_generated": True, "alt_text": "A neon sign"},
    )

    _publish(ig_client, created)

    form = fake_meta.requests_for("create")[0].form
    assert form["is_ai_generated"] == "true"
    assert form["alt_text"] == "A neon sign"
    assert "share_to_feed" not in form
    assert "media_type" not in form


def test_stages_follow_the_real_phases(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    created = instagram_publication(ig_client)
    seen: dict[str, Any] = {}

    def at_create() -> None:
        seen["create"] = attempt_rows(db_path)[0]["stage"]

    def at_publish() -> None:
        seen["publish"] = attempt_rows(db_path)[0]["stage"]
        seen["run"] = instagram_run_rows(db_path)[0]

    fake_meta.create_hook = at_create
    fake_meta.publish_hook = at_publish

    _publish(ig_client, created)

    assert seen["create"] == "processing"
    assert seen["publish"] == "finalizing"
    assert seen["run"]["phase"] == "publishing"
    assert seen["run"]["publish_started_at"] is not None


def test_progress_never_reaches_one_before_success(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    created = instagram_publication(ig_client)
    publication_id = created["publication"]["id"]
    seen: list[float] = []

    def at_publish() -> None:
        attempt = get_publication(ig_client, publication_id)["latest_attempt"]
        seen.append(attempt["progress"])

    fake_meta.publish_hook = at_publish

    _publish(ig_client, created)

    assert seen and seen[0] <= 0.99


def test_missing_permalink_links_to_the_profile(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    fake_meta.permalinks = False
    created = instagram_publication(ig_client)

    publication = _publish(ig_client, created)

    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["external_url"] == "https://www.instagram.com/cyber.studio/"
    assert [w["code"] for w in attempt["warnings"]] == ["permalink_unavailable"]


def test_permalink_is_retried_on_temporary_errors(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    fake_meta.fault_queue["permalink"] = ["server_error"]
    created = instagram_publication(ig_client)

    attempt = _publish(ig_client, created)["latest_attempt"]

    assert attempt["external_url"].startswith("https://www.instagram.com/p/")


# --- US2: Reels ----------------------------------------------------------------------


def test_reel_waits_until_finished(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    recorded_sleeps: list[float],
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allow_reels(monkeypatch)
    fake_meta.status_script = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
    created = instagram_publication(ig_client, kind="reel", is_ai_generated=True)

    publication = _publish(ig_client, created)

    assert publication["status"] == "published"
    form = fake_meta.requests_for("create")[0].form
    assert form["media_type"] == "REELS"
    assert form["share_to_feed"] == "true"
    assert form["is_ai_generated"] == "true"
    assert form["video_url"].startswith("https://fake-account.r2")
    assert "image_url" not in form and "alt_text" not in form
    assert len(fake_meta.requests_for("status")) == 3
    assert sum(recorded_sleeps) == pytest.approx(2.0 + 5.0)
    assert len(fake_meta.published) == 1
    row = temporary_media_rows(db_path)[0]
    assert row["content_type"] == "video/mp4"
    assert fake_delivery.objects == {}


def test_reel_share_to_feed_false_is_sent(
    ig_client: TestClient, fake_meta: FakeMeta, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_reels(monkeypatch)
    created = instagram_publication(ig_client, kind="reel")
    ig_client.put(
        f"/api/publications/{created['publication']['id']}/instagram-options",
        json={"is_ai_generated": False, "share_to_feed": False},
    )

    _publish(ig_client, created)

    assert fake_meta.requests_for("create")[0].form["share_to_feed"] == "false"


@pytest.mark.parametrize(
    ("script", "code"),
    [
        (["IN_PROGRESS", "ERROR"], "instagram_processing_failed"),
        (["EXPIRED"], "instagram_container_expired"),
        (["IN_PROGRESS"], "instagram_processing_timeout"),
    ],
)
def test_reel_processing_failures_never_publish(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    recorded_sleeps: list[float],
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: list[str],
    code: str,
) -> None:
    allow_reels(monkeypatch)
    fake_meta.status_script = script
    created = instagram_publication(ig_client, kind="reel")

    publication = _publish(ig_client, created)

    attempt = publication["latest_attempt"]
    assert publication["status"] == "failed"
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert fake_meta.published == []
    assert fake_meta.requests_for("publish") == []
    assert fake_delivery.objects == {}
    assert instagram_run_rows(db_path)[0]["phase"] == "failed"
    # Bounded, sliced waits; never more than the Reel limit.
    assert sum(recorded_sleeps) <= 600
    assert all(wait <= 1.0 for wait in recorded_sleeps)


def test_reel_status_read_errors_keep_polling(
    ig_client: TestClient, fake_meta: FakeMeta, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_reels(monkeypatch)
    fake_meta.fault_queue["status"] = ["server_error", "transport"]
    created = instagram_publication(ig_client, kind="reel")

    publication = _publish(ig_client, created)

    assert publication["status"] == "published"
    assert len(fake_meta.requests_for("status")) == 3


# --- US3: caption --------------------------------------------------------------------


def test_sent_caption_equals_the_displayed_caption(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    created = instagram_publication(ig_client, description="Ñandú 🌴 @friend")
    publication_id = created["publication"]["id"]
    shown = ig_client.get(f"/api/publications/{publication_id}/instagram-options")

    _publish(ig_client, created)

    sent = fake_meta.requests_for("create")[0].form["caption"]
    assert sent == shown.json()["caption"]
    assert "Not sent to Instagram" not in sent


def test_empty_alt_text_and_caption_are_not_sent(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    created = instagram_publication(ig_client, description=None, hashtags=[])

    publication = _publish(ig_client, created)

    form = fake_meta.requests_for("create")[0].form
    assert publication["status"] == "published"
    assert "caption" not in form
    assert "alt_text" not in form
