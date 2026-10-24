"""Orphaned TikTok credentials (US5): secrets whose reference was replaced are
registered and deleted by an idempotent, opportunistic cleanup. Since Feature 021
they live in the generic `pending_credential_deletions` queue."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.credential_store import CredentialStoreProbe
from app.tiktok_connections import cleanup_pending_credentials
from tests.conftest import (
    connect_tiktok,
    create_tiktok_account,
    make_tiktok_app,
    run_sql,
    start_tiktok_authorization,
    tiktok_callback,
    tiktok_rows,
    tiktok_test_client,
)
from tests.fakes import FakeClock, FakeTikTok, InMemoryCredentialStore

ORPHAN_REF = "0f5e3c1b2a4d4e6f8a9b0c1d2e3f4a5b"
ORPHAN_SECRET = "orphaned-secret-value"


def _orphans(db_path: Path) -> list[dict[str, Any]]:
    return tiktok_rows(db_path, "pending_credential_deletions")


def _register(db_path: Path, ref: str = ORPHAN_REF) -> None:
    run_sql(
        db_path,
        "INSERT INTO pending_credential_deletions (credential_ref, platform, "
        "account_id, created_at) VALUES (?, 'tiktok', NULL, '2026-10-14 00:00:00')",
        ref,
    )


def _cleanup(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    cleanup_pending_credentials(
        app.state.session_factory, app.state.tiktok_credential_store
    )


@pytest.fixture
def orphan(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
) -> str:
    tiktok_credential_store.secrets[ORPHAN_REF] = ORPHAN_SECRET
    _register(db_path)
    return ORPHAN_REF


def test_cleanup_deletes_orphans_idempotently(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    orphan: str,
) -> None:
    _cleanup(tiktok_client)

    assert orphan not in tiktok_credential_store.secrets
    assert _orphans(db_path) == []
    _cleanup(tiktok_client)
    assert _orphans(db_path) == []


def test_cleanup_tolerates_an_already_missing_secret(
    tiktok_client: TestClient, db_path: Path
) -> None:
    _register(db_path)

    _cleanup(tiktok_client)

    assert _orphans(db_path) == []


def test_cleanup_never_deletes_a_reference_in_use(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    [row] = tiktok_rows(db_path)
    _register(db_path, row["credential_ref"])

    _cleanup(tiktok_client)

    assert row["credential_ref"] in tiktok_credential_store.secrets
    assert _orphans(db_path) == []


def test_cleanup_keeps_the_row_when_the_store_is_unavailable(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    db_path: Path,
    orphan: str,
) -> None:
    tiktok_credential_store.unavailable = True

    _cleanup(tiktok_client)

    tiktok_credential_store.unavailable = False
    assert tiktok_credential_store.secrets[orphan] == ORPHAN_SECRET
    assert [row["credential_ref"] for row in _orphans(db_path)] == [orphan]


def test_cleanup_runs_at_startup(
    db_path: Path,
    media_dir: Path,
    tiktok_app_file: Path,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
) -> None:
    store = InMemoryCredentialStore()
    with tiktok_test_client(
        make_tiktok_app(db_path, media_dir, store, fake_tiktok, fake_clock)
    ):
        pass
    store.secrets[ORPHAN_REF] = ORPHAN_SECRET
    _register(db_path)
    # Only with the store seen available (Feature 021); in the background.
    available = CredentialStoreProbe(check=lambda: "available")

    app = make_tiktok_app(db_path, media_dir, store, fake_tiktok, fake_clock, available)
    with tiktok_test_client(app):
        app.state.credential_cleanup.join(timeout=10)
        assert store.secrets == {}
        assert _orphans(db_path) == []


def test_cleanup_runs_when_completing_a_callback(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    _, state, _ = start_tiktok_authorization(tiktok_client, account["id"], fake_tiktok)
    tiktok_credential_store.secrets[ORPHAN_REF] = ORPHAN_SECRET
    _register(db_path)

    tiktok_callback(tiktok_client, state)

    assert ORPHAN_REF not in tiktok_credential_store.secrets
    assert _orphans(db_path) == []


@pytest.mark.parametrize("route", ["disconnect", "remove-local"])
def test_cleanup_runs_on_disconnect_and_local_removal(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    route: str,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    tiktok_credential_store.secrets[ORPHAN_REF] = ORPHAN_SECRET
    _register(db_path)

    response = tiktok_client.post(
        f"/api/accounts/{account['id']}/tiktok-connection/{route}"
    )

    assert response.status_code == 200, response.text
    assert tiktok_credential_store.secrets == {}
    assert _orphans(db_path) == []


def test_orphan_cleanup_failure_never_breaks_the_operation(
    tiktok_client: TestClient,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, account = create_tiktok_account(tiktok_client)
    connect_tiktok(tiktok_client, account["id"], fake_tiktok)
    _register(db_path)
    original_delete = tiktok_credential_store.delete

    def delete(ref: str) -> None:
        if ref == ORPHAN_REF:
            raise RuntimeError("unexpected")
        original_delete(ref)

    monkeypatch.setattr(tiktok_credential_store, "delete", delete)

    response = tiktok_client.post(
        f"/api/accounts/{account['id']}/tiktok-connection/disconnect"
    )

    assert response.status_code == 200, response.text
    assert response.json()["revocation"] == "revoked"
    assert [row["credential_ref"] for row in _orphans(db_path)] == [ORPHAN_REF]
