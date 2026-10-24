"""`ContentFileGuard.deleting` (Feature 021, research §6): a deletion and Remove
metadata of the same media exclude each other, all-or-nothing and without waiting.

Deletions are simulated with the primitive itself (the deletion service comes
later); barriers are `threading.Event`s, never sleeps."""

import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import asset_library
from app.content_files import ContentFileGuard
from app.db import write_transaction
from app.errors import ConflictError
from tests.conftest import create_project, import_one
from tests.test_image_metadata import dirty_png


def _app(client: TestClient) -> Any:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


@pytest.fixture
def content_id(client: TestClient) -> int:
    project = create_project(client, "L4i4")
    return int(
        import_one(client, project["id"], "comfy.png", dirty_png())["content"]["id"]
    )


def _remove(client: TestClient, content_id: int) -> Any:
    return client.post(f"/api/contents/{content_id}/remove-metadata")


def test_remove_metadata_is_refused_while_a_deletion_holds_the_media(
    client: TestClient, content_id: int, media_dir: Path
) -> None:
    app = _app(client)
    guard: ContentFileGuard = app.state.content_file_guard

    with (
        guard.deleting({content_id}),
        write_transaction(app.state.session_factory) as session,
    ):
        # Inside the deletion's transaction (writer lock held).
        session.execute(text("SELECT id FROM contents"))
        response = _remove(client, content_id)

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "content_deleting"
    assert error["message"] == "This media is being deleted."
    assert list(media_dir.glob("projects/*/*.clean.*")) == []
    # Released: Remove metadata works again.
    assert _remove(client, content_id).status_code == 200


def test_a_deletion_is_refused_while_metadata_is_being_removed(
    client: TestClient, content_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard: ContentFileGuard = _app(client).state.content_file_guard
    sanitizing = threading.Event()
    release = threading.Event()
    original = asset_library._sanitize_to
    responses: list[Any] = []

    def held_sanitize(*args: Any) -> None:
        sanitizing.set()
        assert release.wait(timeout=10)
        original(*args)

    monkeypatch.setattr(asset_library, "_sanitize_to", held_sanitize)
    thread = threading.Thread(
        target=lambda: responses.append(_remove(client, content_id))
    )
    thread.start()
    try:
        assert sanitizing.wait(timeout=10)
        with pytest.raises(ConflictError) as refused, guard.deleting({content_id}):
            pytest.fail("never reached")  # pragma: no cover
    finally:
        release.set()
        thread.join()

    assert refused.value.code == "metadata_removal_in_progress"
    assert refused.value.message == (
        "Metadata is being removed from this media. Try again when it finishes."
    )
    assert responses[0].status_code == 200, responses[0].text
    # Nothing stays registered: a deletion can start now.
    with guard.deleting({content_id}):
        pass


def test_acquisition_is_all_or_nothing() -> None:
    guard = ContentFileGuard()
    project_message = (
        "Metadata is being removed from a media item in this project. "
        "Try again when it finishes."
    )

    with guard.sanitizing(2, lambda: None):
        with (
            pytest.raises(ConflictError) as refused,
            guard.deleting([3, 1, 2], blocked_message=project_message),
        ):
            pytest.fail("never reached")  # pragma: no cover
        assert refused.value.code == "metadata_removal_in_progress"
        assert refused.value.message == project_message
        # 1 and 3 were not retained.
        with guard.sanitizing(1, lambda: None), guard.sanitizing(3, lambda: None):
            pass


def test_a_second_deletion_of_the_same_media_is_a_changed_scope() -> None:
    guard = ContentFileGuard()

    with guard.deleting({1, 2}):
        with pytest.raises(ConflictError) as refused, guard.deleting({2, 3}):
            pytest.fail("never reached")  # pragma: no cover
        assert refused.value.code == "deletion_changed"
        # The refused one registered nothing: 3 is free.
        with guard.sanitizing(3, lambda: None):
            pass
        with pytest.raises(ConflictError) as blocked, guard.sanitizing(1, lambda: None):
            pytest.fail("never reached")  # pragma: no cover
        assert blocked.value.code == "content_deleting"


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("forced"),
        ConflictError("deletion_changed", "changed"),
        ConflictError("publication_in_progress", "post in progress"),
    ],
)
def test_every_outcome_releases_every_id(failure: Exception) -> None:
    guard = ContentFileGuard()

    with pytest.raises(type(failure)), guard.deleting({1, 2, 3}):
        raise failure

    for content_id in (1, 2, 3):
        with guard.sanitizing(content_id, lambda: None):
            pass
    with guard.deleting({1, 2, 3}):
        pass


def test_a_claim_waiting_for_sqlite_never_deadlocks_with_a_deletion(
    client: TestClient, content_id: int
) -> None:
    """`claiming` holds the guard's lock while it waits for SQLite; the deletion
    holds the writer lock and only needs the guard's lock to release its ids."""
    app = _app(client)
    guard: ContentFileGuard = app.state.content_file_guard
    in_transaction = threading.Event()
    claim_waiting = threading.Event()
    finished: list[str] = []

    def deletion() -> None:
        with guard.deleting({content_id}):
            with write_transaction(app.state.session_factory) as session:
                session.execute(
                    text("UPDATE contents SET title = 'deleting' WHERE id = :id"),
                    {"id": content_id},
                )
                in_transaction.set()
                assert claim_waiting.wait(timeout=10)
            finished.append("deletion committed")
        finished.append("deletion released")

    thread = threading.Thread(target=deletion)
    thread.start()
    assert in_transaction.wait(timeout=10)
    with guard.claiming(content_id):
        claim_waiting.set()
        # Waits for the deletion's COMMIT (SQLite's busy timeout), never forever.
        with app.state.session_factory() as session:
            session.execute(
                text("UPDATE contents SET title = title || ' claimed' WHERE id = :id"),
                {"id": content_id},
            )
            session.commit()
        finished.append("claim committed")
    thread.join(timeout=10)

    assert not thread.is_alive()
    # The deletion only releases its ids once the claim let go of the lock.
    assert sorted(finished[:2]) == ["claim committed", "deletion committed"]
    assert finished[2] == "deletion released"
    with app.state.session_factory() as session:
        title = session.execute(
            text("SELECT title FROM contents WHERE id = :id"), {"id": content_id}
        ).scalar_one()
    assert title == "deleting claimed"
