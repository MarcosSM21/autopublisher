"""Publish now: real resumable upload against the YouTube simulator (US1, US4, US6)."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app.db import utc_now
from app.main import create_app
from app.youtube_upload import MESSAGES as UPLOAD_MESSAGES
from tests.conftest import (
    FUTURE,
    VIDEO_DESCRIPTION,
    VIDEO_TITLE,
    attempt_rows,
    get_connection,
    get_publication,
    publish_and_wait,
    set_youtube_options,
    setup_publishable,
    stored_file,
    wait_idle,
)
from tests.fakes import (
    FAKE_GOOGLE_ERROR_TEXT,
    FAKE_VIDEO_ID,
    FakeGoogle,
    InMemoryCredentialStore,
    UploadFault,
)

CHUNK = 256 * 1024
SUBMITTED_KEYS = {
    "title",
    "description",
    "privacy_status",
    "made_for_kids",
    "contains_synthetic_media",
    "notify_subscribers",
    "channel_id",
    "channel_title",
    "file_name",
    "file_size",
}


def ready(
    client: TestClient, fake_google: FakeGoogle, **options: Any
) -> dict[str, Any]:
    """A publishable YouTube video publication with complete options."""
    created = setup_publishable(client, fake_google)
    set_youtube_options(client, created["publication"]["id"], **options)
    return created


def _data_puts(fake_google: FakeGoogle) -> list[Any]:
    return [
        r
        for r in fake_google.upload_requests
        if r.method == "PUT" and not r.headers["content-range"].startswith("bytes */")
    ]


def _db_attempt(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT stage, bytes_sent FROM publication_attempts ORDER BY id DESC"
        ).fetchone()
    return dict(row) if row else {}


def test_publish_now_uploads_the_video(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = ready(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    fake_google.block_uploads(at="start")

    response = publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "publishing"
    assert body["latest_attempt"]["status"] == "running"
    assert body["latest_attempt"]["stage"] == "preparing"
    fake_google.release()
    wait_idle(publishing_client)

    publication = get_publication(publishing_client, publication_id)
    assert publication["status"] == "published"
    assert publication["published_at"] is not None
    assert publication["attempt_count"] == 1
    attempt = publication["latest_attempt"]
    assert attempt["status"] == "succeeded"
    assert attempt["stage"] == "done"
    assert attempt["external_id"] == FAKE_VIDEO_ID
    assert attempt["external_url"] == f"https://www.youtube.com/watch?v={FAKE_VIDEO_ID}"
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert attempt["progress"] == 1
    assert attempt["error"] is None
    assert len(fake_google.videos_created) == 1


def test_session_start_request_carries_the_youtube_resource(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = ready(publishing_client, fake_google)
    file_size = created["content"]["size_bytes"]

    publish_and_wait(publishing_client, created["publication"]["id"])

    (start,) = fake_google.session_starts
    params = parse_qs(urlsplit(start.url).query)
    assert params["uploadType"] == ["resumable"]
    assert params["part"] == ["snippet,status"]
    assert params["notifySubscribers"] == ["false"]
    assert start.headers["x-upload-content-length"] == str(file_size)
    assert start.headers["x-upload-content-type"] == "video/mp4"
    resource = json.loads(start.content)
    assert resource == {
        "snippet": {
            "title": VIDEO_TITLE,
            "description": f"{VIDEO_DESCRIPTION}\n\n#cyber #security",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,
        },
    }


def test_notify_subscribers_is_sent_explicitly(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = ready(publishing_client, fake_google, notify_subscribers=True)

    publish_and_wait(publishing_client, created["publication"]["id"])

    params = parse_qs(urlsplit(fake_google.session_starts[0].url).query)
    assert params["notifySubscribers"] == ["true"]


def test_file_is_streamed_in_chunks_and_left_untouched(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    media_dir: Path,
    db_path: Path,
) -> None:
    created = ready(publishing_client, fake_google)
    path = stored_file(media_dir, db_path, created["content"]["id"])
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    mtime = path.stat().st_mtime_ns

    publish_and_wait(publishing_client, created["publication"]["id"])

    puts = _data_puts(fake_google)
    total = path.stat().st_size
    assert len(puts) == -(-total // CHUNK)
    expected_start = 0
    for index, request in enumerate(puts):
        span, size = request.headers["content-range"][len("bytes ") :].split("/")
        start, end = (int(value) for value in span.split("-"))
        assert int(size) == total
        assert start == expected_start
        length = end - start + 1
        assert length == len(request.content)
        assert length <= CHUNK
        if index < len(puts) - 1:
            assert length % CHUNK == 0
        expected_start = end + 1
    assert expected_start == total
    assert fake_google.videos_created[0]["data"] == path.read_bytes()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    assert path.stat().st_mtime_ns == mtime
    assert list((media_dir / "tmp").iterdir()) == []


def test_progress_and_write_ahead_of_the_last_chunk(
    publishing_client: TestClient, fake_google: FakeGoogle, db_path: Path
) -> None:
    created = ready(publishing_client, fake_google)
    seen: list[tuple[str, dict[str, Any]]] = []
    fake_google.upload_hook = lambda kind, request: seen.append(
        (kind, _db_attempt(db_path))
    )

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    chunk_states = [state for kind, state in seen if kind in {"chunk", "last_chunk"}]
    kinds = [kind for kind, _ in seen if kind in {"chunk", "last_chunk"}]
    assert kinds[-1] == "last_chunk"
    assert [state["stage"] for state in chunk_states[:-1]] == ["uploading"] * (
        len(chunk_states) - 1
    )
    assert chunk_states[-1]["stage"] == "final_chunk"
    sent = [state["bytes_sent"] for state in chunk_states]
    assert sent == sorted(sent)
    assert sent[-1] > 0
    attempt = publication["latest_attempt"]
    assert attempt["bytes_sent"] == attempt["total_bytes"]


def test_attempt_records_only_whitelisted_values(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = ready(publishing_client, fake_google)

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    attempt = publication["latest_attempt"]
    assert set(attempt["submitted"]) == SUBMITTED_KEYS
    assert attempt["submitted"]["title"] == VIDEO_TITLE
    assert attempt["submitted"]["channel_id"] == "UC_TEST_1"
    assert attempt["submitted"]["notify_subscribers"] is False
    assert attempt["details"] == {
        "privacy_status": "private",
        "upload_status": "uploaded",
        "processing_status": "processing",
    }
    assert attempt["warnings"] == []


def test_published_result_survives_a_restart(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    media_dir: Path,
    credential_store: InMemoryCredentialStore,
) -> None:
    created = ready(publishing_client, fake_google)
    publication_id = created["publication"]["id"]
    before = publish_and_wait(publishing_client, publication_id)

    app = create_app(
        db_path,
        media_dir,
        credential_store=credential_store,
        google_transport=fake_google.transport(),
    )
    with TestClient(app) as restarted:
        after = get_publication(restarted, publication_id)

    assert after["status"] == "published"
    assert after["published_at"] == before["published_at"]
    assert after["latest_attempt"] == before["latest_attempt"]


def test_real_privacy_different_from_requested_is_kept_with_a_warning(
    publishing_client: TestClient, fake_google: FakeGoogle, db_path: Path
) -> None:
    created = ready(publishing_client, fake_google, privacy_status="public")
    fake_google.returned_privacy = "private"

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "published"
    assert publication["latest_attempt"]["status"] == "succeeded"
    (row,) = attempt_rows(db_path)
    assert json.loads(row["details"])["privacy_status"] == "private"
    warnings = json.loads(row["warnings"])
    assert warnings == [
        {
            "code": "privacy_differs",
            "message": "YouTube set the privacy to private instead of the requested "
            "public. Unverified API projects can only upload private videos.",
        }
    ]
    assert FAKE_GOOGLE_ERROR_TEXT not in row["warnings"]


@pytest.mark.parametrize("outcome", ["server_error", "timeout"])
def test_failed_light_check_keeps_the_publication_published(
    publishing_client: TestClient, fake_google: FakeGoogle, outcome: str
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.videos_list_outcome = outcome

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "published"
    attempt = publication["latest_attempt"]
    assert attempt["status"] == "succeeded"
    assert attempt["error"] is None
    assert attempt["external_id"] == FAKE_VIDEO_ID
    assert attempt["details"] == {
        "privacy_status": "private",
        "upload_status": "uploaded",
    }


# --- Recovery within the same attempt (US4, research.md §4) --------------------------


def _assert_published_once(
    client: TestClient, fake: FakeGoogle, created: dict[str, Any]
) -> dict[str, Any]:
    publication = get_publication(client, created["publication"]["id"])
    assert publication["status"] == "published", publication["latest_attempt"]
    assert publication["attempt_count"] == 1
    assert len(fake.videos_created) == 1
    return publication


def test_lost_connection_resumes_from_the_confirmed_byte(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    recorded_sleeps: list[float],
    media_dir: Path,
    db_path: Path,
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="chunk", store=True)]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    path = stored_file(media_dir, db_path, created["content"]["id"])
    assert fake_google.videos_created[0]["data"] == path.read_bytes()
    assert len(fake_google.session_starts) == 1
    statuses = [
        r
        for r in fake_google.upload_requests
        if r.method == "PUT" and r.headers["content-range"].startswith("bytes */")
    ]
    assert len(statuses) == 1
    assert len(recorded_sleeps) == 1
    assert 1 <= recorded_sleeps[0] <= 1.2


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (500, None),
        (502, None),
        (503, None),
        (504, None),
        (429, None),
        (403, "rateLimitExceeded"),
        (403, "userRateLimitExceeded"),
    ],
)
def test_temporary_youtube_errors_are_recovered(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    recorded_sleeps: list[float],
    status: int,
    reason: str | None,
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="chunk", status=status, reason=reason)]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    assert len(recorded_sleeps) == 1


@pytest.mark.parametrize(
    "fault", [UploadFault(on="start"), UploadFault(on="start", status=503)]
)
def test_session_start_is_retried(
    publishing_client: TestClient, fake_google: FakeGoogle, fault: UploadFault
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [fault]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    assert len(fake_google.session_starts) == 2


def test_backoff_grows_exponentially(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    recorded_sleeps: list[float],
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="put", status=503) for _ in range(5)]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    assert len(recorded_sleeps) == 5
    for base, waited in zip([1, 2, 4, 8, 16], recorded_sleeps, strict=True):
        assert base <= waited <= base * 1.2


def test_failure_counter_restarts_after_progress(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = ready(publishing_client, fake_google)
    data_puts = 0

    def add_faults(kind: str, request: httpx.Request) -> None:
        nonlocal data_puts
        if kind in {"chunk", "last_chunk"}:
            data_puts += 1
            if data_puts in {2, 4}:
                fake_google.upload_faults.extend(
                    UploadFault(on="put", status=503) for _ in range(5)
                )

    fake_google.upload_hook = add_faults

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        (UploadFault(on="put", status=503), "youtube_unavailable"),
        (UploadFault(on="put"), "network_error"),
    ],
)
def test_recovery_is_limited(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    recorded_sleeps: list[float],
    fault: UploadFault,
    code: str,
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [fault for _ in range(6)]

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert len(recorded_sleeps) == 5
    assert fake_google.videos_created == []


# --- Retry-After (research.md §4) ---------------------------------------------------


def test_retry_after_seconds_is_respected(
    publishing_client: TestClient, fake_google: FakeGoogle, recorded_sleeps: list[float]
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="chunk", status=503, retry_after="10")]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    assert recorded_sleeps == [10]


def test_retry_after_http_date_is_respected(
    publishing_client: TestClient, fake_google: FakeGoogle, recorded_sleeps: list[float]
) -> None:
    created = ready(publishing_client, fake_google)
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    fake_google.upload_faults = [UploadFault(on="chunk", status=429, retry_after=when)]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    (waited,) = recorded_sleeps
    assert 27 <= waited <= 30


def test_too_long_retry_after_stops_without_retrying(
    publishing_client: TestClient, fake_google: FakeGoogle, recorded_sleeps: list[float]
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="chunk", status=503, retry_after="120")]

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"]["code"] == "youtube_unavailable"
    assert attempt["outcome_determined"] is True
    assert recorded_sleeps == []
    assert len(_data_puts(fake_google)) == 1


@pytest.mark.parametrize("value", ["soon", "-5", "0"])
def test_unreadable_retry_after_falls_back_to_backoff(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    recorded_sleeps: list[float],
    value: str,
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="chunk", status=503, retry_after=value)]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    (waited,) = recorded_sleeps
    assert 1 <= waited <= 1.2


# --- Definitive errors (research.md §6) ----------------------------------------------


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        (UploadFault(on="chunk", status=403, reason="quotaExceeded"), "quota_exceeded"),
        (
            UploadFault(on="start", status=403, reason="dailyLimitExceeded"),
            "quota_exceeded",
        ),
        (
            UploadFault(on="start", status=400, reason="uploadLimitExceeded"),
            "upload_limit_exceeded",
        ),
        (UploadFault(on="chunk", status=403, reason="forbidden"), "permission_denied"),
        (
            UploadFault(on="start", status=400, reason="invalidTitle"),
            "invalid_metadata",
        ),
        (UploadFault(on="start", status=400, reason="badRequest"), "youtube_rejected"),
        (UploadFault(on="chunk", status=404), "upload_session_expired"),
    ],
)
def test_definitive_errors_are_not_retried(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    recorded_sleeps: list[float],
    fault: UploadFault,
    code: str,
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [fault]

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"] == {"code": code, "message": UPLOAD_MESSAGES[code]}
    assert attempt["outcome_determined"] is True
    assert FAKE_GOOGLE_ERROR_TEXT not in attempt["error"]["message"]
    assert recorded_sleeps == []
    assert len(fake_google.session_starts) == 1
    assert len(_data_puts(fake_google)) <= 1
    assert fake_google.videos_created == []


def test_unauthorized_upload_refreshes_once(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [UploadFault(on="chunk", status=401)]

    publish_and_wait(publishing_client, created["publication"]["id"])

    _assert_published_once(publishing_client, fake_google, created)
    refreshes = [
        r
        for r in fake_google.token_requests
        if r.form.get("grant_type") == "refresh_token"
    ]
    assert len(refreshes) == 1


def test_repeated_unauthorized_requires_reconnecting(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = ready(publishing_client, fake_google)
    fake_google.upload_faults = [
        UploadFault(on="chunk", status=401),
        UploadFault(on="chunk", status=401),
    ]

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["latest_attempt"]["error"]["code"] == "reconnect_required"
    connection = get_connection(publishing_client, created["account"]["id"])
    assert connection["status"] == "reconnect_required"


def test_revoked_credentials_during_the_upload(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    credential_store: InMemoryCredentialStore,
) -> None:
    created = ready(publishing_client, fake_google)

    def revoke(kind: str, request: httpx.Request) -> None:
        if kind == "chunk" and fake_google.refresh_outcome == "ok":
            (ref,) = credential_store.secrets
            secret = json.loads(credential_store.secrets[ref])
            secret["expires_at"] = (utc_now() - timedelta(minutes=1)).isoformat()
            credential_store.secrets[ref] = json.dumps(secret)
            fake_google.refresh_outcome = "invalid_grant"

    fake_google.upload_hook = revoke

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["error"]["code"] == "reconnect_required"
    connection = get_connection(publishing_client, created["account"]["id"])
    assert connection["status"] == "reconnect_required"


def test_file_shrinking_during_the_upload(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    media_dir: Path,
    db_path: Path,
) -> None:
    created = ready(publishing_client, fake_google)
    path = stored_file(media_dir, db_path, created["content"]["id"])

    def shrink(kind: str, request: httpx.Request) -> None:
        if kind == "chunk":
            path.write_bytes(b"x")

    fake_google.upload_hook = shrink

    publication = publish_and_wait(publishing_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    attempt = publication["latest_attempt"]
    assert attempt["error"]["code"] == "media_unavailable"
    assert attempt["outcome_determined"] is True


# --- Publishing a scheduled publication early (US6) ----------------------------------


def test_scheduled_publication_is_published_now_and_keeps_its_date(
    publishing_client: TestClient, fake_google: FakeGoogle
) -> None:
    created = setup_publishable(publishing_client, fake_google, scheduled_at=FUTURE)
    publication_id = created["publication"]["id"]
    set_youtube_options(publishing_client, publication_id)
    check = publishing_client.get(
        f"/api/publications/{publication_id}/publish-check"
    ).json()
    assert check["scheduled_at"].startswith("2100-01-01T10:00:00")

    publication = publish_and_wait(publishing_client, publication_id)

    assert publication["status"] == "published"
    assert publication["scheduled_at"].startswith("2100-01-01T10:00:00")
    assert publication["published_at"] is not None
    resource = json.loads(fake_google.session_starts[0].content)
    assert "publishAt" not in resource["status"]
    again = publishing_client.post(
        f"/api/publications/{publication_id}/publish", json={}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "publication_not_eligible"
    assert len(fake_google.session_starts) == 1
