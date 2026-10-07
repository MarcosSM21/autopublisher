from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.conftest import (
    FUTURE,
    LATER,
    create_publications,
    import_files,
    make_image,
    run_sql,
    setup_project,
    stored_file,
)


def _queue(client: TestClient, project_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/publications")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items


def test_empty_and_unknown_project(client: TestClient) -> None:
    project, _, _ = setup_project(client, ())
    assert _queue(client, project["id"]) == []
    response = client.get("/api/projects/9999/publications")
    assert response.status_code == 404


def test_queue_order(client: TestClient) -> None:
    project, content, accounts = setup_project(
        client, ("instagram", "tiktok", "x", "youtube", "threads", "telegram")
    )
    ids = [a["id"] for a in accounts]
    later = create_publications(client, content["id"], [ids[0]], LATER)[0]
    sooner_a = create_publications(client, content["id"], [ids[1]], FUTURE)[0]
    sooner_b = create_publications(client, content["id"], [ids[2]], FUTURE)[0]
    unscheduled_a, unscheduled_b = create_publications(
        client, content["id"], [ids[3], ids[4]]
    )
    first_cancelled = create_publications(client, content["id"], [ids[5]])[0]
    client.post(f"/api/publications/{first_cancelled['id']}/cancel")
    client.post(f"/api/publications/{unscheduled_b['id']}/cancel")

    queue = _queue(client, project["id"])

    assert [p["id"] for p in queue] == [
        sooner_a["id"],
        sooner_b["id"],
        later["id"],
        unscheduled_a["id"],
        # Cancelled: the most recently cancelled first.
        unscheduled_b["id"],
        first_cancelled["id"],
    ]
    assert [p["status"] for p in queue] == [
        "scheduled",
        "scheduled",
        "scheduled",
        "unscheduled",
        "cancelled",
        "cancelled",
    ]


def test_queue_only_lists_the_project(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    other, other_content, other_accounts = setup_project(
        client, ("instagram",), name="Cybersecurity"
    )
    create_publications(client, content["id"], [accounts[0]["id"]])
    create_publications(client, other_content["id"], [other_accounts[0]["id"]])

    queue = _queue(client, project["id"])

    assert len(queue) == 1
    assert queue[0]["project_id"] == project["id"]


def test_cancelled_and_inactive_account_publications_are_listed(
    client: TestClient,
) -> None:
    project, content, accounts = setup_project(client, ("instagram", "x"))
    instagram, x = create_publications(
        client, content["id"], [a["id"] for a in accounts]
    )
    client.post(f"/api/publications/{instagram['id']}/cancel")
    client.patch(f"/api/accounts/{accounts[1]['id']}", json={"is_active": False})

    queue = _queue(client, project["id"])

    assert {p["id"] for p in queue} == {instagram["id"], x["id"]}
    inactive = next(p for p in queue if p["id"] == x["id"])
    assert inactive["account"]["is_active"] is False


def test_inactive_project_queue_is_readable(client: TestClient) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    create_publications(client, content["id"], [accounts[0]["id"]])
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    queue = _queue(client, project["id"])

    assert len(queue) == 1
    assert queue[0]["project_active"] is False


def test_queue_items_embed_content_and_account(
    client: TestClient, media_dir: Path, db_path: Path
) -> None:
    project, content, accounts = setup_project(client, ("instagram",))
    create_publications(client, content["id"], [accounts[0]["id"]])

    [item] = _queue(client, project["id"])
    assert item["content"] == {
        "id": content["id"],
        "title": None,
        "original_filename": "photo.png",
        "media_type": "image",
        "file_url": f"/api/contents/{content['id']}/file",
        "file_available": True,
    }
    assert item["account"]["platform"] == "instagram"
    assert item["account"]["handle"] == "l4i4"

    stored_file(media_dir, db_path, content["id"]).unlink()
    [item] = _queue(client, project["id"])
    assert item["content"]["file_available"] is False


def test_large_queue(client: TestClient) -> None:
    project, _, accounts = setup_project(client, ("instagram", "x"))
    response = import_files(
        client,
        project["id"],
        [(f"image-{index}.png", make_image()) for index in range(100)],
    )
    contents = [item["content"] for item in response.json()["results"]]
    for content in contents:
        create_publications(client, content["id"], [a["id"] for a in accounts])

    queue = _queue(client, project["id"])

    # 100 imported here + the setup image, which has no publications.
    assert len(queue) == 200
    assert {p["status"] for p in queue} == {"unscheduled"}


# --- Execution states (US7, research.md §14) ----------------------------------------


def _set(
    db_path: Path, publication_id: int, status: str, published_at: str | None = None
) -> None:
    run_sql(
        db_path,
        "UPDATE publications SET status = ?, published_at = ? WHERE id = ?",
        status,
        published_at,
        publication_id,
    )


def _attempt(db_path: Path, publication_id: int, status: str = "running") -> None:
    finished = None if status == "running" else "2026-10-07 10:05:00"
    error = "network_error" if status == "failed" else None
    run_sql(
        db_path,
        "INSERT INTO publication_attempts (publication_id, platform, status, stage, "
        "started_at, finished_at, bytes_sent, total_bytes, error_code, error_message, "
        "outcome_determined, submitted, details, warnings) VALUES (?, 'youtube', ?, "
        "'uploading', '2026-10-07 10:00:00', ?, 5, 10, ?, ?, ?, '{}', '{}', '[]')",
        publication_id,
        status,
        finished,
        error,
        "Lost." if error else None,
        None if status == "running" else 1,
    )


def test_queue_order_with_execution_states(client: TestClient, db_path: Path) -> None:
    project, content, accounts = setup_project(
        client, ("instagram", "tiktok", "x", "youtube", "threads", "telegram")
    )
    ids = [a["id"] for a in accounts]
    created = create_publications(client, content["id"], ids)
    published_old, cancelled, unscheduled, failed, published_new, publishing = created
    _set(db_path, published_old["id"], "published", "2026-10-01 10:00:00")
    _set(db_path, published_new["id"], "published", "2026-10-05 10:00:00")
    client.post(f"/api/publications/{cancelled['id']}/cancel")
    _set(db_path, failed["id"], "failed")
    _attempt(db_path, failed["id"], "failed")
    _set(db_path, publishing["id"], "publishing")
    _attempt(db_path, publishing["id"])
    later_content = import_one_image(client, project["id"])
    scheduled = create_publications(client, later_content["id"], [ids[0]], FUTURE)[0]

    queue = _queue(client, project["id"])

    assert [p["id"] for p in queue] == [
        publishing["id"],
        failed["id"],
        scheduled["id"],
        unscheduled["id"],
        published_new["id"],
        published_old["id"],
        cancelled["id"],
    ]
    by_id = {p["id"]: p for p in queue}
    assert by_id[publishing["id"]]["latest_attempt"]["status"] == "running"
    assert by_id[publishing["id"]]["latest_attempt"]["progress"] == 0.5
    assert by_id[failed["id"]]["latest_attempt"]["error"]["code"] == "network_error"
    assert by_id[unscheduled["id"]]["latest_attempt"] is None
    assert by_id[failed["id"]]["attempt_count"] == 1


def import_one_image(client: TestClient, project_id: int) -> dict[str, Any]:
    response = import_files(client, project_id, [("second.png", make_image())])
    assert response.status_code == 200, response.text
    content: dict[str, Any] = response.json()["results"][0]["content"]
    return content


def test_queue_loads_attempts_with_a_constant_number_of_queries(
    client: TestClient, db_path: Path
) -> None:
    project, content, accounts = setup_project(
        client, ("instagram", "tiktok", "x", "youtube", "threads", "telegram")
    )
    publications = create_publications(
        client, content["id"], [a["id"] for a in accounts]
    )
    app = client.app
    assert isinstance(app, FastAPI)
    engine = app.state.session_factory.kw["bind"]
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", count)
    try:
        for publication in publications[:2]:
            _set(db_path, publication["id"], "failed")
            _attempt(db_path, publication["id"], "failed")
        statements.clear()
        _queue(client, project["id"])
        with_two = len(statements)
        for publication in publications[2:]:
            _set(db_path, publication["id"], "failed")
            _attempt(db_path, publication["id"], "failed")
        statements.clear()
        _queue(client, project["id"])
        with_six = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert with_two == with_six
