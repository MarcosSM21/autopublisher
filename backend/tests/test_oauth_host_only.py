"""YouTube and TikTok OAuth are host-only in installation mode (Feature 020 T017,
contracts/api.md §5, research §15-16)."""

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.loopback import is_loopback_request
from tests.conftest import (
    create_account,
    create_project,
    installation_app,
    installation_client,
    installation_settings,
    sign_in,
)

LAN_URL = "http://192.168.1.40:8000"
PLATFORMS = ("youtube", "tiktok")


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@pytest.fixture
def app(tmp_path: Path, oauth_client_file: Path, tiktok_app_file: Path) -> FastAPI:
    return installation_app(installation_settings(tmp_path, lan_enabled=True))


@pytest.fixture
def host(app: FastAPI) -> Iterator[TestClient]:
    """The browser on the host itself, at http://127.0.0.1:8000, signed in."""
    with installation_client(app) as client:
        sign_in(client, app)
        yield client


def _lan(app: FastAPI, peer: str = "192.168.1.50") -> TestClient:
    """A browser reaching the host's LAN address (socket 192.168.1.40)."""
    client = installation_client(app, base_url=LAN_URL, client=(peer, 50000))
    sign_in(client, app)
    return client


def _account(client: TestClient, platform: str) -> int:
    project = create_project(client, f"Cyber {platform}")
    return int(create_account(client, project["id"], platform, "cyber")["id"])


def _authorize(client: TestClient, platform: str, account_id: int) -> object:
    return client.post(f"/api/accounts/{account_id}/{platform}-connection/authorize")


def _attempts(app: FastAPI, platform: str) -> int:
    registry = (
        app.state.oauth_attempts if platform == "youtube" else app.state.tiktok_attempts
    )
    return len(registry._attempts)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_host_can_start(host: TestClient, platform: str) -> None:
    response = _authorize(host, platform, _account(host, platform))
    assert response.status_code == 201, response.text  # type: ignore[attr-defined]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_start_requires_a_session(
    host: TestClient, app: FastAPI, platform: str
) -> None:
    account_id = _account(host, platform)
    anonymous = installation_client(app)
    response = _authorize(anonymous, platform, account_id)
    assert response.status_code == 401  # type: ignore[attr-defined]
    assert _attempts(app, platform) == 0


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize(
    "peer", ["192.168.1.50", "192.168.1.40"], ids=["phone", "host-via-lan-ip"]
)
def test_lan_start_is_host_only(
    host: TestClient, app: FastAPI, platform: str, peer: str
) -> None:
    account_id = _account(host, platform)
    response = _authorize(_lan(app, peer), platform, account_id)
    assert response.status_code == 409  # type: ignore[attr-defined]
    error = response.json()["error"]  # type: ignore[attr-defined]
    assert error["code"] == "host_only_action"
    assert "http://127.0.0.1:8000" in error["message"]
    assert _attempts(app, platform) == 0  # checked before creating an attempt


@pytest.mark.parametrize(
    ("client", "server", "expected"),
    [
        (("127.0.0.1", 1), ("127.0.0.1", 8000), True),
        (("::1", 1), ("::1", 8000), True),
        (("127.0.0.1", 1), ("192.168.1.40", 8000), False),  # opened at the LAN IP
        (("192.168.1.50", 1), ("127.0.0.1", 8000), False),
        (None, ("127.0.0.1", 8000), False),
    ],
)
def test_host_action_needs_client_and_socket_loopback(
    client: object, server: object, expected: bool
) -> None:
    scope = {"client": client, "server": server, "headers": []}
    assert is_loopback_request(scope) is expected


def _youtube_state(host: TestClient) -> str:
    response = _authorize(host, "youtube", _account(host, "youtube"))
    url = response.json()["authorization_url"]  # type: ignore[attr-defined]
    return str(parse_qs(urlsplit(url).query)["state"][0])


def test_youtube_callback_from_the_lan_keeps_the_state(
    host: TestClient, app: FastAPI
) -> None:
    state = _youtube_state(host)
    lan = installation_client(app, base_url=LAN_URL, client=("192.168.1.50", 1))
    rejected = lan.get("/api/youtube/oauth/callback", params={"state": state})
    assert rejected.status_code == 400
    assert "Authorization not valid" in rejected.text

    # No session needed, and the state was not consumed by the rejected request.
    anonymous = installation_client(app)
    response = anonymous.get(
        "/api/youtube/oauth/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert "cancelled in Google" in response.text


def test_tiktok_callback_stays_public_and_loopback_only(
    host: TestClient, app: FastAPI
) -> None:
    host_response = _authorize(host, "tiktok", _account(host, "tiktok"))
    url = host_response.json()["authorization_url"]  # type: ignore[attr-defined]
    state = parse_qs(urlsplit(url).query)["state"][0]
    params = {"state": state, "error": "access_denied"}

    lan = installation_client(app, base_url=LAN_URL, client=("192.168.1.50", 1))
    lan_response = lan.get(
        "/api/tiktok/oauth/callback", params=params, follow_redirects=False
    )
    assert lan_response.status_code in {302, 303, 307}
    assert "invalid" in lan_response.headers["location"]

    anonymous = installation_client(app)
    response = anonymous.get(
        "/api/tiktok/oauth/callback", params=params, follow_redirects=False
    )
    assert response.status_code in {302, 303, 307}
    assert "invalid" not in response.headers["location"]
    assert anonymous.get("/api/tiktok/oauth/result").status_code == 200
