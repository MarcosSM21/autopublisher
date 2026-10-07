"""Every preflight condition is rejected before any upload (FR-014, FR-015, US1, US3).

Each case asserts the HTTP status and error code, that the publication keeps its
status, that no attempt exists and that the upload endpoint was never contacted.
"""

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import utc_now
from tests.conftest import (
    FUTURE,
    PAST,
    attempt_rows,
    create_account,
    create_publications,
    get_connection,
    get_publication,
    run_sql,
    set_youtube_options,
    setup_publishable,
    stored_file,
    wait_idle,
)
from tests.fakes import FakeChannel, FakeGoogle, InMemoryCredentialStore

Setup = dict[str, Any]


@pytest.fixture
def env(
    publishing_client: TestClient,
    fake_google: FakeGoogle,
    db_path: Path,
    media_dir: Path,
    credential_store: InMemoryCredentialStore,
    oauth_client_file: Path,
) -> dict[str, Any]:
    return {
        "client": publishing_client,
        "fake": fake_google,
        "db_path": db_path,
        "media_dir": media_dir,
        "store": credential_store,
        "oauth_file": oauth_client_file,
    }


def _ready(env: dict[str, Any], **kwargs: Any) -> Setup:
    created = setup_publishable(env["client"], env["fake"], **kwargs)
    if kwargs.get("connect", True):
        set_youtube_options(env["client"], created["publication"]["id"])
    return created


def _publish(env: dict[str, Any], publication_id: int, **body: Any) -> Any:
    return env["client"].post(f"/api/publications/{publication_id}/publish", json=body)


def _assert_rejected(
    env: dict[str, Any],
    created: Setup,
    status_code: int,
    code: str,
    field: str | None = None,
) -> None:
    publication_id = created["publication"]["id"]
    before = get_publication(env["client"], publication_id)["status"]
    response = _publish(env, publication_id)
    assert response.status_code == status_code, response.text
    error = response.json()["error"]
    assert error["code"] == code
    if field is not None:
        assert field in {entry["field"] for entry in error["fields"]}
    assert get_publication(env["client"], publication_id)["status"] == before
    assert attempt_rows(env["db_path"]) == []
    assert env["fake"].upload_requests == []


def _patch_publication(env: dict[str, Any], created: Setup, **body: Any) -> None:
    response = env["client"].patch(
        f"/api/publications/{created['publication']['id']}", json=body
    )
    assert response.status_code == 200, response.text


def _expire_token(store: InMemoryCredentialStore) -> None:
    (ref,) = store.secrets
    secret = json.loads(store.secrets[ref])
    secret["expires_at"] = (utc_now() - timedelta(minutes=1)).isoformat()
    store.secrets[ref] = json.dumps(secret)


# --- Local checks --------------------------------------------------------------------


def test_project_inactive(env: dict[str, Any]) -> None:
    created = _ready(env)
    env["client"].patch(
        f"/api/projects/{created['project']['id']}", json={"is_active": False}
    )
    _assert_rejected(env, created, 409, "project_inactive")


def test_account_inactive(env: dict[str, Any]) -> None:
    created = _ready(env)
    env["client"].patch(
        f"/api/accounts/{created['account']['id']}", json={"is_active": False}
    )
    _assert_rejected(env, created, 409, "account_inactive")


def test_non_youtube_account(env: dict[str, Any]) -> None:
    created = _ready(env)
    account = create_account(
        env["client"], created["project"]["id"], "instagram", "cyber"
    )
    publication = create_publications(
        env["client"], created["content"]["id"], [account["id"]]
    )[0]
    other = {**created, "publication": publication}
    _assert_rejected(env, other, 409, "platform_not_supported")


def test_image_content(env: dict[str, Any]) -> None:
    created = _ready(env, media_type="image")
    _assert_rejected(env, created, 409, "content_not_video")


@pytest.mark.parametrize(
    "change",
    [
        lambda path: path.unlink(),
        lambda path: path.write_bytes(path.read_bytes() + b"extra"),
    ],
    ids=["missing", "different_size"],
)
def test_media_unavailable(env: dict[str, Any], change: Callable[[Path], None]) -> None:
    created = _ready(env)
    change(stored_file(env["media_dir"], env["db_path"], created["content"]["id"]))
    _assert_rejected(env, created, 409, "media_unavailable")


