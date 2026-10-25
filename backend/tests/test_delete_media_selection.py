"""Bulk Media Delete (Feature 022 T007–T009, US1–US3, research §2–§7).

A selection of 1–500 media of one project goes with every post that uses them in
one transaction, or nothing does. The preview is read-only; the delete holds every
selected media first, and a publishing post wins over a Remove metadata. Every race
is forced with barriers, never `sleep`.
"""

import itertools
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app import asset_library, deletion
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
    make_image,
    run_sql,
    run_tick,
    wait_idle,
)
from tests.fakes import FakeClock, FakePublisher
from tests.test_delete_media import (
    _account,
    _app,
    _engine,
    _guard,
    _restart,
    _sanitized_media,
    due,  # noqa: F401 - fixture
    files_of,
    media_post,
    pending_files,
)
from tests.test_delete_media import delete as delete_one
from tests.test_delete_media import preview as preview_one
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
from tests.test_library_folders import move, new_folder


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    return create_project(client, "Cyber")


MISSING = "Some selected media no longer exist. Review your selection."
IN_PROGRESS = (
    "A post using one or more selected media items is being published right now. "
    "Try again when it finishes."
)
METADATA_BUSY = (
    "Metadata is being removed from one or more selected media items. Try again "
    "when it finishes."
)


def preview_response(client: TestClient, project_id: int, ids: list[int]) -> Any:
    return client.post(
        f"/api/projects/{project_id}/contents/deletion-preview",
        json={"content_ids": ids},
    )


def preview(client: TestClient, project_id: int, ids: list[int]) -> dict[str, Any]:
    response = preview_response(client, project_id, ids)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def delete(
    client: TestClient, project_id: int, ids: list[int], confirmation: str
) -> Any:
    return client.post(
        f"/api/projects/{project_id}/contents/delete",
        json={"content_ids": ids, "confirmation": confirmation},
    )


def import_media(client: TestClient, project_id: int, n: int) -> list[int]:
    return [
        int(
            import_one(client, project_id, f"m{index}.png", make_image())["content"][
                "id"
            ]
        )
        for index in range(n)
    ]


def _gone(ids: list[int]) -> Any:
    """`pause_before_commit` condition: every selected media row is deleted."""

    def check(session: Session) -> bool:
        query = select(func.count()).select_from(Content).where(Content.id.in_(ids))
        return session.scalar(query) == 0

    return check


def _hold_remove_metadata(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, content_id: int
) -> tuple[Gate, Background]:
    """Remove metadata of `content_id`, paused while it writes the clean copy."""
    gate = Gate()
    original = asset_library._sanitize_to

    def held(*args: Any) -> None:
        gate.pause()
        original(*args)

    monkeypatch.setattr(asset_library, "_sanitize_to", held)
    removing = Background(
        lambda: client.post(f"/api/contents/{content_id}/remove-metadata")
    )
    gate.wait_reached()
    return gate, removing


# --- Removal ------------------------------------------------------------------------


