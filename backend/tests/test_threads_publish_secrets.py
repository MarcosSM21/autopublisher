"""No Threads token, provider credential, signed URL, raw Meta text or (in logs) post
id ever reaches SQLite, logs, error messages or API responses (US8, FR-052)."""

import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    publish_and_wait,
    threads_image_publication,
    threads_text_publication,
    threads_video_publication,
)
from tests.fakes import (
    FAKE_DELIVERY_ACCESS_KEY,
    FAKE_DELIVERY_SECRET,
    FAKE_META_ERROR_TEXT,
    FAKE_SIGNATURE,
    FAKE_TH_APP_SECRET,
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REFRESHED_TOKEN,
    FakeThreads,
)

SECRETS = (
    FAKE_TH_LONG_TOKEN,
    FAKE_TH_REFRESHED_TOKEN,
    FAKE_TH_APP_SECRET,
    FAKE_DELIVERY_SECRET,
    FAKE_DELIVERY_ACCESS_KEY,
    FAKE_SIGNATURE,
    "X-Amz-Signature",
    "X-Amz-Credential",
    FAKE_META_ERROR_TEXT,
)


def _dump(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        return "\n".join(connection.iterdump())


def _responses(client: TestClient, publication_id: int) -> str:
    paths = [
        f"/api/publications/{publication_id}",
        f"/api/publications/{publication_id}/attempts",
        f"/api/publications/{publication_id}/threads-options",
        f"/api/publications/{publication_id}/publish-check",
        "/api/projects/1/publications",
    ]
    return "\n".join(client.get(path).text for path in paths)


def test_no_secret_anywhere_after_every_kind_of_run(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = threads_publishing_client
    texts: list[str] = []
    ids: list[int] = []

    def run(publication_id: int) -> None:
        ids.append(publication_id)
        texts.append(str(publish_and_wait(client, publication_id)))

    run(threads_text_publication(client)["publication"]["id"])
    run(threads_image_publication(client, project_name="Image")["publication"]["id"])
    run(
        threads_video_publication(client, monkeypatch, project_name="Video")[
            "publication"
        ]["id"]
    )
    fake_threads.faults["create"] = "graph_100"
    run(threads_text_publication(client, project_name="Failed")["publication"]["id"])
    fake_threads.faults.pop("create")
    fake_threads.faults["publish"] = "server_error"
    run(
        threads_image_publication(client, project_name="Ambiguous")["publication"]["id"]
    )
    for publication_id in ids:
        texts.append(_responses(client, publication_id))

    everything = "\n".join(texts)
    database = _dump(db_path)
    logs = caplog.text
    for secret in SECRETS:
        assert secret not in everything, secret
        assert secret not in database, secret
        assert secret not in logs, secret
    assert "r2.cloudflarestorage.com/autopublisher-temp" not in database
    assert "r2.cloudflarestorage.com/autopublisher-temp" not in everything
    # Post and container ids are never logged.
    assert fake_threads.posts
    for post_id in fake_threads.posts:
        assert post_id not in logs
    for container_id in fake_threads.containers:
        assert container_id not in logs


def test_signed_url_only_travels_in_the_post_body(
    threads_publishing_client: TestClient, fake_threads: FakeThreads
) -> None:
    created = threads_image_publication(threads_publishing_client)

    publish_and_wait(threads_publishing_client, created["publication"]["id"])

    [create] = fake_threads.requests_for("create")
    assert FAKE_SIGNATURE in create.form["image_url"]
    assert all(FAKE_SIGNATURE not in r.url for r in fake_threads.requests)


def test_graph_object_ids_are_redacted_from_http_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.threads_connections import install_log_redaction

    install_log_redaction()
    caplog.set_level(logging.DEBUG)

    logging.getLogger("httpx2").info(
        "HTTP Request: GET https://graph.threads.net/v1.0/18000000000777"
        "?fields=id%2Cpermalink&access_token=x"
    )

    assert "18000000000777" not in caplog.text
    assert "v1.0/[id]?" in caplog.text
    assert "access_token=[redacted]" in caplog.text
