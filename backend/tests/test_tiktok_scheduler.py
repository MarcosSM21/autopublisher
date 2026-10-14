"""TikTok through the generic scheduler (spec US5, research §20): arming needs a
valid consent; an armed publication whose consent became stale is blocked by the
local check with no TikTok request and runs on the next eligible automatic retry
once reconfirmed; changed TikTok rules fail safely; races start one execution."""

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TT_OPTIONS,
    attempt_rows,
    get_publication,
    in_minutes,
    iso,
    run_tick,
    tiktok_publication,
    tiktok_ready,
    tiktok_run_rows,
    wait_idle,
)
from tests.fakes import FakeClock, FakeTikTok, tiktok_creator_info


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _scheduled(
    client: TestClient,
    fake: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
    **options: Any,
) -> tuple[int, datetime]:
    at = in_minutes(clock, 5)
    created = tiktok_publication(client, fake, monkeypatch, scheduled_at=iso(at))
    publication_id = int(created["publication"]["id"])
    tiktok_ready(client, publication_id, **options)
    return publication_id, at


def _arm(client: TestClient, publication_id: int) -> Any:
    return client.patch(
        f"/api/publications/{publication_id}", json={"auto_publish_enabled": True}
    )


def _armed(
    client: TestClient,
    fake: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
    **options: Any,
) -> tuple[int, datetime]:
    publication_id, at = _scheduled(client, fake, monkeypatch, clock, **options)
    response = _arm(client, publication_id)
    assert response.status_code == 200, response.text
    fake.requests.clear()
    return publication_id, at


# --- Arming ---------------------------------------------------------------------------


