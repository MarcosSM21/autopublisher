"""Publishing a Threads text post end to end with the fake Threads API (US1), with
the minimal anti-duplicate guarantees of the MVP (research.md §10-§13)."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import ThreadsPublishPhase
from app.threads_publishing import (
    MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS,
    ThreadsPublisher,
)
from tests.conftest import (
    TH_TEXT,
    get_publication,
    publish_and_wait,
    temporary_media_rows,
    threads_run_rows,
    threads_text_publication,
    wait_idle,
)
from tests.fakes import (
    FAKE_TH_LONG_TOKEN,
    TH_USER_ID,
    FakeMediaDeliveryProvider,
    FakeThreads,
)

PERMALINK_PREFIX = "https://www.threads.com/@cyber.studio/post/"
# FINISHED right after creation: only the time the container lacks to reach the
# minimum age is waited, in 1 s slices, then the container is read again.
AGE_WAIT = [1.0] * int(MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS)
INCONCLUSIVE = ["timeout", "transport", "server_error", "rate_limited", "bad_json"]


def _attempts(client: TestClient, publication_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/publications/{publication_id}/attempts")
    assert response.status_code == 200, response.text
    attempts: list[dict[str, Any]] = response.json()
    return attempts


def _row(db_path: Path, sql: str, *params: Any) -> sqlite3.Row:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row: sqlite3.Row = connection.execute(sql, params).fetchone()
    return row


def _publish(
    client: TestClient, **values: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a connected text publication, publish it and wait."""
    publication = threads_text_publication(client, **values)["publication"]
    published = publish_and_wait(client, publication["id"])
    [attempt] = _attempts(client, publication["id"])
    return published, attempt


def _assert_single_container(fake_threads: FakeThreads) -> str:
    [container_id] = fake_threads.containers
    assert len(fake_threads.requests_for("create")) == 1
    assert fake_threads.post_list_requests == 0
    return container_id


def _warning_codes(attempt: dict[str, Any]) -> list[str]:
    return [warning["code"] for warning in attempt["warnings"]]


# --- Success -------------------------------------------------------------------------


def test_publish_text_post(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    recorded_sleeps: list[float],
    db_path: Path,
) -> None:
    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert published["published_at"] is not None
    assert attempt["status"] == "succeeded"
    assert attempt["trigger"] == "manual"
    assert attempt["stage"] == "done"
    assert attempt["platform"] == "threads"
    assert attempt["outcome_determined"] is True
    assert attempt["progress"] == 1.0
    assert attempt["total_bytes"] == 0
    container_id = _assert_single_container(fake_threads)
    # Exactly the text shown to the user: accents, emoji, URL and hashtags block.
    assert fake_threads.containers[container_id] == {
        "media_type": "TEXT",
        "text": TH_TEXT,
    }
    assert fake_threads.publish_count(container_id) == 1
    [post_id] = fake_threads.posts
    assert attempt["external_id"] == post_id
    assert attempt["external_url"] == f"{PERMALINK_PREFIX}{post_id}"
    assert attempt["details"] == {
        "permalink": f"{PERMALINK_PREFIX}{post_id}",
        "threads_timestamp": "2026-10-13T10:00:00+0000",
    }
    assert attempt["warnings"] == []
    assert attempt["submitted"] == {
        "media_kind": "text",
        "text": TH_TEXT,
        "alt_text": None,
        "threads_user_id": TH_USER_ID,
        "username": "cyber.studio",
        "quota_checked": True,
        "quota_usage": 0,
        "quota_total": 250,
        "quota_duration": 86400,
    }
    # Immediate FINISHED: only the wait up to the minimum age, then a second read.
    assert recorded_sleeps == AGE_WAIT
    assert len(fake_threads.requests_for("status")) == 2
    # Text never uses media delivery.
    assert temporary_media_rows(db_path) == []
    assert fake_delivery.put_calls == [] and fake_delivery.signed == []
    [run] = threads_run_rows(db_path)
    assert run["media_kind"] == "text"
    assert run["phase"] == ThreadsPublishPhase.SUCCEEDED
    assert run["container_id"] == container_id
    assert run["container_status"] == "PUBLISHED"
    assert run["publish_started_at"] is not None
    assert FAKE_TH_LONG_TOKEN not in str(attempt)


