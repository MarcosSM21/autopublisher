"""Publishing to Telegram through the generic core with the fake gateway (Feature
015): text, image and video, preflight, anti-duplicates and errors. Telethon and
Telegram are not tested here."""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import telegram_connections
from app.telegram_connections import account_session
from app.telegram_gateway import (
    TelegramChannelUnavailable,
    TelegramRateLimited,
    TelegramUnauthorized,
    TelegramUnavailable,
    TelegramUnconfirmed,
)
from tests.conftest import (
    attempt_rows,
    create_account,
    create_project,
    create_publications,
    get_publication,
    import_one,
    make_image,
    make_mov,
    make_mp4,
    publish_and_wait,
    run_sql,
    stored_file,
    wait_idle,
)
from tests.fakes import FakeClock
from tests.fakes_telegram import (
    CHANNEL,
    FAKE_CODE,
    FAKE_PHONE,
    PRIVATE_CHANNEL,
    SECRETS,
    FakeTelegramGateway,
)

TEXT = "Hola ñandú 🎉 https://example.com"


def ready_account(
    client: TestClient, channel_id: str = CHANNEL.channel_id
) -> tuple[int, int]:
    """A project with a connected Telegram account and its channel chosen."""
    project = create_project(client, "Tg")
    account_id: int = create_account(client, project["id"], "telegram", "tg")["id"]
    url = f"/api/accounts/{account_id}/telegram-connection"
    client.post(f"{url}/login/start", json={"phone": FAKE_PHONE})
    assert client.post(f"{url}/login/code", json={"code": FAKE_CODE}).status_code == 200
    response = client.put(f"{url}/channel", json={"channel_id": channel_id})
    assert response.status_code == 200, response.text
    return project["id"], account_id


def text_publication(
    client: TestClient, project_id: int, account_id: int, text: str = TEXT
) -> int:
    response = client.post(
        f"/api/projects/{project_id}/text-publications",
        json={"account_ids": [account_id], "description": text, "hashtags": ["tg"]},
    )
    assert response.status_code == 201, response.text
    publication_id: int = response.json()[0]["id"]
    return publication_id


def media_publication(
    client: TestClient,
    project_id: int,
    account_id: int,
    name: str,
    data: bytes,
    caption: str = "Caption ✨",
) -> tuple[int, int]:
    content = import_one(client, project_id, name, data)["content"]
    [publication] = create_publications(client, content["id"], [account_id])
    response = client.patch(
        f"/api/publications/{publication['id']}",
        json={"description_override": caption, "hashtags_override": []},
    )
    assert response.status_code == 200, response.text
    return publication["id"], content["id"]


