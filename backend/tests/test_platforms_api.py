"""Platform availability: built from local configuration, never exposing it."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import (
    InMemoryCredentialStore,
    client_config_json,
    instagram_app_config_json,
    threads_app_config_json,
)
from tests.fakes_telegram import telegram_app_config_json

SENTINEL = "SENTINEL-7f3a9c"


def _with_sentinels(config: str) -> str:
    """Replace every string value of a valid config with a recognisable sentinel."""

    def mark(value: object) -> object:
        if isinstance(value, dict):
            return {key: mark(item) for key, item in value.items()}
        if isinstance(value, list):
            return [mark(item) for item in value]
        if isinstance(value, str) and not value.startswith("http"):
            return f"{SENTINEL}-{value}"
        return value

    return json.dumps(mark(json.loads(config)))


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """YouTube, Instagram, Threads and Telegram configured; TikTok invalid; no media
    delivery. Every file lives in a directory whose name is a sentinel too."""
    directory = tmp_path / f"{SENTINEL}-config"
    directory.mkdir()
    files = {
        "AUTOPUBLISHER_GOOGLE_OAUTH_CLIENT_FILE": client_config_json(),
        "AUTOPUBLISHER_INSTAGRAM_APP_FILE": instagram_app_config_json(),
        "AUTOPUBLISHER_THREADS_APP_FILE": threads_app_config_json(),
        "AUTOPUBLISHER_TELEGRAM_APP_FILE": telegram_app_config_json(),
        "AUTOPUBLISHER_TIKTOK_APP_FILE": json.dumps({"client_key": SENTINEL}),
    }
    for variable, content in files.items():
        path = directory / f"{variable.lower()}.json"
        path.write_text(content)
        monkeypatch.setenv(variable, str(path))
    monkeypatch.setenv(
        "AUTOPUBLISHER_MEDIA_DELIVERY_FILE", str(directory / "missing.json")
    )
    monkeypatch.delenv("AUTOPUBLISHER_OAUTH_REDIRECT_URI", raising=False)
    return directory


@pytest.fixture
def platforms_client(
    db_path: Path, media_dir: Path, config_dir: Path
) -> Iterator[TestClient]:
    app = create_app(
        db_path,
        media_dir,
        tiktok_credential_store=InMemoryCredentialStore(),
        instagram_credential_store=InMemoryCredentialStore(),
        threads_credential_store=InMemoryCredentialStore(),
    )
    with TestClient(app) as client:
        yield client


def test_platform_availability(platforms_client: TestClient) -> None:
    response = platforms_client.get("/api/platforms")

    assert response.status_code == 200
    body = {item["platform"]: item for item in response.json()}
    summary = {
        platform: (item["status"], item["can_connect"], item["missing"])
        for platform, item in body.items()
    }
    assert summary == {
        "youtube": ("configured", True, []),
        "instagram": ("partial", True, ["media_delivery"]),
        "tiktok": ("not_configured", False, ["app_credentials"]),
        "x": ("coming_soon", False, []),
        "threads": ("partial", True, ["media_delivery"]),
        "telegram": ("configured", True, []),
    }
    assert body["x"]["integration_available"] is False
    assert body["tiktok"]["message"] == (
        "The TikTok app credentials are missing or invalid."
    )


def test_platforms_never_expose_configuration(
    platforms_client: TestClient, config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Configured files whose every value is a sentinel.
    for name in (
        "autopublisher_google_oauth_client_file.json",
        "autopublisher_instagram_app_file.json",
        "autopublisher_threads_app_file.json",
        "autopublisher_telegram_app_file.json",
    ):
        path = config_dir / name
        path.write_text(_with_sentinels(path.read_text()))

    text = platforms_client.get("/api/platforms").text

    assert SENTINEL not in text
    assert str(config_dir) not in text
    assert "AUTOPUBLISHER_" not in text
    assert ".json" not in text
