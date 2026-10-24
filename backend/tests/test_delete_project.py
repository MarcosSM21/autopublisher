"""Delete Project (Feature 021 T022–T023, US7, research §10).

One `write_transaction` and one COMMIT remove every local row of the project; its
media are held away from Remove metadata from before the transaction; files and
secrets are queued in the same transaction (write-ahead) and deleted only after
the commit. Global settings and other projects never change. Races are forced with
barriers, never `sleep`.
"""

import sqlite3
import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app import asset_library, deletion
from app import db as db_module
from app.content_files import ContentFileGuard
from app.credential_store import CredentialStoreProbe
from app.main import create_app
from app.models import Project
from app.scheduler import TickReport
from app.telegram_connections import TelegramLogin
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
    run_sql,
    scheduled_publication,
    stop,
    wait_idle,
)
from tests.fakes import FakeClock, FakePublisher, InMemoryCredentialStore
from tests.test_delete_media import media_post
from tests.test_delete_post import (
    BASE_URL,
    CHANGED,
    PASSWORD,
    count,
    installation,  # noqa: F401 - fixture
    no_platform_contact,
)
from tests.test_image_metadata import dirty_png

IN_PROGRESS = (
    "A post in this project is being published right now. Try again when it finishes."
)
METADATA_BUSY = (
    "Metadata is being removed from a media item in this project. Try again when it "
    "finishes."
)
# Tables whose rows belong to one project (by `project_id`).
PROJECT_TABLES = (
    "accounts",
    "contents",
    "publications",
    "library_folders",
    "distribution_presets",
    "youtube_connections",
    "instagram_connections",
    "threads_connections",
)


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    _app(fake_scheduler_client).state.credential_probe = CredentialStoreProbe(
        lambda: "available"
    )
    return fake_scheduler_client


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _guard(client: TestClient) -> ContentFileGuard:
    guard: ContentFileGuard = _app(client).state.content_file_guard
    return guard


def _stores(client: TestClient) -> dict[str, InMemoryCredentialStore]:
    state = _app(client).state
    return {
        "youtube": state.credential_store,
        "instagram": state.instagram_credential_store,
        "threads": state.threads_credential_store,
    }


def preview(client: TestClient, project_id: int) -> dict[str, Any]:
    response = client.get(f"/api/projects/{project_id}/deletion-preview")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def delete(client: TestClient, project_id: int, confirmation: str) -> Any:
    return client.delete(
        f"/api/projects/{project_id}", params={"confirmation": confirmation}
    )


def confirmed_delete(client: TestClient, project_id: int) -> Any:
    return delete(client, project_id, preview(client, project_id)["confirmation"])