def attempts(client: TestClient, publication_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/publications/{publication_id}/attempts")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items


def problem_codes(client: TestClient, publication_id: int) -> list[str]:
    body = client.get(f"/api/publications/{publication_id}/publish-check").json()
    return [problem["code"] for problem in body["problems"]]


def database_text(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        return "\n".join(connection.iterdump())


# --- Success ---------------------------------------------------------------------


def test_text_post_is_published_with_message_id_and_public_link(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    project_id, account_id = ready_account(telegram_client)
    publication_id = text_publication(telegram_client, project_id, account_id)

    published = publish_and_wait(telegram_client, publication_id)

    assert published["status"] == "published"
    [attempt] = attempts(telegram_client, publication_id)
    assert attempt["status"] == "succeeded"
    assert attempt["platform"] == "telegram"
    assert attempt["outcome_determined"] is True
    assert attempt["external_id"] == "1001"
    assert attempt["external_url"] == "https://t.me/testchan/1001"
    [(random_id, spec, channel)] = fake_telegram.sent
    assert spec.kind == "text"
    assert spec.text == f"{TEXT}\n\n#tg"
    assert spec.file_path is None
    assert channel.access_hash == CHANNEL.access_hash
    assert attempt["submitted"] == {
        "post_type": "text",
        "channel_id": CHANNEL.channel_id,
        "channel_title": "Test channel",
        "text_length": len(f"{TEXT}\n\n#tg".encode("utf-16-le")) // 2,
        "telegram_random_id": random_id,
    }
    assert attempt["details"] == {
        "channel_id": CHANNEL.channel_id,
        "channel_title": "Test channel",
    }
    exposed = (
        database_text(db_path)
        + json.dumps(attempt)
        + json.dumps(published)
        + caplog.text
    )
    for secret in SECRETS:
        assert secret not in exposed
    assert CHANNEL.access_hash not in json.dumps(attempt) + json.dumps(published)


def test_image_and_video_are_sent_with_their_exact_caption(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
) -> None:
    project_id, account_id = ready_account(telegram_client, PRIVATE_CHANNEL.channel_id)
    image_id, _ = media_publication(
        telegram_client, project_id, account_id, "photo.jpg", make_image("JPEG")
    )
    video_id, _ = media_publication(
        telegram_client, project_id, account_id, "clip.mp4", make_mp4(), "Vídeo 🎬"
    )

    assert publish_and_wait(telegram_client, image_id)["status"] == "published"
    assert publish_and_wait(telegram_client, video_id)["status"] == "published"

    (_, image, _), (_, video, _) = fake_telegram.sent
    assert (image.kind, image.text, image.mime_type) == ("image", "Caption ✨", None)
    assert image.file_path is not None and image.file_path.is_file()
    assert (video.kind, video.text, video.mime_type) == (
        "video",
        "Vídeo 🎬",
        "video/mp4",
    )
    [image_attempt] = attempts(telegram_client, image_id)
    [video_attempt] = attempts(telegram_client, video_id)
    # A private channel gets the message ID but no invented link.
    assert image_attempt["external_id"] == "1001"
    assert image_attempt["external_url"] is None
    assert video_attempt["external_id"] == "1002"
    assert video_attempt["submitted"]["post_type"] == "video"
    assert video_attempt["submitted"]["file_name"] == "clip.mp4"


def test_publish_now_waits_for_the_account_session(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telegram_connections, "LOCK_POLL_SECONDS", 0.01)
    project_id, account_id = ready_account(telegram_client)
    publication_id = text_publication(telegram_client, project_id, account_id)
    release = threading.Event()
    held = threading.Event()

    def holder() -> None:
        with account_session(account_id, wait=False):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(5)
    try:
        response = telegram_client.post(
            f"/api/publications/{publication_id}/publish", json={}
        )
        assert response.status_code == 202, response.text
        assert fake_telegram.sent == []  # Still waiting for the session.
    finally:
        release.set()
        thread.join(5)
    wait_idle(telegram_client)
    assert get_publication(telegram_client, publication_id)["status"] == "published"
    assert len(fake_telegram.sent) == 1


# --- Preflight -------------------------------------------------------------------


def test_preflight_problems(
    telegram_client: TestClient,
    db_path: Path,
    media_dir: Path,
) -> None:
    project = create_project(telegram_client, "Pre")
    lonely = create_account(telegram_client, project["id"], "telegram", "lonely")
    lonely_text = text_publication(telegram_client, project["id"], lonely["id"])
    assert "telegram_not_connected" in problem_codes(telegram_client, lonely_text)

    project_id, account_id = ready_account(telegram_client)
    run_sql(
        db_path,
        "UPDATE telegram_connections SET channel_id = NULL, "
        "channel_access_hash = NULL, channel_title = NULL",
    )
    no_channel = text_publication(telegram_client, project_id, account_id)
    assert problem_codes(telegram_client, no_channel) == ["telegram_channel_required"]
    run_sql(
        db_path,
        "UPDATE telegram_connections SET channel_id = ?, "
        "channel_access_hash = ?, channel_title = 'Test channel'",
        CHANNEL.channel_id,
        CHANNEL.access_hash,
    )

    long_text = text_publication(telegram_client, project_id, account_id, "x" * 4097)
    assert problem_codes(telegram_client, long_text) == ["telegram_text_too_long"]
    # Emoji count twice (UTF-16): 2049 × 2 > 4096.
    emoji = text_publication(telegram_client, project_id, account_id, "🎉" * 2047)
    assert problem_codes(telegram_client, emoji) == ["telegram_text_too_long"]

    caption, _ = media_publication(
        telegram_client, project_id, account_id, "a.png", make_image(), "y" * 1025
    )
    assert problem_codes(telegram_client, caption) == ["telegram_text_too_long"]

    mov, _ = media_publication(
        telegram_client, project_id, account_id, "a.mov", make_mov()
    )
    assert problem_codes(telegram_client, mov) == ["telegram_media_unsupported"]

    wide, wide_content = media_publication(
        telegram_client, project_id, account_id, "w.png", make_image()
    )
    run_sql(
        db_path,
        "UPDATE contents SET width = 9000, height = 300 WHERE id = ?",
        wide_content,
    )
    assert problem_codes(telegram_client, wide) == ["telegram_media_unsupported"]
    run_sql(
        db_path,
        "UPDATE contents SET size_bytes = ? WHERE id = ?",
        11 * 1024 * 1024,
        wide_content,
    )
    assert "telegram_file_too_large" in problem_codes(telegram_client, wide)

    gone, gone_content = media_publication(
        telegram_client, project_id, account_id, "g.png", make_image()
    )
    stored_file(media_dir, db_path, gone_content).unlink()
    assert problem_codes(telegram_client, gone) == ["media_unavailable"]


# --- Anti-duplicates -------------------------------------------------------------


def test_random_id_is_persisted_before_the_message_is_sent(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    db_path: Path,
) -> None:
    project_id, account_id = ready_account(telegram_client)
    publication_id = text_publication(telegram_client, project_id, account_id)
    seen: list[Any] = []

    def check_write_ahead() -> None:
        [row] = attempt_rows(db_path)
        seen.append((json.loads(row["submitted"])["telegram_random_id"], row["stage"]))

    fake_telegram.on_send = check_write_ahead
    publish_and_wait(telegram_client, publication_id)

    [(random_id, _, _)] = fake_telegram.sent
    assert seen == [(random_id, "finalizing")]


def test_unconfirmed_send_is_uncertain_and_the_retry_reuses_its_random_id(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
) -> None:
    project_id, account_id = ready_account(telegram_client)
    publication_id = text_publication(telegram_client, project_id, account_id)
    fake_telegram.publish_results = [TelegramUnconfirmed()]

    failed = publish_and_wait(telegram_client, publication_id)

    assert failed["status"] == "failed"
    [attempt] = attempts(telegram_client, publication_id)
    assert attempt["status"] == "failed"
    assert attempt["error"]["code"] == "telegram_unconfirmed"
    assert attempt["outcome_determined"] is False
    assert attempt["external_id"] is None
    # The generic remote check is required before publishing again.
    again = telegram_client.post(f"/api/publications/{publication_id}/publish", json={})
    assert again.json()["error"]["code"] == "remote_check_required"

    published = publish_and_wait(
        telegram_client, publication_id, confirm_remote_checked=True
    )
    assert published["status"] == "published"
    (first_id, _, _), (second_id, _, _) = fake_telegram.sent
    assert second_id == first_id
    latest = attempts(telegram_client, publication_id)[0]
    assert latest["submitted"]["telegram_random_id"] == first_id

    # A determined outcome never passes its random_id on.
    other = text_publication(telegram_client, project_id, account_id)
    publish_and_wait(telegram_client, other)
    assert fake_telegram.sent[-1][0] != first_id


# --- Errors ----------------------------------------------------------------------


def test_flood_wait_fails_and_blocks_publishing_until_it_passes(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    fake_clock: FakeClock,
) -> None:
    project_id, account_id = ready_account(telegram_client)
    publication_id = text_publication(telegram_client, project_id, account_id)
    fake_telegram.errors["publish"] = TelegramRateLimited(120)

    failed = publish_and_wait(telegram_client, publication_id)

    assert failed["status"] == "failed"
    [attempt] = attempts(telegram_client, publication_id)
    assert attempt["error"]["code"] == "telegram_rate_limited"
    assert "120 seconds" in attempt["error"]["message"]
    assert attempt["outcome_determined"] is True
    assert fake_telegram.sent == []
    assert problem_codes(telegram_client, publication_id) == ["telegram_rate_limited"]
    connection = telegram_client.get(f"/api/accounts/{account_id}/telegram-connection")
    assert connection.json()["rate_limited_until"] is not None
    fake_clock.advance(121)
    assert problem_codes(telegram_client, publication_id) == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TelegramUnauthorized(), "telegram_reconnect_required"),
        (TelegramChannelUnavailable(), "telegram_channel_unavailable"),
        (TelegramUnavailable(), "telegram_unavailable"),
    ],
)
def test_errors_before_sending_are_determined_failures(
    telegram_client: TestClient,
    fake_telegram: FakeTelegramGateway,
    error: Exception,
    code: str,
) -> None:
    project_id, account_id = ready_account(telegram_client)
    publication_id = text_publication(telegram_client, project_id, account_id)
    fake_telegram.errors["publish"] = error

    publish_and_wait(telegram_client, publication_id)

    [attempt] = attempts(telegram_client, publication_id)
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert fake_telegram.sent == []
    status = telegram_client.get(
        f"/api/accounts/{account_id}/telegram-connection"
    ).json()["status"]
    expected = (
        "reconnect_required" if code == "telegram_reconnect_required" else "connected"
    )
    assert status == expected
