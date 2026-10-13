"""Publishing a single video on Threads end to end with fakes (US3, research.md §8,
§10, §14): no transcoding, bounded waits, determined failures, signed URL lifetime."""

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import media_delivery, threads_gateway, threads_publishing
from app.models import Platform
from app.threads_publishing import ThreadsPublishSettings
from tests.conftest import (
    probe_streams,
    publish_and_wait,
    temporary_media_rows,
    threads_video_publication,
)
from tests.fakes import (
    FAKE_SIGNATURE,
    FakeClock,
    FakeMediaDeliveryProvider,
    FakeThreads,
)


def _attempt(client: TestClient, publication_id: int) -> dict[str, Any]:
    [attempt] = client.get(f"/api/publications/{publication_id}/attempts").json()
    result: dict[str, Any] = attempt
    return result


def _publish(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, **values: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    created = threads_video_publication(client, monkeypatch, **values)
    publication_id = created["publication"]["id"]
    published = publish_and_wait(client, publication_id)
    return published, _attempt(client, publication_id)


def test_publish_video(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_threads.status_script = ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
    signed_before_upload: list[int] = []
    fake_delivery.put_hook = lambda key: signed_before_upload.append(
        len(fake_delivery.signed)
    )

    published, attempt = _publish(
        threads_publishing_client, monkeypatch, alt_text="A short clip"
    )

    assert published["status"] == "published"
    assert attempt["status"] == "succeeded"
    [container_id] = fake_threads.containers
    form = fake_threads.containers[container_id]
    [signed] = fake_delivery.signed
    assert form == {
        "media_type": "VIDEO",
        "text": "Summer drop.\n\n#cyber",
        "video_url": signed,
        "alt_text": "A short clip",
    }
    [create] = fake_threads.requests_for("create")
    assert FAKE_SIGNATURE not in create.url
    assert fake_threads.publish_count(container_id) == 1
    # The signed URL is only created after the upload finished.
    assert signed_before_upload == [0]
    [key] = fake_delivery.put_calls
    assert fake_delivery.content_types[key] == "video/mp4"
    submitted = attempt["submitted"]
    assert submitted["media_kind"] == "video"
    assert submitted["converted"] is False
    assert submitted["delivered_format"] == "mp4"
    assert submitted["delegated_checks"] == ["closed_gop", "edit_lists"]
    assert fake_delivery.objects == {}
    assert temporary_media_rows(db_path)[0]["deleted_at"] is not None


def test_unknown_values_are_recorded_as_delegated(
    threads_publishing_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = probe_streams(
        video={"bit_rate": None, "field_order": None},
        audio={"bit_rate": None},
        bit_rate=None,
    )

    published, attempt = _publish(
        threads_publishing_client, monkeypatch, streams=streams
    )

    assert published["status"] == "published"
    assert attempt["submitted"]["delegated_checks"] == [
        "closed_gop",
        "edit_lists",
        "video_bitrate",
        "progressive_scan",
        "audio_bitrate",
    ]


def test_video_waits_are_bounded(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    recorded_sleeps: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_threads.status_script = ["IN_PROGRESS"]

    published, attempt = _publish(threads_publishing_client, monkeypatch)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "threads_processing_timeout"
    assert attempt["outcome_determined"] is True
    # Waits of 10, 20 and 30 s, then every 60 s, never beyond 5 minutes, and only
    # a handful of status reads (no busy loop).
    assert sum(recorded_sleeps) <= 300
    assert len(fake_threads.requests_for("status")) == 8
    assert fake_threads.requests_for("publish") == []
    assert fake_delivery.objects == {}


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("ERROR:INVALID_BIT_RATE", "threads_media_rejected"),
        ("ERROR:INVALID_ASPEC_RATIO", "threads_media_rejected"),
        ("ERROR:FAILED_PROCESSING_VIDEO", "threads_media_rejected"),
        ("ERROR:FAILED_PROCESSING_AUDIO", "threads_media_rejected"),
        ("ERROR:FAILED_DOWNLOADING_VIDEO", "threads_media_fetch_failed"),
        ("ERROR:UNKNOWN", "threads_processing_failed"),
        ("EXPIRED", "threads_container_expired"),
    ],
)
def test_container_failures_never_publish(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    code: str,
) -> None:
    fake_threads.status_script = ["IN_PROGRESS", status]

    published, attempt = _publish(threads_publishing_client, monkeypatch)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == code
    assert attempt["outcome_determined"] is True
    assert fake_threads.requests_for("publish") == []
    assert fake_delivery.objects == {}


def test_shutdown_while_polling_is_determined(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_threads.status_script = ["IN_PROGRESS"]
    app = threads_publishing_client.app
    assert isinstance(app, FastAPI)
    publisher = app.state.publishers[Platform.THREADS]

    def sleep(seconds: float) -> None:
        fake_clock.advance(seconds)
        app.state.publication_runner._stop_event.set()

    publisher.settings = dataclasses.replace(publisher.settings, sleep=sleep)

    published, attempt = _publish(threads_publishing_client, monkeypatch)

    assert published["status"] == "failed"
    assert attempt["error"]["code"] == "interrupted"
    assert attempt["outcome_determined"] is True
    assert fake_threads.requests_for("publish") == []


def test_signed_url_outlives_every_wait() -> None:
    """No valid `url_ttl_seconds` lets the signed URL expire while Threads may still
    fetch or process the media (research.md §14)."""
    needed = (
        threads_gateway.PUBLISH_TIMEOUT_SECONDS
        + ThreadsPublishSettings().video_timeout
        + threads_publishing.URL_TTL_SAFETY_MARGIN_SECONDS
    )

    assert media_delivery.MIN_URL_TTL_SECONDS >= needed
    # The minimum container age is waited inside the processing timeout.
    assert (
        threads_publishing.MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS
        <= ThreadsPublishSettings().video_timeout
    )


def test_mov_is_sent_as_quicktime(
    threads_publishing_client: TestClient,
    fake_delivery: FakeMediaDeliveryProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published, _ = _publish(threads_publishing_client, monkeypatch, format="mov")

    assert published["status"] == "published"
    [key] = fake_delivery.put_calls
    assert fake_delivery.content_types[key] == "video/quicktime"