def rows(db_path: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(sql, params).fetchall()


def project_rows(db_path: Path, project_id: int) -> dict[str, list[tuple[Any, ...]]]:
    snapshot = {
        table: rows(db_path, f"SELECT * FROM {table} WHERE project_id = ?", project_id)
        for table in PROJECT_TABLES
    }
    snapshot["projects"] = rows(
        db_path, "SELECT * FROM projects WHERE id = ?", project_id
    )
    return snapshot


def files_of(db_path: Path, media_dir: Path, project_id: int) -> list[Path]:
    return [
        media_dir / path
        for row in rows(
            db_path,
            "SELECT storage_path, sanitized_storage_path FROM contents "
            "WHERE project_id = ?",
            project_id,
        )
        for path in row
        if path is not None
    ]


def queues(db_path: Path) -> tuple[int, int]:
    return count(db_path, "pending_file_deletions"), count(
        db_path, "pending_credential_deletions"
    )


def folder(db_path: Path, project_id: int, name: str, parent: int | None = None) -> int:
    now = FakeClock().now()
    return readmodels.insert(
        db_path,
        "library_folders",
        project_id=project_id,
        parent_id=parent,
        name=name,
        name_key=name.lower(),
        depth=1 if parent is None else 2,
        created_at=now,
        updated_at=now,
    )


def connected(
    client: TestClient, db_path: Path, project_id: int, platform: str, handle: str
) -> dict[str, Any]:
    """An account with a connection row and its secret in the platform's store."""
    account = create_account(client, project_id, platform, handle)
    readmodels.connect(db_path, account, FakeClock().now())
    _stores(client)[platform].set(f"secret-ref-{account['id']}", "SECRET")
    return account


def populate(
    client: TestClient, db_path: Path, name: str, *, media: int, sanitized: bool
) -> dict[str, Any]:
    """3 connected accounts, `media` media (one with a clean copy), 4 posts per
    account (draft, scheduled, published, needs review), two nested folders and a
    preset."""
    project = create_project(client, name)
    accounts = [
        connected(client, db_path, project["id"], platform, f"{name}-{platform}")
        for platform in ("youtube", "instagram", "threads")
    ]
    contents = [
        import_one(client, project["id"], f"m{index}.png", make_image())["content"]
        for index in range(media - 1)
    ]
    dirty = import_one(client, project["id"], "dirty.png", dirty_png())["content"]
    if sanitized:
        response = client.post(f"/api/contents/{dirty['id']}/remove-metadata")
        assert response.status_code == 200, response.text
    contents.append(dirty)
    now = FakeClock().now()
    specs: list[dict[str, Any]] = [
        {"status": "unscheduled"},
        {"minutes": 60},
        {"status": "published"},
        {"status": "failed", "attempt": "uncertain"},
    ]
    for account in accounts:
        for content, spec in zip(contents, specs, strict=False):
            media_post(db_path, account, content["id"], now, **spec)
    root = folder(db_path, project["id"], "Cyber")
    child = folder(db_path, project["id"], "DDoS", root)
    run_sql(
        db_path, "UPDATE contents SET folder_id = ? WHERE id = ?", child, dirty["id"]
    )
    preset = client.post(
        f"/api/projects/{project['id']}/distribution-presets",
        json={"name": "All", "account_ids": [a["id"] for a in accounts]},
    )
    assert preset.status_code == 201, preset.text
    return {"project": project, "accounts": accounts, "contents": contents}


def global_state(db_path: Path, tmp_path: Path, media_dir: Path) -> dict[str, Any]:
    """Global settings (FR-033): automation, installation and host files."""
    files = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
        and not path.is_relative_to(media_dir)
        and not path.name.startswith(db_path.name)
    }
    return {
        "automation_settings": rows(db_path, "SELECT * FROM automation_settings"),
        "installation_auth": rows(db_path, "SELECT * FROM installation_auth"),
        "files": files,
    }


# --- Removal ------------------------------------------------------------------------


