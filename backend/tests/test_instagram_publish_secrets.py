"""No Instagram token, provider credential, signed URL, raw Meta text or (in logs)
media ID ever reaches SQLite, logs or API responses (FR-066, FR-067, SC-007)."""

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    allow_reels,
    instagram_publication,
    publish_and_wait,
)
from tests.fakes import (
    FAKE_DELIVERY_ACCESS_KEY,
    FAKE_DELIVERY_SECRET,
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REFRESHED_TOKEN,
    FAKE_META_ERROR_TEXT,
    FAKE_SIGNATURE,
    FakeMeta,
)

SECRETS = (
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REFRESHED_TOKEN,
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
        f"/api/publications/{publication_id}/instagram-options",
        f"/api/publications/{publication_id}/publish-check",
        "/api/projects/1/publications",
    ]
    return "\n".join(client.get(path).text for path in paths)


def test_no_secret_anywhere_after_every_kind_of_run(
    ig_client: TestClient,
    fake_meta: FakeMeta,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    allow_reels(monkeypatch)
    caplog.set_level(logging.DEBUG)
    texts: list[str] = []

    image = instagram_publication(ig_client)["publication"]["id"]
    texts.append(str(publish_and_wait(ig_client, image)))
    reel = instagram_publication(ig_client, kind="reel", project_name="Reels")[
        "publication"
    ]["id"]
    texts.append(str(publish_and_wait(ig_client, reel)))
    fake_meta.faults["create"] = "graph_-1_2207032"
    failed = instagram_publication(ig_client, project_name="Failed")["publication"][
        "id"
    ]
    texts.append(str(publish_and_wait(ig_client, failed)))
    fake_meta.faults.pop("create")
    fake_meta.faults["publish"] = "transport"
    uncertain = instagram_publication(ig_client, project_name="Uncertain")[
        "publication"
    ]["id"]
    texts.append(str(publish_and_wait(ig_client, uncertain)))
    for publication_id in (image, reel, failed, uncertain):
        texts.append(_responses(ig_client, publication_id))

    everything = "\n".join(texts)
    database = _dump(db_path)
    logs = caplog.text
    for secret in SECRETS:
        assert secret not in everything, secret
        assert secret not in database, secret
        assert secret not in logs, secret
    # Media IDs are never logged (YouTube precedent).
    assert "18000000000001" not in logs
    assert "r2.cloudflarestorage.com/autopublisher-temp" not in database
    assert "r2.cloudflarestorage.com/autopublisher-temp" not in everything


def test_signed_url_only_travels_in_the_post_body(
    ig_client: TestClient, fake_meta: FakeMeta
) -> None:
    created = instagram_publication(ig_client)

    publish_and_wait(ig_client, created["publication"]["id"])

    bodies: list[dict[str, Any]] = [r.form for r in fake_meta.requests_for("create")]
    assert FAKE_SIGNATURE in bodies[0]["image_url"]
    assert all(FAKE_SIGNATURE not in r.url for r in fake_meta.requests)


def test_graph_object_ids_are_redacted_from_http_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.instagram_connections import install_log_redaction

    install_log_redaction()
    caplog.set_level(logging.DEBUG)

    logging.getLogger("httpx2").info(
        "HTTP Request: GET https://graph.instagram.com/v26.0/18000000000777"
        "?fields=id%2Cpermalink&access_token=x"
    )

    assert "18000000000777" not in caplog.text
    assert "v26.0/[id]?" in caplog.text