@pytest.mark.parametrize(
    "title", ["", "x" * 101, "Learn <b>security</b>"], ids=["empty", "long", "angle"]
)
def test_invalid_title(env: dict[str, Any], title: str) -> None:
    created = _ready(env)
    _patch_publication(env, created, title_override=title)
    _assert_rejected(env, created, 409, "invalid_metadata", field="title")


@pytest.mark.parametrize(
    "description", ["é" * 2600, "a > b"], ids=["too_many_bytes", "angle"]
)
def test_invalid_description(env: dict[str, Any], description: str) -> None:
    created = _ready(env)
    _patch_publication(env, created, description_override=description)
    _assert_rejected(env, created, 409, "invalid_metadata", field="description")


def test_options_incomplete(env: dict[str, Any]) -> None:
    created = setup_publishable(env["client"], env["fake"])
    _assert_rejected(env, created, 409, "youtube_options_incomplete")


def test_oauth_not_configured(env: dict[str, Any]) -> None:
    created = _ready(env)
    env["oauth_file"].unlink()
    _assert_rejected(env, created, 503, "oauth_not_configured")


def test_not_connected(env: dict[str, Any]) -> None:
    created = _ready(env, connect=False)
    set_youtube_options(env["client"], created["publication"]["id"])
    _assert_rejected(env, created, 409, "not_connected")


def test_reconnect_required(env: dict[str, Any]) -> None:
    created = _ready(env)
    run_sql(
        env["db_path"], "UPDATE youtube_connections SET status = 'reconnect_required'"
    )
    _assert_rejected(env, created, 409, "reconnect_required")


@pytest.mark.parametrize("status", ["publishing", "published", "cancelled"])
def test_ineligible_states(env: dict[str, Any], status: str) -> None:
    created = _ready(env)
    published_at = "2026-10-07 10:00:00" if status == "published" else None
    run_sql(
        env["db_path"],
        "UPDATE publications SET status = ?, published_at = ?",
        status,
        published_at,
    )
    code = (
        "publication_in_progress"
        if status == "publishing"
        else ("publication_not_eligible")
    )
    _assert_rejected(env, created, 409, code)


# --- Checks that use the network ---------------------------------------------------


def test_refresh_rejected_requires_reconnecting(env: dict[str, Any]) -> None:
    created = _ready(env)
    _expire_token(env["store"])
    env["fake"].refresh_outcome = "invalid_grant"
    _assert_rejected(env, created, 409, "reconnect_required")
    connection = get_connection(env["client"], created["account"]["id"])
    assert connection["status"] == "reconnect_required"


def test_credential_store_unavailable(env: dict[str, Any]) -> None:
    created = _ready(env)
    env["store"].unavailable = True
    _assert_rejected(env, created, 503, "credential_store_unavailable")


def test_youtube_unreachable_keeps_the_connection(env: dict[str, Any]) -> None:
    created = _ready(env)
    env["fake"].channels_outcome = "server_error"
    _assert_rejected(env, created, 503, "youtube_unavailable")
    connection = get_connection(env["client"], created["account"]["id"])
    assert connection["status"] == "connected"


@pytest.mark.parametrize(
    "channels",
    [
        [FakeChannel("UC_OTHER", "Other")],
        [FakeChannel("UC_TEST_1", "Cyber Channel"), FakeChannel("UC_OTHER", "Other")],
    ],
    ids=["other_channel", "two_channels"],
)
def test_channel_mismatch_never_uploads(
    env: dict[str, Any], channels: list[FakeChannel]
) -> None:
    created = _ready(env)
    env["fake"].channels = channels
    _assert_rejected(env, created, 409, "reconnect_required")
    connection = get_connection(env["client"], created["account"]["id"])
    assert connection["status"] == "reconnect_required"


# --- Eligible states ----------------------------------------------------------------