def test_one_media_without_posts(
    client: TestClient,
    fake_publisher: FakePublisher,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    [media] = import_media(client, project["id"], 1)
    files = files_of(db_path, media_dir, media)

    body = preview(client, project["id"], [media])

    assert body["kind"] == "media_selection"
    assert body["id"] is None and body["name"] is None
    assert body["counts"]["media"] == 1 and body["counts"]["posts"] == 0
    assert body["summary"] == ["1 media item will be removed from AutoPublisher."]
    assert body["blocker"] is None
    assert (
        delete(client, project["id"], [media], body["confirmation"]).status_code == 204
    )
    assert count(db_path, "contents") == 0
    assert not any(path.exists() for path in files)
    no_platform_contact(fake_publisher)


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


def test_several_media_with_posts_in_every_state(
    client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    sanitized = _sanitized_media(client, project)
    plain, unused, published = import_media(client, project["id"], 3)
    ids = [sanitized, plain, unused, published]
    files = [path for id_ in ids for path in files_of(db_path, media_dir, id_)]
    assert len(files) == 5
    now = fake_clock.now()
    for index, spec in enumerate(EVERY_STATE):
        account = _account(client, project, f"cyber{index}")
        media_post(db_path, account, sanitized if index % 2 else plain, now, **spec)
    media_post(
        db_path, _account(client, project, "p"), published, now, status="published"
    )
    # Media of the project outside the selection stays.
    [other] = import_media(client, project["id"], 1)
    kept = media_post(db_path, _account(client, project, "k"), other, now)

    body = preview(client, project["id"], ids)

    assert body["id"] is None and body["name"] is None
    assert body["counts"] == {
        "unpublished_posts": 6,
        "remote_posts": 3,
        "needs_review_posts": 1,
        "accounts": 0,
        "posts": 10,
        "media": 4,
        "subfolders": 0,
        "media_to_unsorted": 0,
    }
    assert body["summary"] == [
        "4 media items and 10 posts will be removed from AutoPublisher.",
        "4 posts may already exist on platforms. Content already published on "
        "platforms is not affected.",
        "1 post may already have been published. Check the platforms before "
        "publishing this content again.",
    ]
    assert body["blocker"] is None

    assert delete(client, project["id"], ids, body["confirmation"]).status_code == 204

    assert not any(path.exists() for path in files)
    assert pending_files(db_path) == set()
    assert count(db_path, "contents") == 1
    assert count(db_path, "publications") == 1
    assert count(db_path, "publications", "id = ?", kept) == 1
    assert count(db_path, "publication_attempts") == 0
    no_platform_contact(fake_publisher)
    listed = client.get(f"/api/projects/{project['id']}/contents").json()
    assert [item["id"] for item in listed] == [other]
    for id_ in ids:
        assert client.get(f"/api/contents/{id_}").status_code == 404

    # Ids are never reused.
    [new] = import_media(client, project["id"], 1)
    assert new > max(ids + [other])


def test_files_are_queued_before_the_commit_and_cleaned_at_start_up(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crash model: the delete committed with its queued files, and the process
    ended before the immediate cleanup."""
    ids = [_sanitized_media(client, project), *import_media(client, project["id"], 1)]
    files = [path for id_ in ids for path in files_of(db_path, media_dir, id_)]
    assert len(files) == 3
    seen: list[tuple[int, set[str]]] = []

    def crash(session_factory: Any, storage: Any, paths: Any) -> None:
        seen.append((count(db_path, "contents"), pending_files(db_path)))

    monkeypatch.setattr(deletion, "run_file_cleanup", crash)
    token = preview(client, project["id"], ids)["confirmation"]
    assert delete(client, project["id"], ids, token).status_code == 204

    assert seen == [(0, {path.relative_to(media_dir).as_posix() for path in files})]
    assert all(path.is_file() for path in files)

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
    ids = import_media(client, project["id"], 2)
    media_post(db_path, _account(client, project, "a"), ids[0], fake_clock.now())
    files = [path for id_ in ids for path in files_of(db_path, media_dir, id_)]
    real_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        if self in files:
            raise PermissionError("busy")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    token = preview(client, project["id"], ids)["confirmation"]

    assert delete(client, project["id"], ids, token).status_code == 204

    assert count(db_path, "contents") == count(db_path, "publications") == 0
    assert all(path.is_file() for path in files)
    assert len(pending_files(db_path)) == 2

    monkeypatch.setattr(Path, "unlink", real_unlink)
    _restart(client, db_path, media_dir, fake_clock)

    assert not any(path.exists() for path in files)
    assert pending_files(db_path) == set()


# --- Token and validation -----------------------------------------------------------


def test_token_ignores_the_order_of_the_ids(
    client: TestClient, fake_clock: FakeClock, db_path: Path, project: dict[str, Any]
) -> None:
    ids = import_media(client, project["id"], 3)
    media_post(db_path, _account(client, project, "a"), ids[1], fake_clock.now())
    tokens = {
        preview(client, project["id"], list(order))["confirmation"]
        for order in itertools.permutations(ids)
    }
    assert len(tokens) == 1
    # The folder is not part of it.
    folder = new_folder(client, project["id"], "Lux")
    assert move(client, project["id"], [ids[0]], folder["id"]).status_code == 200
    assert preview(client, project["id"], ids)["confirmation"] in tokens

    assert delete(client, project["id"], ids[::-1], tokens.pop()).status_code == 204


def test_bulk_and_individual_tokens_never_validate_each_other(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    [media] = import_media(client, project["id"], 1)
    bulk = preview(client, project["id"], [media])["confirmation"]
    single = preview_one(client, media)["confirmation"]
    assert bulk != single

    for response in (
        delete(client, project["id"], [media], single),
        delete_one(client, media, bulk),
    ):
        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "deletion_changed",
            "message": CHANGED,
            "fields": [],
        }
    assert count(db_path, "contents") == 1


@pytest.mark.parametrize(
    "ids",
    [[], "duplicate", list(range(1, 502)), ["x"]],
    ids=["empty", "duplicate", "501", "not-int"],
)
def test_invalid_selection_is_rejected(
    client: TestClient, project: dict[str, Any], ids: Any
) -> None:
    if ids == "duplicate":
        [media] = import_media(client, project["id"], 1)
        ids = [media, media]
    for response in (
        preview_response(client, project["id"], ids),
        delete(client, project["id"], ids, "v1:x"),
    ):
        assert response.status_code == 422


def test_selection_body_is_strict(client: TestClient, project: dict[str, Any]) -> None:
    [media] = import_media(client, project["id"], 1)
    url = f"/api/projects/{project['id']}/contents"
    extra = client.post(
        f"{url}/deletion-preview", json={"content_ids": [media], "folder_id": None}
    )
    no_token = client.post(f"{url}/delete", json={"content_ids": [media]})
    empty_token = delete(client, project["id"], [media], "")
    assert {extra.status_code, no_token.status_code, empty_token.status_code} == {422}


def test_media_of_another_project_or_unknown_project(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    mine = import_media(client, project["id"], 1)
    other_project = create_project(client, "Other")
    foreign = import_media(client, other_project["id"], 1)
    ids = mine + foreign
    token = preview(client, project["id"], mine)["confirmation"]

    response = preview_response(client, project["id"], ids)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == MISSING
    response = delete(client, project["id"], ids, token)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "deletion_changed"

    for response in (
        preview_response(client, 9999, mine),
        delete(client, 9999, mine, token),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Project not found."
    assert count(db_path, "contents") == 2
    assert _guard(client)._deleting == set()


def test_five_hundred_media_at_once(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    """SC-008: rows inserted straight into SQLite, one post each, tiny files."""
    [base] = import_media(client, project["id"], 1)
    account = _account(client, project, "a")
    now = readmodels.ts(fake_clock.now())
    paths = [f"projects/{project['id']}/bulk-{index}.png" for index in range(499)]
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO contents (project_id, folder_id, media_type, media_format,"
            " storage_path, original_filename, checksum, size_bytes, hashtags,"
            " created_at, updated_at, metadata_status)"
            " SELECT project_id, folder_id, media_type, media_format, ?,"
            " original_filename, ?, size_bytes, hashtags, created_at, updated_at,"
            " metadata_status FROM contents WHERE id = ?",
            [(path, f"{index:064x}", base) for index, path in enumerate(paths)],
        )
        ids = [row[0] for row in connection.execute("SELECT id FROM contents")]
        connection.executemany(
            "INSERT INTO publications (project_id, account_id, content_id, status,"
            " auto_publish_enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, 'unscheduled', 0, ?, ?)",
            [(project["id"], account["id"], id_, now, now) for id_ in ids],
        )
    for path in paths:
        (media_dir / path).write_bytes(b"x")
    assert len(ids) == 500

    body = preview(client, project["id"], ids)

    assert body["counts"]["media"] == 500 and body["counts"]["posts"] == 500
    assert body["summary"] == [
        "500 media items and 500 posts will be removed from AutoPublisher."
    ]
    assert delete(client, project["id"], ids, body["confirmation"]).status_code == 204
    assert count(db_path, "contents") == count(db_path, "publications") == 0
    assert pending_files(db_path) == set()
    assert not any((media_dir / path).exists() for path in paths)


def test_selection_routes_are_private_and_guarded(installation: TestClient) -> None:  # noqa: F811
    client = installation
    assert (
        client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    )
    project = create_project(client, "Cyber")
    ids = import_media(client, project["id"], 1)
    token = preview(client, project["id"], ids)["confirmation"]

    anonymous = TestClient(
        client.app,
        base_url=BASE_URL,
        client=("127.0.0.1", 50000),
        headers={"origin": BASE_URL},
    )
    for response in (
        preview_response(anonymous, project["id"], ids),
        delete(anonymous, project["id"], ids, token),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "auth_required"
    url = f"/api/projects/{project['id']}/contents"
    for path, body in (
        ("deletion-preview", {"content_ids": ids}),
        ("delete", {"content_ids": ids, "confirmation": token}),
    ):
        cross_site = client.post(
            f"{url}/{path}", json=body, headers={"origin": "http://evil.example"}
        )
        assert cross_site.json()["error"]["code"] == "origin_not_allowed"
        foreign_host = client.post(
            f"{url}/{path}", json=body, headers={"host": "evil.example"}
        )
        assert foreign_host.json()["error"]["code"] == "host_not_allowed"
    assert client.get(f"/api/contents/{ids[0]}").status_code == 200
    assert delete(client, project["id"], ids, token).status_code == 204


# --- Blockers and precedence (US2) --------------------------------------------------


def _publishing(
    client: TestClient,
    db_path: Path,
    project: dict[str, Any],
    content_id: int,
    now: Any,
) -> None:
    busy = media_post(
        db_path, _account(client, project, "busy"), content_id, now, status="publishing"
    )
    running_attempt(db_path, busy, now)


def _assert_nothing_deleted(
    client: TestClient, db_path: Path, media_dir: Path, ids: list[int], posts: int
) -> None:
    assert count(db_path, "contents") == len(ids)
    assert count(db_path, "publications") == posts
    for id_ in ids:
        assert all(path.is_file() for path in files_of(db_path, media_dir, id_))
    assert pending_files(db_path) == set()
    assert _guard(client)._deleting == set()


def test_a_publishing_post_blocks_the_whole_selection(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    ids = import_media(client, project["id"], 2)
    now = fake_clock.now()
    media_post(db_path, _account(client, project, "a"), ids[0], now)
    _publishing(client, db_path, project, ids[1], now)

    body = preview(client, project["id"], ids)
    assert body["blocker"] == {"code": "post_in_progress", "message": IN_PROGRESS}
    assert body["confirmation"].startswith("v1:")
    response = delete(client, project["id"], ids, body["confirmation"])

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "post_in_progress",
        "message": IN_PROGRESS,
        "fields": [],
    }
    _assert_nothing_deleted(client, db_path, media_dir, ids, posts=2)
    assert count(db_path, "publication_attempts") == 1


def test_remove_metadata_on_a_selected_media_blocks_the_whole_selection(
    client: TestClient,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty = int(
        import_one(client, project["id"], "d.png", dirty_png())["content"]["id"]
    )
    ids = [dirty, *import_media(client, project["id"], 1)]
    token = preview(client, project["id"], ids)["confirmation"]
    gate, removing = _hold_remove_metadata(client, monkeypatch, dirty)

    body = preview(client, project["id"], ids)
    assert body["blocker"] == {
        "code": "metadata_removal_in_progress",
        "message": METADATA_BUSY,
    }
    response = delete(client, project["id"], ids, token)

    assert response.status_code == 409
    assert response.json()["error"]["message"] == METADATA_BUSY
    assert response.json()["error"]["code"] == "metadata_removal_in_progress"
    gate.release()
    assert removing.result().status_code == 200
    _assert_nothing_deleted(client, db_path, media_dir, ids, posts=0)


@pytest.mark.parametrize("order", ["publishing-first", "removing-first"])
def test_publishing_wins_over_remove_metadata_in_the_selection(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    order: str,
) -> None:
    """A has a publishing post, B is having its metadata removed; both selected."""
    [a] = import_media(client, project["id"], 1)
    b = int(import_one(client, project["id"], "d.png", dirty_png())["content"]["id"])
    _publishing(client, db_path, project, a, fake_clock.now())
    ids = [a, b] if order == "publishing-first" else [b, a]
    token = preview(client, project["id"], ids)["confirmation"]
    gate, removing = _hold_remove_metadata(client, monkeypatch, b)

    body = preview(client, project["id"], ids)
    assert body["blocker"] == {"code": "post_in_progress", "message": IN_PROGRESS}
    response = delete(client, project["id"], ids, token)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "post_in_progress"
    assert response.json()["error"]["message"] == IN_PROGRESS
    assert _guard(client)._deleting == set()
    gate.release()
    assert removing.result().status_code == 200
    _assert_nothing_deleted(client, db_path, media_dir, ids, posts=1)


def test_remove_metadata_outside_the_selection_does_not_matter(
    client: TestClient,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = int(
        import_one(client, project["id"], "c.png", dirty_png())["content"]["id"]
    )
    outside_files = files_of(db_path, media_dir, outside)
    ids = import_media(client, project["id"], 2)
    gate, removing = _hold_remove_metadata(client, monkeypatch, outside)

    body = preview(client, project["id"], ids)
    assert body["blocker"] is None
    assert delete(client, project["id"], ids, body["confirmation"]).status_code == 204

    assert count(db_path, "contents") == 1
    assert all(path.is_file() for path in outside_files)
    gate.release()
    response = removing.result()
    assert response.status_code == 200
    assert response.json()["metadata_status"] == "sanitized"


def test_preview_never_holds_the_media(
    client: TestClient,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty = int(
        import_one(client, project["id"], "d.png", dirty_png())["content"]["id"]
    )
    ids = [dirty, *import_media(client, project["id"], 1)]
    guard = _guard(client)
    gate, removing = _hold_remove_metadata(client, monkeypatch, dirty)

    def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the preview must not hold any media")

    with monkeypatch.context() as patch:
        patch.setattr(guard, "deleting", never)
        body = preview(client, project["id"], ids)

    assert body["blocker"]["code"] == "metadata_removal_in_progress"
    assert guard._deleting == set()
    gate.release()
    assert removing.result().status_code == 200
    # Free again, the preview has no blocker.
    assert preview(client, project["id"], ids)["blocker"] is None


def test_bulk_delete_holds_every_selected_media_from_remove_metadata(
    client: TestClient, db_path: Path, media_dir: Path, project: dict[str, Any]
) -> None:
    dirty = int(
        import_one(client, project["id"], "d.png", dirty_png())["content"]["id"]
    )
    ids = [*import_media(client, project["id"], 1), dirty]
    files = [path for id_ in ids for path in files_of(db_path, media_dir, id_)]
    token = preview(client, project["id"], ids)["confirmation"]
    factory = _app(client).state.session_factory

    with pause_before_commit(factory, _gone(ids)) as commit:
        deleting = Background(lambda: delete(client, project["id"], ids, token))
        commit.wait_reached()  # guards held, rows deleted, not committed
        response = client.post(f"/api/contents/{dirty}/remove-metadata")
        commit.release()
        assert deleting.result().status_code == 204

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "content_deleting"
    assert not any(path.exists() for path in files)
    assert list(media_dir.glob("projects/*/*.clean.*")) == []
    assert _guard(client)._deleting == set()


# --- Publication start vs Bulk Delete -----------------------------------------------


def _due_selection(
    client: TestClient, db_path: Path, setup: dict[str, Any], clock: FakeClock
) -> list[int]:
    """The due media (armed post + draft) and a second media with a draft."""
    project = setup["project"]
    [second] = import_media(client, project["id"], 1)
    account = create_account(client, project["id"], "youtube", "second")
    media_post(db_path, account, second, clock.now())
    return [setup["content"]["id"], second]


def test_bulk_delete_first_then_scheduler_claim(
    client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    due: dict[str, Any],  # noqa: F811
) -> None:
    ids = _due_selection(client, db_path, due, fake_clock)
    files = [path for id_ in ids for path in files_of(db_path, media_dir, id_)]
    project_id = due["project"]["id"]
    token = preview(client, project_id, ids)["confirmation"]
    factory = _app(client).state.session_factory

    prepare = pause_in_prepare(fake_publisher)
    tick = Background(lambda: run_tick(client))
    prepare.wait_reached()
    with (
        pause_before_commit(factory, _gone(ids)) as commit,
        statement_reached(_engine(client), "UPDATE publications SET status") as claim,
    ):
        deleting = Background(lambda: delete(client, project_id, ids, token))
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
    assert count(db_path, "youtube_publication_options") == 0
    assert not any(path.exists() for path in files)


@pytest.mark.parametrize("entrypoint", ["scheduler", "publish-now"])
def test_claim_first_blocks_the_whole_bulk_delete(
    client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    due: dict[str, Any],  # noqa: F811
    entrypoint: str,
) -> None:
    """The claim of the due post commits first; its upload stays blocked so the
    attempt is still running when the bulk delete reads."""
    ids = _due_selection(client, db_path, due, fake_clock)
    project_id = due["project"]["id"]
    post_id = due["publication"]["id"]
    token = preview(client, project_id, ids)["confirmation"]

    def start() -> Any:
        if entrypoint == "scheduler":
            return run_tick(client)
        return client.post(f"/api/publications/{post_id}/publish", json={})

    fake_publisher.upload_gate = threading.Event()
    factory = _app(client).state.session_factory
    with pause_before_commit(factory, is_claim) as claim:
        starting = Background(start)
        claim.wait_reached()
        deleting = Background(lambda: delete(client, project_id, ids, token))
        claim.release()
        started = starting.result()
        response = deleting.result()

    if entrypoint == "scheduler":
        assert started.started == [post_id]
    else:
        assert started.status_code == 202
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "post_in_progress"
    assert count(db_path, "contents") == 2
    assert count(db_path, "publications") == 3
    assert [row["status"] for row in attempt_rows(db_path)] == ["running"]
    for id_ in ids:
        assert all(path.is_file() for path in files_of(db_path, media_dir, id_))
    assert pending_files(db_path) == set()
    assert _guard(client)._deleting == set()

    fake_publisher.upload_gate.set()
    wait_idle(client)
    assert count(db_path, "publications", "status = 'published'") == 1


# --- Changed scope and rollback (US3) -----------------------------------------------


@pytest.mark.parametrize(
    "change", ["post-added", "post-deleted", "status-changed", "needs-review"]
)
def test_a_change_after_the_preview_rejects_everything(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
    change: str,
) -> None:
    ids = import_media(client, project["id"], 2)
    now = fake_clock.now()
    failed = media_post(
        db_path,
        _account(client, project, "a"),
        ids[0],
        now,
        status="failed",
        attempt="determined",
    )
    draft = media_post(db_path, _account(client, project, "b"), ids[1], now)
    token = preview(client, project["id"], ids)["confirmation"]
    posts = 2
    if change == "post-added":
        media_post(db_path, _account(client, project, "c"), ids[1], now)
        posts = 3
    elif change == "post-deleted":
        run_sql(db_path, "DELETE FROM publications WHERE id = ?", draft)
        posts = 1
    elif change == "status-changed":
        run_sql(
            db_path, "UPDATE publications SET status = 'cancelled' WHERE id = ?", draft
        )
    else:
        readmodels.failed_attempt(db_path, failed, now, uncertain=True)

    response = delete(client, project["id"], ids, token)

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "deletion_changed",
        "message": CHANGED,
        "fields": [],
    }
    _assert_nothing_deleted(client, db_path, media_dir, ids, posts=posts)
    fresh = preview(client, project["id"], ids)["confirmation"]
    assert fresh != token
    assert delete(client, project["id"], ids, fresh).status_code == 204


def test_a_media_deleted_before_the_preview_is_a_404(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    ids = import_media(client, project["id"], 2)
    response = delete_one(client, ids[0], preview_one(client, ids[0])["confirmation"])
    assert response.status_code == 204

    response = preview_response(client, project["id"], ids)

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": MISSING,
        "fields": [],
    }
    assert count(db_path, "contents") == 1


def test_a_media_deleted_after_the_preview_rejects_the_rest(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    ids = import_media(client, project["id"], 3)
    media_post(db_path, _account(client, project, "a"), ids[2], fake_clock.now())
    token = preview(client, project["id"], ids)["confirmation"]
    response = delete_one(client, ids[0], preview_one(client, ids[0])["confirmation"])
    assert response.status_code == 204

    response = delete(client, project["id"], ids, token)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "deletion_changed"
    _assert_nothing_deleted(client, db_path, media_dir, ids[1:], posts=1)


def test_an_overlapping_delete_in_progress_rejects_the_second(
    client: TestClient, db_path: Path, project: dict[str, Any]
) -> None:
    a, b, c = import_media(client, project["id"], 3)
    first = preview(client, project["id"], [a, b])["confirmation"]
    second = preview(client, project["id"], [b, c])["confirmation"]
    single = preview_one(client, a)["confirmation"]
    factory = _app(client).state.session_factory

    with pause_before_commit(factory, _gone([a, b])) as commit:
        deleting = Background(lambda: delete(client, project["id"], [a, b], first))
        commit.wait_reached()
        overlapping = delete(client, project["id"], [b, c], second)
        individual = delete_one(client, a, single)
        commit.release()
        assert deleting.result().status_code == 204

    for response in (overlapping, individual):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "deletion_changed"
    assert count(db_path, "contents", "id = ?", c) == 1
    assert _guard(client)._deleting == set()


def test_failure_mid_delete_changes_nothing(
    client: TestClient,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
    project: dict[str, Any],
) -> None:
    ids = [_sanitized_media(client, project), *import_media(client, project["id"], 1)]
    for index, id_ in enumerate(ids):
        media_post(
            db_path, _account(client, project, f"a{index}"), id_, fake_clock.now()
        )
    token = preview(client, project["id"], ids)["confirmation"]
    engine = _engine(client)

    def fail(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        # Posts deleted and files queued: the media rows themselves fail.
        if statement.startswith("DELETE FROM contents"):
            raise RuntimeError("disk I/O error")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = delete(
            TestClient(_app(client), raise_server_exceptions=False),
            project["id"],
            ids,
            token,
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    _assert_nothing_deleted(client, db_path, media_dir, ids, posts=2)
    assert delete(client, project["id"], ids, token).status_code == 204