def test_delete_project_removes_everything_local_and_nothing_else(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    media_dir: Path,
    tmp_path: Path,
) -> None:
    other = populate(client, db_path, "Other", media=4, sanitized=False)
    target = populate(client, db_path, "Cyber", media=24, sanitized=True)
    project_id = target["project"]["id"]
    other_id = other["project"]["id"]
    run_sql(
        db_path,
        "INSERT OR IGNORE INTO automation_settings (id, automation_paused, updated_at)"
        " VALUES (1, 1, '2026-10-24 10:00:00')",
    )
    before_other = project_rows(db_path, other_id)
    other_files = {
        path: path.read_bytes() for path in files_of(db_path, media_dir, other_id)
    }
    target_files = files_of(db_path, media_dir, project_id)
    assert len(target_files) == 25  # 24 originals + 1 clean copy
    global_before = global_state(db_path, tmp_path, media_dir)
    stores = _stores(client)
    max_ids = {
        table: rows(db_path, f"SELECT MAX(id) FROM {table}")[0][0]
        for table in ("projects", "accounts", "contents", "publications")
    }

    body = preview(client, project_id)

    assert body["kind"] == "project" and body["name"] == "Cyber"
    assert body["counts"] == {
        "unpublished_posts": 6,
        "remote_posts": 3,
        "needs_review_posts": 3,
        "accounts": 3,
        "posts": 12,
        "media": 24,
        "subfolders": 0,
        "media_to_unsorted": 0,
    }
    assert body["summary"] == [
        "This project contains 3 accounts, 12 posts and 24 media items. Everything "
        "will be removed from AutoPublisher.",
        "Content already published on platforms is not affected.",
        "3 posts may already have been published. Check the platforms before "
        "publishing this content again.",
    ]
    assert body["blocker"] is None

    assert delete(client, project_id, body["confirmation"]).status_code == 204

    # Nothing of it is left: rows, files, folder of files, secrets, queues.
    for table, found in project_rows(db_path, project_id).items():
        assert found == [], table
    assert rows(
        db_path,
        "SELECT COUNT(*) FROM distribution_preset_accounts dpa JOIN accounts a "
        "ON a.id = dpa.account_id WHERE a.project_id = ?",
        project_id,
    ) == [(0,)]
    assert not any(path.exists() for path in target_files)
    assert not (media_dir / "projects" / str(project_id)).exists()
    for account in target["accounts"]:
        ref = f"secret-ref-{account['id']}"
        assert all(ref not in store.secrets for store in stores.values())
    assert queues(db_path) == (0, 0)
    no_platform_contact(fake_publisher)
    # Every read model.
    assert [p["id"] for p in client.get("/api/projects").json()] == [other_id]
    for path in (
        f"/api/projects/{project_id}",
        f"/api/projects/{project_id}/accounts",
        f"/api/projects/{project_id}/contents",
        f"/api/projects/{project_id}/publications",
        f"/api/projects/{project_id}/distribution-presets",
        f"/api/projects/{project_id}/deletion-preview",
    ):
        assert client.get(path).status_code == 404, path
    for content in target["contents"][:2]:
        assert client.get(f"/api/contents/{content['id']}").status_code == 404
    overview = client.get("/api/overview").json()
    assert [p["id"] for p in overview["projects"]] == [other_id]
    assert "Cyber" not in str(overview["upcoming"]) + str(overview["attention"])

    # Another project and the global settings are byte-for-byte unchanged.
    assert project_rows(db_path, other_id) == before_other
    assert {path: path.read_bytes() for path in other_files} == other_files
    for account in other["accounts"]:
        assert f"secret-ref-{account['id']}" in stores[account["platform"]].secrets
    assert global_state(db_path, tmp_path, media_dir) == global_before

    # A new project inherits nothing and reuses no id.
    fresh = create_project(client, "Cyber")
    account = create_account(client, fresh["id"], "youtube", "cyber")
    content = import_one(client, fresh["id"], "new.png", make_image())["content"]
    post_id = media_post(db_path, account, content["id"], FakeClock().now())
    assert fresh["id"] > max_ids["projects"]
    assert account["id"] > max_ids["accounts"]
    assert content["id"] > max_ids["contents"]
    assert post_id > max_ids["publications"]
    library = client.get(f"/api/projects/{fresh['id']}/contents").json()
    assert [item["id"] for item in library] == [content["id"]]
    assert client.get(f"/api/projects/{fresh['id']}/distribution-presets").json() == []

    again = delete(client, project_id, body["confirmation"])
    assert again.status_code == 404
    assert again.json()["error"]["message"] == "Project not found."


def test_deleting_the_last_and_empty_project_leaves_no_project(
    client: TestClient, db_path: Path
) -> None:
    project = create_project(client, "Empty")
    folder(db_path, project["id"], "Only folders")

    body = preview(client, project["id"])
    assert body["summary"] == []
    assert body["counts"]["accounts"] == body["counts"]["posts"] == 0

    assert delete(client, project["id"], body["confirmation"]).status_code == 204
    assert client.get("/api/projects").json() == []
    assert client.get("/api/overview").json()["projects"] == []
    assert count(db_path, "projects") == count(db_path, "library_folders") == 0


# --- Atomicity ----------------------------------------------------------------------


