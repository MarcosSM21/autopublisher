"""Delete Media (Feature 021 T018–T019, US2, research §6, §8).

A media goes with every post that uses it; its files are queued in the same
transaction (write-ahead) and unlinked only after the commit. Remove metadata and a
publication start exclude it; every race is forced with barriers, never `sleep`.
"""

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app import asset_library, deletion
from app.content_files import ContentFileGuard
from app.models import Content
from app.scheduler import TickReport
from tests import readmodels
from tests.barriers import (
    Background,
    Gate,
    is_claim,
    pause_before_commit,
    pause_in_prepare,
    statement_reached,
)
from tests.conftest import (
    attempt_rows,
    create_account,
    create_project,
    import_one,
    in_minutes,
    make_image,
    make_scheduler_app,
    run_sql,
    run_tick,
    scheduled_publication,
    stop,
    use_fake_publisher,
    wait_idle,
)
from tests.fakes import FakeClock, FakePublisher
from tests.test_delete_post import (
    BASE_URL,
    CHANGED,
    PASSWORD,
    count,
    installation,  # noqa: F401 - fixture
    no_platform_contact,
    running_attempt,
)
from tests.test_image_metadata import dirty_png

IN_PROGRESS = (
    "A post using this media is being published right now. Try again when it finishes."
)
METADATA_BUSY = "Metadata is being removed from this media. Try again when it finishes."


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _engine(client: TestClient) -> Engine:
    engine: Engine = _app(client).state.session_factory.kw["bind"]
    return engine


def _guard(client: TestClient) -> ContentFileGuard:
    guard: ContentFileGuard = _app(client).state.content_file_guard
    return guard


def preview(client: TestClient, content_id: int) -> dict[str, Any]:
    response = client.get(f"/api/contents/{content_id}/deletion-preview")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def delete(client: TestClient, content_id: int, confirmation: str) -> Any:
    return client.delete(
        f"/api/contents/{content_id}", params={"confirmation": confirmation}
    )


def files_of(db_path: Path, media_dir: Path, content_id: int) -> list[Path]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT storage_path, sanitized_storage_path FROM contents WHERE id = ?",
            (content_id,),
        ).fetchone()
    return [media_dir / path for path in row if path is not None]


