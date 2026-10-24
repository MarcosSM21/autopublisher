import io
import json
import logging
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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

from app import auth, config, instance_lock, media
from app.credential_store import CredentialStoreProbe
from app.deployment import DataLayout, DeploymentSettings, parse_host_config
from app.instagram_publishing import InstagramPublishSettings
from app.main import create_app
from app.media import StreamInfo, VideoStreams
from app.models import Platform
from app.publishing import PublishingSettings
from app.scheduler import SchedulerSettings, TickReport
from app.youtube_upload import YouTubeUploadSettings
from tests.fakes import (
    ALL_SCOPES,
    FAKE_AUTH_CODE,
    FAKE_IG_CODE,
    FAKE_IG_REDIRECT_URI,
    FAKE_TH_CODE,
    FAKE_TH_REDIRECT_URI,
    FAKE_TT_CODE,
    TT_ALL_SCOPES,
    TT_BASIC,
    TT_PUBLISH,
    FakeClock,
    FakeGoogle,
    FakeMediaDeliveryProvider,
    FakeMeta,
    FakePublisher,
    FakeThreads,
    FakeTikTok,
    InMemoryCredentialStore,
    client_config_json,
    instagram_app_config_json,
    media_delivery_config_json,
    threads_app_config_json,
    tiktok_app_config_json,
)
from tests.fakes_telegram import FakeTelegramGateway, telegram_app_config_json


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    return tmp_path / "media"


@pytest.fixture
def client(db_path: Path, media_dir: Path) -> Iterator[TestClient]:
    app = create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
    )
    with TestClient(app) as test_client:
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


@pytest.fixture(autouse=True)
def isolate_host_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Host configuration, logs and installation data live under `tmp_path`, never
    in the real `~/.config`, `~/.local/state` or `~/.local/share` (Feature 020)."""
    for name in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "xdg" / name.lower()))
    for name in ("AUTOPUBLISHER_CONFIG", "AUTOPUBLISHER_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolate_lock_root(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Instance locks use a temporary home instead of the password database one
    (internal test seam: the environment never decides where locks live). It lives
    outside `tmp_path`, which some tests expect to hold only their own files."""
    home = tmp_path_factory.mktemp("home")
    home.chmod(0o700)
    monkeypatch.setattr(instance_lock, "_passwd_home", lambda uid: home)
    return home.resolve() / ".local" / "state" / "autopublisher" / "locks"


