"""Delete vs publication start (Feature 021 T017, research §5).

SQLite has a single writer: the delete checks and deletes inside `BEGIN IMMEDIATE`,
the claim is one conditional UPDATE. Every order is forced with barriers (never
`sleep`) and exactly one side wins:

- the delete commits first → the claim finds no row: `not_claimed` / 404, no attempt;
- the claim commits first → the delete sees the running attempt: `409
  post_in_progress`, nothing deleted.
"""

import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models import Publication
from app.scheduler import TickReport
from tests.barriers import (
    Background,
    is_claim,
    pause_before_commit,
    pause_in_prepare,
    statement_reached,
)
from tests.conftest import (
    attempt_rows,
    in_minutes,
    make_scheduler_app,
    run_tick,
    scheduled_publication,
    stop,
    use_fake_publisher,
    wait_idle,
)
from tests.fakes import FakeClock, FakePublisher
from tests.test_delete_post import count, delete, preview

pytestmark = pytest.mark.usefixtures("fake_scheduler_client")


def _app(client: TestClient) -> FastAPI:
    app = client.app
    assert isinstance(app, FastAPI)
    return app


def _engine(client: TestClient) -> Engine:
    engine: Engine = _app(client).state.session_factory.kw["bind"]
    return engine


@pytest.fixture
def client(fake_scheduler_client: TestClient) -> TestClient:
    return fake_scheduler_client


@pytest.fixture
def due(client: TestClient, fake_clock: FakeClock, db_path: Path) -> int:
    """An armed automatic post whose time has come."""
    at = in_minutes(fake_clock, 5)
    post_id: int = scheduled_publication(client, db_path, at)["publication"]["id"]
    fake_clock.set(at)
    return post_id


@pytest.fixture
def manual(client: TestClient, fake_clock: FakeClock, db_path: Path) -> int:
    """A scheduled manual post, ready for "Publish now"."""
    at = in_minutes(fake_clock, 60)
    post_id: int = scheduled_publication(client, db_path, at, armed=False)[
        "publication"
    ]["id"]
    return post_id


def _publish_now(client: TestClient, post_id: int) -> Any:
    return client.post(f"/api/publications/{post_id}/publish", json={})


def _assert_deleted_and_never_started(db_path: Path, publisher: FakePublisher) -> None:
    assert count(db_path, "publications") == 0
    assert attempt_rows(db_path) == []
    assert publisher.upload_calls == []


# --- (a) Delete commits first ---------------------------------------------------------


def test_delete_first_then_scheduler_claim(
    client: TestClient, fake_publisher: FakePublisher, db_path: Path, due: int
) -> None:
    """The post exists during the preflight and is deleted before the claim."""
    token = preview(client, due)["confirmation"]
    gate = pause_in_prepare(fake_publisher)
    tick = Background(lambda: run_tick(client))
    gate.wait_reached()

    assert delete(client, due, token).status_code == 204
    gate.release()
    report: TickReport = tick.result()

    assert report.started == [] and report.failed == []  # not_claimed, silent
    _assert_deleted_and_never_started(db_path, fake_publisher)


def test_delete_holding_the_lock_then_scheduler_claim(
    client: TestClient, fake_publisher: FakePublisher, db_path: Path, due: int
) -> None:
    """The claim's UPDATE waits for the delete's COMMIT and then matches no row."""
    token = preview(client, due)["confirmation"]
    factory = _app(client).state.session_factory

    def deleted_in(session: Session) -> bool:
        query = (
            select(func.count()).select_from(Publication).where(Publication.id == due)
        )
        return session.scalar(query) == 0

    prepare = pause_in_prepare(fake_publisher)
    tick = Background(lambda: run_tick(client))
    prepare.wait_reached()
    with (
        pause_before_commit(factory, deleted_in) as delete_commit,
        statement_reached(_engine(client), "UPDATE publications SET status") as claim,
    ):
        deleting = Background(lambda: delete(client, due, token))
        delete_commit.wait_reached()  # deleted, writer lock held, not committed
        prepare.release()
        assert claim.wait(10)  # the claim now waits for the writer lock
        delete_commit.release()
        assert deleting.result().status_code == 204
        report: TickReport = tick.result()

    assert report.started == [] and report.failed == []
    _assert_deleted_and_never_started(db_path, fake_publisher)


