"""Derived usage of contents in the Asset Library (FR-002…FR-007, research §1)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.conftest import (
    create_account,
    create_project,
    import_one,
    make_image,
    run_sql,
)

T1 = "2026-10-01 10:00:00"
T2 = "2026-10-02 10:00:00"
T3 = "2026-10-03 10:00:00"


def _publication(
    db_path: Path,
    content_id: int | None,
    account_id: int,
    status: str,
    *,
    published_at: str | None = None,
    updated_at: str = T1,
) -> None:
    scheduled_at = T3 if status == "scheduled" else None
    run_sql(
        db_path,
        "INSERT INTO publications (project_id, content_id, account_id, status, "
        "scheduled_at, published_at, created_at, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
        content_id,
        account_id,
        status,
        scheduled_at,
        published_at,
        T1,
        updated_at,
    )


def _uncertain_attempt(db_path: Path, publication_id: int) -> None:
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (publication_id, platform, status, stage, "
        "started_at, finished_at, bytes_sent, total_bytes, error_code, "
        "outcome_determined, submitted, details, warnings) VALUES (?, 'youtube', "
        "'failed', 'finalizing', ?, ?, 0, 0, 'interrupted', 0, '{}', '{}', '[]')",
        publication_id,
        T2,
        T2,
    )


@pytest.fixture
def library(client: TestClient, db_path: Path) -> dict[str, int]:
    """One content per representative case, plus a text-only publication."""
    project = create_project(client, "L4i4")
    accounts = {
        platform: create_account(client, project["id"], platform, "l4i4")["id"]
        for platform in ("youtube", "telegram", "tiktok", "instagram")
    }
    names = ["unused", "published", "awaiting", "scheduled", "failed", "uncertain"]
    ids = {
        name: import_one(client, project["id"], f"{name}.png", make_image())["content"][
            "id"
        ]
        for name in names
    }
    _publication(
        db_path, ids["published"], accounts["youtube"], "published", published_at=T1
    )
    _publication(
        db_path,
        ids["published"],
        accounts["telegram"],
        "published",
        published_at=T2,
        updated_at=T2,
    )
    _publication(db_path, ids["published"], accounts["tiktok"], "failed")
    _publication(db_path, ids["awaiting"], accounts["tiktok"], "awaiting_user_action")
    _publication(db_path, ids["scheduled"], accounts["instagram"], "scheduled")
    _publication(db_path, ids["failed"], accounts["instagram"], "failed")
    _publication(db_path, ids["failed"], accounts["telegram"], "cancelled")
    _publication(db_path, ids["uncertain"], accounts["youtube"], "failed")
    _uncertain_attempt(db_path, 8)
    _publication(db_path, None, accounts["telegram"], "published", published_at=T3)
    return ids


EMPTY = {
    "used": False,
    "publication_count": 0,
    "published_count": 0,
    "awaiting_count": 0,
    "scheduled_count": 0,
    "platforms": [],
    "last_published_at": None,
}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("unused", EMPTY),
        (
            "published",
            EMPTY
            | {
                "used": True,
                "publication_count": 3,
                "published_count": 2,
                "platforms": ["telegram", "youtube"],
                "last_published_at": "2026-10-02T10:00:00Z",
            },
        ),
        (
            "awaiting",
            EMPTY
            | {
                "used": True,
                "publication_count": 1,
                "awaiting_count": 1,
                "platforms": ["tiktok"],
            },
        ),
        ("scheduled", EMPTY | {"publication_count": 1, "scheduled_count": 1}),
        ("failed", EMPTY | {"publication_count": 2}),
        ("uncertain", EMPTY | {"publication_count": 1}),
    ],
)
def test_usage_summary_in_listing(
    client: TestClient, library: dict[str, int], name: str, expected: dict[str, Any]
) -> None:
    listing = client.get("/api/projects/1/contents").json()
    by_id = {item["id"]: item for item in listing}

    assert by_id[library[name]]["usage"] == expected
    # The single-content view uses the same rules.
    single = client.get(f"/api/contents/{library[name]}").json()
    assert single["usage"] == expected


@pytest.fixture
def statement_counter(client: TestClient) -> Iterator[list[str]]:
    engine = client.app.state.session_factory.kw["bind"]  # type: ignore[attr-defined]
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", count)
    yield statements
    event.remove(engine, "before_cursor_execute", count)


def test_listing_queries_do_not_grow_with_contents(
    client: TestClient, library: dict[str, int], statement_counter: list[str]
) -> None:
    client.get("/api/projects/1/contents")
    few = len(statement_counter)
    for _ in range(5):
        import_one(client, 1, "more.png", make_image())
    statement_counter.clear()

    client.get("/api/projects/1/contents")

    assert len(statement_counter) == few


def test_usage_history(client: TestClient, library: dict[str, int]) -> None:
    response = client.get(f"/api/contents/{library['published']}/usage")
    assert response.status_code == 200
    body = response.json()
    assert body["usage"]["published_count"] == 2
    # Most recently changed first.
    assert [p["platform"] for p in body["publications"]][0] == "telegram"
    assert {p["status"] for p in body["publications"]} == {"published", "failed"}
    assert "storage_path" not in response.text

    uncertain = client.get(f"/api/contents/{library['uncertain']}/usage").json()
    assert uncertain["publications"][0]["uncertain"] is True
    awaiting = client.get(f"/api/contents/{library['awaiting']}/usage").json()
    assert awaiting["publications"][0]["status"] == "awaiting_user_action"
    assert awaiting["publications"][0]["uncertain"] is False

    assert client.get("/api/contents/999/usage").status_code == 404
