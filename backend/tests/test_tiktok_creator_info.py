"""`GET /api/publications/{id}/tiktok-creator-info` (contracts §3): a fresh Creator
Info read on every call, never cached nor stored."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    run_sql,
    tiktok_probe_streams,
    tiktok_publication,
    tiktok_rows,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_ERROR_TEXT,
    FAKE_TT_REFRESHED_ACCESS_TOKEN,
    FakeTikTok,
    tiktok_creator_info,
)


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


@pytest.fixture
def publication_id(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> int:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    return int(created["publication"]["id"])


def _get(client: TestClient, publication_id: int) -> Any:
    return client.get(f"/api/publications/{publication_id}/tiktok-creator-info")


def test_every_call_reads_creator_info_again(
    client: TestClient, publication_id: int, fake_tiktok: FakeTikTok
) -> None:
    first = _get(client, publication_id)
    second = _get(client, publication_id)

    assert first.status_code == second.status_code == 200
    assert fake_tiktok.calls() == ["creator_info", "creator_info"]
    assert first.json() == {
        "nickname": "Cyber Studio",
        "username": "cyber.studio",
        "avatar_url": "https://p16-sign.tiktokcdn.example/creator.jpeg",
        "privacy_level_options": [
            "FOLLOWER_OF_CREATOR",
            "MUTUAL_FOLLOW_FRIENDS",
            "SELF_ONLY",
        ],
        "comment_disabled": False,
        "duet_disabled": True,
        "stitch_disabled": True,
        "max_video_post_duration_sec": 600,
        "can_post": True,
        "blocked": None,
        "account_appears_public": False,
        "video_within_max_duration": True,
    }


def test_changes_are_seen_at_once(
    client: TestClient, publication_id: int, fake_tiktok: FakeTikTok
) -> None:
    fake_tiktok.creator_info_queue = [
        tiktok_creator_info(),
        tiktok_creator_info(
            privacy_level_options=["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
            max_video_post_duration_sec=10,
        ),
    ]

    _get(client, publication_id)
    second = _get(client, publication_id).json()

    assert second["account_appears_public"] is True
    assert second["video_within_max_duration"] is False


@pytest.mark.parametrize(
    "code",
    [
        "spam_risk_too_many_posts",
        "spam_risk_user_banned_from_posting",
        "reached_active_user_cap",
    ],
)
def test_blocked_creator(
    client: TestClient, publication_id: int, fake_tiktok: FakeTikTok, code: str
) -> None:
    fake_tiktok.faults["creator_info"] = f"api200_{code}"

    response = _get(client, publication_id)

    assert response.status_code == 200
    body = response.json()
    assert body["can_post"] is False
    assert body["blocked"]["code"] == "tiktok_creator_cannot_post"
    assert FAKE_TT_ERROR_TEXT not in body["blocked"]["message"]
    for name in (
        "nickname",
        "privacy_level_options",
        "comment_disabled",
        "max_video_post_duration_sec",
        "video_within_max_duration",
    ):
        assert body[name] is None


def test_unknown_duration_is_not_judged(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(
        client,
        fake_tiktok,
        monkeypatch,
        streams=tiktok_probe_streams(duration_seconds=None),
    )

    body = _get(client, created["publication"]["id"]).json()

    assert body["video_within_max_duration"] is None


def test_rejected_token_is_renewed_once(
    client: TestClient, publication_id: int, fake_tiktok: FakeTikTok
) -> None:
    fake_tiktok.fault_queue["creator_info"] = ["api_access_token_invalid"]

    response = _get(client, publication_id)

    assert response.status_code == 200
    assert fake_tiktok.calls() == ["creator_info", "refresh", "creator_info"]
    [_, retried] = fake_tiktok.requests_to("creator_info")
    assert (
        retried.headers["authorization"] == f"Bearer {FAKE_TT_REFRESHED_ACCESS_TOKEN}"
    )


def test_missing_scope_requires_reconnecting(
    client: TestClient, publication_id: int, fake_tiktok: FakeTikTok, db_path: Path
) -> None:
    fake_tiktok.faults["creator_info"] = "api_scope_not_authorized"

    response = _get(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_reconnect_required"
    assert tiktok_rows(db_path)[0]["status"] == "reconnect_required"


@pytest.mark.parametrize(
    ("fault", "status", "code"),
    [
        ("rate_limited", 429, "tiktok_rate_limited"),
        ("api_rate_limit_exceeded", 429, "tiktok_rate_limited"),
        ("server_error", 503, "tiktok_unavailable"),
        ("transport", 503, "tiktok_unavailable"),
        ("missing_fields", 502, "tiktok_unexpected_response"),
        ("bad_json", 502, "tiktok_unexpected_response"),
    ],
)
def test_temporary_and_unexpected_errors(
    client: TestClient,
    publication_id: int,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    fault: str,
    status: int,
    code: str,
) -> None:
    fake_tiktok.faults["creator_info"] = fault

    response = _get(client, publication_id)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert FAKE_TT_ERROR_TEXT not in response.text
    # Temporary problems never touch the connection.
    assert tiktok_rows(db_path)[0]["status"] == "connected"


def test_malformed_payload_is_unexpected(
    client: TestClient, publication_id: int, fake_tiktok: FakeTikTok
) -> None:
    fake_tiktok.creator_info_data = tiktok_creator_info(duet_disabled="no")

    response = _get(client, publication_id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tiktok_unexpected_response"


@pytest.mark.parametrize(
    ("statement", "code"),
    [
        ("DELETE FROM tiktok_connections", "tiktok_not_connected"),
        (
            "UPDATE tiktok_connections SET status = 'reconnect_required'",
            "tiktok_reconnect_required",
        ),
    ],
)
def test_connection_required(
    client: TestClient,
    publication_id: int,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    statement: str,
    code: str,
) -> None:
    run_sql(db_path, statement)

    response = _get(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert fake_tiktok.requests == []


def test_nothing_is_stored(
    client: TestClient, publication_id: int, db_path: Path
) -> None:
    response = _get(client, publication_id)

    assert response.status_code == 200
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
    assert "creator.jpeg" not in dump
    assert "cyber.studio" not in dump
    assert FAKE_TT_ACCESS_TOKEN not in dump
    for table in ("tiktok_publication_options", "tiktok_publish_runs"):
        assert tiktok_rows(db_path, table) == []
