"""Read-only reconciliation of an uncertain Instagram attempt before asking the user
to check it (FR-046a, FR-044a, research.md §11b, contracts/api.md)."""

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
)
from tests.fakes import FakeMeta, InMemoryCredentialStore


def _uncertain(client: TestClient, fake_meta: FakeMeta) -> int:
    """media_publish times out and the container does not confirm anything yet."""
    fake_meta.faults["publish"] = "transport"
    publication_id: int = instagram_publication(client)["publication"]["id"]
    publication = publish_and_wait(client, publication_id)
    assert publication["latest_attempt"]["requires_manual_review"] is True
    fake_meta.faults.pop("publish")
    return publication_id


def _set_container(fake_meta: FakeMeta, status: str) -> None:
    for container in fake_meta.containers:
        fake_meta.container_statuses[container] = [status]


def _check(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/publish-check")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _counts(fake_meta: FakeMeta) -> tuple[int, int, int]:
    return (
        len(fake_meta.requests_for("publish")),
        len(fake_meta.containers),
        fake_meta.media_list_requests,
    )


def _assert_reconciled(client: TestClient, db_path: Path, publication_id: int) -> None:
    publication = get_publication(client, publication_id)
    attempt = publication["latest_attempt"]
    assert publication["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["outcome_determined"] is True
    assert attempt["requires_manual_review"] is False
    assert attempt["error"] is None
    assert attempt["external_id"] is None
    assert attempt["external_url"] is None
    assert [w["code"] for w in attempt["warnings"]] == ["remote_identity_unavailable"]
    [run] = instagram_run_rows(db_path)
    assert run["phase"] == "succeeded"
    # published_at is approximate: the write-ahead time of the attempt.
    assert (
        publication["published_at"]
        .replace("Z", "")
        .replace("T", " ")
        .startswith(run["publish_started_at"][:19])
    )
    assert len(attempt_rows(db_path)) == 1


def test_publish_check_reconciles_a_published_container(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    publication_id = _uncertain(ig_client, fake_meta)
    counts = _counts(fake_meta)
    _set_container(fake_meta, "PUBLISHED")

    check = _check(ig_client, publication_id)

    assert check["requires_remote_check"] is False
    assert check["eligible"] is False
    assert check["problems"][0]["code"] == "publication_not_eligible"
    _assert_reconciled(ig_client, db_path, publication_id)
    assert _counts(fake_meta) == counts


def test_publish_now_reconciles_without_confirmation(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    publication_id = _uncertain(ig_client, fake_meta)
    counts = _counts(fake_meta)
    _set_container(fake_meta, "PUBLISHED")

    response = ig_client.post(f"/api/publications/{publication_id}/publish", json={})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "publication_not_eligible"
    _assert_reconciled(ig_client, db_path, publication_id)
    assert _counts(fake_meta) == counts


def test_reconciliation_is_idempotent(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    publication_id = _uncertain(ig_client, fake_meta)
    _set_container(fake_meta, "PUBLISHED")

    first = _check(ig_client, publication_id)
    reads = len(fake_meta.requests_for("status"))
    second = _check(ig_client, publication_id)

    assert first == second
    assert len(fake_meta.requests_for("status")) == reads  # Nothing to settle.
    _assert_reconciled(ig_client, db_path, publication_id)


@pytest.mark.parametrize(
    "status", ["FINISHED", "IN_PROGRESS", "ERROR", "EXPIRED", "SOMETHING_NEW"]
)
def test_any_other_status_keeps_the_attempt_uncertain(
    ig_client: TestClient, fake_meta: FakeMeta, status: str
) -> None:
    publication_id = _uncertain(ig_client, fake_meta)
    counts = _counts(fake_meta)
    _set_container(fake_meta, status)
    reads = len(fake_meta.requests_for("status"))

    check = _check(ig_client, publication_id)
    response = ig_client.post(f"/api/publications/{publication_id}/publish", json={})

    assert check["requires_remote_check"] is True
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "remote_check_required"
    publication = get_publication(ig_client, publication_id)
    assert publication["status"] == "failed"
    assert publication["latest_attempt"]["requires_manual_review"] is True
    # One read per request, never a polling loop.
    assert len(fake_meta.requests_for("status")) == reads + 2
    assert _counts(fake_meta) == counts


@pytest.mark.parametrize("fault", ["server_error", "transport", "bad_json"])
def test_unreachable_meta_keeps_the_attempt_uncertain(
    ig_client: TestClient, fake_meta: FakeMeta, fault: str
) -> None:
    publication_id = _uncertain(ig_client, fake_meta)
    fake_meta.faults["status"] = fault

    check = _check(ig_client, publication_id)

    assert check["requires_remote_check"] is True
    assert get_publication(ig_client, publication_id)["status"] == "failed"


def test_unusable_credential_keeps_the_attempt_uncertain(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    instagram_credential_store: InMemoryCredentialStore,
) -> None:
    publication_id = _uncertain(ig_client, fake_meta)
    _set_container(fake_meta, "PUBLISHED")
    instagram_credential_store.secrets.clear()

    check = _check(ig_client, publication_id)

    assert check["requires_remote_check"] is True
    assert get_publication(ig_client, publication_id)["status"] == "failed"


def test_attempts_before_the_final_step_are_not_reconciled(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    fake_meta.faults["create"] = "graph_-1_2207032"
    publication_id = instagram_publication(ig_client)["publication"]["id"]
    publish_and_wait(ig_client, publication_id)
    reads = len(fake_meta.requests_for("status"))

    _check(ig_client, publication_id)

    assert len(fake_meta.requests_for("status")) == reads


def test_confirmed_retry_after_unconfirmed_reconciliation(
    ig_client: TestClient, fake_meta: FakeMeta, db_path: Path
) -> None:
    publication_id = _uncertain(ig_client, fake_meta)
    _set_container(fake_meta, "EXPIRED")

    response = ig_client.post(
        f"/api/publications/{publication_id}/publish",
        json={"confirm_remote_checked": True},
    )

    assert response.status_code == 202
    publication = publish_wait(ig_client, publication_id)
    assert publication["status"] == "published"
    assert len(attempt_rows(db_path)) == 2
    assert len(fake_meta.published) == 1


def publish_wait(client: TestClient, publication_id: int) -> dict[str, Any]:
    from tests.conftest import wait_idle

    wait_idle(client)
    return get_publication(client, publication_id)
