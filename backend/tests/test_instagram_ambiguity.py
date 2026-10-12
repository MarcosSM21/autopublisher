"""media_publish is called at most once and never repeated; after an inconclusive
result only the original container read as PUBLISHED settles it (US6, FR-043-FR-046,
FR-044a, research.md §11)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    attempt_rows,
    get_publication,
    instagram_publication,
    instagram_run_rows,
    publish_and_wait,
    wait_idle,
)
from tests.fakes import FakeMediaDeliveryProvider, FakeMeta

INCONCLUSIVE = ["transport", "server_error", "rate_limited", "graph_2", "bad_json"]


def _publish(client: TestClient, publication_id: int, **body: Any) -> Any:
    return client.post(f"/api/publications/{publication_id}/publish", json=body)


def _single_publish(fake_meta: FakeMeta) -> None:
    assert len(fake_meta.requests_for("publish")) == 1
    assert len(fake_meta.containers) == 1
    assert fake_meta.media_list_requests == 0


def test_write_ahead_is_committed_before_media_publish(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    created = instagram_publication(ig_client)
    seen: list[tuple[str, str]] = []
    fake_meta.publish_hook = lambda: seen.append(
        (attempt_rows(db_path)[0]["stage"], instagram_run_rows(db_path)[0]["phase"])
    )

    publish_and_wait(ig_client, created["publication"]["id"])

    assert seen == [("finalizing", "publishing")]


def test_no_publish_when_the_write_ahead_cannot_be_saved(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import publishing

    original = publishing.set_stage

    def failing(ctx: Any, attempt_id: int, stage: Any) -> bool:
        if stage == "finalizing":
            return False
        return original(ctx, attempt_id, stage)

    monkeypatch.setattr(publishing, "set_stage", failing)
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["outcome_determined"] is True
    assert fake_meta.requests_for("publish") == []


@pytest.mark.parametrize("fault", INCONCLUSIVE)
def test_inconclusive_publish_with_published_container_is_published(
    ig_client: TestClient, fake_meta: FakeMeta, fault: str
) -> None:
    fake_meta.faults["publish"] = f"{fault}_after_publish"
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert [w["code"] for w in attempt["warnings"]] == ["remote_identity_unavailable"]
    assert "@cyber.studio" in attempt["warnings"][0]["message"]
    _single_publish(fake_meta)


@pytest.mark.parametrize(
    "status", ["ERROR", "EXPIRED", "FINISHED", "IN_PROGRESS", "SOMETHING_NEW"]
)
def test_inconclusive_publish_without_published_container_stays_uncertain(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    recorded_sleeps: list[float],
    status: str,
) -> None:
    fake_meta.faults["publish"] = "transport"
    created = instagram_publication(ig_client)
    publication_id = created["publication"]["id"]

    def set_status() -> None:
        for container in fake_meta.containers:
            fake_meta.container_statuses[container] = [status]

    fake_meta.publish_hook = set_status

    publication = publish_and_wait(ig_client, publication_id)

    attempt = publication["latest_attempt"]
    assert publication["status"] == "failed"
    assert attempt["error"]["code"] == "instagram_publish_uncertain"
    assert attempt["outcome_determined"] is False
    assert attempt["requires_manual_review"] is True
    assert "@cyber.studio" in attempt["error"]["message"]
    assert "Summer drop." in attempt["error"]["message"]
    # Five read-only checks over 60 s, never another media_publish.
    assert len(fake_meta.requests_for("status")) >= 5
    assert recorded_sleeps[-4:] == [5.0, 10.0, 15.0, 30.0]
    _single_publish(fake_meta)

    # Still uncertain: a new attempt needs the explicit manual acknowledgement.
    response = _publish(ig_client, publication_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"
    assert len(attempt_rows_of(ig_client, publication_id)) == 1


def attempt_rows_of(client: TestClient, publication_id: int) -> list[Any]:
    response = client.get(f"/api/publications/{publication_id}/attempts")
    rows: list[Any] = response.json()
    return rows


def test_unreachable_container_keeps_the_result_uncertain(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    created = instagram_publication(ig_client)
    fake_meta.faults["publish"] = "transport"

    def break_status_reads() -> None:
        fake_meta.faults["status"] = "transport"

    fake_meta.publish_hook = break_status_reads

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    assert publication["latest_attempt"]["error"]["code"] == (
        "instagram_publish_uncertain"
    )
    _single_publish(fake_meta)


def test_retry_after_acknowledgement_starts_a_new_attempt(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    fake_meta.faults["publish"] = "transport"
    created = instagram_publication(ig_client)
    publication_id = created["publication"]["id"]
    publish_and_wait(ig_client, publication_id)
    # The container expires in the meantime (never published).
    for container in fake_meta.containers:
        fake_meta.container_statuses[container] = ["EXPIRED"]
    fake_meta.faults.pop("publish")

    response = _publish(ig_client, publication_id, confirm_remote_checked=True)
    wait_idle(ig_client)

    assert response.status_code == 202
    publication = get_publication(ig_client, publication_id)
    assert publication["status"] == "published"
    assert len(attempt_rows(db_path)) == 2
    assert len(fake_meta.containers) == 2  # The expired one is never reused.
    assert len(fake_meta.published) == 1


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("graph_9_2207042", "instagram_publishing_limit_reached"),
        ("graph_9007_2207027", "instagram_publish_failed"),
        ("graph_25_2207050", "instagram_account_restricted"),
        ("graph_100", "instagram_publish_failed"),
        ("graph_190", "instagram_reconnect_required"),
    ],
)
def test_explicit_rejection_is_determined(
    ig_client: TestClient, fake_meta: FakeMeta, fault: str, code: str
) -> None:
    fake_meta.faults["publish"] = fault
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    attempt = publication["latest_attempt"]
    assert publication["status"] == "failed"
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    _single_publish(fake_meta)


def test_explicit_rejection_with_published_container_is_published(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    fake_meta.faults["publish"] = "graph_100_after_publish"
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    assert publication["status"] == "published"
    assert publication["latest_attempt"]["external_id"] is None
    _single_publish(fake_meta)


def test_delivery_failure_creates_nothing_on_instagram(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    fake_delivery.put_failures = 3
    created = instagram_publication(ig_client)

    publication = publish_and_wait(ig_client, created["publication"]["id"])

    assert publication["latest_attempt"]["error"]["code"] == "media_delivery_failed"
    assert publication["latest_attempt"]["outcome_determined"] is True
    assert fake_meta.containers == {}
