"""Upload to Inbox failures (Feature 014, US7, research §9): each TikTok signal has
its safe code and wording, is determined before the write-ahead, is never retried
and a missing `video.upload` never asks to reconnect the account."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    get_tiktok_connection,
    publish_tiktok,
    tiktok_attempts,
    tiktok_inbox_publication,
    tiktok_ready_publication,
)
from tests.fakes import FakeTikTok

NOTHING_SENT = "Nothing was sent to TikTok."


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _send_with_init_fault(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["inbox_init"] = fault
    publish_tiktok(client, created["publication"]["id"])
    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    return created, attempt


def test_too_many_pending_shares(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created, attempt = _send_with_init_fault(
        client, fake_tiktok, monkeypatch, "api_spam_risk_too_many_pending_share"
    )

    assert attempt["error"]["code"] == "tiktok_too_many_pending_shares"
    message = attempt["error"]["message"]
    assert "waiting for review in this account's inbox" in message
    assert "at most 5 in 24 hours" in message
    assert "publish or discard the pending drafts" in message
    assert attempt["outcome_determined"] is True
    # One init, never retried, nothing uploaded.
    assert fake_tiktok.calls() == ["inbox_init"]
    connection = get_tiktok_connection(client, created["account"]["id"])
    assert connection["status"] == "connected"


def test_missing_video_upload_never_degrades_the_connection(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created, attempt = _send_with_init_fault(
        client, fake_tiktok, monkeypatch, "api_scope_not_authorized"
    )

    assert attempt["error"]["code"] == "tiktok_upload_permission_missing"
    assert "video.upload" in attempt["error"]["message"]
    assert attempt["outcome_determined"] is True
    assert fake_tiktok.calls() == ["inbox_init"]
    connection = get_tiktok_connection(client, created["account"]["id"])
    assert connection["status"] == "connected"


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("api_spam_risk_user_banned_from_posting", "tiktok_creator_cannot_post"),
        ("api_invalid_param", "tiktok_init_failed"),
        ("api_access_token_invalid", "tiktok_unavailable"),
        ("api_rate_limit_exceeded", "tiktok_rate_limited"),
        ("rate_limited", "tiktok_rate_limited"),
        ("server_error", "tiktok_unavailable"),
        ("transport", "tiktok_unavailable"),
    ],
)
def test_init_errors(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    code: str,
) -> None:
    created, attempt = _send_with_init_fault(client, fake_tiktok, monkeypatch, fault)

    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert fake_tiktok.calls().count("inbox_init") == 1
    assert fake_tiktok.requests_to("upload") == []
    connection = get_tiktok_connection(client, created["account"]["id"])
    assert connection["status"] == "connected"
    if code != "tiktok_creator_cannot_post":
        assert NOTHING_SENT in attempt["error"]["message"]
        assert "published" not in attempt["error"]["message"]


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("file_format_check_failed", "tiktok_video_rejected"),
        ("spam_risk", "tiktok_content_rejected"),
        ("spam_risk_too_many_posts", "tiktok_creator_cannot_post"),
        ("internal", "tiktok_publish_failed"),
    ],
)
def test_failed_statuses_use_inbox_wording(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    code: str,
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": reason}]

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert "not delivered to your TikTok inbox" in attempt["error"]["message"]
    assert "not published" not in attempt["error"]["message"]


def test_auth_removed_asks_to_reconnect_as_in_direct_post(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "auth_removed"}]

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["error"]["code"] == "tiktok_publish_failed"
    connection = get_tiktok_connection(client, created["account"]["id"])
    assert connection["status"] == "reconnect_required"


def test_direct_post_scope_not_authorized_is_unchanged(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feature 013: a missing `video.publish` while publishing still asks to
    reconnect the account."""
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["init"] = "api_scope_not_authorized"

    publish_tiktok(client, created["publication"]["id"])

    [attempt] = tiktok_attempts(client, created["publication"]["id"])
    assert attempt["error"]["code"] == "tiktok_reconnect_required"
    connection = get_tiktok_connection(client, created["account"]["id"])
    assert connection["status"] == "reconnect_required"
