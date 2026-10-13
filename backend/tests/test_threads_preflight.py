"""Threads preflight (US5, FR-025/FR-026): every detectable problem fails before any
remote effect: the publication keeps its status, no attempt is created, nothing is
uploaded to the media delivery provider and no container is created."""

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import media, threads_media
from tests.conftest import (
    attempt_rows,
    create_account,
    create_publications,
    import_one,
    probe_streams,
    publish_and_wait,
    run_sql,
    stored_file,
    threads_image_publication,
    threads_text_publication,
    threads_video_publication,
    wait_idle,
)
from tests.conftest import connect_threads as connect
from tests.fakes import (
    TH_BASIC,
    FakeMediaDeliveryProvider,
    FakeThreads,
    InMemoryCredentialStore,
)


def _start(client: TestClient, publication_id: int) -> Any:
    response = client.post(f"/api/publications/{publication_id}/publish", json={})
    wait_idle(client)
    return response


def _assert_nothing_happened(
    client: TestClient,
    publication: dict[str, Any],
    db_path: Path,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    current = client.get(f"/api/publications/{publication['id']}").json()
    assert current["status"] == publication["status"]
    assert attempt_rows(db_path) == []
    assert fake_delivery.put_calls == []
    assert fake_threads.containers == {}
    assert fake_threads.requests_for("publish") == []


def _animated_webp() -> bytes:
    frames = [Image.new("RGB", (64, 64), color) for color in ("red", "blue")]
    buffer = io.BytesIO()
    frames[0].save(buffer, "WEBP", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


def _image_publication(client: TestClient, data: bytes, name: str) -> dict[str, Any]:
    project_id = client.post("/api/projects", json={"name": "Media"}).json()["id"]
    account = create_account(client, project_id, "threads", "media")
    connect(client, account["id"])
    content = import_one(client, project_id, name, data)["content"]
    publication = create_publications(client, content["id"], [account["id"]])[0]
    return {"account": account, "content": content, "publication": publication}


Setup = Callable[..., dict[str, Any]]


def _text(**values: Any) -> Setup:
    return lambda client, **_: threads_text_publication(client, **values)


def _inactive_project(client: TestClient, **_: Any) -> dict[str, Any]:
    created = threads_text_publication(client)
    client.patch(
        f"/api/projects/{created['publication']['project_id']}",
        json={"is_active": False},
    )
    return created


def _inactive_account(client: TestClient, **_: Any) -> dict[str, Any]:
    created = threads_text_publication(client)
    client.patch(f"/api/accounts/{created['account']['id']}", json={"is_active": False})
    return created


def _reconnect_required(client: TestClient, db_path: Path, **_: Any) -> dict[str, Any]:
    created = threads_text_publication(client)
    run_sql(db_path, "UPDATE threads_connections SET status = 'reconnect_required'")
    return created


def _identity_mismatch(
    client: TestClient, fake_threads: FakeThreads, **_: Any
) -> dict[str, Any]:
    created = threads_text_publication(client)
    fake_threads.debug_user_id = "99999999999999999"
    return created


def _missing_permission(
    client: TestClient, fake_threads: FakeThreads, **_: Any
) -> dict[str, Any]:
    created = threads_text_publication(client)
    fake_threads.debug_scopes = [TH_BASIC]
    return created


def _store_unavailable(
    client: TestClient, threads_credential_store: InMemoryCredentialStore, **_: Any
) -> dict[str, Any]:
    created = threads_text_publication(client)
    threads_credential_store.unavailable = True
    return created


def _missing_file(
    client: TestClient, db_path: Path, media_dir: Path, **_: Any
) -> dict[str, Any]:
    created = threads_image_publication(client)
    stored_file(media_dir, db_path, created["content"]["id"]).unlink()
    return created


def _changed_file(
    client: TestClient, db_path: Path, media_dir: Path, **_: Any
) -> dict[str, Any]:
    created = threads_image_publication(client)
    path = stored_file(media_dir, db_path, created["content"]["id"])
    path.write_bytes(path.read_bytes() + b"tampered")
    return created


def _animated(client: TestClient, **_: Any) -> dict[str, Any]:
    return _image_publication(client, _animated_webp(), "animated.webp")


def _too_wide(client: TestClient, **_: Any) -> dict[str, Any]:
    buffer = io.BytesIO()
    Image.new("RGB", (1100, 100), "red").save(buffer, "PNG")
    return _image_publication(client, buffer.getvalue(), "wide.png")


def _oversized_derivative(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, **_: Any
) -> dict[str, Any]:
    created = threads_image_publication(client, format="webp")
    monkeypatch.setattr(threads_media, "IMAGE_MAX_BYTES", 10)
    return created


def _video(**streams: Any) -> Setup:
    def setup(
        client: TestClient, monkeypatch: pytest.MonkeyPatch, **_: Any
    ) -> dict[str, Any]:
        return threads_video_publication(
            client, monkeypatch, streams=probe_streams(**streams)
        )

    return setup


def _no_ffprobe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, **_: Any
) -> dict[str, Any]:
    created = threads_video_publication(client, monkeypatch)
    monkeypatch.setattr(media, "probe_video_streams", lambda path: None)
    return created


def _no_delivery(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **_: Any
) -> dict[str, Any]:
    created = threads_image_publication(client)
    monkeypatch.setenv(
        "AUTOPUBLISHER_MEDIA_DELIVERY_FILE", str(tmp_path / "missing.json")
    )
    return created


def _quota(value: tuple[int, int] | None = None, fault: str | None = None) -> Setup:
    def setup(
        client: TestClient, fake_threads: FakeThreads, **_: Any
    ) -> dict[str, Any]:
        created = threads_image_publication(client)
        if value is not None:
            fake_threads.quota = value
        if fault is not None:
            fake_threads.faults["limit"] = fault
        return created

    return setup


def _publishing(client: TestClient, db_path: Path, **_: Any) -> dict[str, Any]:
    created = threads_text_publication(client)
    run_sql(
        db_path,
        "UPDATE publications SET status = 'publishing' WHERE id = ?",
        created["publication"]["id"],
    )
    created["publication"]["status"] = "publishing"
    return created


CASES: list[tuple[str, Setup, int, str]] = [
    ("inactive project", _inactive_project, 409, "project_inactive"),
    ("inactive account", _inactive_account, 409, "account_inactive"),
    ("not connected", _text(connect=False), 409, "threads_not_connected"),
    ("reconnect required", _reconnect_required, 409, "threads_reconnect_required"),
    ("identity mismatch", _identity_mismatch, 409, "threads_identity_mismatch"),
    ("missing permission", _missing_permission, 409, "threads_reconnect_required"),
    ("store unavailable", _store_unavailable, 503, "credential_store_unavailable"),
    ("missing file", _missing_file, 409, "media_unavailable"),
    ("changed file", _changed_file, 409, "media_unavailable"),
    (
        "text too long",
        _text(description="x" * 501, hashtags=[]),
        409,
        "threads_text_invalid",
    ),
    (
        "too many links",
        _text(
            description=" ".join(f"https://s{n}.example" for n in range(6)),
            hashtags=[],
        ),
        409,
        "threads_text_invalid",
    ),
    ("empty text", _text(description="", hashtags=[]), 409, "threads_text_invalid"),
    ("animated webp", _animated, 409, "threads_image_incompatible"),
    ("aspect over 10:1", _too_wide, 409, "threads_image_incompatible"),
    ("oversized derivative", _oversized_derivative, 409, "threads_image_incompatible"),
    (
        "video codec",
        _video(video={"codec_name": "vp9"}),
        409,
        "threads_video_incompatible",
    ),
    (
        "unknown pix_fmt",
        _video(video={"pix_fmt": None}),
        409,
        "threads_video_incompatible",
    ),
    (
        "unknown duration",
        _video(duration_seconds=None),
        409,
        "threads_video_incompatible",
    ),
    ("no ffprobe", _no_ffprobe, 409, "threads_media_unverifiable"),
    ("delivery not configured", _no_delivery, 503, "media_delivery_not_configured"),
    ("quota exhausted", _quota((250, 250)), 409, "threads_publishing_limit_reached"),
    (
        "quota unexpected shape",
        _quota(fault="missing_fields"),
        502,
        "threads_unexpected_response",
    ),
    ("quota rejected", _quota(fault="graph_100"), 502, "threads_unexpected_response"),
    ("already publishing", _publishing, 409, "publication_in_progress"),
]


@pytest.mark.parametrize(
    ("setup", "status_code", "code"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_preflight_failures_have_no_remote_effect(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    threads_credential_store: InMemoryCredentialStore,
    db_path: Path,
    media_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setup: Setup,
    status_code: int,
    code: str,
) -> None:
    created = setup(
        threads_publishing_client,
        fake_threads=fake_threads,
        threads_credential_store=threads_credential_store,
        db_path=db_path,
        media_dir=media_dir,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    response = _start(threads_publishing_client, created["publication"]["id"])

    assert response.status_code == status_code, response.text
    assert response.json()["error"]["code"] == code
    threads_credential_store.unavailable = False
    _assert_nothing_happened(
        threads_publishing_client,
        created["publication"],
        db_path,
        fake_threads,
        fake_delivery,
    )


def test_quota_temporarily_unavailable_still_publishes(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
) -> None:
    fake_threads.faults["limit"] = "server_error"
    created = threads_image_publication(threads_publishing_client)

    published = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    attempt = published["latest_attempt"]
    assert published["status"] == "published"
    assert attempt["submitted"]["quota_checked"] is False
    assert [w["code"] for w in attempt["warnings"]] == ["quota_unavailable"]


def test_text_posts_never_need_media_delivery(
    threads_publishing_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = threads_text_publication(threads_publishing_client)
    monkeypatch.setenv(
        "AUTOPUBLISHER_MEDIA_DELIVERY_FILE", str(tmp_path / "missing.json")
    )

    published = publish_and_wait(
        threads_publishing_client, created["publication"]["id"]
    )

    assert published["status"] == "published"


def test_previous_published_container_blocks_the_attempt(
    threads_publishing_client: TestClient,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
) -> None:
    """Research §11: a determined failure whose container Threads later reports as
    PUBLISHED blocks a new attempt before anything is uploaded or created."""
    fake_threads.fault_queue["publish"] = ["graph_100"]
    created = threads_image_publication(threads_publishing_client)
    publication_id = created["publication"]["id"]
    failed = publish_and_wait(threads_publishing_client, publication_id)
    assert failed["latest_attempt"]["outcome_determined"] is True
    [container_id] = fake_threads.containers
    fake_threads.container_statuses[container_id] = ["PUBLISHED"]
    puts = len(fake_delivery.put_calls)

    response = _start(threads_publishing_client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "threads_already_published"
    assert len(fake_threads.containers) == 1
    assert len(fake_delivery.put_calls) == puts
    assert len(fake_threads.requests_for("publish")) == 1


def test_publish_check_lists_the_local_problems(
    threads_publishing_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = threads_video_publication(
        threads_publishing_client,
        monkeypatch,
        streams=probe_streams(video={"codec_name": "vp9", "width": 4000}),
    )

    check = threads_publishing_client.get(
        f"/api/publications/{created['publication']['id']}/publish-check"
    ).json()

    assert check["eligible"] is False
    codes = [problem["code"] for problem in check["problems"]]
    assert codes == ["threads_video_incompatible", "threads_video_incompatible"]
    assert {problem["field"] for problem in check["problems"]} == {"media"}
    labels = [item["label"] for item in check["summary"]]
    assert labels == ["Post type", "Threads account", "Text", "Alt text", "File"]
