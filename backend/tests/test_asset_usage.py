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
# Scheduled dates relative to the real clock of the default test app.
FUTURE_SQL = "2100-01-01 10:00:00"
PAST_SQL = "2000-01-01 10:00:00"


def _publication(
    db_path: Path,
    content_id: int | None,
    account_id: int,
    status: str,
    *,
    published_at: str | None = None,
    updated_at: str = T1,
) -> None:
    scheduled_at = FUTURE_SQL if status == "scheduled" else None
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
    "draft_count": 0,
    "attention_count": 0,
    "upcoming_count": 0,
    "next_scheduled_at": None,
    "cancelled_count": 0,
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
                # Its failed TikTok post needs the user.
                "attention_count": 1,
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
                "attention_count": 1,
            },
        ),
        (
            "scheduled",
            EMPTY
            | {
                "publication_count": 1,
                "scheduled_count": 1,
                "upcoming_count": 1,
                "next_scheduled_at": "2100-01-01T10:00:00Z",
            },
        ),
        (
            "failed",
            EMPTY
            | {"publication_count": 2, "attention_count": 1, "cancelled_count": 1},
        ),
        # Needs review counts as attention like failed.
        ("uncertain", EMPTY | {"publication_count": 1, "attention_count": 1}),
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


# --- Feature 019: visible-state counts, display state, inheritance, consent --------


def _post(
    db_path: Path,
    content_id: int,
    account_id: int,
    status: str,
    *,
    scheduled_at: str | None = None,
    armed: bool = False,
    description_override: str | None = None,
) -> None:
    run_sql(
        db_path,
        "INSERT INTO publications (project_id, content_id, account_id, status, "
        "scheduled_at, auto_publish_enabled, description_override, created_at, "
        "updated_at) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
        content_id,
        account_id,
        status,
        scheduled_at,
        int(armed),
        description_override,
        T1,
        T1,
    )


@pytest.fixture
def states(client: TestClient, db_path: Path) -> dict[str, int]:
    """One content whose posts cover every visible state that is counted."""
    project = create_project(client, "L4i4")
    accounts = [
        create_account(client, project["id"], "youtube", f"l4i4-{n}")["id"]
        for n in range(8)
    ]
    content = import_one(client, project["id"], "all.png", make_image())["content"]
    only_cancelled = import_one(client, project["id"], "gone.png", make_image())[
        "content"
    ]
    cid = content["id"]
    _post(db_path, cid, accounts[0], "unscheduled")  # draft
    _post(db_path, cid, accounts[1], "scheduled", scheduled_at=FUTURE_SQL, armed=True)
    _post(db_path, cid, accounts[2], "scheduled", scheduled_at="2099-01-01 08:00:00")
    _post(db_path, cid, accounts[3], "scheduled", scheduled_at=PAST_SQL)  # missed
    # Armed and past its 10-minute window: missed (overdue) as well.
    _post(db_path, cid, accounts[4], "scheduled", scheduled_at=PAST_SQL, armed=True)
    _post(db_path, cid, accounts[5], "publishing")
    _post(db_path, cid, accounts[6], "awaiting_user_action")  # needs action
    _post(db_path, cid, accounts[7], "cancelled")
    _post(db_path, only_cancelled["id"], accounts[0], "cancelled")
    return {"content": cid, "only_cancelled": only_cancelled["id"]}


def test_usage_counts_follow_the_visible_state(
    client: TestClient, states: dict[str, int]
) -> None:
    usage = client.get(f"/api/contents/{states['content']}").json()["usage"]

    assert usage["draft_count"] == 1
    # Manual past + armed overdue (missed) + awaiting the user (needs action).
    assert usage["attention_count"] == 3
    # Two scheduled ahead + one publishing.
    assert usage["upcoming_count"] == 3
    assert usage["next_scheduled_at"] == "2099-01-01T08:00:00Z"
    assert usage["cancelled_count"] == 1

    gone = client.get(f"/api/contents/{states['only_cancelled']}").json()["usage"]
    # "Not used yet": every post of the media is cancelled.
    assert gone["publication_count"] == gone["cancelled_count"] == 1


