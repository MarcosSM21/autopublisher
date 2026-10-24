"""Delete a Post (Feature 021 T016, US1, contracts/api.md §1).

Rows are written straight to SQLite (tests.readmodels) so each test states exactly
the situation it deletes. YouTube posts go to a `FakePublisher` that records every
call: no delete may contact a platform.
"""

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app import auth
from app.deployment import DataLayout, DeploymentSettings, parse_host_config
from app.main import create_app
from app.models import Publication
from app.post_state import requires_remote_check
from app.scheduler import SchedulerSettings
from tests import readmodels
from tests.conftest import (
    FUTURE,
    create_account,
    create_project,
    create_publications,
    run_sql,
    setup_project,
)
from tests.fakes import (
    FakeClock,
    FakeMediaDeliveryProvider,
    FakePublisher,
    InMemoryCredentialStore,
)

CHANGED = "Something changed since you opened this. Review it again before deleting."
IN_PROGRESS = "This post is being published right now. Try again when it finishes."


def preview(client: TestClient, post_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{post_id}/deletion-preview")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def delete(client: TestClient, post_id: int, confirmation: str) -> Any:
    return client.delete(
        f"/api/publications/{post_id}", params={"confirmation": confirmation}
    )


def count(db_path: Path, table: str, where: str = "1", *params: Any) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", params
        ).fetchone()
    return int(row[0])


def running_attempt(db_path: Path, post_id: int, now: datetime) -> int:
    return readmodels.insert(
        db_path,
        "publication_attempts",
        publication_id=post_id,
        platform="youtube",
        status="running",
        stage="uploading",
        started_at=now,
        bytes_sent=0,
        total_bytes=10,
        submitted="{}",
        details="{}",
        warnings="[]",
    )


def no_platform_contact(publisher: FakePublisher) -> None:
    assert publisher.check_calls == []
    assert publisher.prepare_calls == []
    assert publisher.upload_calls == []
    assert publisher.release_calls == []
    assert publisher.reconcile_calls == []
    assert publisher.follow_up_calls == []


@pytest.fixture
def youtube(fake_scheduler_client: TestClient) -> dict[str, Any]:
    project = create_project(fake_scheduler_client, "Cyber")
    return create_account(fake_scheduler_client, project["id"], "youtube", "cyber")


# --- Every state ---------------------------------------------------------------------

REMOTE = (
    "It will only be removed from AutoPublisher. The content published on YouTube "
    "is not affected."
)
REVIEW = (
    "This post may have been published. Check YouTube before publishing this media "
    "again."
)
STATES: dict[str, tuple[dict[str, Any], str, list[str]]] = {
    # name: (post row, bucket, summary)
    "draft": ({"status": "unscheduled"}, "unpublished_posts", []),
    "scheduled-automatic": (
        {"armed": True, "in": 60},
        "unpublished_posts",
        ["This post will not be published."],
    ),
    "scheduled-manual": (
        {"in": 60},
        "unpublished_posts",
        ["This post will not be published."],
    ),
    "missed": ({"in": -600}, "unpublished_posts", ["This post will not be published."]),
    "failed": ({"status": "failed", "attempt": "determined"}, "unpublished_posts", []),
    "cancelled": ({"status": "cancelled"}, "unpublished_posts", []),
    "needs-review": (
        {"status": "failed", "attempt": "uncertain"},
        "needs_review_posts",
        [REVIEW],
    ),
    "awaiting-user-action": (
        {"status": "awaiting_user_action"},
        "remote_posts",
        [REMOTE],
    ),
    "published": ({"status": "published"}, "remote_posts", [REMOTE]),
}


def make_post(
    db_path: Path, account: dict[str, Any], now: datetime, spec: dict[str, Any]
) -> int:
    values = dict(spec)
    minutes = values.pop("in", None)
    attempt = values.pop("attempt", None)
    if minutes is not None:
        values.setdefault("status", "scheduled")
        values["scheduled_at"] = now + timedelta(minutes=minutes)
    post_id = readmodels.post(db_path, account, now, **values)
    if attempt is not None:
        readmodels.failed_attempt(
            db_path, post_id, now, uncertain=attempt == "uncertain"
        )
    return post_id