def pending_files(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT storage_path FROM pending_file_deletions")
        return {row[0] for row in rows}


def media_post(
    db_path: Path,
    account: dict[str, Any],
    content_id: int,
    now: datetime,
    *,
    status: str = "unscheduled",
    minutes: int | None = None,
    armed: bool = False,
    attempt: str | None = None,
) -> int:
    """A post of the media on `account`, written straight to SQLite."""
    if minutes is not None:
        status = "scheduled"
    post_id = readmodels.insert(
        db_path,
        "publications",
        project_id=account["project_id"],
        account_id=account["id"],
        content_id=content_id,
        status=status,
        scheduled_at=now + timedelta(minutes=minutes) if minutes is not None else None,
        auto_publish_enabled=armed,
        published_at=now if status == "published" else None,
        created_at=now,
        updated_at=now,
    )
    if attempt is not None:
        readmodels.failed_attempt(
            db_path, post_id, now, uncertain=attempt == "uncertain"
        )
    return post_id


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


def _account(
    client: TestClient, project: dict[str, Any], handle: str
) -> dict[str, Any]:
    return create_account(client, project["id"], "youtube", handle)


def _sanitized_media(client: TestClient, project: dict[str, Any]) -> int:
    content = import_one(client, project["id"], "comfy.png", dirty_png())["content"]
    response = client.post(f"/api/contents/{content['id']}/remove-metadata")
    assert response.status_code == 200, response.text
    assert response.json()["metadata_status"] == "sanitized"
    return int(content["id"])


# --- Removal ------------------------------------------------------------------------

EVERY_STATE: list[dict[str, Any]] = [
    {"status": "unscheduled"},
    {"minutes": 60, "armed": True},  # scheduled automatic
    {"minutes": 60},  # scheduled manual
    {"minutes": -600},  # missed
    {"status": "failed", "attempt": "determined"},
    {"status": "cancelled"},
    {"status": "failed", "attempt": "uncertain"},  # needs review
    {"status": "awaiting_user_action"},
    {"status": "published"},
]


def test_delete_media_removes_every_post_and_both_files(
    client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    content_id = _sanitized_media(client, project)
    files = files_of(db_path, media_dir, content_id)
    assert len(files) == 2 and all(path.is_file() for path in files)
    now = fake_clock.now()
    for index, spec in enumerate(EVERY_STATE):
        account = _account(client, project, f"cyber{index}")
        media_post(db_path, account, content_id, now, **spec)

    body = preview(client, content_id)

    assert body["kind"] == "media" and body["id"] == content_id
    assert body["name"] == "comfy.png"
    assert body["counts"] == {
        "unpublished_posts": 6,
        "remote_posts": 2,
        "needs_review_posts": 1,
        "accounts": 0,
        "posts": 9,
        "media": 1,
        "subfolders": 0,
        "media_to_unsorted": 0,
    }
    assert body["summary"] == [
        "6 unpublished posts and 3 published posts will also be removed from "
        "AutoPublisher.",
        "Content already published on platforms is not affected.",
        "1 post may have been published. Check YouTube before publishing this media "
        "again.",
    ]
    assert body["blocker"] is None

    assert delete(client, content_id, body["confirmation"]).status_code == 204

    assert not any(path.exists() for path in files)
    assert pending_files(db_path) == set()
    for table in ("contents", "publications", "publication_attempts"):
        assert count(db_path, table) == 0, table
    no_platform_contact(fake_publisher)

    # Read models: Library, detail, usage, Posts (also History and Calendar), Home.
    assert client.get(f"/api/projects/{project['id']}/contents").json() == []
    assert client.get(f"/api/contents/{content_id}").status_code == 404
    assert client.get(f"/api/contents/{content_id}/usage").status_code == 404
    assert client.get(f"/api/projects/{project['id']}/publications").json() == []
    overview = client.get("/api/overview").json()
    assert overview["upcoming"] == []
    assert [item for item in overview["attention"] if item["post"]] == []
    assert overview["projects"][0]["onboarding"]["media_imported"] is False

    again = delete(client, content_id, body["confirmation"])
    assert again.status_code == 404
    assert again.json()["error"]["message"] == "Media not found."
    assert pending_files(db_path) == set()


def test_summary_of_the_spec(
    client: TestClient, fake_clock: FakeClock, db_path: Path, project: dict[str, Any]
) -> None:
    content = import_one(client, project["id"], "photo.png", dirty_png())["content"]
    now = fake_clock.now()
    specs: list[dict[str, Any]] = [
        {"status": "unscheduled"},
        {"minutes": 60},
        {"status": "published"},
    ]
    for index, spec in enumerate(specs):
        media_post(
            db_path, _account(client, project, f"c{index}"), content["id"], now, **spec
        )

    assert preview(client, content["id"])["summary"] == [
        "2 unpublished posts and 1 published post will also be removed from "
        "AutoPublisher.",
        "Content already published on platforms is not affected.",
    ]


def test_unused_media_has_a_plain_confirmation(
    client: TestClient, project: dict[str, Any]
) -> None:
    content = import_one(client, project["id"], "photo.png", dirty_png())["content"]
    body = preview(client, content["id"])
    assert body["summary"] == []
    assert body["counts"]["posts"] == 0 and body["counts"]["media"] == 1


def test_token_follows_the_posts_of_the_media(
    client: TestClient, fake_clock: FakeClock, db_path: Path, project: dict[str, Any]
) -> None:
    content = import_one(client, project["id"], "photo.png", dirty_png())["content"]
    now = fake_clock.now()
    first = preview(client, content["id"])["confirmation"]
    # Renaming the file, or time passing, changes nothing.
    response = client.patch(f"/api/contents/{content['id']}", json={"title": "New"})
    assert response.status_code == 200
    fake_clock.advance(timedelta(days=3).total_seconds())
    assert preview(client, content["id"])["confirmation"] == first

    post_id = media_post(db_path, _account(client, project, "a"), content["id"], now)
    added = preview(client, content["id"])["confirmation"]
    assert added != first
    readmodels.failed_attempt(db_path, post_id, now, uncertain=True)
    run_sql(db_path, "UPDATE publications SET status = 'failed' WHERE id = ?", post_id)
    review = preview(client, content["id"])["confirmation"]
    assert review not in (first, added)


# --- Write-ahead, unlink failure and start-up retry --------------------------------


def _restart(
    client: TestClient, db_path: Path, media_dir: Path, clock: FakeClock
) -> None:
    """A new server on the same data: start-up runs the queued file cleanup."""
    stop(client)
    with TestClient(make_scheduler_app(db_path, media_dir, clock)):
        pass


@pytest.mark.parametrize("sanitized", [False, True], ids=["original", "clean-copy"])
def test_files_are_queued_before_the_commit_and_cleaned_at_start_up(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    sanitized: bool,
) -> None:
    """Crash model: the delete committed with its queued files, and the process
    ended before the immediate cleanup."""
    if sanitized:
        content_id = _sanitized_media(client, project)
    else:
        content_id = import_one(client, project["id"], "p.png", dirty_png())["content"][
            "id"
        ]
    files = files_of(db_path, media_dir, content_id)
    assert len(files) == (2 if sanitized else 1)
    seen: list[tuple[int, set[str]]] = []

    def crash(session_factory: Any, storage: Any, paths: Any) -> None:
        # Called after the COMMIT, with every file already queued.
        seen.append((count(db_path, "contents"), pending_files(db_path)))

    monkeypatch.setattr(deletion, "run_file_cleanup", crash)
    assert (
        delete(
            client, content_id, preview(client, content_id)["confirmation"]
        ).status_code
        == 204
    )

    relative = {path.relative_to(media_dir).as_posix() for path in files}
    assert seen == [(0, relative)]
    assert all(path.is_file() for path in files)  # nothing unlinked yet

    _restart(client, db_path, media_dir, fake_clock)

    assert not any(path.exists() for path in files)
    assert pending_files(db_path) == set()


def test_unlink_failure_keeps_the_delete_and_retries_at_start_up(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_id = _sanitized_media(client, project)
    media_post(db_path, _account(client, project, "a"), content_id, fake_clock.now())
    files = files_of(db_path, media_dir, content_id)
    real_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        if self in files:
            raise PermissionError("busy")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    token = preview(client, content_id)["confirmation"]

    assert delete(client, content_id, token).status_code == 204

    assert count(db_path, "contents") == count(db_path, "publications") == 0
    assert all(path.is_file() for path in files)
    assert len(pending_files(db_path)) == 2
    assert client.get(f"/api/contents/{content_id}").status_code == 404

    monkeypatch.setattr(Path, "unlink", real_unlink)
    _restart(client, db_path, media_dir, fake_clock)

    assert not any(path.exists() for path in files)
    assert pending_files(db_path) == set()


def test_a_path_still_referenced_is_never_unlinked(
    client: TestClient, db_path: Path, media_dir: Path, project: dict[str, Any]
) -> None:
    """Forged: B's clean copy is A's original. Deleting A keeps the file while B
    uses it; deleting B then removes it."""
    first = import_one(client, project["id"], "a.png", make_image())["content"]["id"]
    second = import_one(client, project["id"], "b.png", make_image())["content"]["id"]
    (shared,) = files_of(db_path, media_dir, first)
    (own,) = files_of(db_path, media_dir, second)
    run_sql(
        db_path,
        "UPDATE contents SET metadata_status = 'sanitized', sanitized_storage_path = ?,"
        " sanitized_checksum = checksum, sanitized_size_bytes = size_bytes,"
        " sanitized_at = created_at WHERE id = ?",
        shared.relative_to(media_dir).as_posix(),
        second,
    )

    assert (
        delete(client, first, preview(client, first)["confirmation"]).status_code == 204
    )
    assert shared.is_file()
    assert pending_files(db_path) == set()

    assert (
        delete(client, second, preview(client, second)["confirmation"]).status_code
        == 204
    )
    assert not shared.exists() and not own.exists()


def test_the_same_file_can_be_imported_again(
    client: TestClient, fake_clock: FakeClock, db_path: Path, project: dict[str, Any]
) -> None:
    data = dirty_png()
    old = import_one(client, project["id"], "photo.png", data)["content"]
    media_post(db_path, _account(client, project, "a"), old["id"], fake_clock.now())
    assert (
        delete(
            client, old["id"], preview(client, old["id"])["confirmation"]
        ).status_code
        == 204
    )

    result = import_one(client, project["id"], "photo.png", data)

    assert result["status"] == "imported"
    new = result["content"]
    assert new["id"] > old["id"]
    usage = client.get(f"/api/contents/{new['id']}/usage").json()
    assert usage["publications"] == []


# --- Blockers and changed scope -----------------------------------------------------


def test_remove_metadata_first_blocks_the_delete(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = import_one(client, project["id"], "comfy.png", dirty_png())["content"]
    media_post(db_path, _account(client, project, "a"), content["id"], fake_clock.now())
    token = preview(client, content["id"])["confirmation"]
    gate = Gate()
    original = asset_library._sanitize_to

    def held(*args: Any) -> None:
        gate.pause()
        original(*args)

    monkeypatch.setattr(asset_library, "_sanitize_to", held)
    removing = Background(
        lambda: client.post(f"/api/contents/{content['id']}/remove-metadata")
    )
    gate.wait_reached()

    body = preview(client, content["id"])
    assert body["blocker"] == {
        "code": "metadata_removal_in_progress",
        "message": METADATA_BUSY,
    }
    response = delete(client, content["id"], token)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "metadata_removal_in_progress",
        "message": METADATA_BUSY,
        "fields": [],
    }
    assert count(db_path, "contents") == count(db_path, "publications") == 1
    assert pending_files(db_path) == set()
    gate.release()
    assert removing.result().status_code == 200


def test_delete_first_blocks_remove_metadata(
    client: TestClient, db_path: Path, media_dir: Path, project: dict[str, Any]
) -> None:
    content = import_one(client, project["id"], "comfy.png", dirty_png())["content"]
    files = files_of(db_path, media_dir, content["id"])
    token = preview(client, content["id"])["confirmation"]
    factory = _app(client).state.session_factory

    def deleted(session: Session) -> bool:
        query = select(func.count()).select_from(Content)
        return session.scalar(query.where(Content.id == content["id"])) == 0

    with pause_before_commit(factory, deleted) as commit:
        deleting = Background(lambda: delete(client, content["id"], token))
        commit.wait_reached()  # guard held, rows deleted, not committed
        response = client.post(f"/api/contents/{content['id']}/remove-metadata")
        commit.release()
        assert deleting.result().status_code == 204

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "content_deleting"
    assert not any(path.exists() for path in files)
    assert list(media_dir.glob("projects/*/*.clean.*")) == []


def test_a_publishing_post_blocks_the_whole_media(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    content = import_one(client, project["id"], "photo.png", dirty_png())["content"]
    now = fake_clock.now()
    media_post(db_path, _account(client, project, "a"), content["id"], now)
    busy = media_post(
        db_path, _account(client, project, "b"), content["id"], now, status="publishing"
    )
    running_attempt(db_path, busy, now)

    body = preview(client, content["id"])
    assert body["blocker"] == {"code": "post_in_progress", "message": IN_PROGRESS}
    response = delete(client, content["id"], body["confirmation"])

    assert response.status_code == 409
    assert response.json()["error"]["message"] == IN_PROGRESS
    assert count(db_path, "contents") == 1
    assert count(db_path, "publications") == 2
    assert count(db_path, "publication_attempts") == 1
    assert all(path.is_file() for path in files_of(db_path, media_dir, content["id"]))
    assert pending_files(db_path) == set()
    assert _guard(client)._deleting == set()


def test_changed_scope_is_rejected_and_releases_everything(
    client: TestClient, fake_clock: FakeClock, db_path: Path, project: dict[str, Any]
) -> None:
    content = import_one(client, project["id"], "photo.png", dirty_png())["content"]
    token = preview(client, content["id"])["confirmation"]
    # A post is created with this media in another tab.
    media_post(db_path, _account(client, project, "a"), content["id"], fake_clock.now())

    response = delete(client, content["id"], token)

    assert response.status_code == 409
    assert response.json()["error"]["message"] == CHANGED
    assert count(db_path, "contents") == count(db_path, "publications") == 1
    assert pending_files(db_path) == set()
    assert _guard(client)._deleting == set()
    assert (
        client.post(f"/api/contents/{content['id']}/remove-metadata").status_code == 200
    )


def test_failure_mid_delete_changes_nothing(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    content_id = _sanitized_media(client, project)
    media_post(db_path, _account(client, project, "a"), content_id, fake_clock.now())
    files = files_of(db_path, media_dir, content_id)
    token = preview(client, content_id)["confirmation"]
    engine = _engine(client)

    def fail(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        # Posts deleted and files queued: the media row itself fails.
        if statement.startswith("DELETE FROM contents"):
            raise RuntimeError("disk I/O error")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = delete(
            TestClient(_app(client), raise_server_exceptions=False), content_id, token
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert count(db_path, "contents") == count(db_path, "publications") == 1
    assert pending_files(db_path) == set()
    assert all(path.is_file() for path in files)
    assert _guard(client)._deleting == set()
    assert delete(client, content_id, token).status_code == 204


# --- Publication start vs Delete Media ----------------------------------------------


@pytest.fixture
def due(client: TestClient, fake_clock: FakeClock, db_path: Path) -> dict[str, Any]:
    """An armed automatic post whose time has come, plus a draft of the same media
    on another account."""
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(client, db_path, at)
    other = create_account(client, setup["project"]["id"], "youtube", "other")
    media_post(db_path, other, setup["content"]["id"], fake_clock.now())
    fake_clock.set(at)
    return setup


def test_delete_media_first_then_scheduler_claim(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    media_dir: Path,
    due: dict[str, Any],
) -> None:
    """The delete holds the writer lock while the claim's UPDATE waits for it."""
    content_id = due["content"]["id"]
    files = files_of(db_path, media_dir, content_id)
    token = preview(client, content_id)["confirmation"]
    factory = _app(client).state.session_factory

    def deleted(session: Session) -> bool:
        query = select(func.count()).select_from(Content)
        return session.scalar(query.where(Content.id == content_id)) == 0

    prepare = pause_in_prepare(fake_publisher)
    tick = Background(lambda: run_tick(client))
    prepare.wait_reached()
    with (
        pause_before_commit(factory, deleted) as commit,
        statement_reached(_engine(client), "UPDATE publications SET status") as claim,
    ):
        deleting = Background(lambda: delete(client, content_id, token))
        commit.wait_reached()
        prepare.release()
        assert claim.wait(10)
        commit.release()
        assert deleting.result().status_code == 204
        report: TickReport = tick.result()

    assert report.started == [] and report.failed == []
    assert attempt_rows(db_path) == []
    assert fake_publisher.upload_calls == []
    assert count(db_path, "publications") == count(db_path, "contents") == 0
    assert not any(path.exists() for path in files)


def _claim_first(
    client: TestClient, publisher: FakePublisher, content_id: int, start: Any
) -> tuple[Any, Any]:
    """The claim commits first; its upload stays blocked so the attempt is still
    running when the delete reads. The delete waits on the content guard's mutex
    (held by `claiming`) or on SQLite's writer lock: either way after the claim."""
    token = preview(client, content_id)["confirmation"]
    publisher.upload_gate = threading.Event()
    factory = _app(client).state.session_factory
    with pause_before_commit(factory, is_claim) as claim:
        starting = Background(start)
        claim.wait_reached()
        deleting = Background(lambda: delete(client, content_id, token))
        claim.release()
        started = starting.result()
        deleted = deleting.result()
    return started, deleted


def _assert_media_intact(db_path: Path, media_dir: Path, content_id: int) -> None:
    assert count(db_path, "contents") == 1
    assert count(db_path, "publications") == 2
    assert [row["status"] for row in attempt_rows(db_path)] == ["running"]
    assert all(path.is_file() for path in files_of(db_path, media_dir, content_id))
    assert pending_files(db_path) == set()


@pytest.mark.parametrize("entrypoint", ["scheduler", "publish-now"])
def test_claim_first_blocks_the_media_delete(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    media_dir: Path,
    due: dict[str, Any],
    entrypoint: str,
) -> None:
    content_id = due["content"]["id"]
    post_id = due["publication"]["id"]

    def start() -> Any:
        if entrypoint == "scheduler":
            return run_tick(client)
        return client.post(f"/api/publications/{post_id}/publish", json={})

    started, response = _claim_first(client, fake_publisher, content_id, start)

    if entrypoint == "scheduler":
        assert started.started == [post_id]
    else:
        assert started.status_code == 202
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "post_in_progress"
    _assert_media_intact(db_path, media_dir, content_id)

    assert fake_publisher.upload_gate is not None
    fake_publisher.upload_gate.set()
    wait_idle(client)
    assert count(db_path, "publications", "status = 'published'") == 1


def test_deleted_media_posts_never_run_after_a_restart(
    client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    content_id = scheduled_publication(client, db_path, at)["content"]["id"]
    assert (
        delete(
            client, content_id, preview(client, content_id)["confirmation"]
        ).status_code
        == 204
    )
    stop(client)

    with TestClient(make_scheduler_app(db_path, media_dir, fake_clock)) as restarted:
        use_fake_publisher(restarted, fake_publisher)
        fake_clock.set(at + timedelta(minutes=1))
        report = run_tick(restarted)

    assert report.started == [] and fake_publisher.prepare_calls == []
    assert attempt_rows(db_path) == []


# --- Installation guards ------------------------------------------------------------


def test_media_routes_are_private_and_guarded(installation: TestClient) -> None:  # noqa: F811
    client = installation
    assert (
        client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    )
    project = create_project(client, "Cyber")
    content = import_one(client, project["id"], "photo.png", dirty_png())["content"]
    token = preview(client, content["id"])["confirmation"]
    url = f"/api/contents/{content['id']}"

    anonymous = TestClient(
        client.app,
        base_url=BASE_URL,
        client=("127.0.0.1", 50000),
        headers={"origin": BASE_URL},
    )
    for response in (
        anonymous.get(f"{url}/deletion-preview"),
        anonymous.delete(url, params={"confirmation": token}),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_required"
    cross_site = client.delete(
        url, params={"confirmation": token}, headers={"origin": "http://evil.example"}
    )
    assert cross_site.json()["error"]["code"] == "origin_not_allowed"
    foreign_host = client.delete(
        url, params={"confirmation": token}, headers={"host": "evil.example"}
    )
    assert foreign_host.json()["error"]["code"] == "host_not_allowed"
    assert client.get(url).status_code == 200

    missing = client.get("/api/contents/9999/deletion-preview")
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "Media not found."
    assert client.delete(url, params={"confirmation": token}).status_code == 204