def test_paused_automation_keeps_armed_posts_upcoming(
    client: TestClient, states: dict[str, int]
) -> None:
    assert client.put("/api/automation", json={"paused": True}).status_code == 200

    usage = client.get(f"/api/contents/{states['content']}").json()["usage"]
    rows = client.get(f"/api/contents/{states['content']}/usage").json()

    assert usage["upcoming_count"] == 3
    assert "scheduled_paused" in {p["display_state"] for p in rows["publications"]}


def test_usage_rows_carry_display_state_and_inheritance(
    client: TestClient, db_path: Path, states: dict[str, int]
) -> None:
    rows = client.get(f"/api/contents/{states['content']}/usage").json()
    states_seen = sorted(p["display_state"] for p in rows["publications"])

    assert states_seen == sorted(
        [
            "draft",
            "scheduled_automatic",
            "scheduled_manual",
            "missed",
            "missed",
            "publishing",
            "needs_action",
            "cancelled",
        ]
    )
    for row in rows["publications"]:
        assert row["inherits"] == {"title": True, "description": True, "hashtags": True}
        assert row["consent_covers_caption"] is False

    run_sql(
        db_path,
        "UPDATE publications SET description_override = '', hashtags_override = '[]' "
        "WHERE status = 'unscheduled'",
    )
    snapshot = [
        p
        for p in client.get(f"/api/contents/{states['content']}/usage").json()[
            "publications"
        ]
        if p["display_state"] == "draft"
    ]
    # An explicit empty override is not inheritance.
    assert snapshot[0]["inherits"] == {
        "title": True,
        "description": False,
        "hashtags": False,
    }


def _tiktok_options(
    db_path: Path, publication_id: int, mode: str, consented: bool
) -> None:
    run_sql(
        db_path,
        "INSERT INTO tiktok_publication_options (publication_id, mode, "
        "consent_fingerprint, consent_declaration_version, consented_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        publication_id,
        mode,
        "f" * 64 if consented else None,
        "v1" if consented else None,
        T1 if consented else None,
        T1,
    )


def test_consent_covers_caption_only_for_consented_direct_posts(
    client: TestClient, db_path: Path
) -> None:
    project = create_project(client, "L4i4")
    accounts = [
        create_account(client, project["id"], "tiktok", f"tt-{n}")["id"]
        for n in range(3)
    ]
    content = import_one(client, project["id"], "clip.png", make_image())["content"]
    for account in accounts:
        _post(db_path, content["id"], account, "scheduled", scheduled_at=FUTURE_SQL)
    _tiktok_options(db_path, 1, "DIRECT_POST", consented=True)
    _tiktok_options(db_path, 2, "INBOX_UPLOAD", consented=False)
    _tiktok_options(db_path, 3, "DIRECT_POST", consented=False)

    rows = client.get(f"/api/contents/{content['id']}/usage").json()["publications"]
    covered = {row["publication_id"]: row["consent_covers_caption"] for row in rows}

    assert covered == {1: True, 2: False, 3: False}


def test_usage_rows_queries_do_not_grow_with_posts(
    client: TestClient,
    db_path: Path,
    states: dict[str, int],
    statement_counter: list[str],
) -> None:
    # One TikTok post first: its options lookup is one query whatever the count.
    first = create_account(client, 1, "tiktok", "first")["id"]
    _post(db_path, states["content"], first, "unscheduled")
    statement_counter.clear()
    client.get(f"/api/contents/{states['content']}/usage")
    few = len(statement_counter)
    for n in range(4):
        account = create_account(client, 1, "tiktok", f"more-{n}")["id"]
        _post(db_path, states["content"], account, "unscheduled")
    statement_counter.clear()

    client.get(f"/api/contents/{states['content']}/usage")

    assert len(statement_counter) == few