def test_arming_needs_a_consent(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    at = in_minutes(fake_clock, 5)
    created = tiktok_publication(client, fake_tiktok, monkeypatch, scheduled_at=iso(at))
    publication_id = created["publication"]["id"]
    client.put(f"/api/publications/{publication_id}/tiktok-options", json=TT_OPTIONS)

    response = _arm(client, publication_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "tiktok_consent_required"
    assert error["fields"][0]["field"] == "auto_publish_enabled"
    assert get_publication(client, publication_id)["auto_publish_enabled"] is False
    assert fake_tiktok.requests == []


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"privacy_level": None}, "tiktok_options_incomplete"),
        ({"is_aigc": None}, "tiktok_options_incomplete"),
        ({"commercial_disclosure_enabled": True}, "tiktok_options_incomplete"),
    ],
)
def test_incomplete_options_cannot_be_armed(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    change: dict[str, Any],
    code: str,
) -> None:
    at = in_minutes(fake_clock, 5)
    created = tiktok_publication(client, fake_tiktok, monkeypatch, scheduled_at=iso(at))
    publication_id = created["publication"]["id"]
    client.put(
        f"/api/publications/{publication_id}/tiktok-options",
        json={**TT_OPTIONS, **change},
    )

    response = _arm(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


def test_invalid_caption_cannot_be_armed(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    publication_id, _ = _scheduled(client, fake_tiktok, monkeypatch, fake_clock)
    client.patch(
        f"/api/publications/{publication_id}",
        json={"description_override": "😀" * 1100 + "a", "hashtags_override": []},
    )

    response = _arm(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_caption_invalid"


def test_creating_an_armed_tiktok_publication_is_rejected(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    project_id = created["account"]["project_id"]
    from tests.conftest import create_account, import_one, tiktok_video

    other = create_account(client, project_id, "youtube", "cyberchannel")
    name, data = tiktok_video(size=5000)
    content = import_one(client, project_id, name, data)["content"]
    before = len(client.get(f"/api/projects/{project_id}/publications").json())

    response = client.post(
        f"/api/contents/{content['id']}/publications",
        json={
            "account_ids": [other["id"], created["account"]["id"]],
            "scheduled_at": iso(in_minutes(fake_clock, 30)),
            "auto_publish_enabled": True,
        },
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "tiktok_consent_required"
    assert len(error["fields"]) == 1
    assert error["fields"][0]["field"] == "account_ids"
    assert "@cyberstudio" in error["fields"][0]["message"]
    after = len(client.get(f"/api/projects/{project_id}/publications").json())
    assert after == before
    assert fake_tiktok.requests == []


# --- Execution ------------------------------------------------------------------------


def test_armed_publication_runs_once_with_a_fresh_creator_info(
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
    for _ in range(3):
        fake_clock.advance(30)
        assert run_tick(client).started == []
    wait_idle(client)

    assert report.started == [publication_id]
    publication = get_publication(client, publication_id)
    assert publication["status"] == "published"
    assert publication["latest_attempt"]["trigger"] == "scheduled"
    assert fake_tiktok.calls()[:2] == ["creator_info", "init"]
    assert fake_tiktok.calls().count("init") == 1
    assert len(attempt_rows(db_path)) == 1


def test_stale_consent_blocks_without_any_request_then_reconfirming_runs_it(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock)
    response = client.patch(
        f"/api/publications/{publication_id}",
        json={"description_override": "Edited after arming"},
    )
    assert response.status_code == 200
    publication = get_publication(client, publication_id)
    assert publication["status"] == "scheduled"
    assert publication["auto_publish_enabled"] is True
    options = client.get(f"/api/publications/{publication_id}/tiktok-options").json()
    assert options["consent"]["state"] == "stale"
    fake_tiktok.requests.clear()
    fake_clock.set(at)

    report = run_tick(client)

    assert report.failed == [publication_id]
    assert fake_tiktok.requests == []
    assert attempt_rows(db_path) == []
    assert tiktok_run_rows(db_path) == []
    publication = get_publication(client, publication_id)
    assert publication["status"] == "scheduled"
    error = publication["auto_publish_error"]
    assert error["code"] == "tiktok_consent_required"
    assert "rejected" not in error["message"]
    after = client.get(f"/api/publications/{publication_id}/tiktok-options").json()
    for name in TT_OPTIONS:
        assert after[name] == options[name]

    # Reconfirming over the current fingerprint, without rescheduling.
    tiktok_ready(client, publication_id)
    fake_tiktok.requests.clear()
    assert run_tick(client).started == []  # Still within the retry interval.
    fake_clock.advance(120)
    retried = run_tick(client)
    wait_idle(client)

    assert retried.started == [publication_id]
    publication = get_publication(client, publication_id)
    assert publication["status"] == "published"
    assert publication["latest_attempt"]["trigger"] == "scheduled"
    assert fake_tiktok.calls().count("init") == 1


@pytest.mark.parametrize(
    ("info", "options", "code"),
    [
        (
            tiktok_creator_info(privacy_level_options=["FOLLOWER_OF_CREATOR"]),
            {},
            "tiktok_privacy_unavailable",
        ),
        (
            tiktok_creator_info(comment_disabled=True),
            {"allow_comment": True},
            "tiktok_interaction_unavailable",
        ),
        (
            tiktok_creator_info(max_video_post_duration_sec=10),
            {},
            "tiktok_video_too_long",
        ),
    ],
)
def test_changed_rules_at_run_time_fail_safely(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    db_path: Path,
    info: dict[str, Any],
    options: dict[str, Any],
    code: str,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock, **options)
    before = client.get(f"/api/publications/{publication_id}/tiktok-options").json()
    fake_tiktok.creator_info_data = info
    fake_clock.set(at)

    report = run_tick(client)

    assert report.failed == [publication_id]
    assert fake_tiktok.requests_to("init") == []
    assert attempt_rows(db_path) == []
    publication = get_publication(client, publication_id)
    assert publication["auto_publish_error"]["code"] == code
    after = client.get(f"/api/publications/{publication_id}/tiktok-options").json()
    for name in TT_OPTIONS:
        assert after[name] == before[name]


def test_pause_blocks_and_resume_runs_within_the_window(
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
    client.put("/api/automation", json={"paused": False})
    fake_clock.advance(60)
    report = run_tick(client)
    wait_idle(client)

    assert report.started == [publication_id]
    assert get_publication(client, publication_id)["status"] == "published"
    assert fake_tiktok.calls().count("init") == 1


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


def test_manual_and_scheduled_race_starts_one_execution(
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
    assert fake_tiktok.calls().count("init") == 1
    assert get_publication(client, publication_id)["status"] == "published"


def test_two_concurrent_cycles_start_one_execution(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock)
    fake_clock.set(at)

    _in_parallel(lambda: run_tick(client), lambda: run_tick(client))
    wait_idle(client)

    assert len(attempt_rows(db_path)) == 1
    assert fake_tiktok.calls().count("init") == 1
    assert get_publication(client, publication_id)["status"] == "published"


def test_an_uncertain_result_is_never_retried_automatically(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    db_path: Path,
) -> None:
    publication_id, at = _armed(client, fake_tiktok, monkeypatch, fake_clock)
    fake_tiktok.statuses = [{"status": "PROCESSING_UPLOAD"}]
    fake_clock.set(at)

    run_tick(client)
    wait_idle(client)
    for _ in range(5):
        fake_clock.advance(120)
        assert run_tick(client).started == []
    wait_idle(client)

    [attempt] = attempt_rows(db_path)
    assert attempt["outcome_determined"] == 0
    assert fake_tiktok.calls().count("init") == 1
    assert get_publication(client, publication_id)["status"] == "failed"
