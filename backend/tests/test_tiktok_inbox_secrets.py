"""Upload to Inbox never exposes the upload URL, tokens, the `Authorization` header
nor the `publish_id` (Feature 014, FR-037): not in the database, the logs, the API
responses nor the error messages."""

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import publish_tiktok, tiktok_inbox_publication
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_ERROR_TEXT,
    FAKE_TT_PUBLISH_ID_PREFIX,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_UPLOAD_ID,
    FAKE_TT_UPLOAD_TOKEN,
    TT_UPLOAD_BASE,
    FakeTikTok,
)

SECRETS = (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_UPLOAD_ID,
    FAKE_TT_UPLOAD_TOKEN,
    FAKE_TT_PUBLISH_ID_PREFIX,
    TT_UPLOAD_BASE,
    "open-upload.tiktokapis",
    "upload_token=",
    "Bearer ",
)


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _texts(client: TestClient, publication_id: int, db_path: Path) -> list[str]:
    return [
        _dump(db_path),
        client.get(f"/api/publications/{publication_id}").text,
        client.get(f"/api/publications/{publication_id}/attempts").text,
        client.get(f"/api/publications/{publication_id}/tiktok-options").text,
        client.get(f"/api/publications/{publication_id}/publish-check").text,
    ]


def _dump(db_path: Path) -> str:
    """The whole database, except the run's own `publish_id` column: that one
    record is how the same upload is ever checked again (research §10)."""
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
        publish_ids = [
            row[0]
            for row in connection.execute(
                "SELECT publish_id FROM tiktok_publish_runs "
                "WHERE publish_id IS NOT NULL"
            )
        ]
    for publish_id in publish_ids:
        # Exactly once: the run row.
        assert dump.count(publish_id) == 1
        dump = dump.replace(publish_id, "<publish_id>")
    return dump


def _assert_clean(texts: list[str]) -> None:
    for text in texts:
        for secret in SECRETS:
            assert secret not in text, secret
        assert "authorization" not in text.lower()


@pytest.mark.parametrize(
    "statuses",
    [
        [{"status": "PROCESSING_UPLOAD"}, {"status": "SEND_TO_USER_INBOX"}],
        [{"status": "FAILED", "fail_reason": "spam_risk"}],
        [{"status": "PROCESSING_DOWNLOAD"}],
    ],
    ids=["delivered", "failed", "ambiguous"],
)
def test_upload_to_inbox_leaves_no_secret(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_path: Path,
    statuses: list[dict[str, Any]],
) -> None:
    caplog.set_level(logging.DEBUG)
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.statuses = list(statuses)
    publication_id = created["publication"]["id"]

    publish_tiktok(client, publication_id)

    assert fake_tiktok.requests_to("upload"), "the scenario must upload"
    _assert_clean([*_texts(client, publication_id, db_path), caplog.text])
    assert FAKE_TT_ERROR_TEXT not in caplog.text


@pytest.mark.parametrize(
    "fault",
    [
        "api_spam_risk_too_many_pending_share",
        "api_scope_not_authorized",
        "api_invalid_param",
        "server_error",
    ],
)
def test_init_errors_leave_no_secret(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_path: Path,
    fault: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.faults["inbox_init"] = fault
    publication_id = created["publication"]["id"]

    publish_tiktok(client, publication_id)

    texts = _texts(client, publication_id, db_path)
    _assert_clean([*texts, caplog.text])
    # TikTok's own error text never reaches the user.
    assert all(FAKE_TT_ERROR_TEXT not in text for text in texts)


@pytest.mark.parametrize(
    "check",
    [
        {"status": "SEND_TO_USER_INBOX"},
        {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7]},
        {"status": "FAILED", "fail_reason": "spam_risk"},
        "server_error",
        "api_invalid_publish_id",
    ],
    ids=["awaiting", "published", "failed", "unavailable", "status_unavailable"],
)
def test_check_status_and_delivery_leave_no_secret(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_path: Path,
    check: dict[str, Any] | str,
) -> None:
    caplog.set_level(logging.DEBUG)
    created = tiktok_inbox_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    publish_tiktok(client, publication_id)
    if isinstance(check, str):
        fake_tiktok.faults["status"] = check
    else:
        fake_tiktok.statuses = [check]

    response = client.post(f"/api/publications/{publication_id}/check-status")
    delivery = client.get(f"/api/publications/{publication_id}/tiktok-delivery")

    assert fake_tiktok.requests_to("status")
    texts = [
        response.text,
        delivery.text,
        *_texts(client, publication_id, db_path),
    ]
    _assert_clean([*texts, caplog.text])
    assert all(FAKE_TT_ERROR_TEXT not in text for text in texts)
