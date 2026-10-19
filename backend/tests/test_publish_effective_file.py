"""Publishers send the effective file and the claim never races Remove metadata
(Feature 016, research §3–§4). Missing/corrupt copies are covered once in
test_content_files.py; here only the publisher-specific uses of the file."""

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import telegram_publishing, threads_media
from app.errors import AppError
from app.instagram_media import fingerprint
from app.models import Platform, Publication
from app.publishing import PreparedPublication, create_running_attempt
from tests.conftest import (
    attempt_rows,
    create_account,
    create_project,
    create_publications,
    get_publication,
    import_one,
    in_minutes,
    instagram_publication,
    make_image,
    make_mp4,
    run_tick,
    scheduled_publication,
    set_youtube_options,
    setup_publishable,
    stored_file,
    threads_image_publication,
    threads_video_publication,
    tiktok_ready,
    tiktok_ready_publication,
    tiktok_video,
    wait_idle,
)
from tests.fakes import FakeClock, FakeGoogle, FakePublisher
from tests.fakes_telegram import CHANNEL, FAKE_CODE, FAKE_PHONE


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize(media_dir: Path, db_path: Path, content_id: int, data: bytes) -> Path:
    """Give a content a clean copy, as Remove metadata does once it succeeds."""
    original = stored_file(media_dir, db_path, content_id)
    relative = (
        f"projects/{original.parent.name}/{uuid.uuid4().hex}.clean{original.suffix}"
    )
    copy = media_dir / relative
    copy.write_bytes(data)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE contents SET metadata_status = 'sanitized', "
            "sanitized_storage_path = ?, sanitized_checksum = ?, "
            "sanitized_size_bytes = ?, sanitized_at = '2026-10-16 10:00:00' "
            "WHERE id = ?",
            (relative, _sha(data), len(data), content_id),
        )
    return copy


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _prepare(client: TestClient, platform: Platform, publication_id: int) -> Any:
    app = _app(client)
    ctx = app.state.publish_context
    with ctx.session_factory() as session:
        publication = session.get_one(Publication, publication_id)
        return app.state.publishers[platform].prepare(session, publication, ctx)


def _telegram_ready(client: TestClient, data: bytes, name: str) -> dict[str, Any]:
    project = create_project(client, "Tg")
    account_id = create_account(client, project["id"], "telegram", "tg")["id"]
    url = f"/api/accounts/{account_id}/telegram-connection"
    client.post(f"{url}/login/start", json={"phone": FAKE_PHONE})
    client.post(f"{url}/login/code", json={"code": FAKE_CODE})
    response = client.put(f"{url}/channel", json={"channel_id": CHANNEL.channel_id})
    assert response.status_code == 200, response.text
    content = import_one(client, project["id"], name, data)["content"]
    publication = create_publications(client, content["id"], [account_id])[0]
    return {"content": content, "publication": publication}


def _setup(
    platform: Platform,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, dict[str, Any], bytes]:
    """A ready publication of `platform` and the bytes of its future clean copy."""
    if platform == Platform.YOUTUBE:
        client = request.getfixturevalue("publishing_client")
        created = setup_publishable(client, request.getfixturevalue("fake_google"))
        set_youtube_options(client, created["publication"]["id"])
        return client, created, make_mp4(payload=b"clean video" * 50)
    if platform == Platform.INSTAGRAM:
        client = request.getfixturevalue("ig_client")
        created = instagram_publication(client, kind="jpeg")
        return client, created, make_image("JPEG", (1080, 1080))
    if platform == Platform.THREADS:
        client = request.getfixturevalue("threads_publishing_client")
        created = threads_image_publication(client)
        return client, created, make_image("JPEG", (1080, 1350))
    if platform == Platform.TELEGRAM:
        client = request.getfixturevalue("telegram_client")
        created = _telegram_ready(client, make_image(), "photo.png")
        return client, created, make_image()
    client = request.getfixturevalue("tiktok_publishing_client")
    created = tiktok_ready_publication(
        client, request.getfixturevalue("fake_tiktok"), monkeypatch
    )
    return client, created, tiktok_video(size=5000)[1]


