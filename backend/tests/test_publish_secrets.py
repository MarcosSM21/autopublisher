"""Upload session URLs, tokens and video IDs never leak (FR-032, FR-052, SC-007)."""

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import publishing
from app.youtube_connections import HTTP_LOGGERS, install_log_redaction
from tests.conftest import set_youtube_options, setup_publishable, wait_idle
from tests.fakes import (
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_UPLOAD_ID,
    FAKE_VIDEO_ID,
    UPLOAD_URL,
    FakeGoogle,
    UploadFault,
)

SESSION_URL = f"{UPLOAD_URL}?uploadType=resumable&upload_id={FAKE_UPLOAD_ID}"


@pytest.mark.parametrize("logger_name", HTTP_LOGGERS)
def test_upload_session_ids_are_redacted_from_http_logs(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    install_log_redaction()
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger(logger_name)

    logger.info(
        'HTTP Request: %s %s "%s %d %s"', "PUT", SESSION_URL, "HTTP/1.1", 308, ""
    )
    logger.debug(
        "receive_response_headers.complete return_value=%r",
        (b"HTTP/1.1", 200, b"OK", [(b"Location", SESSION_URL.encode())]),
    )
    logger.debug(f"plain message with {SESSION_URL}")

    assert FAKE_UPLOAD_ID not in caplog.text
    assert caplog.text.count("upload_id=[redacted]") == 3


@pytest.mark.parametrize("logger_name", HTTP_LOGGERS)
def test_upload_id_headers_are_redacted_from_http_logs(
    caplog: pytest.LogCaptureFixture, logger_name: str
) -> None:
    """YouTube repeats the session id in `X-GUploader-UploadID`; httpcore2 logs
    response headers at DEBUG (found during the real validation, T063)."""
    install_log_redaction()
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger(logger_name)

    logger.debug(
        "receive_response_headers.complete return_value=%r",
        (
            b"HTTP/1.1",
            200,
            b"OK",
            [
                (b"Content-Type", b"text/plain"),
                (b"X-GUploader-UploadID", FAKE_UPLOAD_ID.encode()),
                (b"Location", SESSION_URL.encode()),
            ],
        ),
    )
    logger.debug(f"x-guploader-uploadid: {FAKE_UPLOAD_ID}")

    assert FAKE_UPLOAD_ID not in caplog.text
    assert "text/plain" in caplog.text


def test_video_ids_are_redacted_from_http_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    install_log_redaction()
    caplog.set_level(logging.DEBUG)

    logging.getLogger("httpx2").info(
        'HTTP Request: %s %s "%s %d %s"',
        "GET",
        f"https://www.googleapis.com/youtube/v3/videos?part=status&id={FAKE_VIDEO_ID}",
        "HTTP/1.1",
        200,
        "OK",
    )

    assert FAKE_VIDEO_ID not in caplog.text
    assert "id=[redacted]" in caplog.text


# --- End to end: SQLite, API responses and logs --------------------------------------

SECRETS = [
    FAKE_UPLOAD_ID,
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    "Bearer ",
]


def _scenario_success(fake: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing goes wrong."""


def _scenario_recovered(fake: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.upload_faults = [
        UploadFault(on="chunk", store=True),
        UploadFault(on="chunk", status=401),
    ]


def _scenario_failed(fake: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.upload_faults = [UploadFault(on="chunk", status=403, reason="quotaExceeded")]


def _scenario_not_saved(fake: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publishing, "persist_success", lambda *args: False)


@pytest.mark.parametrize(
    "scenario",
    [_scenario_success, _scenario_recovered, _scenario_failed, _scenario_not_saved],
    ids=["success", "recovered", "failed", "result_not_saved"],
)
def test_no_secret_reaches_storage_responses_or_logs(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    scenario: Callable[[FakeGoogle, pytest.MonkeyPatch], None],
) -> None:
    caplog.set_level(logging.DEBUG)
    created = setup_publishable(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    set_youtube_options(publishing_client, publication_id)
    scenario(fake_google, monkeypatch)

    bodies = [
        publishing_client.post(
            f"/api/publications/{publication_id}/publish", json={}
        ).text
    ]
    wait_idle(publishing_client)
    for path in (
        f"/api/publications/{publication_id}",
        f"/api/publications/{publication_id}/attempts",
        f"/api/publications/{publication_id}/publish-check",
        f"/api/publications/{publication_id}/youtube-options",
        f"/api/projects/{created['project']['id']}/publications",
        f"/api/accounts/{created['account']['id']}/youtube-connection",
    ):
        response = publishing_client.get(path)
        assert response.status_code == 200, response.text
        bodies.append(response.text)
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())

    assert fake_google.session_starts, "the scenario must reach YouTube"
    for secret in SECRETS:
        assert secret not in dump
        assert all(secret not in body for body in bodies)
        assert secret not in caplog.text
    assert FAKE_VIDEO_ID not in caplog.text
