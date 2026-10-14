"""Publish now with Direct Post and FILE_UPLOAD, single chunk (spec US1, research
§9–§16): request order and shapes, generic stages, bounded polling and the result."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import publishing
from app.models import AttemptStage, Platform
from app.publishing import PreparedPublication, PublishOutcome
from app.tiktok_publishing import TikTokPublisher
from tests.conftest import (
    attempt_rows,
    get_publication,
    publish_tiktok,
    tiktok_attempts,
    tiktok_probe_streams,
    tiktok_ready_publication,
    tiktok_run_rows,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_PUBLISH_ID_PREFIX,
    FAKE_TT_UPLOAD_ID,
    FAKE_TT_UPLOAD_TOKEN,
    FakeClock,
    FakeTikTok,
)


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def test_the_tiktok_publisher_is_registered(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)

    publisher = app.state.publishers[Platform.TIKTOK]

    assert isinstance(publisher, TikTokPublisher)
    assert publisher.accepts_text_only is False


def test_single_chunk_publication(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    size = len(created["data"])

    response = publish_tiktok(client, publication_id)

    assert response.status_code == 202, response.text
    assert fake_tiktok.calls() == [
        "creator_info",
        "init",
        "upload",
        "status",
        "status",
    ]
    [body] = fake_tiktok.init_bodies()
    assert body == {
        "post_info": {
            "title": "Validation clip — please ignore\n\n#autopublisher",
            "privacy_level": "SELF_ONLY",
            "disable_comment": True,
            "disable_duet": True,
            "disable_stitch": True,
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
            "is_aigc": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        },
    }
    [put] = fake_tiktok.requests_to("upload")
    assert put.headers["content-range"] == f"bytes 0-{size - 1}/{size}"
    assert put.headers["content-type"] == "video/mp4"
    assert put.content == created["data"]
    publication = get_publication(client, publication_id)
    assert publication["status"] == "published"
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["status"] == "succeeded"
    assert attempt["trigger"] == "manual"
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert [w["code"] for w in attempt["warnings"]] == ["tiktok_private_post_no_link"]
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "succeeded"
    assert run["publish_id"] == f"{FAKE_TT_PUBLISH_ID_PREFIX}1"
    assert run["last_remote_status"] == "PUBLISH_COMPLETE"
    assert run["confirmed_bytes"] == size
    assert run["final_chunk_http_status"] == 201
    assert run["final_chunk_started_at"] is not None
    assert (run["video_size"], run["chunk_size"], run["total_chunk_count"]) == (
        size,
        size,
        1,
    )
    [row] = attempt_rows(db_path)
    assert row["bytes_sent"] == row["total_bytes"] == size


@pytest.mark.parametrize(
    ("media_format", "content_type"),
    [("mov", "video/quicktime"), ("webm", "video/webm")],
)
def test_content_type_per_container(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    media_format: str,
    content_type: str,
) -> None:
    created = tiktok_ready_publication(
        client, fake_tiktok, monkeypatch, media_format=media_format
    )

    publish_tiktok(client, created["publication"]["id"])

    [put] = fake_tiktok.requests_to("upload")
    assert put.headers["content-type"] == content_type


def test_options_are_sent_as_chosen(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tiktok.creator_info_data["duet_disabled"] = False
    created = tiktok_ready_publication(
        client,
        fake_tiktok,
        monkeypatch,
        options={
            "allow_comment": True,
            "allow_duet": True,
            "is_aigc": True,
            "commercial_disclosure_enabled": True,
            "brand_organic_toggle": True,
        },
    )

    publish_tiktok(client, created["publication"]["id"])

    info = fake_tiktok.init_bodies()[0]["post_info"]
    assert (info["disable_comment"], info["disable_duet"], info["disable_stitch"]) == (
        False,
        False,
        True,
    )
    assert info["is_aigc"] is True
    assert (info["brand_content_toggle"], info["brand_organic_toggle"]) == (False, True)


def test_empty_caption_sends_no_title(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(
        client, fake_tiktok, monkeypatch, description=None, hashtags=[]
    )

    publish_tiktok(client, created["publication"]["id"])

    assert "title" not in fake_tiktok.init_bodies()[0]["post_info"]


def test_generic_stages_in_order(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    stages: list[str] = []
    original = publishing.set_stage

    def record(ctx: Any, attempt_id: int, stage: AttemptStage) -> bool:
        stages.append(stage.value)
        return original(ctx, attempt_id, stage)

    monkeypatch.setattr(publishing, "set_stage", record)
    seen: dict[str, str] = {}

    def stage_now(name: str) -> Any:
        def hook(request: httpx.Request) -> None:
            with sqlite3.connect(db_path) as connection:
                seen.setdefault(
                    name,
                    connection.execute(
                        "SELECT stage FROM publication_attempts"
                    ).fetchone()[0],
                )

        return hook

    for endpoint in ("init", "upload", "status"):
        fake_tiktok.hooks[endpoint] = stage_now(endpoint)

    publish_tiktok(client, created["publication"]["id"])

    assert stages == ["uploading", "final_chunk", "finalizing"]
    assert seen == {
        "init": "preparing",
        "upload": "final_chunk",
        "status": "finalizing",
    }


def test_one_public_post_id_is_the_external_id(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [
        {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [73000001]}
    ]

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["external_id"] == "73000001"
    assert attempt["external_url"] is None
    assert attempt["warnings"] == []


def test_several_post_ids_are_never_guessed(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [
        {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [1, 2]}
    ]

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["status"] == "succeeded"
    assert attempt["external_id"] is None


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("file_format_check_failed", "tiktok_video_rejected"),
        ("duration_check_failed", "tiktok_video_rejected"),
        ("frame_rate_check_failed", "tiktok_video_rejected"),
        ("picture_size_check_failed", "tiktok_video_rejected"),
        ("spam_risk_text", "tiktok_content_rejected"),
        ("spam_risk", "tiktok_content_rejected"),
        ("spam_risk_too_many_posts", "tiktok_creator_cannot_post"),
        ("internal", "tiktok_publish_failed"),
        ("publish_cancelled", "tiktok_publish_failed"),
        ("auth_removed", "tiktok_publish_failed"),
        ("something_new", "tiktok_publish_failed"),
    ],
)
def test_failed_status_is_a_determined_failure(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    reason: str,
    code: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [
        {"status": "PROCESSING_UPLOAD"},
        {"status": "FAILED", "fail_reason": reason},
    ]

    publish_tiktok(client, created["publication"]["id"])

    assert get_publication(client, created["publication"]["id"])["status"] == "failed"
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "failed"
    assert run["last_remote_status"] == "FAILED"
    assert run["fail_reason"] == reason


def test_polling_follows_the_bounded_schedule(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    reads: list[datetime] = []
    sent: list[datetime] = []
    fake_tiktok.hooks["upload"] = lambda request: sent.append(fake_clock.now())
    fake_tiktok.hooks["status"] = lambda request: reads.append(fake_clock.now())
    processing: list[dict[str, Any] | str] = [{"status": "PROCESSING_UPLOAD"}] * 12
    fake_tiktok.statuses = [*processing, {"status": "PUBLISH_COMPLETE"}]

    publish_tiktok(client, created["publication"]["id"])

    offsets = [round((read - sent[0]).total_seconds()) for read in reads]
    assert offsets == [3, 6, 11, 16, 26, 36, 51, 66, 96, 126, 156, 186, 216]
    for index, first in enumerate(reads):
        within = [r for r in reads[index:] if (r - first).total_seconds() < 60]
        assert len(within) <= 30
    assert get_publication(client, created["publication"]["id"])["status"] == (
        "published"
    )


def test_processing_until_the_timeout_is_uncertain(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]
    sent: list[datetime] = []
    fake_tiktok.hooks["upload"] = lambda request: sent.append(fake_clock.now())

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["error"]["code"] == "tiktok_processing_pending"
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    assert (fake_clock.now() - sent[0]).total_seconds() <= 600
    assert len(fake_tiktok.requests_to("status")) <= 30
    assert fake_tiktok.calls().count("init") == 1
    assert fake_tiktok.calls().count("upload") == 1


def test_submitted_snapshot_is_safe(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)

    publish_tiktok(client, created["publication"]["id"])

    [row] = attempt_rows(db_path)
    submitted = json.loads(row["submitted"])
    assert submitted["post_info"]["privacy_level"] == "SELF_ONLY"
    assert submitted["source_info"]["source"] == "FILE_UPLOAD"
    assert submitted["creator_nickname"] == "Cyber Studio"
    assert submitted["max_video_post_duration_sec"] == 600
    assert submitted["declaration_version"] == "music-usage-2026-10-14"
    assert submitted["consented_at"] is not None
    assert submitted["delegated_checks"] == []
    text = row["submitted"] + row["details"] + row["warnings"]
    for secret in (
        FAKE_TT_ACCESS_TOKEN,
        FAKE_TT_UPLOAD_TOKEN,
        FAKE_TT_UPLOAD_ID,
        FAKE_TT_PUBLISH_ID_PREFIX,
        "upload_url",
        "publish_id",
    ):
        assert secret not in text


def test_delegated_frame_rate_is_recorded(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(
        client,
        fake_tiktok,
        monkeypatch,
        streams=tiktok_probe_streams(video={"frame_rate": None}),
    )

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["submitted"]["delegated_checks"] == ["frame_rate"]


def test_refresh_details_and_release_do_nothing(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    publisher = app.state.publishers[Platform.TIKTOK]
    ctx = app.state.publish_context
    outcome = PublishOutcome(external_id=None, external_url=None)
    prepared = PreparedPublication(
        publication_id=1, file_path=None, total_bytes=1, submitted={}, payload=None
    )

    assert publisher.refresh_details(prepared, outcome, ctx) is outcome
    assert publisher.release(prepared, ctx, attempt_id=1, succeeded=True) == []
