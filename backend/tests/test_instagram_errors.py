"""Every Instagram execution error has a stable, safe code and message; credential
errors mark the connection for reconnection, temporary ones never (US7, FR-047-FR-049,
FR-063, research.md §18)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    allow_reels,
    get_instagram_connection,
    instagram_publication,
    publish_and_wait,
)
from tests.fakes import (
    FAKE_IG_LONG_TOKEN,
    FAKE_META_ERROR_TEXT,
    FAKE_SIGNATURE,
    FakeMediaDeliveryProvider,
    FakeMeta,
)

CASES: list[tuple[str, str, str, bool]] = [
    # (endpoint, fault, code, connection still connected)
    ("create", "graph_-1_2207032", "instagram_container_failed", True),
    ("create", "graph_9004_2207052", "instagram_media_fetch_failed", True),
    ("create", "graph_-2_2207003", "instagram_media_fetch_failed", True),
    ("create", "graph_36003_2207009", "instagram_media_rejected", True),
    ("create", "graph_352_2207026", "instagram_media_rejected", True),
    ("create", "graph_25_2207050", "instagram_account_restricted", True),
    ("create", "graph_4_2207051", "instagram_account_restricted", True),
    ("create", "graph_100", "instagram_container_failed", True),
    ("create", "server_error", "instagram_unavailable", True),
    ("create", "rate_limited", "instagram_unavailable", True),
    ("create", "transport", "instagram_unavailable", True),
    ("create", "graph_190", "instagram_reconnect_required", False),
    ("create", "graph_10", "instagram_reconnect_required", False),
    ("publish", "graph_9_2207042", "instagram_publishing_limit_reached", True),
    ("publish", "graph_-2_2207020", "instagram_container_expired", True),
    ("publish", "graph_9007_2207027", "instagram_publish_failed", True),
    ("publish", "graph_190", "instagram_reconnect_required", False),
]


@pytest.mark.parametrize(("endpoint", "fault", "code", "connected"), CASES)
def test_execution_errors(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    endpoint: str,
    fault: str,
    code: str,
    connected: bool,
) -> None:
    fake_meta.faults[endpoint] = fault
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    attempt = publication["latest_attempt"]
    assert publication["status"] == "failed"
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert len(attempt["error"]["code"]) <= 40
    message = attempt["error"]["message"]
    for secret in (FAKE_META_ERROR_TEXT, FAKE_IG_LONG_TOKEN, FAKE_SIGNATURE):
        assert secret not in message
    assert "18000000000" not in message
    connection = get_instagram_connection(ig_client, created["account"]["id"])
    assert connection["status"] == ("connected" if connected else "reconnect_required")
    assert fake_meta.published == []


def test_delivery_failure(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    fake_delivery.put_failures = 10
    created = instagram_publication(ig_client)

    attempt = publish_and_wait(ig_client, created["publication"]["id"])[
        "latest_attempt"
    ]

    assert attempt["error"]["code"] == "media_delivery_failed"
    assert fake_meta.containers == {}


@pytest.mark.parametrize(
    ("script", "code"),
    [
        (["ERROR"], "instagram_processing_failed"),
        (["EXPIRED"], "instagram_container_expired"),
        (["IN_PROGRESS"], "instagram_processing_timeout"),
    ],
)
def test_processing_errors(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    monkeypatch: pytest.MonkeyPatch,
    script: list[str],
    code: str,
) -> None:
    allow_reels(monkeypatch)
    fake_meta.status_script = script
    created = instagram_publication(ig_client, kind="reel")

    attempt = publish_and_wait(ig_client, created["publication"]["id"])[
        "latest_attempt"
    ]

    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True


def test_temporary_status_errors_never_require_reconnection(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    fake_meta.fault_queue["status"] = ["server_error", "rate_limited", "transport"]
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    assert publication["status"] == "published"
    connection = get_instagram_connection(ig_client, created["account"]["id"])
    assert connection["status"] == "connected"


def test_token_rejected_while_polling_requires_reconnection(
    ig_client: TestClient, fake_meta: FakeMeta, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_reels(monkeypatch)
    fake_meta.faults["status"] = "graph_190"
    created = instagram_publication(ig_client, kind="reel")

    attempt: dict[str, Any] = publish_and_wait(ig_client, created["publication"]["id"])[
        "latest_attempt"
    ]

    assert attempt["error"]["code"] == "instagram_reconnect_required"
    connection = get_instagram_connection(ig_client, created["account"]["id"])
    assert connection["status"] == "reconnect_required"
