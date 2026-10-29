"""Analytics scenes (Feature 027), written straight to SQLite like `readmodels`, plus
YouTube and Instagram adapters wired to `FakeGoogle`/`FakeMeta` and in-memory
credential stores."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2 as httpx
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.adapters.base import MetricsAdapter
from app.analytics.adapters.instagram import InstagramMetricsAdapter
from app.analytics.adapters.youtube import YouTubeMetricsAdapter
from app.db import create_db_engine, run_migrations
from app.instagram_gateway import InstagramGateway, InstagramToken
from app.models import Platform
from app.youtube_gateway import GoogleGateway, TokenSet
from tests import readmodels
from tests.fakes import (
    ALL_SCOPES,
    FAKE_ACCESS_TOKEN,
    FAKE_IG_LONG_TOKEN,
    FAKE_REFRESH_TOKEN,
    IG_ALL_PERMISSIONS,
    FakeGoogle,
    FakeMeta,
    InMemoryCredentialStore,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
# `submitted` key of the remote identity, and the identity `readmodels.connect` gives.
IDENTITY_KEYS = {
    "youtube": ("channel_id", "UC-SENTINEL-{}"),
    "instagram": ("instagram_user_id", "IG-SENTINEL-{}"),
    "threads": ("threads_user_id", "TH-SENTINEL-{}"),
}
CONNECTED = "connected"


def project(db_path: Path, name: str = "Cyber") -> int:
    return readmodels.insert(
        db_path,
        "projects",
        name=name,
        name_key=name.lower(),
        is_active=1,
        created_at=NOW,
        updated_at=NOW,
    )


def account(
    db_path: Path,
    project_id: int,
    platform: str,
    handle: str = "cyber",
    *,
    connection: str | None = "connected",
) -> dict[str, Any]:
    account_id = readmodels.insert(
        db_path,
        "accounts",
        project_id=project_id,
        platform=platform,
        handle=handle,
        handle_key=handle,
        is_active=1,
        created_at=NOW,
        updated_at=NOW,
    )
    row: dict[str, Any] = {
        "id": account_id,
        "project_id": project_id,
        "platform": platform,
    }
    if connection is not None:
        readmodels.connect(db_path, row, NOW, status=connection)
    return row


def attempt(
    db_path: Path,
    post_id: int,
    platform: str,
    *,
    status: str = "succeeded",
    external_id: str | None = None,
    details: dict[str, Any] | None = None,
    warnings: list[dict[str, str]] | None = None,
    started_at: datetime = NOW,
    submitted: dict[str, Any] | None = None,
) -> int:
    return readmodels.insert(
        db_path,
        "publication_attempts",
        publication_id=post_id,
        platform=platform,
        status=status,
        stage="done",
        started_at=started_at,
        finished_at=started_at,
        bytes_sent=0,
        total_bytes=0,
        outcome_determined=1,
        external_id=external_id,
        error_code="rejected" if status == "failed" else None,
        error_message="Rejected." if status == "failed" else None,
        submitted=json.dumps(submitted or {}),
        details=json.dumps(details or {}),
        warnings=json.dumps(warnings or []),
    )


def published(
    db_path: Path,
    owner: dict[str, Any],
    external_id: str | None = "VIDEO-1",
    *,
    published_at: datetime = NOW,
    identity: str | None = CONNECTED,
    **attempt_options: Any,
) -> int:
    """A published post whose succeeded attempt has `external_id`, published by
    the remote identity connected now (`CONNECTED`), another one, or none known."""
    post_id = readmodels.post(db_path, owner, published_at, status="published")
    submitted: dict[str, Any] = {}
    if owner["platform"] in IDENTITY_KEYS and identity is not None:
        key, connected = IDENTITY_KEYS[owner["platform"]]
        submitted[key] = (
            connected.format(owner["id"]) if identity == CONNECTED else identity
        )
    attempt(
        db_path,
        post_id,
        owner["platform"],
        external_id=external_id,
        started_at=published_at,
        submitted=submitted,
        **attempt_options,
    )
    return post_id


def rows(db_path: Path, sql: str, *params: Any) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, params)]


def state(db_path: Path, post_id: int) -> dict[str, Any] | None:
    found = rows(
        db_path,
        "SELECT * FROM publication_metric_states WHERE publication_id = ?",
        post_id,
    )
    return found[0] if found else None


def values(db_path: Path, post_id: int) -> list[dict[str, dict[str, Any]]]:
    """Every snapshot of the post, oldest first, with its values by name."""
    snapshots = rows(
        db_path,
        "SELECT * FROM metric_snapshots WHERE publication_id = ? ORDER BY id",
        post_id,
    )
    return [
        {
            "snapshot": snapshot,
            "values": {
                row["metric_name"]: row
                for row in rows(
                    db_path,
                    "SELECT * FROM metric_values WHERE snapshot_id = ?",
                    snapshot["id"],
                )
            },
        }
        for snapshot in snapshots
    ]


def ts(value: datetime) -> str:
    return readmodels.ts(value)


@dataclass
class YouTubeWorld:
    """A migrated database, FakeGoogle and a YouTube adapter using them."""

    db_path: Path
    session_factory: sessionmaker[Session]
    google: FakeGoogle
    store: InMemoryCredentialStore
    adapter: YouTubeMetricsAdapter
    meta: FakeMeta
    ig_store: InMemoryCredentialStore
    instagram: InstagramMetricsAdapter

    @property
    def adapters(self) -> dict[Platform, MetricsAdapter]:
        return {Platform.YOUTUBE: self.adapter, Platform.INSTAGRAM: self.instagram}

    def store_tokens(
        self, owner: dict[str, Any], expires_at: datetime | None = None
    ) -> None:
        self.store.secrets[f"secret-ref-{owner['id']}"] = TokenSet(
            FAKE_ACCESS_TOKEN,
            FAKE_REFRESH_TOKEN,
            expires_at or datetime(2999, 1, 1, tzinfo=UTC),
            frozenset(ALL_SCOPES.split()),
        ).to_json()

    def youtube_account(self, handle: str = "cyber") -> dict[str, Any]:
        owner = account(self.db_path, project(self.db_path, handle), "youtube", handle)
        self.store_tokens(owner)
        return owner

    def instagram_account(self, handle: str = "cyber.ig") -> dict[str, Any]:
        owner = account(
            self.db_path, project(self.db_path, handle), "instagram", handle
        )
        # Issued an hour ago: valid and not renewable yet, so no refresh call.
        self.ig_store.secrets[f"secret-ref-{owner['id']}"] = InstagramToken(
            FAKE_IG_LONG_TOKEN,
            NOW - timedelta(hours=1),
            NOW + timedelta(days=50),
            frozenset(IG_ALL_PERMISSIONS.split(",")),
        ).to_json()
        return owner


@contextmanager
def youtube_world(tmp_path: Path) -> Iterator[YouTubeWorld]:
    db_path = tmp_path / "analytics.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    google, meta = FakeGoogle(), FakeMeta()
    store, ig_store = InMemoryCredentialStore(), InMemoryCredentialStore()
    with (
        httpx.Client(transport=google.transport()) as client,
        httpx.Client(transport=meta.transport()) as meta_client,
    ):
        yield YouTubeWorld(
            db_path,
            sessionmaker(engine, expire_on_commit=False),
            google,
            store,
            YouTubeMetricsAdapter(GoogleGateway(client), store, lambda: NOW),
            meta,
            ig_store,
            InstagramMetricsAdapter(
                InstagramGateway(meta_client, lambda: NOW), ig_store, lambda: NOW
            ),
        )
    engine.dispose()


def later(minutes: float) -> datetime:
    return NOW + timedelta(minutes=minutes)
