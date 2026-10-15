"""Check status of a TikTok publication Ready in TikTok (Feature 014, US5): exactly
one status read of the same `publish_id`, never an init nor a new attempt, and the
derived Upload to Inbox delivery state (`GET /tiktok-delivery`, no network)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    attempt_rows,
    get_publication,
    get_tiktok_connection,
    publish_tiktok,
    run_sql,
    tiktok_inbox_publication,
    tiktok_publication,
    tiktok_run_rows,
)
from tests.fakes import FakeTikTok


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _ready(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """A publication delivered to the inbox; the fake's log is cleared."""
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    publish_tiktok(client, created["publication"]["id"])
    assert get_publication(client, created["publication"]["id"])["status"] == (
        "awaiting_user_action"
    )
    fake_tiktok.requests.clear()
    return created


def _check(client: TestClient, publication_id: int) -> Any:
    return client.post(f"/api/publications/{publication_id}/check-status")


def _delivery(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/tiktok-delivery")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_still_in_the_inbox(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)["publication"]["id"]
    [before] = tiktok_run_rows(db_path)
    attempts = attempt_rows(db_path)
    fake_tiktok.statuses = [{"status": "SEND_TO_USER_INBOX"}]

    response = _check(client, publication_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "awaiting"
    assert body["publication"]["status"] == "awaiting_user_action"
    assert fake_tiktok.calls() == ["status"]
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "delivered"
    assert run["last_status_at"] >= before["last_status_at"]
    assert attempt_rows(db_path) == attempts


def test_published_by_the_user(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)["publication"]["id"]
    attempts = attempt_rows(db_path)
    fake_tiktok.statuses = [
        {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7, 8, 9]}
    ]

    response = _check(client, publication_id)

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "published"
    publication = get_publication(client, publication_id)
    assert publication["status"] == "published"
    assert publication["published_at"] is not None
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "succeeded"
    assert run["user_published_at"] is not None
    assert run["public_post_count"] == 3
    # The delivery attempt stays as it was: no post id, nothing new.
    assert attempt_rows(db_path) == attempts
    assert attempts[0]["external_id"] is None
    delivery = _delivery(client, publication_id)
    assert delivery["state"] == "published"
    assert delivery["user_published_at"] is not None
    assert delivery["can_check_status"] is False


def test_failed_after_delivery(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)["publication"]["id"]
    attempts = attempt_rows(db_path)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "spam_risk"}]

    response = _check(client, publication_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "failed"
    assert "TikTok rejected the content" in body["message"]
    assert get_publication(client, publication_id)["status"] == "failed"
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "failed"
    assert run["fail_reason"] == "spam_risk"
    assert attempt_rows(db_path) == attempts
    assert attempts[0]["status"] == "succeeded"
    delivery = _delivery(client, publication_id)
    assert delivery["state"] == "failed"
    assert delivery["after_delivery_failure"]["code"] == "tiktok_content_rejected"


@pytest.mark.parametrize(
    ("fault", "status", "code"),
    [
        ("server_error", 503, "tiktok_unavailable"),
        ("transport", 503, "tiktok_unavailable"),
        ("rate_limited", 503, "tiktok_rate_limited"),
        ("api_invalid_publish_id", 409, "tiktok_status_unavailable"),
        (
            "api_token_not_authorized_for_specified_publish_id",
            409,
            "tiktok_status_unavailable",
        ),
    ],
)
def test_errors_leave_everything_as_it_was(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    fault: str,
    status: int,
    code: str,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)["publication"]["id"]
    runs = tiktok_run_rows(db_path)
    attempts = attempt_rows(db_path)
    fake_tiktok.faults["status"] = fault

    response = _check(client, publication_id)

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert get_publication(client, publication_id)["status"] == ("awaiting_user_action")
    assert tiktok_run_rows(db_path) == runs
    assert attempt_rows(db_path) == attempts
    # One read, never repeated automatically (a token renewal aside).
    assert fake_tiktok.calls().count("status") == 1
    assert "inbox_init" not in fake_tiktok.calls()


def test_disconnected_account(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = _ready(client, fake_tiktok, monkeypatch)
    run_sql(
        db_path,
        "UPDATE tiktok_connections SET status = 'reconnect_required' "
        "WHERE account_id = ?",
        created["account"]["id"],
    )

    response = _check(client, created["publication"]["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_reconnect_required"
    assert fake_tiktok.requests == []


def test_one_read_per_click_and_never_an_init(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)["publication"]["id"]
    fake_tiktok.statuses = [{"status": "SEND_TO_USER_INBOX"}]

    for _ in range(3):
        assert _check(client, publication_id).status_code == 200

    assert fake_tiktok.calls() == ["status", "status", "status"]
    assert len(attempt_rows(db_path)) == 1


@pytest.mark.parametrize("status", ["PROCESSING_UPLOAD", "SOMETHING_NEW"])
def test_unexpected_statuses_keep_waiting(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    status: str,
) -> None:
    publication_id = _ready(client, fake_tiktok, monkeypatch)["publication"]["id"]
    fake_tiktok.statuses = [{"status": status}]

    response = _check(client, publication_id)

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "awaiting"
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "delivered"


def test_auth_removed_failure_asks_to_reconnect(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _ready(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "auth_removed"}]

    response = _check(client, created["publication"]["id"])

    assert response.json()["result"] == "failed"
    connection = get_tiktok_connection(client, created["account"]["id"])
    assert connection["status"] == "reconnect_required"


# --- Delivery state (no network) ------------------------------------------------------


def test_delivery_states_before_and_after_sending(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]

    assert _delivery(client, publication_id) == {
        "mode": "INBOX_UPLOAD",
        "state": "not_sent",
        "delivered_at": None,
        "user_published_at": None,
        "after_delivery_failure": None,
        "instruction": None,
        "can_check_status": False,
    }
    publish_tiktok(client, publication_id)
    ready = _delivery(client, publication_id)

    assert ready["state"] == "ready"
    assert ready["delivered_at"] is not None
    assert ready["instruction"] == (
        "Open your TikTok inbox to review, edit and publish the video."
    )
    assert ready["can_check_status"] is True
    assert fake_tiktok.calls().count("status") == 2


def test_delivery_of_a_direct_post_publication_is_empty(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)

    delivery = _delivery(client, created["publication"]["id"])

    assert delivery["mode"] == "DIRECT_POST"
    assert delivery["state"] is None
    assert delivery["can_check_status"] is False


def test_scheduled_inbox_delivery(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tiktok_inbox_publication(
        client, fake_tiktok, monkeypatch, scheduled_at="2099-01-01T10:00:00Z"
    )

    assert _delivery(client, created["publication"]["id"])["state"] == "scheduled"


def test_failed_before_delivery_has_no_after_delivery_failure(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": "spam_risk"}]
    publish_tiktok(client, created["publication"]["id"])

    delivery = _delivery(client, created["publication"]["id"])

    assert delivery["state"] == "failed"
    assert delivery["after_delivery_failure"] is None
