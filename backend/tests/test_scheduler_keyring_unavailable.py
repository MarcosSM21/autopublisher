"""Secure storage unavailable during the automatic window (Feature 020, research §1).

The behaviour lives in the shared path: `prepare()` runs before the claim, the
scheduler records the failure and keeps the Post scheduled, and once the window ends
it is Missed (`overdue`) and never published late. Two representative cases: the
real YouTube integration and an unwrapped exception from a fake publisher.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.credential_store import CredentialStoreUnavailable
from tests.conftest import (
    attempt_rows,
    get_publication,
    in_minutes,
    make_scheduler_app,
    run_tick,
    scheduled_publication,
    use_fake_publisher,
)
from tests.fakes import FakeClock, FakeGoogle, FakePublisher, InMemoryCredentialStore

# Arranges a publication whose storage fails; returns its id and a counter of
# anything really sent to the platform.
Arrange = Callable[[TestClient, Path, FakeClock], tuple[int, Callable[[], int]]]


def _youtube_keyring_down(
    fake_google: FakeGoogle, store: InMemoryCredentialStore
) -> Arrange:
    """Really connected to the YouTube simulator; then the keyring goes away, so
    `list_channels` maps it to `AppError(503, "credential_store_unavailable")`."""

    def arrange(
        client: TestClient, db_path: Path, clock: FakeClock
    ) -> tuple[int, Callable[[], int]]:
        at = in_minutes(clock, 5)
        setup = scheduled_publication(client, db_path, at, fake_google=fake_google)
        store.unavailable = True
        clock.set(at + timedelta(seconds=30))
        return setup["publication"]["id"], lambda: len(fake_google.session_starts)

    return arrange


def _fake_publisher_raises(publisher: FakePublisher) -> Arrange:
    """`prepare()` raises the storage exception itself, without an AppError."""

    def arrange(
        client: TestClient, db_path: Path, clock: FakeClock
    ) -> tuple[int, Callable[[], int]]:
        use_fake_publisher(client, publisher)
        publisher.prepare_error[None] = CredentialStoreUnavailable()
        at = in_minutes(clock, 5)
        setup = scheduled_publication(client, db_path, at)
        clock.set(at + timedelta(seconds=30))
        return setup["publication"]["id"], lambda: len(publisher.upload_calls)

    return arrange


@pytest.mark.parametrize(
    ("case", "code"),
    [("youtube", "credential_store_unavailable"), ("fake_publisher", "internal_error")],
)
def test_unavailable_storage_fails_visibly_then_is_missed_never_late(
    db_path: Path,
    media_dir: Path,
    oauth_client_file: Path,
    case: str,
    code: str,
) -> None:
    clock = FakeClock()
    fake_google = FakeGoogle()
    store = InMemoryCredentialStore()
    arrange = (
        _youtube_keyring_down(fake_google, store)
        if case == "youtube"
        else _fake_publisher_raises(FakePublisher())
    )
    app = make_scheduler_app(
        db_path, media_dir, clock, credential_store=store, fake_google=fake_google
    )
    with TestClient(app) as client:
        publication_id, sent = arrange(client, db_path, clock)

        # Inside the window: a visible failure, still scheduled, no attempt.
        report = run_tick(client)
        assert report.started == []
        assert report.failed == [publication_id]
        publication = get_publication(client, publication_id)
        assert publication["status"] == "scheduled"
        assert publication["auto_publish_state"] != "overdue"
        assert publication["auto_publish_error"]["code"] == code
        assert publication["auto_publish_error"]["message"]
        assert attempt_rows(db_path) == []

        # After the 10-minute window: Missed; later ticks never start it.
        start = clock.now()
        for minutes in (11, 20, 60):
            clock.set(start + timedelta(minutes=minutes))
            assert publication_id not in run_tick(client).started

        publication = get_publication(client, publication_id)
        assert publication["status"] == "scheduled"
        assert publication["auto_publish_state"] == "overdue"
        assert publication["attempt_count"] == 0
        assert attempt_rows(db_path) == []
        assert sent() == 0