@pytest.mark.parametrize(
    "platform",
    [
        Platform.YOUTUBE,
        Platform.INSTAGRAM,
        Platform.THREADS,
        Platform.TELEGRAM,
        Platform.TIKTOK,
    ],
)
def test_prepare_sends_the_clean_copy(
    platform: Platform,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    db_path: Path,
) -> None:
    client, created, clean = _setup(platform, request, monkeypatch)
    content_id = created["content"]["id"]
    publication_id = created["publication"]["id"]
    copy = sanitize(media_dir, db_path, content_id, clean)
    if platform == Platform.TIKTOK:
        # The consent was for the original: confirm it again for the copy.
        tiktok_ready(client, publication_id)

    prepared = _prepare(client, platform, publication_id)

    assert prepared.file_path == copy
    assert prepared.file_checksum == _sha(clean)
    assert prepared.total_bytes == len(clean)
    submitted = prepared.submitted
    file_size = submitted.get("file_size", submitted.get("video", {}).get("size_bytes"))
    assert file_size == len(clean)
    if platform == Platform.INSTAGRAM:
        payload = prepared.payload
        assert payload.fingerprint == fingerprint(
            _sha(clean),
            "image",
            payload.caption,
            {"is_ai_generated": False, "alt_text": None},
        )
    if platform == Platform.TIKTOK:
        assert prepared.payload.checksum == _sha(clean)
        assert prepared.payload.plan.video_size == len(clean)


@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.THREADS])
def test_size_limits_apply_to_the_clean_copy(
    platform: Platform,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    db_path: Path,
) -> None:
    limit_owner: ModuleType
    if platform == Platform.TELEGRAM:
        client = request.getfixturevalue("telegram_client")
        original = make_image()
        created = _telegram_ready(client, original, "photo.png")
        limit_owner, limit, code = (
            telegram_publishing,
            "PHOTO_MAX_BYTES",
            ("telegram_file_too_large"),
        )
    else:
        client = request.getfixturevalue("threads_publishing_client")
        created = threads_video_publication(client, monkeypatch)
        original = stored_file(
            media_dir, db_path, created["content"]["id"]
        ).read_bytes()
        limit_owner, limit, code = (
            threads_media,
            "VIDEO_MAX_BYTES",
            ("threads_video_incompatible"),
        )
    # Only the copy is over the limit: the check must look at the copy.
    sanitize(media_dir, db_path, created["content"]["id"], original + b"\0" * 100)
    monkeypatch.setattr(limit_owner, limit, len(original) + 50)

    check = client.get(
        f"/api/publications/{created['publication']['id']}/publish-check"
    ).json()

    assert code in {problem["code"] for problem in check["problems"]}


def test_missing_clean_copy_blocks_publishing(
    telegram_client: TestClient, media_dir: Path, db_path: Path
) -> None:
    created = _telegram_ready(telegram_client, make_image(), "photo.png")
    copy = sanitize(media_dir, db_path, created["content"]["id"], make_image())
    copy.unlink()
    publication_id = created["publication"]["id"]

    response = telegram_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "media_unavailable"
    assert "Remove metadata" in error["message"]
    assert attempt_rows(db_path) == []
    assert get_publication(telegram_client, publication_id)["status"] == "unscheduled"


def test_removing_metadata_invalidates_the_tiktok_consent(
    tiktok_publishing_client: TestClient,
    fake_tiktok: Any,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    db_path: Path,
) -> None:
    client = tiktok_publishing_client
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]

    sanitize(media_dir, db_path, created["content"]["id"], tiktok_video(size=5000)[1])

    options = client.get(f"/api/publications/{publication_id}/tiktok-options").json()
    assert options["consent"]["state"] == "stale"
    check = client.get(f"/api/publications/{publication_id}/publish-check").json()
    assert "tiktok_consent_required" in {p["code"] for p in check["problems"]}


# --- Claim vs Remove metadata (shared by Publish now and the scheduler) ----------


@pytest.fixture
def fake_client(
    publishing_client: TestClient, fake_publisher: FakePublisher
) -> TestClient:
    _app(publishing_client).state.publishers[Platform.YOUTUBE] = fake_publisher
    return publishing_client


def _ready_fake(client: TestClient) -> dict[str, Any]:
    created = setup_publishable(client, FakeGoogle(), connect=False)
    set_youtube_options(client, created["publication"]["id"])
    return created


def _unchanged(client: TestClient, db_path: Path, publication_id: int) -> None:
    publication = get_publication(client, publication_id)
    assert publication["status"] == "unscheduled"
    assert attempt_rows(db_path) == []