def test_scheduled_with_a_past_date_is_eligible(env: dict[str, Any]) -> None:
    created = _ready(env, scheduled_at=FUTURE)
    run_sql(env["db_path"], "UPDATE publications SET scheduled_at = ?", PAST)

    response = _publish(env, created["publication"]["id"])

    assert response.status_code == 202, response.text
    wait_idle(env["client"])


def test_failed_with_a_determined_outcome_is_eligible(env: dict[str, Any]) -> None:
    created = _ready(env)
    publication_id = created["publication"]["id"]
    run_sql(env["db_path"], "UPDATE publications SET status = 'failed'")
    run_sql(
        env["db_path"],
        "INSERT INTO publication_attempts (publication_id, platform, status, stage, "
        "started_at, finished_at, bytes_sent, total_bytes, error_code, error_message, "
        "outcome_determined, submitted, details, warnings) VALUES (?, 'youtube', "
        "'failed', 'uploading', '2026-10-07 10:00:00', '2026-10-07 10:01:00', 0, 10, "
        "'network_error', 'Network error.', 1, '{}', '{}', '[]')",
        publication_id,
    )

    response = _publish(env, publication_id)

    assert response.status_code == 202, response.text
    wait_idle(env["client"])
    publication = get_publication(env["client"], publication_id)
    assert publication["status"] == "published"
    assert publication["attempt_count"] == 2


# --- publish-check matches POST /publish (US3) ---------------------------------------


def _check(env: dict[str, Any], publication_id: int) -> dict[str, Any]:
    response = env["client"].get(f"/api/publications/{publication_id}/publish-check")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


LOCAL_CASES: dict[str, Callable[[dict[str, Any], Setup], None]] = {
    "project_inactive": lambda env, created: env["client"].patch(
        f"/api/projects/{created['project']['id']}", json={"is_active": False}
    ),
    "account_inactive": lambda env, created: env["client"].patch(
        f"/api/accounts/{created['account']['id']}", json={"is_active": False}
    ),
    "media_unavailable": lambda env, created: stored_file(
        env["media_dir"], env["db_path"], created["content"]["id"]
    ).unlink(),
    "invalid_metadata": lambda env, created: _patch_publication(
        env, created, title_override="x" * 101
    ),
    "oauth_not_configured": lambda env, created: env["oauth_file"].unlink(),
    "reconnect_required": lambda env, created: run_sql(
        env["db_path"], "UPDATE youtube_connections SET status = 'reconnect_required'"
    ),
    "publication_in_progress": lambda env, created: run_sql(
        env["db_path"], "UPDATE publications SET status = 'publishing'"
    ),
}


@pytest.mark.parametrize("code", sorted(LOCAL_CASES))
def test_publish_check_reports_what_publish_would_reject(
    env: dict[str, Any], code: str
) -> None:
    created = _ready(env)
    publication_id = created["publication"]["id"]
    LOCAL_CASES[code](env, created)
    requests_before = len(env["fake"].requests)

    check = _check(env, publication_id)

    assert len(env["fake"].requests) == requests_before
    assert check["eligible"] is False
    first = check["problems"][0]
    response = _publish(env, publication_id)
    error = response.json()["error"]
    assert first["code"] == error["code"] == code
    if first["field"] is not None:
        assert first["field"] in {entry["field"] for entry in error["fields"]}


def test_publish_check_for_a_valid_publication(env: dict[str, Any]) -> None:
    created = _ready(env, scheduled_at=FUTURE)
    requests_before = len(env["fake"].requests)

    check = _check(env, created["publication"]["id"])

    assert len(env["fake"].requests) == requests_before
    assert check["eligible"] is True
    assert check["problems"] == []
    assert check["requires_remote_check"] is False
    assert check["scheduled_at"].startswith("2100-01-01T10:00:00")
    assert [item["label"] for item in check["summary"]] == [
        "Title",
        "Channel",
        "Privacy",
        "Notify subscribers",
        "Made for kids",
        "Altered or synthetic content",
        "File",
    ]
    summary = {item["label"]: item["value"] for item in check["summary"]}
    assert summary["Channel"] == "Cyber Channel (UC_TEST_1)"
    assert summary["Privacy"] == "private"
    assert summary["Notify subscribers"] == "No"
