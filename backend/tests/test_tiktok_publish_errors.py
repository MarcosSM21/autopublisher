"""Error taxonomy wired to Feature 012 (spec US8, research §19): credentials are
renewed and reconnection is decided only by Feature 012's services; temporary errors
never touch the connection; messages are fixed safe strings."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    get_publication,
    publish_tiktok,
    tiktok_attempts,
    tiktok_ready_publication,
    tiktok_rows,
)
from tests.fakes import FAKE_TT_ERROR_TEXT, FAKE_TT_LOG_ID, FakeTikTok


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _status(db_path: Path) -> str:
    return str(tiktok_rows(db_path)[0]["status"])


def _ready(
    client: TestClient, fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> int:
    created = tiktok_ready_publication(client, fake, monkeypatch)
    return int(created["publication"]["id"])


def test_rejected_token_on_creator_info_is_renewed_once(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.fault_queue["creator_info"] = ["api_access_token_invalid"]

    publish_tiktok(client, publication_id)

    assert fake_tiktok.calls()[:4] == [
        "creator_info",
        "refresh",
        "creator_info",
        "init",
    ]
    assert get_publication(client, publication_id)["status"] == "published"
    assert _status(db_path) == "connected"


def test_rejected_token_on_status_is_renewed_once(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.fault_queue["status"] = ["api_access_token_invalid"]

    publish_tiktok(client, publication_id)

    assert "refresh" in fake_tiktok.calls()
    assert get_publication(client, publication_id)["status"] == "published"
    assert _status(db_path) == "connected"


def test_rejected_token_on_init_is_never_retried(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["init"] = "api_access_token_invalid"

    publish_tiktok(client, publication_id)

    assert fake_tiktok.calls().count("init") == 1
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_unavailable"
    assert attempt["outcome_determined"] is True
    assert _status(db_path) == "connected"


def test_missing_scope_in_the_preflight_requires_reconnecting(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["creator_info"] = "api_scope_not_authorized"

    response = client.post(f"/api/publications/{publication_id}/publish", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_reconnect_required"
    assert _status(db_path) == "reconnect_required"
    assert fake_tiktok.requests_to("init") == []


def test_missing_scope_on_init_requires_reconnecting(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["init"] = "api_scope_not_authorized"

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_reconnect_required"
    assert attempt["outcome_determined"] is True
    assert _status(db_path) == "reconnect_required"


def test_missing_scope_on_status_is_uncertain_and_requires_reconnecting(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["status"] = "api_scope_not_authorized"

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is False
    assert attempt["error"]["code"] == "tiktok_result_uncertain"
    assert _status(db_path) == "reconnect_required"


def test_auth_removed_is_determined_and_requires_reconnecting(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "auth_removed"}]

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_publish_failed"
    assert attempt["outcome_determined"] is True
    assert _status(db_path) == "reconnect_required"


@pytest.mark.parametrize(
    ("endpoint", "fault"),
    [
        ("creator_info", "transport"),
        ("creator_info", "rate_limited"),
        ("init", "server_error"),
        ("init", "rate_limited"),
        ("init", "timeout"),
        ("status", "rate_limited"),
        ("status", "server_error"),
    ],
)
def test_temporary_errors_never_touch_the_connection(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    endpoint: str,
    fault: str,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults[endpoint] = fault

    response = client.post(f"/api/publications/{publication_id}/publish", json={})
    from tests.conftest import wait_idle

    wait_idle(client)

    assert _status(db_path) == "connected"
    text = response.text + str(tiktok_attempts(client, publication_id))
    assert FAKE_TT_ERROR_TEXT not in text


def test_credential_failure_after_the_write_ahead_is_uncertain(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["status"] = "api_access_token_invalid"

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    # Feature 012 decided: a second rejection after renewing requires reconnecting.
    assert _status(db_path) == "reconnect_required"
    assert fake_tiktok.calls().count("upload") == 1


def test_log_id_only_in_logs(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    publication_id = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["init"] = "api_invalid_param"

    publish_tiktok(client, publication_id)

    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["error"]["code"] == "tiktok_init_failed"
    assert FAKE_TT_LOG_ID not in attempt["error"]["message"]
    assert FAKE_TT_ERROR_TEXT not in attempt["error"]["message"]
    assert FAKE_TT_LOG_ID in caplog.text