def test_stages_and_phases(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str, str]] = []

    def record(label: str) -> None:
        attempt = _row(
            db_path,
            "SELECT stage, bytes_sent, total_bytes FROM "
            "publication_attempts ORDER BY id DESC",
        )
        run = _row(db_path, "SELECT phase FROM threads_publish_runs")
        # Progress stays 0.0 while running: nothing is uploaded for a text post.
        assert (attempt["bytes_sent"], attempt["total_bytes"]) == (0, 0)
        seen.append((label, attempt["stage"], run["phase"]))

    original_post = fake_threads._post

    def post(post_id: str) -> dict[str, Any]:
        record("post")
        return original_post(post_id)

    fake_threads.create_hook = lambda: record("create")
    fake_threads.publish_hook = lambda: record("publish")
    monkeypatch.setattr(fake_threads, "_post", post)

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert seen == [
        ("create", "processing", "creating_container"),
        ("publish", "finalizing", "publishing"),
        ("post", "finalizing", "verifying_result"),
    ]
    assert attempt["stage"] == "done"
    assert threads_run_rows(db_path)[0]["phase"] == "succeeded"


def test_container_in_progress_is_polled_then_published(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    recorded_sleeps: list[float],
) -> None:
    fake_threads.status_script = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert len(fake_threads.requests_for("status")) == 4
    # Waits of 2 s and 5 s, then only the 23 s the container lacks to be 30 s old,
    # all split in 1 s slices to notice a shutdown.
    assert recorded_sleeps == AGE_WAIT
    container_id = _assert_single_container(fake_threads)
    assert fake_threads.publish_count(container_id) == 1


def test_container_that_never_finishes_times_out(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    recorded_sleeps: list[float],
) -> None:
    fake_threads.status_script = ["IN_PROGRESS"]

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_processing_timeout"
    assert attempt["outcome_determined"] is True
    assert sum(recorded_sleeps) <= 60
    assert fake_threads.requests_for("publish") == []


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("ERROR:UNKNOWN", "threads_processing_failed"),
        ("ERROR", "threads_processing_failed"),
        ("EXPIRED", "threads_container_expired"),
    ],
)
def test_container_errors_never_publish(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
    status: str,
    code: str,
) -> None:
    fake_threads.status_script = [status]

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert fake_threads.requests_for("publish") == []
    assert threads_run_rows(db_path)[0]["phase"] == "failed"