@pytest.mark.parametrize("state", list(STATES))
def test_delete_post_in_every_state(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    youtube: dict[str, Any],
    state: str,
) -> None:
    client = fake_scheduler_client
    spec, bucket, summary = STATES[state]
    post_id = make_post(db_path, youtube, fake_clock.now(), spec)

    body = preview(client, post_id)

    assert body["kind"] == "post" and body["id"] == post_id
    assert body["summary"] == summary
    assert body["blocker"] is None
    assert body["counts"]["posts"] == body["counts"][bucket] == 1
    assert body["confirmation"].startswith("v1:")

    assert delete(client, post_id, body["confirmation"]).status_code == 204

    assert client.get(f"/api/publications/{post_id}").status_code == 404
    assert count(db_path, "publications") == 0
    assert count(db_path, "publication_attempts") == 0
    listed = client.get(f"/api/projects/{youtube['project_id']}/publications").json()
    assert listed == []
    no_platform_contact(fake_publisher)

    # Duplicate delete (another tab, double click): the post is already gone.
    again = delete(client, post_id, body["confirmation"])
    assert again.status_code == 404
    assert again.json()["error"] == {
        "code": "not_found",
        "message": "Post not found.",
        "fields": [],
    }
    assert (
        client.get(f"/api/publications/{post_id}/deletion-preview").status_code == 404
    )


def test_deleted_posts_get_no_follow_up_nor_review(
    fake_scheduler_client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    youtube: dict[str, Any],
) -> None:
    """Awaiting user action and Needs review: the manual follow-ups end with 404
    and nothing reaches the platform."""
    client = fake_scheduler_client
    now = fake_clock.now()
    awaiting = make_post(db_path, youtube, now, {"status": "awaiting_user_action"})
    review = make_post(
        db_path, youtube, now, {"status": "failed", "attempt": "uncertain"}
    )
    for post_id in (awaiting, review):
        assert (
            delete(
                client, post_id, preview(client, post_id)["confirmation"]
            ).status_code
            == 204
        )

    assert client.post(f"/api/publications/{awaiting}/check-status").status_code == 404
    assert client.get(f"/api/publications/{review}/publish-check").status_code == 404
    assert (
        client.post(f"/api/publications/{review}/publish", json={}).status_code == 404
    )
    no_platform_contact(fake_publisher)


# --- Blockers and changed scope ------------------------------------------------------


@pytest.mark.parametrize("status", ["publishing", "scheduled"])
def test_post_in_progress_is_not_deleted(
    fake_scheduler_client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    youtube: dict[str, Any],
    status: str,
) -> None:
    """Blocked by `publishing` or by a running attempt (whatever the status says)."""
    client = fake_scheduler_client
    now = fake_clock.now()
    spec: dict[str, Any] = {"status": status}
    if status == "scheduled":
        spec["in"] = 60
    post_id = make_post(db_path, youtube, now, spec)
    running_attempt(db_path, post_id, now)

    body = preview(client, post_id)
    assert body["blocker"] == {"code": "post_in_progress", "message": IN_PROGRESS}

    response = delete(client, post_id, body["confirmation"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "post_in_progress"
    assert response.json()["error"]["message"] == IN_PROGRESS
    assert count(db_path, "publications") == 1
    assert count(db_path, "publication_attempts") == 1


def test_changed_consequences_are_rejected(
    fake_scheduler_client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    youtube: dict[str, Any],
) -> None:
    client = fake_scheduler_client
    now = fake_clock.now()
    post_id = make_post(db_path, youtube, now, {"status": "unscheduled"})
    draft = preview(client, post_id)

    # Scheduled in another tab: the summary would now say it will not publish.
    run_sql(
        db_path,
        "UPDATE publications SET status = 'scheduled', scheduled_at = ? WHERE id = ?",
        readmodels.ts(now + timedelta(hours=1)),
        post_id,
    )
    response = delete(client, post_id, draft["confirmation"])

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "deletion_changed",
        "message": CHANGED,
        "fields": [],
    }
    assert count(db_path, "publications") == 1

    scheduled = preview(client, post_id)
    assert scheduled["confirmation"] != draft["confirmation"]
    assert scheduled["summary"] == ["This post will not be published."]
    # Equivalent scope: the same token again; time passing alone changes nothing.
    fake_clock.advance(timedelta(days=2).total_seconds())
    assert preview(client, post_id)["confirmation"] == scheduled["confirmation"]
    assert delete(client, post_id, scheduled["confirmation"]).status_code == 204


def test_confirmation_is_required_and_checked(
    fake_scheduler_client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    youtube: dict[str, Any],
) -> None:
    client = fake_scheduler_client
    post_id = make_post(db_path, youtube, fake_clock.now(), {"status": "unscheduled"})

    missing = client.delete(f"/api/publications/{post_id}")
    assert missing.status_code == 422
    forged = delete(client, post_id, "v1:" + "0" * 64)
    assert forged.status_code == 409
    assert forged.json()["error"]["code"] == "deletion_changed"
    assert count(db_path, "publications") == 1


# --- Dependencies, temporary media and atomicity -------------------------------------


@pytest.fixture
def delivery() -> FakeMediaDeliveryProvider:
    return FakeMediaDeliveryProvider()


@pytest.fixture
def delivery_client(
    db_path: Path,
    media_dir: Path,
    media_delivery_file: Path,
    delivery: FakeMediaDeliveryProvider,
) -> Iterator[TestClient]:
    app = create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        media_delivery_provider=delivery,
        scheduler_settings=SchedulerSettings(autostart=False),
    )
    with TestClient(app) as test_client:
        yield test_client


