"""Cleanup of Threads temporary media: always after the outcome is saved, never
changing it (FR-045, research.md §13-§14)."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import (
    get_publication,
    publish_and_wait,
    temporary_media_rows,
    threads_image_publication,
    threads_text_publication,
)
from tests.fakes import FakeMediaDeliveryProvider, FakeThreads


def test_release_runs_after_published_is_saved(
    threads_publishing_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    created = threads_image_publication(threads_publishing_client)
    publication_id = created["publication"]["id"]
    seen: list[dict[str, Any]] = []
    fake_delivery.delete_hook = lambda key: seen.append(
        get_publication(threads_publishing_client, publication_id)
    )

    publish_and_wait(threads_publishing_client, publication_id)

    [during] = seen
    assert during["status"] == "published"
    assert during["latest_attempt"]["status"] == "succeeded"


def test_failed_cleanup_only_adds_a_warning(
    threads_publishing_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    fake_delivery.delete_failures = 2  # The release and the sweep right after.
    created = threads_image_publication(threads_publishing_client)

    publication = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert [w["code"] for w in attempt["warnings"]] == [
        "temporary_media_cleanup_failed"
    ]
    [row] = temporary_media_rows(db_path)
    assert row["deleted_at"] is None
    assert len(fake_delivery.objects) == 1

    # A later sweep deletes it without touching the publication.
    app: Any = threads_publishing_client.app
    assert app.state.temporary_media.sweep() == 0
    assert fake_delivery.objects == {}
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None
    assert get_publication(threads_publishing_client, created["publication"]["id"])[
        "status"
    ] == ("published")


def test_cleanup_after_a_determined_failure(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    fake_threads.faults["create"] = "graph_100"
    created = threads_image_publication(threads_publishing_client)

    publication = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["error"]["code"] == "threads_container_failed"
    assert fake_delivery.objects == {}
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None


def test_cleanup_after_an_uncertain_result(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    fake_threads.faults["publish"] = "server_error"
    created = threads_image_publication(threads_publishing_client)

    publication = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    assert publication["latest_attempt"]["error"]["code"] == (
        "threads_publish_uncertain"
    )
    assert fake_delivery.objects == {}


def test_text_posts_never_touch_the_provider(
    threads_publishing_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    created = threads_text_publication(threads_publishing_client)

    publication = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    assert publication["status"] == "published"
    assert publication["latest_attempt"]["warnings"] == []
    assert temporary_media_rows(db_path) == []
    assert fake_delivery.put_calls == []
    assert fake_delivery.delete_calls == []
    assert fake_delivery.signed == []
