"""Safe, understandable Threads failures and connection effects (US8, research
§16): definitive credential errors mark the connection, temporary ones never do."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    get_threads_connection,
    publish_and_wait,
    threads_text_publication,
)
from tests.fakes import FAKE_META_ERROR_TEXT, FakeThreads

PUBLISH_CREDENTIAL_ERRORS = ["graph_190", "graph_10"]


def _publish(client: TestClient) -> tuple[dict[str, object], int]:
    created = threads_text_publication(client)
    published = publish_and_wait(client, created["publication"]["id"])
    return published, created["account"]["id"]


def _status_fault_after_creation(fake_threads: FakeThreads, fault: str) -> None:
    def break_reads() -> None:
        fake_threads.faults["status"] = fault

    fake_threads.create_hook = break_reads


@pytest.mark.parametrize("fault", PUBLISH_CREDENTIAL_ERRORS)
@pytest.mark.parametrize("step", ["create", "status", "publish"])
def test_credential_errors_mark_reconnect_required(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fault: str,
    step: str,
) -> None:
    if step == "status":
        _status_fault_after_creation(fake_threads, fault)
    else:
        fake_threads.faults[step] = fault

    published, account_id = _publish(threads_publishing_client)

    attempt = published["latest_attempt"]
    assert isinstance(attempt, dict)
    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_reconnect_required"
    assert attempt["outcome_determined"] is True
    connection = get_threads_connection(threads_publishing_client, account_id)
    assert connection["status"] == "reconnect_required"
    assert len(fake_threads.requests_for("publish")) <= 1


@pytest.mark.parametrize("step", ["create", "status"])
def test_temporary_errors_never_change_the_connection(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    step: str,
) -> None:
    if step == "status":
        _status_fault_after_creation(fake_threads, "server_error")
    else:
        fake_threads.faults[step] = "server_error"

    published, account_id = _publish(threads_publishing_client)

    attempt = published["latest_attempt"]
    assert isinstance(attempt, dict)
    expected = (
        "threads_unavailable" if step == "create" else "threads_processing_timeout"
    )
    assert attempt["error"]["code"] == expected
    assert attempt["outcome_determined"] is True
    connection = get_threads_connection(threads_publishing_client, account_id)
    assert connection["status"] == "connected"
    assert fake_threads.requests_for("publish") == []


def test_temporary_publish_error_keeps_the_connection_and_is_uncertain(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["publish"] = "rate_limited"

    published, account_id = _publish(threads_publishing_client)

    attempt = published["latest_attempt"]
    assert isinstance(attempt, dict)
    assert attempt["error"]["code"] == "threads_publish_uncertain"
    connection = get_threads_connection(threads_publishing_client, account_id)
    assert connection["status"] == "connected"


def test_link_limit_rejection_is_a_text_problem(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["create"] = "link_limit"

    published, _ = _publish(threads_publishing_client)

    attempt = published["latest_attempt"]
    assert isinstance(attempt, dict)
    assert attempt["error"]["code"] == "threads_text_invalid"
    assert "5 links" in attempt["error"]["message"]


SCENARIOS: dict[str, dict[str, Any]] = {
    "threads_container_failed": {"faults": {"create": "graph_100"}},
    "threads_unavailable": {"faults": {"create": "server_error"}},
    "threads_processing_failed": {"status_script": ["ERROR:UNKNOWN"]},
    "threads_media_rejected": {"status_script": ["ERROR:INVALID_FRAME_RATE"]},
    "threads_media_fetch_failed": {"status_script": ["ERROR:FAILED_DOWNLOADING_VIDEO"]},
    "threads_container_expired": {"status_script": ["EXPIRED"]},
    "threads_processing_timeout": {"status_script": ["IN_PROGRESS"]},
    "threads_publish_failed": {"faults": {"publish": "graph_100"}},
    "threads_publish_uncertain": {"faults": {"publish": "timeout"}},
    "threads_reconnect_required": {"faults": {"publish": "graph_190"}},
}


@pytest.mark.parametrize("code", sorted(SCENARIOS))
def test_every_failure_has_a_safe_english_message_and_history(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    code: str,
) -> None:
    scenario = SCENARIOS[code]
    for key, value in scenario.get("faults", {}).items():
        fake_threads.faults[key] = value
    if "status_script" in scenario:
        fake_threads.status_script = scenario["status_script"]

    published, _ = _publish(threads_publishing_client)

    attempt = published["latest_attempt"]
    assert isinstance(attempt, dict)
    error = attempt["error"]
    assert error["code"] == code
    assert len(code) <= 40
    message: str = error["message"]
    assert message.strip()
    assert FAKE_META_ERROR_TEXT not in message
    assert attempt["outcome_determined"] is (code != "threads_publish_uncertain")
    attempts = threads_publishing_client.get(
        f"/api/publications/{published['id']}/attempts"
    ).json()
    assert [(a["trigger"], a["error"]["code"]) for a in attempts] == [("manual", code)]
