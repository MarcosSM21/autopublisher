import io
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import keyring
import keyring.core
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from keyring.backends import fail
from PIL import Image

from app import media
from app.main import create_app
from app.publishing import PublishingSettings
from app.youtube_upload import YouTubeUploadSettings
from tests.fakes import (
    ALL_SCOPES,
    FAKE_AUTH_CODE,
    FakeGoogle,
    InMemoryCredentialStore,
    client_config_json,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    return tmp_path / "media"


@pytest.fixture
def client(db_path: Path, media_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_path, media_dir)) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolate_system_keyring() -> Iterator[None]:
    """Never touch the real system keyring: install a failing backend, then restore.

    Tests of the credential store replace it again with `keyring.set_keyring(...)`.
    """
    original = keyring.core._keyring_backend
    keyring.set_keyring(fail.Keyring())  # type: ignore[no-untyped-call]
    yield
    keyring.core._keyring_backend = original


@pytest.fixture
def oauth_client_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "google-oauth-client.json"
    path.write_text(client_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE", str(path))
    monkeypatch.delenv("AUTOPUBLISHER_OAUTH_REDIRECT_URI", raising=False)
    return path


@pytest.fixture
def credential_store() -> InMemoryCredentialStore:
    return InMemoryCredentialStore()


@pytest.fixture
def fake_google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def youtube_client(
    db_path: Path,
    media_dir: Path,
    oauth_client_file: Path,
    credential_store: InMemoryCredentialStore,
    fake_google: FakeGoogle,
) -> Iterator[TestClient]:
    app = create_app(
        db_path,
        media_dir,
        credential_store=credential_store,
        google_transport=fake_google.transport(),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def recorded_sleeps() -> list[float]:
    """Every wait requested by the publishing code; nothing really sleeps."""
    return []


@pytest.fixture
def publishing_app(
    db_path: Path,
    media_dir: Path,
    oauth_client_file: Path,
    credential_store: InMemoryCredentialStore,
    fake_google: FakeGoogle,
    recorded_sleeps: list[float],
) -> FastAPI:
    return create_app(
        db_path,
        media_dir,
        credential_store=credential_store,
        google_transport=fake_google.transport(),
        publishing_settings=PublishingSettings(sleep=recorded_sleeps.append),
        youtube_upload_settings=YouTubeUploadSettings(
            chunk_size=256 * 1024,
            slice_size=64 * 1024,
            sleep=recorded_sleeps.append,
        ),
    )


@pytest.fixture
def publishing_client(publishing_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(publishing_app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def stub_probe_video(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep tests independent of ffprobe unless they opt in with `real_ffprobe`."""
    if request.node.get_closest_marker("real_ffprobe") is None:
        monkeypatch.setattr(media, "probe_video", lambda path: media.VideoInfo())


def create_project(
    client: TestClient, name: str, description: str | None = None
) -> dict[str, Any]:
    response = client.post(
        "/api/projects", json={"name": name, "description": description}
    )
    assert response.status_code == 201, response.text
    project: dict[str, Any] = response.json()
    return project


def create_account(
    client: TestClient,
    project_id: int,
    platform: str,
    handle: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    response = client.post(
        f"/api/projects/{project_id}/accounts",
        json={"platform": platform, "handle": handle, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    account: dict[str, Any] = response.json()
    return account


_color_seed = 0


def make_image(
    fmt: str = "PNG",
    size: tuple[int, int] = (8, 6),
    color: tuple[int, int, int] | None = None,
) -> bytes:
    """Return a small valid image; each call without `color` yields different bytes."""
    global _color_seed
    if color is None:
        _color_seed += 1
        color = (_color_seed % 256, (_color_seed // 256) % 256, 128)
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def _box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def make_mp4(brand: bytes = b"isom", payload: bytes = b"") -> bytes:
    """Return a minimal ISO-BMFF file: an `ftyp` box and a `free` box."""
    ftyp = _box(b"ftyp", brand + b"\x00\x00\x02\x00" + brand + b"mp41")
    return ftyp + _box(b"free", payload or b"autopublisher")


def make_mov(payload: bytes = b"") -> bytes:
    return make_mp4(b"qt  ", payload)


def make_webm(payload: bytes = b"", doctype: bytes = b"webm") -> bytes:
    """Return a minimal EBML header with the given DocType."""
    body = b"\x42\x86\x81\x01" + b"\x42\x82" + bytes([0x80 | len(doctype)]) + doctype
    header = b"\x1a\x45\xdf\xa3" + bytes([0x80 | len(body)]) + body
    return header + b"\xec" + bytes([0x80 | 0x20]) + (payload or b"x").ljust(32, b"\0")


def import_files(
    client: TestClient, project_id: int, files: list[tuple[str, bytes]]
) -> httpx.Response:
    return client.post(
        f"/api/projects/{project_id}/contents",
        files=[("files", (name, data)) for name, data in files],
    )


def import_one(
    client: TestClient, project_id: int, name: str, data: bytes
) -> dict[str, Any]:
    """Import a single file and return its result item."""
    response = import_files(client, project_id, [(name, data)])
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["results"][0]
    return result


# Fixed instants far from today, so publication tests never depend on the clock.
FUTURE = "2100-01-01T10:00:00Z"
LATER = "2100-02-01T18:30:00Z"
PAST = "2000-01-01T10:00:00Z"


def setup_project(
    client: TestClient,
    platforms: tuple[str, ...] = ("instagram", "tiktok", "x"),
    name: str = "L4i4",
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Create a project with one imported image and one account per platform."""
    project = create_project(client, name)
    content = import_one(client, project["id"], "photo.png", make_image())["content"]
    accounts = [
        create_account(client, project["id"], platform, name.lower())
        for platform in platforms
    ]
    return project, content, accounts


def create_publications(
    client: TestClient,
    content_id: int,
    account_ids: list[int],
    scheduled_at: str | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"account_ids": account_ids}
    if scheduled_at is not None:
        body["scheduled_at"] = scheduled_at
    response = client.post(f"/api/contents/{content_id}/publications", json=body)
    assert response.status_code == 201, response.text
    publications: list[dict[str, Any]] = response.json()
    return publications


def stored_file(media_dir: Path, db_path: Path, content_id: int) -> Path:
    """Locate the stored file of a content through its database row."""
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT storage_path FROM contents WHERE id = ?", (content_id,)
        ).fetchone()
    storage_path: str = row[0]
    return media_dir / storage_path


def run_sql(db_path: Path, statement: str, *params: Any) -> None:
    """Change the database directly, e.g. to simulate a date that has passed."""
    with sqlite3.connect(db_path) as connection:
        connection.execute(statement, params)


def authorize(client: TestClient, account_id: int) -> tuple[dict[str, Any], str]:
    """Start a YouTube authorization; return the response body and its `state`."""
    response = client.post(f"/api/accounts/{account_id}/youtube-connection/authorize")
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    state = parse_qs(urlsplit(body["authorization_url"]).query)["state"][0]
    return body, state


def complete_callback(
    client: TestClient,
    state: str | None,
    code: str | None = FAKE_AUTH_CODE,
    scope: str = ALL_SCOPES,
    error: str | None = None,
) -> httpx.Response:
    params: dict[str, str] = {}
    if state is not None:
        params["state"] = state
    if code is not None:
        params["code"] = code
        params["scope"] = scope
    if error is not None:
        params["error"] = error
    return client.get("/api/youtube/oauth/callback", params=params)


def get_attempt(client: TestClient, attempt_id: str) -> dict[str, Any]:
    response = client.get(f"/api/youtube/oauth/attempts/{attempt_id}")
    assert response.status_code == 200, response.text
    attempt: dict[str, Any] = response.json()
    return attempt


def get_connection(client: TestClient, account_id: int) -> dict[str, Any]:
    response = client.get(f"/api/accounts/{account_id}/youtube-connection")
    assert response.status_code == 200, response.text
    connection: dict[str, Any] = response.json()
    return connection


def connect_youtube(
    client: TestClient,
    fake_google: FakeGoogle,
    account_id: int,
    channel_id: str = "UC_TEST_1",
    title: str = "Cyber Channel",
    handle: str | None = "@cyberchannel",
) -> dict[str, Any]:
    """Run authorize → callback with the fake Google and return the connection."""
    fake_google.set_channel(channel_id, title, handle)
    body, state = authorize(client, account_id)
    response = complete_callback(client, state)
    assert response.status_code == 200, response.text
    attempt = get_attempt(client, body["attempt_id"])
    assert attempt["status"] == "completed", attempt
    connection: dict[str, Any] = attempt["connection"]
    return connection


def setup_youtube_account(
    client: TestClient, project_name: str = "Cyber", handle: str = "cyberchannel"
) -> tuple[dict[str, Any], dict[str, Any]]:
    project = create_project(client, project_name)
    account = create_account(client, project["id"], "youtube", handle, "Cyber")
    return project, account


# --- Publishing to YouTube ----------------------------------------------------------

VIDEO_SIZE = 700_000
VIDEO_TITLE = "Cybersecurity basics"
VIDEO_DESCRIPTION = "Intro to threat models."
VIDEO_HASHTAGS = ["cyber", "security"]


def setup_publishable(
    client: TestClient,
    fake_google: FakeGoogle,
    *,
    size: int = VIDEO_SIZE,
    media_type: str = "video",
    scheduled_at: str | None = None,
    project_name: str = "Cyber",
    connect: bool = True,
) -> dict[str, Any]:
    """Active project, connected YouTube account, a titled content and a publication.

    Returns the created project, account, content and publication.
    """
    project, account = setup_youtube_account(client, project_name)
    if connect:
        connect_youtube(client, fake_google, account["id"])
    if media_type == "video":
        data = make_mp4(payload=bytes(range(256)) * (size // 256 + 1))
        name = "intro.mp4"
    else:
        data = make_image()
        name = "photo.png"
    content = import_one(client, project["id"], name, data)["content"]
    response = client.patch(
        f"/api/contents/{content['id']}",
        json={
            "title": VIDEO_TITLE,
            "description": VIDEO_DESCRIPTION,
            "hashtags": VIDEO_HASHTAGS,
        },
    )
    assert response.status_code == 200, response.text
    publication = create_publications(
        client, content["id"], [account["id"]], scheduled_at
    )[0]
    return {
        "project": project,
        "account": account,
        "content": response.json(),
        "publication": publication,
    }


def set_youtube_options(
    client: TestClient, publication_id: int, **overrides: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "privacy_status": "private",
        "made_for_kids": False,
        "contains_synthetic_media": False,
        "notify_subscribers": False,
    }
    body.update(overrides)
    response = client.put(
        f"/api/publications/{publication_id}/youtube-options", json=body
    )
    assert response.status_code == 200, response.text
    options: dict[str, Any] = response.json()
    return options


def wait_idle(client: TestClient) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    assert app.state.publication_runner.wait_idle(timeout=10)


def publish_and_wait(
    client: TestClient, publication_id: int, **body: Any
) -> dict[str, Any]:
    """Publish now, wait for the background upload and return the publication."""
    response = client.post(f"/api/publications/{publication_id}/publish", json=body)
    assert response.status_code == 202, response.text
    wait_idle(client)
    return get_publication(client, publication_id)


def get_publication(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}")
    assert response.status_code == 200, response.text
    publication: dict[str, Any] = response.json()
    return publication


def attempt_rows(db_path: Path) -> list[dict[str, Any]]:
    """Raw rows of publication_attempts, oldest first."""
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM publication_attempts ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]