def stop(client: TestClient) -> None:
    """Shut an app down before starting another one on the same database: like a
    real restart, two servers never share it (instance locks, Feature 020). The
    fixture that opened `client` may exit it again later; that is a no-op."""
    client.__exit__(None, None, None)


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
        tiktok_credential_store=InMemoryCredentialStore(),
        credential_store=credential_store,
        google_transport=fake_google.transport(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
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
        tiktok_credential_store=InMemoryCredentialStore(),
        credential_store=credential_store,
        google_transport=fake_google.transport(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
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


# --- Scheduler (Feature 007) --------------------------------------------------------


@pytest.fixture
def fake_clock() -> FakeClock:
    """Starts at the real time, so API rules about future dates still hold."""
    return FakeClock()


@pytest.fixture
def fake_publisher() -> FakePublisher:
    return FakePublisher()


def make_scheduler_app(
    db_path: Path,
    media_dir: Path,
    clock: FakeClock,
    *,
    credential_store: InMemoryCredentialStore | None = None,
    fake_google: FakeGoogle | None = None,
    recorded_sleeps: list[float] | None = None,
    **scheduler_options: Any,
) -> FastAPI:
    """An app whose scheduler uses the fake clock and only runs when asked
    (`autostart=False` unless overridden)."""
    sleeps = recorded_sleeps if recorded_sleeps is not None else []
    options: dict[str, Any] = {"autostart": False, "clock": clock.now}
    options.update(scheduler_options)
    return create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        credential_store=credential_store or InMemoryCredentialStore(),
        google_transport=(fake_google or FakeGoogle()).transport(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        publishing_settings=PublishingSettings(sleep=sleeps.append),
        youtube_upload_settings=YouTubeUploadSettings(
            chunk_size=256 * 1024, slice_size=64 * 1024, sleep=sleeps.append
        ),
        scheduler_settings=SchedulerSettings(**options),
        clock=clock.now,
    )


@pytest.fixture
def scheduler_client(
    db_path: Path,
    media_dir: Path,
    oauth_client_file: Path,
    credential_store: InMemoryCredentialStore,
    fake_google: FakeGoogle,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
) -> Iterator[TestClient]:
    """Scheduler with the fake clock and the YouTube simulator."""
    app = make_scheduler_app(
        db_path,
        media_dir,
        fake_clock,
        credential_store=credential_store,
        fake_google=fake_google,
        recorded_sleeps=recorded_sleeps,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_scheduler_client(
    db_path: Path,
    media_dir: Path,
    fake_clock: FakeClock,
    fake_publisher: FakePublisher,
) -> Iterator[TestClient]:
    """Scheduler with the fake clock and a `FakePublisher` for YouTube accounts."""
    app = make_scheduler_app(db_path, media_dir, fake_clock)
    with TestClient(app) as test_client:
        use_fake_publisher(test_client, fake_publisher)
        yield test_client


def use_fake_publisher(client: TestClient, publisher: FakePublisher) -> None:
    """Replace the YouTube publisher; the scheduler shares the same registry."""
    app = client.app
    assert isinstance(app, FastAPI)
    app.state.publishers[Platform.YOUTUBE] = publisher


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def in_minutes(clock: FakeClock, minutes: float) -> datetime:
    """A whole-minute instant about `minutes` after the fake clock (publications are
    scheduled to the minute)."""
    return (clock.now() + timedelta(minutes=minutes)).replace(second=0, microsecond=0)


def arm(db_path: Path, publication_id: int) -> None:
    """Enable auto-publish directly in the database (tests before the API exists)."""
    run_sql(
        db_path,
        "UPDATE publications SET auto_publish_enabled = 1 WHERE id = ?",
        publication_id,
    )


def run_tick(client: TestClient) -> TickReport:
    app = client.app
    assert isinstance(app, FastAPI)
    report: TickReport = app.state.scheduler.run_once()
    return report


def scheduled_publication(
    client: TestClient,
    db_path: Path,
    at: datetime,
    *,
    fake_google: FakeGoogle | None = None,
    project_name: str = "Cyber",
    armed: bool = True,
) -> dict[str, Any]:
    """A YouTube video publication scheduled at `at`, with complete options and
    (by default) armed. With `fake_google` the account is really connected to the
    simulator; otherwise it is meant for a `FakePublisher`."""
    setup = setup_publishable(
        client,
        fake_google or FakeGoogle(),
        scheduled_at=iso(at),
        project_name=project_name,
        connect=fake_google is not None,
    )
    publication_id = setup["publication"]["id"]
    set_youtube_options(client, publication_id)
    if armed:
        arm(db_path, publication_id)
    return setup


# --- Instagram Login (Feature 008) ---------------------------------------------------


@pytest.fixture
def instagram_app_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "instagram-app.json"
    path.write_text(instagram_app_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_INSTAGRAM_APP_FILE", str(path))
    return path


@pytest.fixture
def instagram_credential_store() -> InMemoryCredentialStore:
    return InMemoryCredentialStore()


@pytest.fixture
def fake_meta() -> FakeMeta:
    return FakeMeta()


def make_instagram_app(
    db_path: Path,
    media_dir: Path,
    store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    clock: FakeClock,
) -> FastAPI:
    return create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=store,
        instagram_transport=fake_meta.transport(),
        scheduler_settings=SchedulerSettings(autostart=False),
        clock=clock.now,
    )


@pytest.fixture
def instagram_client(
    db_path: Path,
    media_dir: Path,
    instagram_app_file: Path,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
) -> Iterator[TestClient]:
    """Instagram endpoints with the fake Meta, an in-memory store and the fake clock
    (shared by the attempt registry and the token lifecycle)."""
    app = make_instagram_app(
        db_path, media_dir, instagram_credential_store, fake_meta, fake_clock
    )
    with TestClient(app) as test_client:
        yield test_client


def create_instagram_account(
    client: TestClient,
    project_name: str = "Cyber",
    handle: str = "cyberstudio",
    project_id: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return (project_id, account) for a new Instagram account."""
    if project_id is None:
        project_id = create_project(client, project_name)["id"]
    account = create_account(client, project_id, "instagram", handle)
    return project_id, account


def start_instagram_authorization(
    client: TestClient, account_id: int
) -> tuple[str, str]:
    """Start an Instagram authorization; return its (attempt_id, state)."""
    response = client.post(f"/api/accounts/{account_id}/instagram-connection/authorize")
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    state = parse_qs(urlsplit(body["authorization_url"]).query)["state"][0]
    return body["attempt_id"], state


def redirect_url_for(state: str, code: str = FAKE_IG_CODE) -> str:
    """The address Instagram sends the browser to (Meta appends `#_`)."""
    return f"{FAKE_IG_REDIRECT_URI}?code={code}&state={state}#_"


def complete_instagram(
    client: TestClient, attempt_id: str, redirect_url: str
) -> httpx.Response:
    return client.post(
        f"/api/instagram/oauth/attempts/{attempt_id}/complete",
        json={"redirect_url": redirect_url},
    )


def connect_instagram(
    client: TestClient,
    account_id: int,
    fake_meta: FakeMeta | None = None,
    **identity: Any,
) -> dict[str, Any]:
    """Run authorize → complete with the fake Meta and return the connection."""
    if fake_meta is not None and identity:
        fake_meta.set_identity(**identity)
    attempt_id, state = start_instagram_authorization(client, account_id)
    response = complete_instagram(client, attempt_id, redirect_url_for(state))
    assert response.status_code == 200, response.text
    attempt: dict[str, Any] = response.json()
    assert attempt["status"] == "completed", attempt
    connection: dict[str, Any] = attempt["connection"]
    return connection


def get_instagram_connection(client: TestClient, account_id: int) -> dict[str, Any]:
    response = client.get(f"/api/accounts/{account_id}/instagram-connection")
    assert response.status_code == 200, response.text
    connection: dict[str, Any] = response.json()
    return connection


def instagram_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM instagram_connections ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


# --- Instagram publishing (Feature 009) ----------------------------------------------

IG_DESCRIPTION = "Summer drop."
IG_HASHTAGS = ["cyber", "studio"]
IG_CAPTION = "Summer drop.\n\n#cyber #studio"

VALID_REEL_STREAMS = VideoStreams(
    format_names=frozenset({"mov", "mp4"}),
    duration_seconds=10.0,
    size_bytes=1000,
    bit_rate=8_000_000,
    streams=(
        StreamInfo(
            codec_type="video",
            codec_name="h264",
            width=1080,
            height=1920,
            frame_rate=30.0,
            pix_fmt="yuv420p",
            field_order="progressive",
            bit_rate=7_800_000,
        ),
        StreamInfo(
            codec_type="audio", codec_name="aac", sample_rate=48_000, channels=2
        ),
    ),
)


@pytest.fixture(autouse=True)
def stub_probe_video_streams(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without `real_ffprobe`, videos cannot be inspected unless a test allows it."""
    if request.node.get_closest_marker("real_ffprobe") is None:
        monkeypatch.setattr(media, "probe_video_streams", lambda path: None)


def allow_reels(
    monkeypatch: pytest.MonkeyPatch, streams: VideoStreams = VALID_REEL_STREAMS
) -> None:
    """Make every video look like a valid Reel to the Instagram checks."""
    monkeypatch.setattr(media, "probe_video_streams", lambda path: streams)
    monkeypatch.setattr(media, "moov_before_mdat", lambda path: True)


@pytest.fixture
def media_delivery_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "media-delivery.json"
    path.write_text(media_delivery_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_MEDIA_DELIVERY_FILE", str(path))
    return path


@pytest.fixture
def no_media_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "AUTOPUBLISHER_MEDIA_DELIVERY_FILE", str(tmp_path / "missing-delivery.json")
    )


@pytest.fixture
def fake_delivery() -> FakeMediaDeliveryProvider:
    return FakeMediaDeliveryProvider()


def make_instagram_publishing_app(
    db_path: Path,
    media_dir: Path,
    store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    delivery: FakeMediaDeliveryProvider,
    clock: FakeClock,
    sleeps: list[float],
    **scheduler_options: Any,
) -> FastAPI:
    """Instagram publishing with the fake Meta, the fake media delivery provider, the
    fake clock and waits that are only recorded."""
    options: dict[str, Any] = {"autostart": False, "clock": clock.now}
    options.update(scheduler_options)
    return create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        credential_store=InMemoryCredentialStore(),
        instagram_credential_store=store,
        instagram_transport=fake_meta.transport(),
        publishing_settings=PublishingSettings(sleep=sleeps.append),
        media_delivery_provider=delivery,
        instagram_publish_settings=InstagramPublishSettings(
            sleep=sleeps.append, clock=clock.now
        ),
        scheduler_settings=SchedulerSettings(**options),
        clock=clock.now,
    )


@pytest.fixture
def ig_client(
    db_path: Path,
    media_dir: Path,
    instagram_app_file: Path,
    media_delivery_file: Path,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_delivery: FakeMediaDeliveryProvider,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
) -> Iterator[TestClient]:
    app = make_instagram_publishing_app(
        db_path,
        media_dir,
        instagram_credential_store,
        fake_meta,
        fake_delivery,
        fake_clock,
        recorded_sleeps,
    )
    with TestClient(app) as test_client:
        yield test_client


def instagram_media(kind: str) -> tuple[str, bytes]:
    """(file name, bytes) of a content of the given kind."""
    if kind == "jpeg":
        return "poster.jpg", make_image("JPEG", (1080, 1080))
    if kind == "png":
        return "poster.png", make_image("PNG", (1080, 1350))
    if kind == "webp":
        return "poster.webp", make_image("WEBP", (1080, 1080))
    if kind == "wide":
        return "banner.jpg", make_image("JPEG", (1000, 300))
    if kind == "reel":
        return "reel.mp4", make_mp4(payload=bytes(range(256)) * 40)
    if kind == "webm":
        return "clip.webm", make_webm(b"video")
    raise ValueError(kind)


def instagram_publication(
    client: TestClient,
    *,
    kind: str = "jpeg",
    scheduled_at: str | None = None,
    project_name: str = "Cyber",
    connect: bool = True,
    is_ai_generated: bool | None = False,
    description: str | None = IG_DESCRIPTION,
    hashtags: list[str] | None = None,
) -> dict[str, Any]:
    """Project, Instagram account (connected to the fake Meta by default), content
    and publication; AI-generated declared as No unless told otherwise."""
    _, account = create_instagram_account(client, project_name)
    if connect:
        connect_instagram(client, account["id"])
    project_id = account["project_id"]
    name, data = instagram_media(kind)
    content = import_one(client, project_id, name, data)["content"]
    response = client.patch(
        f"/api/contents/{content['id']}",
        json={
            "title": "Not sent to Instagram",
            "description": description,
            "hashtags": IG_HASHTAGS if hashtags is None else hashtags,
        },
    )
    assert response.status_code == 200, response.text
    content = response.json()
    publication = create_publications(
        client, content["id"], [account["id"]], scheduled_at
    )[0]
    if is_ai_generated is not None:
        response = client.put(
            f"/api/publications/{publication['id']}/instagram-options",
            json={"is_ai_generated": is_ai_generated},
        )
        assert response.status_code == 200, response.text
    return {
        "account": account,
        "content": content,
        "publication": publication,
    }


def temporary_media_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM temporary_media_objects ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def instagram_run_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM instagram_publish_runs ORDER BY attempt_id"
        ).fetchall()
    return [dict(row) for row in rows]


# --- Threads API (Feature 010) -------------------------------------------------------


@pytest.fixture
def threads_app_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "threads-app.json"
    path.write_text(threads_app_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_THREADS_APP_FILE", str(path))
    return path


@pytest.fixture
def threads_credential_store() -> InMemoryCredentialStore:
    return InMemoryCredentialStore()


@pytest.fixture
def fake_threads() -> FakeThreads:
    return FakeThreads()


def make_threads_app(
    db_path: Path,
    media_dir: Path,
    store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    clock: FakeClock,
) -> FastAPI:
    return create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=store,
        threads_transport=fake_threads.transport(),
        scheduler_settings=SchedulerSettings(autostart=False),
        clock=clock.now,
    )


@pytest.fixture
def threads_client(
    db_path: Path,
    media_dir: Path,
    threads_app_file: Path,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_clock: FakeClock,
) -> Iterator[TestClient]:
    """Threads endpoints with the fake Threads API, an in-memory store and the fake
    clock (shared by the attempt registry and the token lifecycle)."""
    app = make_threads_app(
        db_path, media_dir, threads_credential_store, fake_threads, fake_clock
    )
    with TestClient(app) as test_client:
        yield test_client


def create_threads_account(
    client: TestClient,
    project_name: str = "Cyber",
    handle: str = "cyberstudio",
    project_id: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return (project_id, account) for a new Threads account."""
    if project_id is None:
        project_id = create_project(client, project_name)["id"]
    account = create_account(client, project_id, "threads", handle)
    return project_id, account


def start_threads_authorization(client: TestClient, account_id: int) -> tuple[str, str]:
    """Start a Threads authorization; return its (attempt_id, state)."""
    response = client.post(f"/api/accounts/{account_id}/threads-connection/authorize")
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    state = parse_qs(urlsplit(body["authorization_url"]).query)["state"][0]
    return body["attempt_id"], state


def threads_redirect_url_for(state: str, code: str = FAKE_TH_CODE) -> str:
    """The address Threads sends the browser to (Meta appends `#_`)."""
    return f"{FAKE_TH_REDIRECT_URI}?code={code}&state={state}#_"


def complete_threads(
    client: TestClient, attempt_id: str, redirect_url: str
) -> httpx.Response:
    return client.post(
        f"/api/threads/oauth/attempts/{attempt_id}/complete",
        json={"redirect_url": redirect_url},
    )


def connect_threads(
    client: TestClient,
    account_id: int,
    fake_threads: FakeThreads | None = None,
    **identity: Any,
) -> dict[str, Any]:
    """Run authorize → complete with the fake Threads API and return the connection."""
    if fake_threads is not None and identity:
        fake_threads.set_identity(**identity)
    attempt_id, state = start_threads_authorization(client, account_id)
    response = complete_threads(client, attempt_id, threads_redirect_url_for(state))
    assert response.status_code == 200, response.text
    attempt: dict[str, Any] = response.json()
    assert attempt["status"] == "completed", attempt
    connection: dict[str, Any] = attempt["connection"]
    return connection


def get_threads_connection(client: TestClient, account_id: int) -> dict[str, Any]:
    response = client.get(f"/api/accounts/{account_id}/threads-connection")
    assert response.status_code == 200, response.text
    connection: dict[str, Any] = response.json()
    return connection


def threads_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM threads_connections ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


# --- Threads publishing (Feature 011) ------------------------------------------------

TH_TEXT_DESCRIPTION = "Validation post — ¡acentos! 🚀 https://example.com/a?b=1"
TH_TEXT_HASHTAGS = ["autopublisher", "threads"]
TH_TEXT = f"{TH_TEXT_DESCRIPTION}\n\n#autopublisher #threads"


def make_threads_publishing_app(
    db_path: Path,
    media_dir: Path,
    store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    delivery: FakeMediaDeliveryProvider,
    clock: FakeClock,
    sleeps: list[float],
    **scheduler_options: Any,
) -> FastAPI:
    """Threads publishing with the fake Threads API, the fake media delivery
    provider and the fake clock. Waits are recorded and only advance the fake clock,
    so the age of containers grows without really sleeping."""
    from app.threads_publishing import ThreadsPublishSettings

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    options: dict[str, Any] = {"autostart": False, "clock": clock.now}
    options.update(scheduler_options)
    return create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=store,
        threads_transport=fake_threads.transport(),
        publishing_settings=PublishingSettings(sleep=sleep),
        media_delivery_provider=delivery,
        threads_publish_settings=ThreadsPublishSettings(sleep=sleep, clock=clock.now),
        scheduler_settings=SchedulerSettings(**options),
        clock=clock.now,
    )


@pytest.fixture
def threads_publishing_client(
    db_path: Path,
    media_dir: Path,
    threads_app_file: Path,
    media_delivery_file: Path,
    threads_credential_store: InMemoryCredentialStore,
    fake_threads: FakeThreads,
    fake_delivery: FakeMediaDeliveryProvider,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
) -> Iterator[TestClient]:
    app = make_threads_publishing_app(
        db_path,
        media_dir,
        threads_credential_store,
        fake_threads,
        fake_delivery,
        fake_clock,
        recorded_sleeps,
    )
    with TestClient(app) as test_client:
        yield test_client


def create_text_publications(
    client: TestClient,
    project_id: int,
    account_ids: list[int],
    *,
    description: str | None = TH_TEXT_DESCRIPTION,
    hashtags: list[str] | None = None,
    scheduled_at: str | None = None,
    auto_publish_enabled: bool = False,
) -> httpx.Response:
    body: dict[str, Any] = {
        "account_ids": account_ids,
        "description": description,
        "hashtags": TH_TEXT_HASHTAGS if hashtags is None else hashtags,
        "auto_publish_enabled": auto_publish_enabled,
    }
    if scheduled_at is not None:
        body["scheduled_at"] = scheduled_at
    return client.post(f"/api/projects/{project_id}/text-publications", json=body)


def threads_text_publication(
    client: TestClient,
    *,
    description: str | None = TH_TEXT_DESCRIPTION,
    hashtags: list[str] | None = None,
    scheduled_at: str | None = None,
    project_name: str = "Cyber",
    connect: bool = True,
) -> dict[str, Any]:
    """Project, Threads account (connected to the fake Threads API by default) and a
    text publication without content."""
    project_id, account = create_threads_account(client, project_name)
    if connect:
        connect_threads(client, account["id"])
    response = create_text_publications(
        client,
        project_id,
        [account["id"]],
        description=description,
        hashtags=hashtags,
        scheduled_at=scheduled_at,
    )
    assert response.status_code == 201, response.text
    return {"account": account, "publication": response.json()[0]}


def threads_media(media_format: str) -> tuple[str, bytes]:
    """(file name, bytes) of a Threads image or video content."""
    if media_format == "jpeg":
        return "poster.jpg", make_image("JPEG", (1080, 1350))
    if media_format == "png":
        return "poster.png", make_image("PNG", (1080, 1080))
    if media_format == "webp":
        return "poster.webp", make_image("WEBP", (1080, 1080))
    if media_format == "mp4":
        return "clip.mp4", make_mp4(payload=bytes(range(256)) * 40)
    if media_format == "mov":
        return "clip.mov", make_mov(payload=bytes(range(256)) * 40)
    raise ValueError(media_format)


def _threads_media_publication(
    client: TestClient,
    media_format: str,
    *,
    project_name: str,
    connect: bool,
    scheduled_at: str | None,
    alt_text: str | None,
) -> dict[str, Any]:
    project_id, account = create_threads_account(client, project_name)
    if connect:
        connect_threads(client, account["id"])
    name, data = threads_media(media_format)
    content = import_one(client, project_id, name, data)["content"]
    response = client.patch(
        f"/api/contents/{content['id']}",
        json={
            "title": "Not sent to Threads",
            "description": "Summer drop.",
            "hashtags": ["cyber"],
        },
    )
    assert response.status_code == 200, response.text
    content = response.json()
    publication = create_publications(
        client, content["id"], [account["id"]], scheduled_at
    )[0]
    if alt_text is not None:
        response = client.put(
            f"/api/publications/{publication['id']}/threads-options",
            json={"alt_text": alt_text},
        )
        assert response.status_code == 200, response.text
    return {"account": account, "content": content, "publication": publication}


def threads_image_publication(
    client: TestClient,
    *,
    format: str = "jpeg",
    project_name: str = "Cyber",
    connect: bool = True,
    scheduled_at: str | None = None,
    alt_text: str | None = None,
) -> dict[str, Any]:
    return _threads_media_publication(
        client,
        format,
        project_name=project_name,
        connect=connect,
        scheduled_at=scheduled_at,
        alt_text=alt_text,
    )


def probe_streams(
    *,
    video: dict[str, Any] | None = None,
    audio: dict[str, Any] | None = None,
    has_audio: bool = True,
    **container: Any,
) -> VideoStreams:
    """`VideoStreams` of a video that meets every Threads rule, with overrides."""
    video_values: dict[str, Any] = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1080,
        "height": 1920,
        "frame_rate": 30.0,
        "pix_fmt": "yuv420p",
        "field_order": "progressive",
        "bit_rate": 7_800_000,
    }
    video_values.update(video or {})
    audio_values: dict[str, Any] = {
        "codec_type": "audio",
        "codec_name": "aac",
        "sample_rate": 48_000,
        "channels": 2,
        "bit_rate": 128_000,
    }
    audio_values.update(audio or {})
    streams = [StreamInfo(**video_values)]
    if has_audio:
        streams.append(StreamInfo(**audio_values))
    values: dict[str, Any] = {
        "format_names": frozenset({"mov", "mp4"}),
        "duration_seconds": 10.0,
        "size_bytes": 1000,
        "bit_rate": 8_000_000,
        "streams": tuple(streams),
    }
    values.update(container)
    return VideoStreams(**values)


def threads_video_publication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    streams: VideoStreams | None = None,
    format: str = "mp4",
    project_name: str = "Cyber",
    connect: bool = True,
    scheduled_at: str | None = None,
    alt_text: str | None = None,
) -> dict[str, Any]:
    """A Threads video publication whose file looks like `streams` to ffprobe."""
    probed = probe_streams() if streams is None else streams
    monkeypatch.setattr(media, "probe_video_streams", lambda path: probed)
    monkeypatch.setattr(media, "moov_before_mdat", lambda path: True)
    return _threads_media_publication(
        client,
        format,
        project_name=project_name,
        connect=connect,
        scheduled_at=scheduled_at,
        alt_text=alt_text,
    )


def threads_run_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM threads_publish_runs ORDER BY attempt_id"
        ).fetchall()
    return [dict(row) for row in rows]


# --- TikTok Login Kit (Feature 012) --------------------------------------------------

TIKTOK_BASE_URL = "http://127.0.0.1:8000"
TIKTOK_LOOPBACK_CLIENT = ("127.0.0.1", 50000)


@pytest.fixture
def tiktok_app_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tiktok-app.json"
    path.write_text(tiktok_app_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_TIKTOK_APP_FILE", str(path))
    return path


@pytest.fixture
def tiktok_credential_store() -> InMemoryCredentialStore:
    return InMemoryCredentialStore()


@pytest.fixture
def fake_tiktok() -> FakeTikTok:
    return FakeTikTok()


def make_tiktok_app(
    db_path: Path,
    media_dir: Path,
    store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    clock: FakeClock,
    credential_probe: CredentialStoreProbe | None = None,
) -> FastAPI:
    return create_app(
        db_path,
        media_dir,
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        tiktok_credential_store=store,
        tiktok_transport=fake_tiktok.transport(),
        scheduler_settings=SchedulerSettings(autostart=False),
        clock=clock.now,
        credential_probe=credential_probe,
    )


def tiktok_test_client(
    app: FastAPI,
    base_url: str = TIKTOK_BASE_URL,
    client: tuple[str, int] = TIKTOK_LOOPBACK_CLIENT,
) -> TestClient:
    """A client whose server socket and peer are loopback, like the real browser."""
    return TestClient(app, base_url=base_url, client=client)


@pytest.fixture
def tiktok_client(
    db_path: Path,
    media_dir: Path,
    tiktok_app_file: Path,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
) -> Iterator[TestClient]:
    """TikTok endpoints with the fake TikTok API, an in-memory store and the fake
    clock (shared by the attempt registry and the credential lifecycle)."""
    app = make_tiktok_app(
        db_path, media_dir, tiktok_credential_store, fake_tiktok, fake_clock
    )
    with tiktok_test_client(app) as test_client:
        yield test_client


def create_tiktok_account(
    client: TestClient,
    project_name: str = "Cyber",
    handle: str = "cyberstudio",
    project_id: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return (project_id, account) for a new TikTok account."""
    if project_id is None:
        project_id = create_project(client, project_name)["id"]
    account = create_account(client, project_id, "tiktok", handle)
    return project_id, account


def start_tiktok_authorization(
    client: TestClient, account_id: int, fake_tiktok: FakeTikTok | None = None
) -> tuple[str, str, str]:
    """Start a TikTok authorization; return its (attempt_id, state, code_challenge).

    With `fake_tiktok`, the challenge is registered so the fake accepts the verifier.
    """
    response = client.post(f"/api/accounts/{account_id}/tiktok-connection/authorize")
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    query = parse_qs(urlsplit(body["authorization_url"]).query)
    state, challenge = query["state"][0], query["code_challenge"][0]
    if fake_tiktok is not None:
        fake_tiktok.register_challenge(challenge)
    return body["attempt_id"], state, challenge


def tiktok_callback(
    client: TestClient,
    state: str | None,
    code: str | None = FAKE_TT_CODE,
    **extra: str,
) -> httpx.Response:
    """Call the callback like TikTok's redirect would, without following the 303."""
    params: dict[str, str] = {}
    if code is not None:
        params["code"] = code
    if state is not None:
        params["state"] = state
    params.update(extra)
    return client.get(
        "/api/tiktok/oauth/callback", params=params, follow_redirects=False
    )


def poll_tiktok_attempt(client: TestClient, attempt_id: str) -> dict[str, Any]:
    response = client.get(f"/api/tiktok/oauth/attempts/{attempt_id}")
    assert response.status_code == 200, response.text
    attempt: dict[str, Any] = response.json()
    return attempt


def connect_tiktok(
    client: TestClient, account_id: int, fake_tiktok: FakeTikTok
) -> dict[str, Any]:
    """Run authorize → callback with the fake TikTok API; return the connection."""
    attempt_id, state, _ = start_tiktok_authorization(client, account_id, fake_tiktok)
    response = tiktok_callback(client, state)
    assert response.status_code == 303, response.text
    attempt = poll_tiktok_attempt(client, attempt_id)
    assert attempt["status"] == "completed", attempt
    connection: dict[str, Any] = attempt["connection"]
    return connection


def get_tiktok_connection(client: TestClient, account_id: int) -> dict[str, Any]:
    response = client.get(f"/api/accounts/{account_id}/tiktok-connection")
    assert response.status_code == 200, response.text
    connection: dict[str, Any] = response.json()
    return connection


def tiktok_rows(
    db_path: Path, table: str = "tiktok_connections"
) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(row) for row in rows]


def set_tiktok_granted_scopes(
    store: InMemoryCredentialStore,
    db_path: Path,
    account_id: int,
    scopes: list[str],
) -> None:
    """Rewrite the scopes recorded in the account's TikTok secret, e.g. to simulate a
    connection made before Feature 014 with the base scopes only."""
    [row] = [row for row in tiktok_rows(db_path) if row["account_id"] == account_id]
    secret = json.loads(store.secrets[row["credential_ref"]])
    secret["scopes"] = sorted(scopes)
    store.secrets[row["credential_ref"]] = json.dumps(secret)


def connect_tiktok_base_scopes(
    client: TestClient,
    account_id: int,
    fake_tiktok: FakeTikTok,
    store: InMemoryCredentialStore,
    db_path: Path,
) -> dict[str, Any]:
    """A connection as Feature 012 left it: `user.info.basic` and `video.publish`
    only (Connect now requires the three scopes, so the secret is rewritten)."""
    connect_tiktok(client, account_id, fake_tiktok)
    set_tiktok_granted_scopes(store, db_path, account_id, [TT_BASIC, TT_PUBLISH])
    fake_tiktok.requests.clear()
    return get_tiktok_connection(client, account_id)


def connect_tiktok_all_scopes(
    client: TestClient, account_id: int, fake_tiktok: FakeTikTok
) -> dict[str, Any]:
    """A connection granting the three requested scopes (incl. `video.upload`)."""
    fake_tiktok.scope = TT_ALL_SCOPES
    connection = connect_tiktok(client, account_id, fake_tiktok)
    fake_tiktok.requests.clear()
    return connection


# --- TikTok publishing (Feature 013) -------------------------------------------------

TT_DESCRIPTION = "Validation clip — please ignore"
TT_HASHTAGS = ["autopublisher"]
TT_CAPTION = "Validation clip — please ignore\n\n#autopublisher"
TT_OPTIONS: dict[str, Any] = {
    "mode": "DIRECT_POST",
    "privacy_level": "SELF_ONLY",
    "allow_comment": False,
    "allow_duet": False,
    "allow_stitch": False,
    "commercial_disclosure_enabled": False,
    "brand_organic_toggle": False,
    "brand_content_toggle": False,
    "is_aigc": False,
}
# The initial (unchosen) option values, as a row inserted by migration 0013.
TT_INITIAL_OPTIONS: dict[str, Any] = {
    "privacy_level": None,
    "allow_comment": False,
    "allow_duet": False,
    "allow_stitch": False,
    "commercial_disclosure_enabled": False,
    "brand_organic_toggle": False,
    "brand_content_toggle": False,
    "is_aigc": None,
}


def tiktok_probe_streams(
    *, video: dict[str, Any] | None = None, **container: Any
) -> VideoStreams:
    """`VideoStreams` of a video that meets every TikTok rule, with overrides."""
    video_values: dict[str, Any] = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1080,
        "height": 1920,
        "frame_rate": 30.0,
        "pix_fmt": "yuv420p",
    }
    video_values.update(video or {})
    values: dict[str, Any] = {
        "format_names": frozenset({"mov", "mp4"}),
        "duration_seconds": 12.4,
        "size_bytes": 1000,
        "bit_rate": 8_000_000,
        "streams": (
            StreamInfo(**video_values),
            StreamInfo(codec_type="audio", codec_name="aac"),
        ),
    }
    values.update(container)
    return VideoStreams(**values)


def allow_tiktok_video(
    monkeypatch: pytest.MonkeyPatch, streams: VideoStreams | None = None
) -> None:
    """Make every video look like `streams` (a valid TikTok video by default)."""
    probed = tiktok_probe_streams() if streams is None else streams
    monkeypatch.setattr(media, "probe_video_streams", lambda path: probed)


def tiktok_video(media_format: str = "mp4", size: int = 4096) -> tuple[str, bytes]:
    """(file name, bytes) of a small video of about `size` bytes, unique per size."""
    filler = bytes((i * 7 + size) % 251 for i in range(size))
    if media_format == "mp4":
        return "clip.mp4", make_mp4(payload=filler)
    if media_format == "mov":
        return "clip.mov", make_mov(payload=filler)
    if media_format == "webm":
        return "clip.webm", make_webm(payload=filler)
    raise ValueError(media_format)


def make_tiktok_publishing_app(
    db_path: Path,
    media_dir: Path,
    store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    clock: FakeClock,
    sleeps: list[float],
    *,
    single_chunk_max: int | None = None,
    chunk_size: int | None = None,
    **scheduler_options: Any,
) -> FastAPI:
    """TikTok publishing with the fake TikTok API and the fake clock. Waits are
    recorded and only advance the fake clock; chunk constants can be shrunk so
    multi-chunk uploads use files of a few KB."""
    from app.tiktok_publishing import TikTokPublishSettings

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    chunks: dict[str, Any] = {}
    if single_chunk_max is not None:
        chunks["single_chunk_max"] = single_chunk_max
    if chunk_size is not None:
        chunks["chunk_size"] = chunk_size
    options: dict[str, Any] = {"autostart": False, "clock": clock.now}
    options.update(scheduler_options)
    return create_app(
        db_path,
        media_dir,
        credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        tiktok_credential_store=store,
        tiktok_transport=fake_tiktok.transport(),
        publishing_settings=PublishingSettings(sleep=sleep),
        tiktok_publish_settings=TikTokPublishSettings(
            sleep=sleep, clock=clock.now, **chunks
        ),
        scheduler_settings=SchedulerSettings(**options),
        clock=clock.now,
    )


@pytest.fixture
def tiktok_publishing_client(
    db_path: Path,
    media_dir: Path,
    tiktok_app_file: Path,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
) -> Iterator[TestClient]:
    app = make_tiktok_publishing_app(
        db_path,
        media_dir,
        tiktok_credential_store,
        fake_tiktok,
        fake_clock,
        recorded_sleeps,
    )
    with tiktok_test_client(app) as test_client:
        yield test_client


def tiktok_publication(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    *,
    media_format: str = "mp4",
    size: int = 4096,
    streams: VideoStreams | None = None,
    description: str | None = TT_DESCRIPTION,
    hashtags: list[str] | None = None,
    connect: bool = True,
    scheduled_at: str | None = None,
    project_name: str = "Cyber",
    mode: str | None = "DIRECT_POST",
) -> dict[str, Any]:
    """Project, TikTok account (connected to the fake TikTok API by default), a
    small video content and its TikTok publication. With `mode` (`DIRECT_POST` by
    default, as every publication created before Feature 014, or `INBOX_UPLOAD`) the
    initial options are saved with that mode; `None` leaves the mode undecided."""
    allow_tiktok_video(monkeypatch, streams)
    project_id, account = create_tiktok_account(client, project_name)
    if connect:
        connect_tiktok(client, account["id"], fake_tiktok)
    name, data = tiktok_video(media_format, size)
    content = import_one(client, project_id, name, data)["content"]
    response = client.patch(
        f"/api/contents/{content['id']}",
        json={
            "title": "Not sent to TikTok",
            "description": description,
            "hashtags": TT_HASHTAGS if hashtags is None else hashtags,
        },
    )
    assert response.status_code == 200, response.text
    content = response.json()
    publication = create_publications(
        client, content["id"], [account["id"]], scheduled_at
    )[0]
    if mode is not None:
        response = client.put(
            f"/api/publications/{publication['id']}/tiktok-options",
            json={**TT_INITIAL_OPTIONS, "mode": mode},
        )
        assert response.status_code == 200, response.text
    fake_tiktok.requests.clear()
    return {
        "account": account,
        "content": content,
        "publication": publication,
        "data": data,
    }


def tiktok_ready(
    client: TestClient, publication_id: int, **overrides: Any
) -> dict[str, Any]:
    """Save complete TikTok options and record a valid consent for them; return
    the options read after the consent."""
    body = {**TT_OPTIONS, **overrides}
    response = client.put(
        f"/api/publications/{publication_id}/tiktok-options", json=body
    )
    assert response.status_code == 200, response.text
    options: dict[str, Any] = response.json()
    response = client.post(
        f"/api/publications/{publication_id}/tiktok-consent",
        json={
            "fingerprint": options["fingerprint"],
            "declaration_version": options["declaration"]["version"],
        },
    )
    assert response.status_code == 200, response.text
    consented: dict[str, Any] = response.json()
    return consented


def tiktok_run_rows(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM tiktok_publish_runs ORDER BY attempt_id"
        ).fetchall()
    return [dict(row) for row in rows]


def tiktok_ready_publication(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    *,
    options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A TikTok publication with complete options and a valid consent; the fake's
    request log is cleared."""
    created = tiktok_publication(client, fake_tiktok, monkeypatch, **kwargs)
    created["options"] = tiktok_ready(
        client, created["publication"]["id"], **(options or {})
    )
    fake_tiktok.requests.clear()
    return created


def tiktok_inbox_publication(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: Any,
) -> dict[str, Any]:
    """A TikTok publication in Upload to Inbox, connected with the three scopes (the
    fake's default); the fake's request log is cleared. Upload to Inbox needs no
    options nor consent."""
    created = tiktok_publication(
        client, fake_tiktok, monkeypatch, mode="INBOX_UPLOAD", **kwargs
    )
    fake_tiktok.statuses = [
        {"status": "PROCESSING_UPLOAD"},
        {"status": "SEND_TO_USER_INBOX"},
    ]
    fake_tiktok.requests.clear()
    return created


def publish_tiktok(client: TestClient, publication_id: int) -> httpx.Response:
    """`Publish now` and wait for the background execution."""
    response = client.post(f"/api/publications/{publication_id}/publish", json={})
    wait_idle(client)
    return response


def tiktok_attempts(client: TestClient, publication_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/publications/{publication_id}/attempts")
    assert response.status_code == 200, response.text
    attempts: list[dict[str, Any]] = response.json()
    return attempts


@pytest.fixture
def tiktok_chunked_client(
    db_path: Path,
    media_dir: Path,
    tiktok_app_file: Path,
    tiktok_credential_store: InMemoryCredentialStore,
    fake_tiktok: FakeTikTok,
    fake_clock: FakeClock,
    recorded_sleeps: list[float],
) -> Iterator[TestClient]:
    """Chunk constants shrunk so a 4 KB video is uploaded in 8 chunks of 512 B."""
    app = make_tiktok_publishing_app(
        db_path,
        media_dir,
        tiktok_credential_store,
        fake_tiktok,
        fake_clock,
        recorded_sleeps,
        single_chunk_max=1024,
        chunk_size=512,
    )
    with tiktok_test_client(app) as test_client:
        yield test_client


# --- Telegram (Feature 015) -----------------------------------------------------------


@pytest.fixture
def telegram_app_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "telegram-app.json"
    path.write_text(telegram_app_config_json())
    monkeypatch.setenv("AUTOPUBLISHER_TELEGRAM_APP_FILE", str(path))
    return path


@pytest.fixture
def telegram_credential_store() -> InMemoryCredentialStore:
    return InMemoryCredentialStore()


@pytest.fixture
def fake_telegram() -> FakeTelegramGateway:
    return FakeTelegramGateway()


@pytest.fixture
def telegram_client(
    db_path: Path,
    media_dir: Path,
    telegram_app_file: Path,
    telegram_credential_store: InMemoryCredentialStore,
    fake_telegram: FakeTelegramGateway,
    fake_clock: FakeClock,
) -> Iterator[TestClient]:
    """Telegram endpoints with the fake gateway, an in-memory store and the fake
    clock, shared by the API and a scheduler that only runs when asked."""
    app = create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
        telegram_credential_store=telegram_credential_store,
        telegram_gateway=fake_telegram,
        scheduler_settings=SchedulerSettings(autostart=False, clock=fake_clock.now),
        clock=fake_clock.now,
    )
    with TestClient(app) as test_client:
        yield test_client


# --- Installation mode (Feature 020) ------------------------------------------------

INSTALLATION_URL = "http://127.0.0.1:8000"
INSTALLATION_PASSWORD = "correct horse battery"


def installation_settings(tmp_path: Path, **values: Any) -> DeploymentSettings:
    """Installation settings whose data and frontend build live under `tmp_path`."""
    data = tmp_path / "data"
    host_values = {
        "data_dir": str(data),
        "frontend_dist": str(tmp_path / "dist"),
        **values,
    }
    host_config = parse_host_config(host_values, tmp_path / "config.toml")
    layout = DataLayout(
        data_dir=data,
        db_path=data / "autopublisher.db",
        media_dir=data / "media",
        platform_files={},
    )
    return DeploymentSettings.installation(host_config, layout)


def installation_app(settings: DeploymentSettings, **kwargs: Any) -> FastAPI:
    options: dict[str, Any] = {
        "tiktok_credential_store": InMemoryCredentialStore(),
        "instagram_credential_store": InMemoryCredentialStore(),
        "threads_credential_store": InMemoryCredentialStore(),
        "scheduler_settings": SchedulerSettings(autostart=False),
        **kwargs,
    }
    return create_app(deployment=settings, **options)


def installation_client(
    app: FastAPI,
    base_url: str = INSTALLATION_URL,
    client: tuple[str, int] = ("127.0.0.1", 50000),
) -> TestClient:
    """A browser on this app: its requests carry the matching `Origin`."""
    return TestClient(
        app, base_url=base_url, client=client, headers={"origin": base_url}
    )


def sign_in(client: TestClient, app: FastAPI) -> None:
    """Set the installation password (if needed) and sign `client` in; the app's
    lifespan must be running."""
    with app.state.session_factory() as db:
        if auth.current_password_hash(db) is None:
            auth.set_password(db, INSTALLATION_PASSWORD, datetime.now(UTC))
    response = client.post("/api/auth/login", json={"password": INSTALLATION_PASSWORD})
    assert response.status_code == 204, response.text


@pytest.fixture
def serve_process_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`serve` changes process-wide state: the installation data directory, the
    temporary directory, TMPDIR, the umask and the root log handlers. Put all of
    it back after the test."""
    monkeypatch.setattr(config, "_installation_data_dir", None)
    monkeypatch.setattr(tempfile, "tempdir", None)
    if "TMPDIR" in os.environ:
        monkeypatch.setenv("TMPDIR", os.environ["TMPDIR"])
    else:
        monkeypatch.delenv("TMPDIR", raising=False)
    umask = os.umask(0o022)
    os.umask(umask)
    root = logging.getLogger()
    level = root.level
    yield
    for handler in list(root.handlers):
        if getattr(handler, "_autopublisher_handler", False):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = False
    os.umask(umask)