def _post_with_dependents(
    db_path: Path,
    account: dict[str, Any],
    now: datetime,
    delivery: FakeMediaDeliveryProvider,
) -> int:
    """A failed post with options, a publish run and two temporary objects: one
    still pending on the delivery provider and one already cleaned up."""
    post_id = make_post(
        db_path, account, now, {"status": "failed", "attempt": "determined"}
    )
    (attempt_id,) = [
        row[0]
        for row in sqlite3.connect(db_path).execute(
            "SELECT id FROM publication_attempts WHERE publication_id = ?", (post_id,)
        )
    ]
    readmodels.insert(
        db_path,
        "youtube_publication_options",
        publication_id=post_id,
        privacy_status="private",
        notify_subscribers=0,
        updated_at=now,
    )
    readmodels.insert(
        db_path,
        "instagram_publish_runs",
        attempt_id=attempt_id,
        publication_id=post_id,
        media_kind="image",
        fingerprint="f" * 64,
        phase="failed",
        updated_at=now,
    )
    for key, deleted_at in (("pending/key.jpg", None), ("released/key.jpg", now)):
        readmodels.insert(
            db_path,
            "temporary_media_objects",
            provider=delivery.name,
            object_key=key,
            attempt_id=attempt_id,
            content_type="image/jpeg",
            size_bytes=3,
            created_at=now,
            uploaded_at=now,
            deleted_at=deleted_at,
            cleanup_failures=0,
        )
    delivery.objects["pending/key.jpg"] = b"abc"
    return post_id


