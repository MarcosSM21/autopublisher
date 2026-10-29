"""Capability per account and metric group (Feature 027 T016, FR-001, FR-024).

Computed from the local connection only: no network, no keyring, no adapter fetch.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics import capability as capability_module
from app.analytics.adapters.registry import ADAPTERS
from app.analytics.capability import Capability, account_capability
from app.models import Account, Platform
from tests import readmodels
from tests.conftest import create_account, create_project
from tests.fakes import FakeClock

YT_READONLY = "https://www.googleapis.com/auth/youtube.readonly"


@pytest.fixture(autouse=True)
def no_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capabilities never read metrics."""

    def fail(*args: object) -> None:
        raise AssertionError("fetch must not be called")

    for adapter in ADAPTERS.values():
        monkeypatch.setattr(type(adapter), "fetch", fail)


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


def capability_of(client: TestClient, account: dict[str, Any]) -> Capability:
    app = client.app
    assert isinstance(app, FastAPI)
    with app.state.session_factory() as session:
        row = session.get(Account, account["id"])
        assert row is not None
        return account_capability(session, row)


def connected(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    platform: str,
    status: str = "connected",
) -> dict[str, Any]:
    account = create_account(client, project["id"], platform, f"{platform}-cyber")
    readmodels.connect(db_path, account, FakeClock().now(), status=status)
    return account


def groups(capability: Capability) -> list[tuple[str, str, str | None]]:
    return [(g.group, g.state, g.missing_permission) for g in capability.groups]


def test_connected_youtube_is_supported(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    result = capability_of(client, connected(client, db_path, project, "youtube"))

    assert result.state == "supported"
    assert groups(result) == [("basic", "supported", None)]
    assert result.reason is None
    assert result.is_refreshable


def test_instagram_has_basic_supported_and_insights_pending_permission(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    result = capability_of(client, connected(client, db_path, project, "instagram"))

    assert result.state == "supported"
    assert groups(result) == [
        ("basic", "supported", None),
        ("insights", "permission_required", "instagram_business_manage_insights"),
    ]
    assert result.is_refreshable


def test_threads_requires_the_insights_permission(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    result = capability_of(client, connected(client, db_path, project, "threads"))

    assert result.state == "permission_required"
    assert groups(result) == [
        ("insights", "permission_required", "threads_manage_insights")
    ]
    assert result.reason
    assert not result.is_refreshable


@pytest.mark.parametrize(
    ("platform", "state", "connect"),
    [
        ("tiktok", "not_supported", True),
        ("tiktok", "not_supported", False),
        ("telegram", "not_supported", True),
        ("telegram", "not_supported", False),
        ("x", "not_applicable", False),
    ],
)
def test_platforms_without_adapter_have_a_static_state(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    platform: str,
    state: str,
    connect: bool,
) -> None:
    account = create_account(client, project["id"], platform, "cyber")
    if connect:
        readmodels.connect(db_path, account, FakeClock().now())

    result = capability_of(client, account)

    assert result.state == state
    assert result.groups == ()
    assert result.reason
    assert not result.is_refreshable


@pytest.mark.parametrize("platform", ["youtube", "instagram", "threads"])
def test_an_account_without_connection_is_not_connected(
    client: TestClient, project: dict[str, Any], platform: str
) -> None:
    account = create_account(client, project["id"], platform, "cyber")

    result = capability_of(client, account)

    assert result.state == "not_connected"
    assert {g.state for g in result.groups} == {"not_connected"}
    assert {g.missing_permission for g in result.groups} == {None}
    assert not result.is_refreshable


@pytest.mark.parametrize("platform", ["youtube", "instagram", "threads"])
def test_a_connection_to_repair_is_reconnect_required(
    client: TestClient, db_path: Path, project: dict[str, Any], platform: str
) -> None:
    account = connected(client, db_path, project, platform, "reconnect_required")

    result = capability_of(client, account)

    assert result.state == "reconnect_required"
    assert {g.state for g in result.groups} == {"reconnect_required"}
    assert not result.is_refreshable


def test_a_granted_group_that_is_not_read_yet_is_never_supported(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even if the Threads insights permission were granted, v1 never reads it.
    model, granted = capability_module.CONNECTIONS[Platform.THREADS]
    monkeypatch.setitem(
        capability_module.CONNECTIONS,
        Platform.THREADS,
        (model, granted | {"threads_manage_insights"}),
    )

    result = capability_of(client, connected(client, db_path, project, "threads"))

    assert result.state == "not_supported"
    assert groups(result) == [("insights", "not_supported", None)]
    assert not result.is_refreshable


def test_youtube_readonly_is_a_scope_the_connection_requires() -> None:
    # The capability relies on the connection flow refusing tokens without it.
    _, granted = capability_module.CONNECTIONS[Platform.YOUTUBE]
    assert YT_READONLY in granted
    assert ADAPTERS[Platform.YOUTUBE].groups["basic"] == YT_READONLY


def test_telegram_is_not_supported_yet_without_claiming_it_has_no_metrics(
    client: TestClient, project: dict[str, Any]
) -> None:
    result = capability_of(
        client, create_account(client, project["id"], "telegram", "c")
    )

    assert result.state == "not_supported"
    assert result.reason == (
        "Telegram metrics are not supported by AutoPublisher in this version."
    )
