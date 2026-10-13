"""Publishing a single image on Threads end to end with fakes (US2, research.md §7,
§10, §14): media delivery, IMAGE container, minimum age, one threads_publish."""

import hashlib
import io
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import connect_threads as connect
from tests.conftest import (
    create_account,
    create_project,
    create_publications,
    import_one,
    publish_and_wait,
    stored_file,
    temporary_media_rows,
    threads_image_publication,
    threads_run_rows,
)
from tests.fakes import (
    FAKE_SIGNATURE,
    FakeMediaDeliveryProvider,
    FakeThreads,
)

AGE_WAIT = [1.0] * 30


def _attempt(client: TestClient, publication_id: int) -> dict[str, Any]:
    [attempt] = client.get(f"/api/publications/{publication_id}/attempts").json()
    result: dict[str, Any] = attempt
    return result


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("media_format", "content_type", "converted"),
    [("jpeg", "image/jpeg", False), ("png", "image/png", False)],
)
def test_publish_jpeg_and_png_as_they_are(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    recorded_sleeps: list[float],
    db_path: Path,
    media_dir: Path,
    media_format: str,
    content_type: str,
    converted: bool,
) -> None:
    created = threads_image_publication(
        threads_publishing_client, format=media_format, alt_text="A red square"
    )
    publication_id = created["publication"]["id"]
    original = stored_file(media_dir, db_path, created["content"]["id"])
    before = _sha(original)

    published = publish_and_wait(threads_publishing_client, publication_id)

    attempt = _attempt(threads_publishing_client, publication_id)
    assert published["status"] == "published"
    assert attempt["status"] == "succeeded"
    assert attempt["stage"] == "done"
    [container_id] = fake_threads.containers
    form = fake_threads.containers[container_id]
    [signed] = fake_delivery.signed
    assert form == {
        "media_type": "IMAGE",
        "text": "Summer drop.\n\n#cyber",
        "image_url": signed,
        "alt_text": "A red square",
    }
    [create] = fake_threads.requests_for("create")
    assert FAKE_SIGNATURE not in create.url
    assert fake_threads.publish_count(container_id) == 1
    # The exact original bytes were uploaded.
    [key] = fake_delivery.put_calls
    assert fake_delivery.content_types[key] == content_type
    assert attempt["submitted"]["delivered_format"] == media_format
    assert attempt["submitted"]["converted"] is converted
    assert attempt["submitted"]["alt_text"] == "A red square"
    assert attempt["total_bytes"] == original.stat().st_size
    # Immediate FINISHED: only the wait up to the minimum container age.
    assert recorded_sleeps == AGE_WAIT
    # Cleaned up after success; the original file is untouched.
    assert fake_delivery.objects == {}
    [row] = temporary_media_rows(db_path)
    assert row["deleted_at"] is not None
    assert _sha(original) == before
    assert threads_run_rows(db_path)[0]["media_kind"] == "image"


def test_static_webp_is_sent_as_png(
    threads_publishing_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
    media_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = threads_image_publication(threads_publishing_client, format="webp")
    publication_id = created["publication"]["id"]
    original = stored_file(media_dir, db_path, created["content"]["id"])
    before = _sha(original)
    uploaded: list[bytes] = []
    original_put = fake_delivery.put

    def put(key: str, source: Any, content_type: str, size: int, progress: Any) -> None:
        uploaded.append(source if isinstance(source, bytes) else source.read_bytes())
        original_put(key, source, content_type, size, progress)

    monkeypatch.setattr(fake_delivery, "put", put)

    check = threads_publishing_client.get(
        f"/api/publications/{publication_id}/publish-check"
    ).json()
    published = publish_and_wait(threads_publishing_client, publication_id)

    attempt = _attempt(threads_publishing_client, publication_id)
    assert published["status"] == "published"
    assert [i["value"] for i in check["summary"] if i["label"] == "File"][0].endswith(
        "→ sent as PNG"
    )
    assert attempt["submitted"]["converted"] is True
    assert attempt["submitted"]["delivered_format"] == "png"
    [data] = uploaded
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "PNG"
    assert attempt["submitted"]["delivered_size"] == len(data)
    assert _sha(original) == before


def test_upload_progress_and_stages(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
) -> None:
    created = threads_image_publication(threads_publishing_client)
    seen: list[tuple[Any, ...]] = []

    def at_put(key: str) -> None:
        with sqlite3.connect(db_path) as connection:
            seen.append(
                connection.execute(
                    "SELECT t.object_key, r.phase FROM temporary_media_objects t, "
                    "threads_publish_runs r"
                ).fetchone()
            )

    fake_delivery.put_hook = at_put
    stages: list[tuple[Any, ...]] = []
    fake_threads.create_hook = lambda: stages.append(
        sqlite3.connect(db_path)
        .execute("SELECT stage, bytes_sent, total_bytes FROM publication_attempts")
        .fetchone()
    )

    publish_and_wait(threads_publishing_client, created["publication"]["id"])

    # The object is registered (committed) before anything is uploaded.
    [(key, phase)] = seen
    assert key == fake_delivery.put_calls[0]
    assert phase == "delivering_media"
    [(stage, sent, total)] = stages
    assert stage == "processing"
    # Real bytes were reported (writes are throttled to one per second).
    assert 0 < sent <= total


def test_in_progress_image_is_polled_up_to_three_minutes(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    recorded_sleeps: list[float],
) -> None:
    fake_threads.status_script = ["IN_PROGRESS"]
    created = threads_image_publication(threads_publishing_client)

    published = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    attempt = _attempt(threads_publishing_client, created["publication"]["id"])
    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_processing_timeout"
    assert attempt["outcome_determined"] is True
    # 2, 5, 10, 15 s, then every 30 s, never beyond 3 minutes.
    assert 150 <= sum(recorded_sleeps) <= 180
    assert fake_threads.requests_for("publish") == []


def test_fetch_error_of_the_container(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    fake_threads.status_script = ["ERROR:FAILED_DOWNLOADING_VIDEO"]
    created = threads_image_publication(threads_publishing_client)

    publish_and_wait(threads_publishing_client, created["publication"]["id"])

    attempt = _attempt(threads_publishing_client, created["publication"]["id"])
    assert attempt["error"]["code"] == "threads_media_fetch_failed"
    assert attempt["outcome_determined"] is True
    assert fake_threads.requests_for("publish") == []
    assert fake_delivery.objects == {}


def test_delivery_failure_happens_before_any_container(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    fake_delivery.put_failures = 3  # The upload and its two retries.
    created = threads_image_publication(threads_publishing_client)

    published = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    attempt = _attempt(threads_publishing_client, created["publication"]["id"])
    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "media_delivery_failed"
    assert attempt["outcome_determined"] is True
    assert fake_threads.containers == {}


def test_empty_text_and_alt_text_are_omitted(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
) -> None:
    project = create_project(threads_publishing_client, "Quiet")
    account = create_account(threads_publishing_client, project["id"], "threads", "q")
    connect(threads_publishing_client, account["id"])
    content = import_one(
        threads_publishing_client,
        project["id"],
        "plain.png",
        _png(),
    )["content"]
    [publication] = create_publications(
        threads_publishing_client, content["id"], [account["id"]]
    )

    published = publish_and_wait(threads_publishing_client, publication["id"])

    assert published["status"] == "published"
    [form] = fake_threads.containers.values()
    assert form == {"media_type": "IMAGE", "image_url": form["image_url"]}


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400), (10, 20, 30)).save(buffer, "PNG")
    return buffer.getvalue()
