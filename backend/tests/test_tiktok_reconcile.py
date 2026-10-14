"""Read-only reconciliation of an uncertain TikTok attempt (research §17): only the
status of the original `publish_id` is read; nothing is initialized, uploaded or
listed."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    get_publication,
    publish_tiktok,
    run_sql,
    tiktok_attempts,
    tiktok_ready_publication,
    tiktok_run_rows,
    wait_idle,
)
from tests.fakes import FAKE_TT_PUBLISH_ID_PREFIX, FakeTikTok


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _uncertain(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> int:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = int(created["publication"]["id"])
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]
    publish_tiktok(client, publication_id)
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["requires_manual_review"] is True
    fake_tiktok.requests.clear()
    return publication_id


def test_publish_complete_settles_it_as_published(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _uncertain(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "PUBLISH_COMPLETE"}]

    check = client.get(f"/api/publications/{publication_id}/publish-check")

    assert check.status_code == 200
    assert fake_tiktok.calls() == ["status"]
    import json

    assert json.loads(fake_tiktok.requests[0].content) == {
        "publish_id": f"{FAKE_TT_PUBLISH_ID_PREFIX}1"
    }
    publication = get_publication(client, publication_id)
    assert publication["status"] == "published"
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["status"] == "succeeded"
    assert attempt["external_url"] is None
    assert attempt["requires_manual_review"] is False
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "succeeded"
    assert publication["published_at"] is not None


@pytest.mark.parametrize(
    "status",
    [
        {"status": "PROCESSING_UPLOAD"},
        {"status": "SEND_TO_USER_INBOX"},
        {"status": "PROCESSING_DOWNLOAD"},
        "server_error",
        "bad_json",
        "api_invalid_publish_id",
        "api_token_not_authorized_for_specified_publish_id",
    ],
)
def test_anything_else_stays_uncertain(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    status: object,
) -> None:
    publication_id = _uncertain(client, fake_tiktok, monkeypatch)
    if isinstance(status, str):
        fake_tiktok.faults["status"] = status
    else:
        fake_tiktok.statuses = [status]  # type: ignore[list-item]

    client.get(f"/api/publications/{publication_id}/publish-check")

    assert get_publication(client, publication_id)["status"] == "failed"
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["requires_manual_review"] is True
    assert set(fake_tiktok.calls()) == {"status"}


def test_publish_now_reconciles_first_and_never_publishes_again(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _uncertain(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "PUBLISH_COMPLETE"}]

    response = client.post(f"/api/publications/{publication_id}/publish", json={})

    assert response.status_code == 409
    assert fake_tiktok.calls() == ["status"]
    assert get_publication(client, publication_id)["status"] == "published"
    assert fake_tiktok.unexpected == []


def test_published_at_is_the_write_ahead_time(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _uncertain(client, fake_tiktok, monkeypatch)
    [run] = tiktok_run_rows(db_path)
    fake_tiktok.statuses = [{"status": "PUBLISH_COMPLETE"}]

    client.get(f"/api/publications/{publication_id}/publish-check")

    publication = get_publication(client, publication_id)
    assert (
        publication["published_at"]
        .replace("T", " ")
        .startswith(run["final_chunk_started_at"][:19])
    )
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("internal", "tiktok_publish_failed"),
        ("frame_rate_check_failed", "tiktok_video_rejected"),
        ("spam_risk_text", "tiktok_content_rejected"),
    ],
)
def test_failed_is_a_confirmed_failure(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    reason: str,
    code: str,
) -> None:
    publication_id = _uncertain(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "FAILED", "fail_reason": reason}]

    check = client.get(f"/api/publications/{publication_id}/publish-check").json()

    assert check["requires_remote_check"] is False
    assert get_publication(client, publication_id)["status"] == "failed"
    [attempt] = tiktok_attempts(client, publication_id)
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert attempt["error"]["code"] == code
    [run] = tiktok_run_rows(db_path)
    assert run["phase"] == "failed"
    assert run["last_remote_status"] == "FAILED"
    assert run["fail_reason"] == reason
    assert fake_tiktok.calls() == ["status"]


def test_runs_without_write_ahead_are_never_read(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    publication_id = _uncertain(client, fake_tiktok, monkeypatch)
    run_sql(db_path, "UPDATE tiktok_publish_runs SET final_chunk_started_at = NULL")

    check = client.get(f"/api/publications/{publication_id}/publish-check").json()

    assert check["requires_remote_check"] is True
    assert fake_tiktok.requests == []


def test_unresolved_attempt_still_needs_the_manual_check(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication_id = _uncertain(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]

    refused = client.post(f"/api/publications/{publication_id}/publish", json={})

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "remote_check_required"
    assert fake_tiktok.calls() == ["status"]
    fake_tiktok.statuses = [{"status": "PUBLISH_COMPLETE"}]
    fake_tiktok.requests.clear()
    # The user checked TikTok: a new attempt is a new Direct Post.
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]
    accepted = client.post(
        f"/api/publications/{publication_id}/publish",
        json={"confirm_remote_checked": True},
    )
    assert accepted.status_code == 202, accepted.text
    wait_idle(client)
    assert fake_tiktok.calls().count("init") == 1