def test_failure_mid_delete_changes_nothing(
    client: TestClient, db_path: Path, media_dir: Path
) -> None:
    """Posts, accounts, presets and folders deleted and everything queued; then the
    media rows fail: the whole project is still there."""
    target = populate(client, db_path, "Cyber", media=4, sanitized=True)
    project_id = target["project"]["id"]
    account_id = target["accounts"][0]["id"]
    logins = _app(client).state.telegram_logins
    logins.put(
        account_id,
        TelegramLogin("code", "s", "+1", "h", FakeClock().now() + timedelta(minutes=5)),
    )
    before = project_rows(db_path, project_id)
    files = files_of(db_path, media_dir, project_id)
    secrets = {
        platform: dict(store.secrets) for platform, store in _stores(client).items()
    }
    token = preview(client, project_id)["confirmation"]
    engine: Engine = _app(client).state.session_factory.kw["bind"]
    executed: list[str] = []

    def fail(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        executed.append(statement.split(" WHERE")[0])
        if statement.startswith("DELETE FROM contents"):
            raise RuntimeError("disk I/O error")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = delete(
            TestClient(_app(client), raise_server_exceptions=False), project_id, token
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)

    assert response.status_code == 500
    assert {
        "DELETE FROM publications",
        "DELETE FROM accounts",
        "DELETE FROM distribution_presets",
        "DELETE FROM library_folders",
    } <= set(executed)
    assert any(
        s.startswith("INSERT INTO pending_credential_deletions") for s in executed
    )
    assert any(s.startswith("INSERT INTO pending_file_deletions") for s in executed)
    assert project_rows(db_path, project_id) == before
    assert queues(db_path) == (0, 0)
    assert all(path.is_file() for path in files)
    assert {p: dict(s.secrets) for p, s in _stores(client).items()} == secrets
    assert _guard(client)._deleting == set()
    assert logins.get(account_id) is not None  # attempts untouched

    assert delete(client, project_id, token).status_code == 204
    assert logins.get(account_id) is None  # invalidated only after the commit


# --- Media guards -------------------------------------------------------------------


def _three_media(client: TestClient, project_id: int) -> list[dict[str, Any]]:
    """A media with metadata to remove between two plain ones."""
    first = import_one(client, project_id, "a.png", make_image())["content"]
    dirty = import_one(client, project_id, "dirty.png", dirty_png())["content"]
    last = import_one(client, project_id, "c.png", make_image())["content"]
    return [first, dirty, last]


def test_remove_metadata_on_any_media_blocks_the_project(
    client: TestClient,
    db_path: Path,
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One media of several is having its metadata removed."""
    project = create_project(client, "Cyber")
    contents = _three_media(client, project["id"])
    token = preview(client, project["id"])["confirmation"]
    gate = Gate()
    original = asset_library._sanitize_to

    def held(*args: Any) -> None:
        gate.pause()
        original(*args)

    monkeypatch.setattr(asset_library, "_sanitize_to", held)
    target = contents[1]["id"]
    removing = Background(
        lambda: client.post(f"/api/contents/{target}/remove-metadata")
    )
    gate.wait_reached()

    body = preview(client, project["id"])
    assert body["blocker"] == {
        "code": "metadata_removal_in_progress",
        "message": METADATA_BUSY,
    }
    response = delete(client, project["id"], token)

    assert response.status_code == 409
    assert response.json()["error"]["message"] == METADATA_BUSY
    assert count(db_path, "projects") == 1 and count(db_path, "contents") == 3
    assert queues(db_path) == (0, 0)
    assert _guard(client)._deleting == set()
    gate.release()
    assert removing.result().status_code == 200


def test_the_project_delete_holds_every_media_away_from_remove_metadata(
    client: TestClient, db_path: Path, media_dir: Path
) -> None:
    project = create_project(client, "Cyber")
    contents = _three_media(client, project["id"])
    token = preview(client, project["id"])["confirmation"]
    factory = _app(client).state.session_factory

    def deleted(session: Session) -> bool:
        query = select(func.count()).select_from(Project)
        return session.scalar(query.where(Project.id == project["id"])) == 0

    with pause_before_commit(factory, deleted) as commit:
        deleting = Background(lambda: delete(client, project["id"], token))
        commit.wait_reached()  # guards held, rows deleted, not committed
        responses = [
            client.post(f"/api/contents/{content['id']}/remove-metadata")
            for content in (contents[0], contents[2])
        ]
        commit.release()
        assert deleting.result().status_code == 204

    assert [r.json()["error"]["code"] for r in responses] == ["content_deleting"] * 2
    assert list(media_dir.glob("projects/*/*")) == []


def test_a_media_imported_after_the_guards_rejects_the_delete(
    client: TestClient, db_path: Path, media_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Cyber")
    for index in range(2):
        import_one(client, project["id"], f"m{index}.png", make_image())
    token = preview(client, project["id"])["confirmation"]
    real = db_module.write_transaction
    imported: list[int] = []

    def import_then_write(factory: Any) -> Any:
        # Guards on A and B are held; C arrives before the transaction.
        if not imported:
            content = import_one(client, project["id"], "c.png", make_image())
            imported.append(content["content"]["id"])
        return real(factory)

    monkeypatch.setattr(deletion, "write_transaction", import_then_write)

    response = delete(client, project["id"], token)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "deletion_changed",
        "message": CHANGED,
        "fields": [],
    }
    assert count(db_path, "projects") == 1 and count(db_path, "contents") == 3
    assert queues(db_path) == (0, 0)
    assert _guard(client)._deleting == set()
    monkeypatch.setattr(deletion, "write_transaction", real)
    body = preview(client, project["id"])
    assert body["counts"]["media"] == 3
    assert delete(client, project["id"], body["confirmation"]).status_code == 204
    assert list(media_dir.glob("projects/*/*")) == []


# --- Publication start vs Delete Project --------------------------------------------


@pytest.fixture
def due(client: TestClient, fake_clock: FakeClock, db_path: Path) -> dict[str, Any]:
    """An armed automatic post whose time has come, among other project rows."""
    at = in_minutes(fake_clock, 5)
    setup = scheduled_publication(client, db_path, at)
    import_one(client, setup["project"]["id"], "other.png", make_image())
    fake_clock.set(at)
    return setup


def test_delete_project_first_then_scheduler_claim(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    due: dict[str, Any],
) -> None:
    project_id = due["project"]["id"]
    token = preview(client, project_id)["confirmation"]
    factory = _app(client).state.session_factory
    engine: Engine = factory.kw["bind"]

    def deleted(session: Session) -> bool:
        query = select(func.count()).select_from(Project)
        return session.scalar(query.where(Project.id == project_id)) == 0

    prepare = pause_in_prepare(fake_publisher)
    tick = Background(lambda: _run_tick(client))
    prepare.wait_reached()
    with (
        pause_before_commit(factory, deleted) as commit,
        statement_reached(engine, "UPDATE publications SET status") as claim,
    ):
        deleting = Background(lambda: delete(client, project_id, token))
        commit.wait_reached()
        prepare.release()
        assert claim.wait(10)
        commit.release()
        assert deleting.result().status_code == 204
        report: TickReport = tick.result()

    assert report.started == [] and report.failed == []
    assert attempt_rows(db_path) == []
    assert fake_publisher.upload_calls == []
    assert count(db_path, "projects") == count(db_path, "publications") == 0
    publish = client.post(
        f"/api/publications/{due['publication']['id']}/publish", json={}
    )
    assert publish.status_code == 404


def _run_tick(client: TestClient) -> TickReport:
    report: TickReport = _app(client).state.scheduler.run_once()
    return report


@pytest.mark.parametrize("entrypoint", ["scheduler", "publish-now"])
def test_claim_first_blocks_the_whole_project(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    media_dir: Path,
    due: dict[str, Any],
    entrypoint: str,
) -> None:
    project_id = due["project"]["id"]
    post_id = due["publication"]["id"]
    token = preview(client, project_id)["confirmation"]
    before = project_rows(db_path, project_id)
    fake_publisher.upload_gate = threading.Event()
    factory = _app(client).state.session_factory

    def start() -> Any:
        if entrypoint == "scheduler":
            return _run_tick(client)
        return client.post(f"/api/publications/{post_id}/publish", json={})

    with pause_before_commit(factory, is_claim) as claim:
        starting = Background(start)
        claim.wait_reached()
        deleting = Background(lambda: delete(client, project_id, token))
        claim.release()
        starting.result()
        response = deleting.result()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "post_in_progress"
    assert response.json()["error"]["message"] == IN_PROGRESS
    after = project_rows(db_path, project_id)
    assert {k: v for k, v in after.items() if k != "publications"} == {
        k: v for k, v in before.items() if k != "publications"
    }
    assert len(after["publications"]) == 1
    assert all(path.is_file() for path in files_of(db_path, media_dir, project_id))
    assert queues(db_path) == (0, 0)
    assert _guard(client)._deleting == set()
    assert fake_publisher.upload_gate is not None
    fake_publisher.upload_gate.set()
    wait_idle(client)
    assert count(db_path, "publications", "status = 'published'") == 1


# --- Cleanup failures and start-up retry --------------------------------------------


@pytest.fixture
def failing_unlink(monkeypatch: pytest.MonkeyPatch) -> Iterator[set[Path]]:
    blocked: set[Path] = set()
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self in blocked:
            raise PermissionError("busy")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    yield blocked
    monkeypatch.setattr(Path, "unlink", real_unlink)


def test_cleanup_failures_keep_the_delete_and_start_up_finishes_it(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    failing_unlink: set[Path],
) -> None:
    project = create_project(client, "Cyber")
    youtube = connected(client, db_path, project["id"], "youtube", "cy")
    instagram = connected(client, db_path, project["id"], "instagram", "cy")
    import_one(client, project["id"], "m.png", make_image())
    files = files_of(db_path, media_dir, project["id"])
    stores = _stores(client)
    stores["youtube"].fail_on = {"delete"}
    failing_unlink.update(files)

    assert confirmed_delete(client, project["id"]).status_code == 204

    assert count(db_path, "projects") == count(db_path, "accounts") == 0
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    # The other platform's secret is still cleaned: one failure blocks no other.
    assert f"secret-ref-{instagram['id']}" not in stores["instagram"].secrets
    youtube_ref = f"secret-ref-{youtube['id']}"
    assert rows(db_path, "SELECT credential_ref FROM pending_credential_deletions") == [
        (youtube_ref,)
    ]
    assert count(db_path, "pending_file_deletions") == len(files) == 1
    assert all(path.is_file() for path in files)

    # Resources available again: the next start-up finishes the cleanup.
    failing_unlink.clear()
    stores["youtube"].fail_on = set()
    stop(client)
    app = create_app(
        db_path,
        media_dir,
        credential_store=stores["youtube"],
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        tiktok_credential_store=InMemoryCredentialStore(),
        credential_probe=CredentialStoreProbe(lambda: "available"),
        clock=fake_clock.now,
    )
    with TestClient(app):
        app.state.credential_cleanup.join(10)
    assert queues(db_path) == (0, 0)
    assert youtube_ref not in stores["youtube"].secrets
    assert not any(path.exists() for path in files)


# --- Installation guards ------------------------------------------------------------


def test_project_routes_are_private_and_guarded(installation: TestClient) -> None:  # noqa: F811
    client = installation
    assert (
        client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    )
    project = create_project(client, "Cyber")
    token = preview(client, project["id"])["confirmation"]
    url = f"/api/projects/{project['id']}"

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
    cross_site = client.delete(
        url, params={"confirmation": token}, headers={"origin": "http://evil.example"}
    )
    assert cross_site.json()["error"]["code"] == "origin_not_allowed"
    foreign_host = client.delete(
        url, params={"confirmation": token}, headers={"host": "evil.example"}
    )
    assert foreign_host.json()["error"]["code"] == "host_not_allowed"
    assert client.delete(url).status_code == 422
    forged = client.delete(url, params={"confirmation": "v1:" + "0" * 64})
    assert forged.status_code == 409
    assert client.get("/api/projects/9999/deletion-preview").status_code == 404
    assert client.delete(url, params={"confirmation": token}).status_code == 204