def test_container_creation_failure(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["create"] = "graph_100"

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_container_failed"
    assert attempt["outcome_determined"] is True
    assert fake_threads.requests_for("publish") == []
    assert "raw-meta-error" not in attempt["error"]["message"]


def test_link_limit_rejection_is_a_text_problem(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["create"] = "link_limit"

    _, attempt = _publish(threads_publishing_client)

    assert attempt["error"]["code"] == "threads_text_invalid"
    assert attempt["outcome_determined"] is True


# --- Permalink -----------------------------------------------------------------------


@pytest.mark.parametrize("fault", ["server_error", "missing_fields", "omitted"])
def test_missing_permalink_never_fails_the_publication(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fault: str,
) -> None:
    if fault == "omitted":
        fake_threads.permalinks = False
    else:
        fake_threads.faults["post"] = fault

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    [post_id] = fake_threads.posts
    assert attempt["external_id"] == post_id
    assert attempt["external_url"] is None
    assert _warning_codes(attempt) == ["permalink_unavailable"]
    container_id = _assert_single_container(fake_threads)
    assert fake_threads.publish_count(container_id) == 1


def test_permalink_read_is_retried_with_bounded_waits(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    recorded_sleeps: list[float],
) -> None:
    fake_threads.fault_queue["post"] = ["server_error", "timeout"]

    _, attempt = _publish(threads_publishing_client)

    assert attempt["external_url"] is not None
    assert attempt["warnings"] == []
    assert recorded_sleeps == [*AGE_WAIT, 2.0, 5.0]
    assert len(fake_threads.requests_for("post")) == 3


def test_refresh_details_fills_the_permalink_later(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    # The three reads inside the upload fail; the light check afterwards succeeds.
    fake_threads.fault_queue["post"] = ["server_error"] * 3

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    [post_id] = fake_threads.posts
    assert attempt["details"]["permalink"] == f"{PERMALINK_PREFIX}{post_id}"
    assert attempt["warnings"] == []
    # An already closed attempt keeps its external URL as it was saved.
    assert attempt["external_url"] is None
    assert len(fake_threads.requests_for("publish")) == 1


# --- Anti-duplicates -----------------------------------------------------------------


def test_container_is_read_before_publishing(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.status_script = ["IN_PROGRESS", "FINISHED"]

    _publish(threads_publishing_client)

    endpoints = [
        fake_threads._endpoint_of(r.method, r.url)
        for r in fake_threads.requests
        if r.url.startswith("https://graph.threads.net/v1.0/")
        and fake_threads._endpoint_of(r.method, r.url)
        in ("create", "status", "publish")
    ]
    assert endpoints == ["create", "status", "status", "status", "publish"]


def test_write_ahead_is_committed_before_publishing(
    threads_publishing_client: TestClient, fake_threads: FakeThreads, db_path: Path
) -> None:
    seen: list[tuple[str, str, Any]] = []

    def check() -> None:
        attempt = _row(db_path, "SELECT stage FROM publication_attempts")
        run = _row(
            db_path, "SELECT phase, publish_started_at FROM threads_publish_runs"
        )
        seen.append((attempt["stage"], run["phase"], run["publish_started_at"]))

    fake_threads.publish_hook = check

    _publish(threads_publishing_client)

    [(stage, phase, started)] = seen
    assert (stage, phase) == ("finalizing", "publishing")
    assert started is not None


@pytest.mark.parametrize("failing", ["run", "stage"])
def test_write_ahead_failure_never_publishes(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    monkeypatch: pytest.MonkeyPatch,
    failing: str,
) -> None:
    if failing == "run":
        original = ThreadsPublisher._update_run

        def update_run(
            self: ThreadsPublisher, ctx: Any, attempt_id: int, **values: Any
        ) -> bool:
            if values.get("phase") == ThreadsPublishPhase.PUBLISHING:
                return False
            return original(self, ctx, attempt_id, **values)

        monkeypatch.setattr(ThreadsPublisher, "_update_run", update_run)
    else:
        from app import publishing

        original_set_stage = publishing.set_stage

        def set_stage(ctx: Any, attempt_id: int, stage: Any) -> bool:
            if stage == "finalizing":
                return False
            return original_set_stage(ctx, attempt_id, stage)

        monkeypatch.setattr(publishing, "set_stage", set_stage)

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "internal_error"
    assert attempt["outcome_determined"] is True
    assert fake_threads.requests_for("publish") == []


def test_explicit_rejection_without_publication_is_determined(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["publish"] = "graph_100"

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_publish_failed"
    assert attempt["outcome_determined"] is True
    container_id = _assert_single_container(fake_threads)
    assert fake_threads.publish_count(container_id) == 1
    # Two reads before publishing (minimum age), exactly one after the rejection.
    assert len(fake_threads.requests_for("status")) == 3


def test_explicit_rejection_of_a_published_container(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["publish"] = "graph_100_after_publish"

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert _warning_codes(attempt) == ["remote_identity_unavailable"]
    container_id = _assert_single_container(fake_threads)
    assert fake_threads.publish_count(container_id) == 1


@pytest.mark.parametrize("fault", [*INCONCLUSIVE, "missing_fields"])
def test_inconclusive_result_settled_by_the_container(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fault: str,
) -> None:
    fake_threads.faults["publish"] = f"{fault}_after_publish"

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    # Never inferred: no post id, no permalink.
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert _warning_codes(attempt) == ["remote_identity_unavailable"]
    assert "@cyber.studio" in attempt["warnings"][0]["message"]
    container_id = _assert_single_container(fake_threads)
    assert fake_threads.publish_count(container_id) == 1
    assert fake_threads.requests_for("post") == []


@pytest.mark.parametrize("fault", [*INCONCLUSIVE, "missing_fields"])
def test_inconclusive_result_stays_uncertain(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    recorded_sleeps: list[float],
    fault: str,
) -> None:
    fake_threads.faults["publish"] = fault

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_publish_uncertain"
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    message = attempt["error"]["message"]
    assert "@cyber.studio" in message
    assert "UTC" in message
    assert "Validation post" in message
    container_id = _assert_single_container(fake_threads)
    assert fake_threads.publish_count(container_id) == 1
    # Only reads of the original container, at 0, 5, 15, 30 and 60 s.
    assert len(fake_threads.requests_for("status")) == 2 + 5
    assert recorded_sleeps == [*AGE_WAIT, 5.0, 10.0, 15.0, 30.0]


def test_inconclusive_result_with_failing_reads_stays_uncertain(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["publish"] = "server_error"

    def break_reads() -> None:
        fake_threads.faults["status"] = "server_error"

    fake_threads.publish_hook = break_reads

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_publish_uncertain"
    assert attempt["outcome_determined"] is False
    container_id = _assert_single_container(fake_threads)
    assert fake_threads.publish_count(container_id) == 1


@pytest.mark.parametrize("status", ["FINISHED", "ERROR", "EXPIRED", "IN_PROGRESS"])
def test_any_other_container_status_stays_uncertain(
    threads_publishing_client: TestClient, fake_threads: FakeThreads, status: str
) -> None:
    fake_threads.faults["publish"] = "timeout"

    def change_status() -> None:
        [container_id] = fake_threads.containers
        fake_threads.container_statuses[container_id] = [status]

    fake_threads.publish_hook = change_status

    _, attempt = _publish(threads_publishing_client)

    assert attempt["error"]["code"] == "threads_publish_uncertain"
    assert attempt["outcome_determined"] is False
    assert len(fake_threads.requests_for("publish")) == 1


def test_uncertain_publication_needs_confirmation_and_never_republishes(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["publish"] = "server_error"
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])
    url = f"/api/publications/{publication['id']}/publish"

    again = threads_publishing_client.post(url, json={})

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "remote_check_required"
    assert len(fake_threads.requests_for("create")) == 1
    assert len(fake_threads.requests_for("publish")) == 1


def test_published_container_of_an_uncertain_attempt_is_never_published_again(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["publish"] = "server_error"
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])
    # The user confirms by mistake, but Threads reports the container published:
    # the read-only reconciliation settles it before anything is created.
    [container_id] = fake_threads.containers
    fake_threads.container_statuses[container_id] = ["PUBLISHED"]

    response = threads_publishing_client.post(
        f"/api/publications/{publication['id']}/publish",
        json={"confirm_remote_checked": True},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_eligible"
    assert len(fake_threads.requests_for("create")) == 1
    assert len(fake_threads.requests_for("publish")) == 1
    assert (
        get_publication(threads_publishing_client, publication["id"])["status"]
        == "published"
    )


def test_confirmed_retry_creates_a_new_container(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.fault_queue["publish"] = ["server_error"]
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])

    published = publish_and_wait(
        threads_publishing_client, publication["id"], confirm_remote_checked=True
    )

    assert published["status"] == "published"
    first, second = fake_threads.containers
    assert fake_threads.publish_count(first) == 1
    assert fake_threads.publish_count(second) == 1
    assert fake_threads.post_list_requests == 0


# --- Preflight -----------------------------------------------------------------------


def _start(client: TestClient, publication_id: int) -> Any:
    response = client.post(f"/api/publications/{publication_id}/publish", json={})
    wait_idle(client)
    return response


def test_quota_exhausted_blocks_before_any_container(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.quota = (250, 250)
    publication = threads_text_publication(threads_publishing_client)["publication"]

    response = _start(threads_publishing_client, publication["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_publishing_limit_reached"
    assert fake_threads.containers == {}
    assert (
        get_publication(threads_publishing_client, publication["id"])["status"]
        == "unscheduled"
    )


@pytest.mark.parametrize("fault", ["missing_fields", "graph_100"])
def test_quota_unexpected_answer_blocks(
    threads_publishing_client: TestClient, fake_threads: FakeThreads, fault: str
) -> None:
    fake_threads.faults["limit"] = fault
    publication = threads_text_publication(threads_publishing_client)["publication"]

    response = _start(threads_publishing_client, publication["id"])

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "threads_unexpected_response"
    assert fake_threads.containers == {}


def test_quota_temporarily_unavailable_still_publishes(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    fake_threads.faults["limit"] = "server_error"

    published, attempt = _publish(threads_publishing_client)

    assert published["status"] == "published"
    assert attempt["submitted"]["quota_checked"] is False
    assert "quota_usage" not in attempt["submitted"]
    assert _warning_codes(attempt) == ["quota_unavailable"]


def test_not_connected_account_cannot_publish(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    publication = threads_text_publication(threads_publishing_client, connect=False)[
        "publication"
    ]

    response = _start(threads_publishing_client, publication["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_not_connected"
    assert fake_threads.containers == {}


def test_invalid_text_fails_in_preflight(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    publication = threads_text_publication(
        threads_publishing_client, description="x" * 501, hashtags=[]
    )["publication"]

    check = threads_publishing_client.get(
        f"/api/publications/{publication['id']}/publish-check"
    ).json()
    response = _start(threads_publishing_client, publication["id"])

    assert check["eligible"] is False
    assert [p["code"] for p in check["problems"]] == ["threads_text_invalid"]
    assert response.status_code == 409
    assert fake_threads.containers == {}


def test_publish_check_summary(threads_publishing_client: TestClient) -> None:
    publication = threads_text_publication(threads_publishing_client)["publication"]

    check = threads_publishing_client.get(
        f"/api/publications/{publication['id']}/publish-check"
    ).json()

    assert check["eligible"] is True
    assert check["requires_remote_check"] is False
    assert check["summary"] == [
        {"label": "Post type", "value": "Text"},
        {"label": "Threads account", "value": f"cyber.studio ({TH_USER_ID})"},
        {"label": "Text", "value": TH_TEXT},
    ]