def test_claim_waits_while_metadata_is_being_removed(
    fake_client: TestClient, db_path: Path
) -> None:
    created = _ready_fake(fake_client)
    publication_id = created["publication"]["id"]
    guard = _app(fake_client).state.content_file_guard

    with guard.sanitizing(created["content"]["id"], lambda: None):
        response = fake_client.post(
            f"/api/publications/{publication_id}/publish", json={}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "content_metadata_busy"
        _unchanged(fake_client, db_path, publication_id)

    retry = fake_client.post(f"/api/publications/{publication_id}/publish", json={})
    assert retry.status_code == 202
    wait_idle(fake_client)


def test_claim_after_the_file_changed_is_rejected(
    fake_client: TestClient,
    fake_publisher: FakePublisher,
    media_dir: Path,
    db_path: Path,
) -> None:
    created = _ready_fake(fake_client)
    publication_id = created["publication"]["id"]
    content_id = created["content"]["id"]

    # Metadata is removed between prepare() and the claim.
    def remove_metadata(_: int) -> None:
        sanitize(media_dir, db_path, content_id, make_mp4(payload=b"clean"))

    fake_publisher.prepare_hook = remove_metadata

    response = fake_client.post(f"/api/publications/{publication_id}/publish", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "content_file_changed"
    _unchanged(fake_client, db_path, publication_id)
    fake_publisher.prepare_hook = None
    retry = fake_client.post(f"/api/publications/{publication_id}/publish", json={})
    assert retry.status_code == 202
    wait_idle(fake_client)


def test_content_publication_needs_its_prepared_file(
    fake_client: TestClient, db_path: Path
) -> None:
    created = _ready_fake(fake_client)
    publication_id = created["publication"]["id"]
    ctx = _app(fake_client).state.publish_context
    prepared = PreparedPublication(
        publication_id=publication_id,
        file_path=None,
        total_bytes=0,
        submitted={},
        payload=None,
    )

    with ctx.session_factory() as session, pytest.raises(AppError) as error:
        publication = session.get_one(Publication, publication_id)
        create_running_attempt(session, publication, prepared, "youtube")

    assert error.value.code == "internal_error"
    _unchanged(fake_client, db_path, publication_id)


def test_scheduler_does_not_record_a_lost_claim(
    fake_scheduler_client: TestClient, fake_clock: FakeClock, db_path: Path
) -> None:
    client = fake_scheduler_client
    created = scheduled_publication(client, db_path, in_minutes(fake_clock, 1))
    fake_clock.advance(120)
    guard = _app(client).state.content_file_guard

    with guard.sanitizing(created["content"]["id"], lambda: None):
        report = run_tick(client)

    assert report.started == [] and report.failed == []
    publication = get_publication(client, created["publication"]["id"])
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_enabled"] is True
    assert publication["auto_publish_error"] is None
    assert attempt_rows(db_path) == []
    # The next tick starts it once the removal has finished.
    assert run_tick(client).started == [created["publication"]["id"]]
    wait_idle(client)


# --- The checksum of the file each attempt sent (Feature 019, FR-076) ---------------


def _attempts(client: TestClient, publication_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/publications/{publication_id}/attempts")
    assert response.status_code == 200, response.text
    attempts: list[dict[str, Any]] = response.json()
    return attempts


def test_attempt_keeps_the_checksum_of_the_prepared_file(
    fake_client: TestClient, media_dir: Path, db_path: Path
) -> None:
    created = _ready_fake(fake_client)
    publication_id = created["publication"]["id"]
    original = created["content"]["checksum"]

    response = fake_client.post(f"/api/publications/{publication_id}/publish", json={})
    assert response.status_code == 202
    wait_idle(fake_client)

    [row] = attempt_rows(db_path)
    assert json.loads(row["submitted"])["file_checksum"] == original
    [attempt] = _attempts(fake_client, publication_id)
    assert attempt["submitted"] == {"title": "fake", "file_checksum": original}

    # Removing metadata later changes the Media's effective file, never what the
    # attempt recorded: the current checksum is not a fallback.
    sanitize(media_dir, db_path, created["content"]["id"], make_mp4(payload=b"new"))
    [attempt] = _attempts(fake_client, publication_id)
    assert attempt["submitted"]["file_checksum"] == original


def test_legacy_attempt_without_checksum_is_still_read(
    fake_client: TestClient, db_path: Path
) -> None:
    created = _ready_fake(fake_client)
    publication_id = created["publication"]["id"]
    fake_client.post(f"/api/publications/{publication_id}/publish", json={})
    wait_idle(fake_client)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE publication_attempts SET submitted = ?", ('{"title": "fake"}',)
        )

    [attempt] = _attempts(fake_client, publication_id)

    assert attempt["submitted"] == {"title": "fake"}
