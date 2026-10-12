"""Cleanup of the temporary media always happens after the outcome is saved and
never changes it (FR-054-FR-056, research.md §13, §16)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    allow_reels,
    get_publication,
    instagram_publication,
    publish_and_wait,
    temporary_media_rows,
)
from tests.fakes import FakeMediaDeliveryProvider, FakeMeta


def test_cleanup_runs_after_published_is_saved(
    ig_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    created = instagram_publication(ig_client)
    publication_id = created["publication"]["id"]
    seen: list[dict[str, Any]] = []
    fake_delivery.delete_hook = lambda key: seen.append(
        get_publication(ig_client, publication_id)
    )

    publish_and_wait(ig_client, publication_id)

    assert len(seen) == 1
    assert seen[0]["status"] == "published"
    assert seen[0]["latest_attempt"]["status"] == "succeeded"


def test_failed_cleanup_only_adds_a_warning(
    ig_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    fake_delivery.delete_failures = 2  # The release and the sweep right after.
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["progress"] == 1
    assert [w["code"] for w in attempt["warnings"]] == [
        "temporary_media_cleanup_failed"
    ]
    [row] = temporary_media_rows(db_path)
    assert row["deleted_at"] is None
    assert row["cleanup_failures"] == 2
    assert len(fake_delivery.objects) == 1

    # A later sweep (e.g. at the next start-up or attempt) deletes it.
    app: Any = ig_client.app
    assert app.state.temporary_media.sweep() == 0
    assert fake_delivery.objects == {}
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None
    assert get_publication(ig_client, created["publication"]["id"])["status"] == (
        "published"
    )


def test_cleanup_after_a_determined_failure(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    fake_meta.faults["create"] = "graph_-1_2207032"
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["error"]["code"] == (
        "instagram_container_failed"
    )
    assert fake_delivery.objects == {}
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None


def test_cleanup_after_an_uncertain_result(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allow_reels(monkeypatch)
    fake_meta.faults["publish"] = "transport"
    created = instagram_publication(ig_client, kind="reel")

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    assert publication["latest_attempt"]["error"]["code"] == (
        "instagram_publish_uncertain"
    )
    assert fake_delivery.objects == {}