def test_delete_first_then_publish_now(
    client: TestClient, fake_publisher: FakePublisher, db_path: Path, manual: int
) -> None:
    token = preview(client, manual)["confirmation"]
    gate = pause_in_prepare(fake_publisher)
    publishing = Background(lambda: _publish_now(client, manual))
    gate.wait_reached()

    assert delete(client, manual, token).status_code == 204
    gate.release()
    response = publishing.result()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    _assert_deleted_and_never_started(db_path, fake_publisher)


# --- (b) The claim commits first ------------------------------------------------------


def _claim_first(
    client: TestClient, fake_publisher: FakePublisher, post_id: int, start: Any
) -> tuple[Any, Any]:
    """Pause the claim with its UPDATE done (writer lock held) and the attempt
    pending; start the delete, which waits for the lock; then let the claim commit.
    The upload stays blocked so the attempt is still running when the delete reads."""
    token = preview(client, post_id)["confirmation"]
    fake_publisher.upload_gate = threading.Event()
    factory = _app(client).state.session_factory
    with (
        pause_before_commit(factory, is_claim) as claim,
        statement_reached(_engine(client), "BEGIN IMMEDIATE") as delete_waiting,
    ):
        starting = Background(start)
        claim.wait_reached()
        deleting = Background(lambda: delete(client, post_id, token))
        assert delete_waiting.wait(10)
        claim.release()
        started = starting.result()
        deleted = deleting.result()
    return started, deleted


def _assert_blocked(response: Any) -> None:
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "post_in_progress"


def test_scheduler_claim_first_then_delete(
    client: TestClient, fake_publisher: FakePublisher, db_path: Path, due: int
) -> None:
    report, response = _claim_first(
        client, fake_publisher, due, lambda: run_tick(client)
    )

    assert report.started == [due]
    _assert_blocked(response)
    assert count(db_path, "publications", "status = 'publishing'") == 1
    assert [row["status"] for row in attempt_rows(db_path)] == ["running"]

    assert fake_publisher.upload_gate is not None
    fake_publisher.upload_gate.set()
    wait_idle(client)
    assert count(db_path, "publications", "status = 'published'") == 1
    assert len(attempt_rows(db_path)) == 1


def test_publish_now_claim_first_then_delete(
    client: TestClient, fake_publisher: FakePublisher, db_path: Path, manual: int
) -> None:
    started, response = _claim_first(
        client, fake_publisher, manual, lambda: _publish_now(client, manual)
    )

    assert started.status_code == 202
    _assert_blocked(response)
    assert count(db_path, "publications", "status = 'publishing'") == 1
    assert [row["status"] for row in attempt_rows(db_path)] == ["running"]

    assert fake_publisher.upload_gate is not None
    fake_publisher.upload_gate.set()
    wait_idle(client)
    assert count(db_path, "publications", "status = 'published'") == 1


# --- (e) Restart ---------------------------------------------------------------------


def test_deleted_scheduled_post_never_runs_after_a_restart(
    client: TestClient,
    fake_publisher: FakePublisher,
    fake_clock: FakeClock,
    db_path: Path,
    media_dir: Path,
) -> None:
    at = in_minutes(fake_clock, 5)
    post_id = scheduled_publication(client, db_path, at)["publication"]["id"]
    assert (
        delete(client, post_id, preview(client, post_id)["confirmation"]).status_code
        == 204
    )
    stop(client)

    # A new server: start-up recovery runs, then the clock passes the post's time.
    app = make_scheduler_app(db_path, media_dir, fake_clock)
    with TestClient(app) as restarted:
        use_fake_publisher(restarted, fake_publisher)
        fake_clock.set(at + timedelta(minutes=1))
        report = run_tick(restarted)
        assert restarted.get(f"/api/publications/{post_id}").status_code == 404

    assert report.started == [] and report.failed == []
    assert fake_publisher.prepare_calls == []
    _assert_deleted_and_never_started(db_path, fake_publisher)
