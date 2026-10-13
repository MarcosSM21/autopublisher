"""Never publishing a duplicate on Threads (US7, research.md §11-§12): write-ahead,
at most one threads_publish per container, ambiguity and container states between
attempts, for text, image and video."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    attempt_rows,
    get_publication,
    publish_and_wait,
    threads_image_publication,
    threads_text_publication,
    threads_video_publication,
    wait_idle,
)
from tests.fakes import FakeMediaDeliveryProvider, FakeThreads

INCONCLUSIVE = ["timeout", "transport", "server_error", "rate_limited", "bad_json"]
OTHER_STATUSES = ["FINISHED", "ERROR", "EXPIRED", "IN_PROGRESS", "UNREADABLE"]


def _assert_at_most_one_publish(fake_threads: FakeThreads) -> None:
    for container_id in fake_threads.containers:
        assert fake_threads.publish_count(container_id) <= 1
    assert fake_threads.post_list_requests == 0


def _set_after_publish(fake_threads: FakeThreads, status: str) -> None:
    def change() -> None:
        [container_id] = fake_threads.containers
        if status == "UNREADABLE":
            fake_threads.faults["status"] = "server_error"
        else:
            fake_threads.container_statuses[container_id] = [status]

    fake_threads.publish_hook = change


@pytest.mark.parametrize("fault", INCONCLUSIVE)
@pytest.mark.parametrize("status", OTHER_STATUSES)
def test_inconclusive_with_any_other_status_is_uncertain(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fault: str,
    status: str,
) -> None:
    fake_threads.faults["publish"] = fault
    _set_after_publish(fake_threads, status)
    publication = threads_text_publication(threads_publishing_client)["publication"]

    published = publish_and_wait(threads_publishing_client, publication["id"])

    attempt = published["latest_attempt"]
    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_publish_uncertain"
    assert attempt["outcome_determined"] is False
    message = attempt["error"]["message"]
    assert "@cyber.studio" in message and "UTC" in message
    assert len(fake_threads.requests_for("publish")) == 1
    _assert_at_most_one_publish(fake_threads)


@pytest.mark.parametrize("fault", INCONCLUSIVE)
def test_inconclusive_with_a_container_published_later(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fault: str,
) -> None:
    fake_threads.faults["publish"] = fault

    # Threads takes a moment to report PUBLISHED: the third read sees it.
    def later() -> None:
        [container_id] = fake_threads.containers
        fake_threads.container_statuses[container_id] = [
            "FINISHED",
            "FINISHED",
            "PUBLISHED",
        ]

    fake_threads.publish_hook = later
    publication = threads_text_publication(threads_publishing_client)["publication"]

    published = publish_and_wait(threads_publishing_client, publication["id"])

    attempt = published["latest_attempt"]
    assert published["status"] == "published"
    assert attempt["external_id"] is None
    assert [w["code"] for w in attempt["warnings"]] == ["remote_identity_unavailable"]
    _assert_at_most_one_publish(fake_threads)


def test_write_ahead_is_visible_inside_the_publish_request(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    seen: list[tuple[Any, ...]] = []

    def check() -> None:
        with sqlite3.connect(db_path) as connection:
            seen.append(
                connection.execute(
                    "SELECT a.stage, r.phase, r.publish_started_at IS NOT NULL "
                    "FROM publication_attempts a JOIN threads_publish_runs r "
                    "ON r.attempt_id = a.id"
                ).fetchone()
            )

    fake_threads.publish_hook = check
    publication = threads_text_publication(threads_publishing_client)["publication"]

    publish_and_wait(threads_publishing_client, publication["id"])

    assert seen == [("finalizing", "publishing", 1)]


@pytest.mark.parametrize(
    ("previous", "expected"),
    [
        ("PUBLISHED", "blocked"),
        ("FINISHED", "new container"),
        ("EXPIRED", "new container"),
        ("UNKNOWN_TO_META", "new container"),
    ],
)
def test_container_states_between_attempts(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    previous: str,
    expected: str,
) -> None:
    fake_threads.fault_queue["publish"] = ["graph_100"]
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])
    [container_id] = fake_threads.containers
    if previous == "UNKNOWN_TO_META":
        fake_threads.container_statuses[container_id] = []
    else:
        fake_threads.container_statuses[container_id] = [previous]

    response = threads_publishing_client.post(
        f"/api/publications/{publication['id']}/publish", json={}
    )
    wait_idle(threads_publishing_client)

    if expected == "blocked":
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "threads_already_published"
        assert len(fake_threads.containers) == 1
    else:
        assert response.status_code == 202
        assert len(fake_threads.containers) == 2
        status = get_publication(threads_publishing_client, publication["id"])
        assert status["status"] == "published"
    _assert_at_most_one_publish(fake_threads)


def test_previous_container_unreadable_blocks_with_unavailable(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
) -> None:
    fake_threads.fault_queue["publish"] = ["graph_100"]
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])
    fake_threads.faults["status"] = "server_error"

    response = threads_publishing_client.post(
        f"/api/publications/{publication['id']}/publish", json={}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "threads_unavailable"
    assert len(fake_threads.containers) == 1


def test_manual_retry_after_confirmation_never_duplicates(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
) -> None:
    fake_threads.fault_queue["publish"] = ["timeout"]
    publication = threads_text_publication(threads_publishing_client)["publication"]
    publish_and_wait(threads_publishing_client, publication["id"])

    published = publish_and_wait(
        threads_publishing_client, publication["id"], confirm_remote_checked=True
    )

    assert published["status"] == "published"
    assert len(attempt_rows(db_path)) == 2
    assert len(fake_threads.containers) == 2
    _assert_at_most_one_publish(fake_threads)


Creator = Callable[..., dict[str, Any]]


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("fault", ["timeout", "server_error_after_publish"])
def test_media_attempts_follow_the_same_rules(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    fault: str,
) -> None:
    fake_threads.faults["publish"] = fault
    if kind == "image":
        created = threads_image_publication(threads_publishing_client)
    else:
        created = threads_video_publication(threads_publishing_client, monkeypatch)

    published = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    attempt = published["latest_attempt"]
    if fault == "timeout":
        assert attempt["error"]["code"] == "threads_publish_uncertain"
        assert attempt["outcome_determined"] is False
    else:
        assert published["status"] == "published"
        assert attempt["external_id"] is None
    assert len(fake_delivery.put_calls) == 1
    assert fake_delivery.objects == {}
    _assert_at_most_one_publish(fake_threads)