def test_delete_removes_dependents_and_keeps_pending_delivery_objects(
    delivery_client: TestClient,
    delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    client = delivery_client
    project = create_project(client, "Cyber")
    account = create_account(client, project["id"], "instagram", "cyber")
    post_id = _post_with_dependents(db_path, account, FakeClock().now(), delivery)

    assert (
        delete(client, post_id, preview(client, post_id)["confirmation"]).status_code
        == 204
    )

    for table in (
        "publications",
        "publication_attempts",
        "youtube_publication_options",
        "instagram_publish_runs",
    ):
        assert count(db_path, table) == 0, table
    # The released object went with its post; the pending one stays queued.
    assert count(db_path, "temporary_media_objects") == 1
    pending = "object_key = 'pending/key.jpg' AND attempt_id IS NULL"
    assert count(db_path, "temporary_media_objects", pending) == 1
    assert delivery.delete_calls == []  # nothing remote during the delete

    app = client.app
    assert isinstance(app, FastAPI)
    assert app.state.temporary_media.sweep() == 0
    assert delivery.delete_calls == ["pending/key.jpg"]
    assert count(db_path, "temporary_media_objects", "deleted_at IS NOT NULL") == 1


def test_failure_mid_delete_rolls_everything_back(
    delivery_client: TestClient,
    delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    client = delivery_client
    project = create_project(client, "Cyber")
    account = create_account(client, project["id"], "instagram", "cyber")
    post_id = _post_with_dependents(db_path, account, FakeClock().now(), delivery)
    token = preview(client, post_id)["confirmation"]
    tables = (
        "publications",
        "publication_attempts",
        "youtube_publication_options",
        "instagram_publish_runs",
        "temporary_media_objects",
    )
    before = {table: count(db_path, table) for table in tables}
    app = client.app
    assert isinstance(app, FastAPI)
    engine = app.state.session_factory.kw["bind"]

    def fail(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if statement.startswith("DELETE FROM publication_attempts"):
            raise RuntimeError("disk I/O error at publication_attempts")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = delete(
            TestClient(app, raise_server_exceptions=False), post_id, token
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred. Please try again.",
        "fields": [],
    }
    assert {table: count(db_path, table) for table in tables} == before
    assert count(db_path, "temporary_media_objects", "attempt_id IS NULL") == 0
    assert delivery.delete_calls == []
    # Nothing was left half-done: the same confirmation still deletes it.
    assert delete(client, post_id, token).status_code == 204


# --- Read models ---------------------------------------------------------------------


def test_deleted_posts_leave_no_ghost_rows(client: TestClient, db_path: Path) -> None:
    """Posts list (also History and Calendar), Home overview, Media usage and the
    needs-review warning forget the deleted posts."""
    project, content, (instagram, tiktok, _) = setup_project(client)
    scheduled = create_publications(client, content["id"], [instagram["id"]], FUTURE)[0]
    review = create_publications(client, content["id"], [tiktok["id"]])[0]
    now = FakeClock().now()
    run_sql(
        db_path, "UPDATE publications SET status = 'failed' WHERE id = ?", review["id"]
    )
    readmodels.failed_attempt(db_path, review["id"], now, uncertain=True)

    def overview_ids() -> tuple[set[int], set[int]]:
        body = client.get("/api/overview").json()
        upcoming = {item["post_id"] for item in body["upcoming"]}
        attention = {item["post"]["id"] for item in body["attention"] if item["post"]}
        return upcoming, attention

    assert overview_ids() == ({scheduled["id"]}, {review["id"]})
    usage = client.get(f"/api/contents/{content['id']}/usage").json()
    assert usage["usage"]["publication_count"] == 2

    for post in (scheduled, review):
        token = preview(client, post["id"])["confirmation"]
        assert delete(client, post["id"], token).status_code == 204

    assert client.get(f"/api/projects/{project['id']}/publications").json() == []
    assert overview_ids() == (set(), set())
    summary = client.get("/api/overview").json()["projects"][0]
    assert summary["next_post"] is None and summary["attention_count"] == 0
    usage = client.get(f"/api/contents/{content['id']}/usage").json()
    assert usage["publications"] == []
    assert usage["usage"]["publication_count"] == 0
    assert usage["usage"]["used"] is False
    listed = client.get(f"/api/projects/{project['id']}/contents").json()
    assert listed[0]["usage"]["publication_count"] == 0
    # The uncertain attempt is gone: a new post of the same media and account
    # needs no "check before publishing again" confirmation.
    again = create_publications(client, content["id"], [tiktok["id"]])[0]
    assert again["latest_attempt"] is None
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        assert not requires_remote_check(
            session, session.get_one(Publication, again["id"])
        )


# --- Installation guards -------------------------------------------------------------

PASSWORD = "correct horse battery"
BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
def installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)
    data = tmp_path / "data"
    settings = DeploymentSettings.installation(
        parse_host_config({"data_dir": str(data)}, tmp_path / "config.toml"),
        DataLayout(
            data_dir=data,
            db_path=data / "autopublisher.db",
            media_dir=data / "media",
            platform_files={},
        ),
    )
    clock = FakeClock()
    app = create_app(
        deployment=settings,
        clock=clock.now,
        scheduler_settings=SchedulerSettings(clock=clock.now, autostart=False),
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
    )
    with TestClient(
        app,
        base_url=BASE_URL,
        client=("127.0.0.1", 50000),
        headers={"origin": BASE_URL},
    ) as test_client:
        with app.state.session_factory() as db:
            auth.set_password(db, PASSWORD, clock.now())
        yield test_client


def test_routes_are_private_and_guarded(
    installation: TestClient, tmp_path: Path
) -> None:
    client = installation
    assert (
        client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    )
    project = create_project(client, "Cyber")
    account = create_account(client, project["id"], "telegram", "cyber")
    db_path = tmp_path / "data" / "autopublisher.db"
    post_id = readmodels.post(db_path, account, FakeClock().now(), status="unscheduled")
    token = preview(client, post_id)["confirmation"]
    url = f"/api/publications/{post_id}"

    anonymous = TestClient(
        client.app,
        base_url=BASE_URL,
        client=("127.0.0.1", 50000),
        headers={"origin": BASE_URL},
    )
    for response in (
        anonymous.get(f"{url}/deletion-preview"),
        anonymous.delete(
            url, params={"confirmation": token}
        ),  # a valid token is no key
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_required"

    cross_site = client.delete(
        url, params={"confirmation": token}, headers={"origin": "http://evil.example"}
    )
    assert cross_site.status_code == 403
    assert cross_site.json()["error"]["code"] == "origin_not_allowed"
    foreign_host = client.delete(
        url, params={"confirmation": token}, headers={"host": "evil.example"}
    )
    assert foreign_host.status_code == 403
    assert foreign_host.json()["error"]["code"] == "host_not_allowed"
    assert count(db_path, "publications") == 1

    assert client.delete(url, params={"confirmation": token}).status_code == 204
