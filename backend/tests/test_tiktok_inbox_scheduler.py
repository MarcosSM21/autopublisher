"""Scheduling Send to TikTok (Feature 014, US4): the generic scheduler runs an
armed Upload to Inbox publication once, with the mode chosen and the `video.upload`
capability but no Direct Post consent; pauses, races and later cycles never send it
twice."""

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    iso,
    run_tick,
    set_tiktok_granted_scopes,
    tiktok_inbox_publication,
    tiktok_publication,
    tiktok_run_rows,
    wait_idle,
)
from tests.fakes import (
    TT_BASIC,
    TT_PUBLISH,
    FakeClock,
    FakeTikTok,
    InMemoryCredentialStore,
)


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _arm(client: TestClient, publication_id: int) -> Any:
    return client.patch(
        f"/api/publications/{publication_id}", json={"auto_publish_enabled": True}
    )


def _scheduled(
    client: TestClient,
    fake: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
    **kwargs: Any,
) -> tuple[dict[str, Any], datetime]:
    at = in_minutes(clock, 5)
    created = tiktok_inbox_publication(
        client, fake, monkeypatch, scheduled_at=iso(at), **kwargs
    )
    return created, at


def _armed(
    client: TestClient,
    fake: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
    **kwargs: Any,
) -> tuple[int, datetime]:
    created, at = _scheduled(client, fake, monkeypatch, clock, **kwargs)
    publication_id = int(created["publication"]["id"])
    response = _arm(client, publication_id)
    assert response.status_code == 200, response.text
    fake.requests.clear()
    return publication_id, at


def _in_parallel(*calls: Callable[[], Any]) -> None:
    errors: list[BaseException] = []

    def run(call: Callable[[], Any]) -> None:
        try:
            call()
        except BaseException as error:  # noqa: BLE001 - reported below
            errors.append(error)

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []


# --- Arming -------------------------------------------------------------------------


def test_arming_needs_no_direct_post_consent(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    publication_id, _ = _armed(client, fake_tiktok, monkeypatch, fake_clock)

    publication = get_publication(client, publication_id)

    assert publication["auto_publish_enabled"] is True
    assert fake_tiktok.requests == []


def test_arming_requires_a_mode(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    at = in_minutes(fake_clock, 5)
    created = tiktok_publication(
        client, fake_tiktok, monkeypatch, scheduled_at=iso(at), mode=None
    )

    response = _arm(client, created["publication"]["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_mode_required"


def test_arming_requires_video_upload(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    created, _ = _scheduled(client, fake_tiktok, monkeypatch, fake_clock)
    set_tiktok_granted_scopes(
        tiktok_credential_store,
        db_path,
        created["account"]["id"],
        [TT_BASIC, TT_PUBLISH],
    )

    response = _arm(client, created["publication"]["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "tiktok_upload_permission_missing"
    assert error["fields"][0]["field"] == "auto_publish_enabled"


# --- Execution ------------------------------------------------------------------------


def test_due_publication_is_sent_once_and_then_left_alone(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock)
    fake_clock.set(at)

    report = run_tick(client)
    wait_idle(client)
    calls = list(fake_tiktok.calls())
    for _ in range(3):
        fake_clock.advance(120)
        assert run_tick(client).started == []
    wait_idle(client)

    assert report.started == [publication_id]
    publication = get_publication(client, publication_id)
    assert publication["status"] == "awaiting_user_action"
    assert publication["latest_attempt"]["trigger"] == "scheduled"
    assert calls[0] == "inbox_init"
    assert "creator_info" not in calls
    # Later cycles never touch a publication awaiting the user.
    assert fake_tiktok.calls() == calls
    assert len(attempt_rows(db_path)) == 1


def test_paused_automation_does_not_send_but_manual_send_works(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock)
    client.put("/api/automation", json={"paused": True})
    fake_clock.set(at)

    assert run_tick(client).started == []
    assert fake_tiktok.requests == []
    response = client.post(f"/api/publications/{publication_id}/publish", json={})
    wait_idle(client)

    assert response.status_code == 202, response.text
    publication = get_publication(client, publication_id)
    assert publication["status"] == "awaiting_user_action"
    assert publication["latest_attempt"]["trigger"] == "manual"


def test_manual_and_scheduled_race_sends_once(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock)
    fake_clock.set(at)

    _in_parallel(
        lambda: client.post(f"/api/publications/{publication_id}/publish", json={}),
        lambda: run_tick(client),
    )
    wait_idle(client)

    assert len(attempt_rows(db_path)) == 1
    assert fake_tiktok.calls().count("inbox_init") == 1


def test_two_concurrent_cycles_send_once(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    _armed(client, fake_tiktok, monkeypatch, fake_clock)
    _, at = _armed(client, fake_tiktok, monkeypatch, fake_clock, project_name="Other")
    fake_clock.set(at)

    _in_parallel(lambda: run_tick(client), lambda: run_tick(client))
    wait_idle(client)

    # Two different publications, each sent exactly once.
    assert len(attempt_rows(db_path)) == 2
    assert fake_tiktok.calls().count("inbox_init") == 2


def test_losing_video_upload_before_the_due_time_fails_without_network(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock)
    account_id = get_publication(client, publication_id)["account"]["id"]
    set_tiktok_granted_scopes(
        tiktok_credential_store, db_path, account_id, [TT_BASIC, TT_PUBLISH]
    )
    fake_clock.set(at)

    report = run_tick(client)

    assert report.failed == [publication_id]
    assert fake_tiktok.requests == []
    assert attempt_rows(db_path) == []
    assert tiktok_run_rows(db_path) == []
    publication = get_publication(client, publication_id)
    assert publication["auto_publish_error"]["code"] == (
        "tiktok_upload_permission_missing"
    )
