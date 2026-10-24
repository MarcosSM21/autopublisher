from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.credential_store import CredentialStoreProbe, ProbeStatus
from app.main import create_app
from app.scheduler import SchedulerSettings
from tests.conftest import (
    installation_app,
    installation_client,
    installation_settings,
    sign_in,
)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_returns_not_found(client: TestClient) -> None:
    response = client.get("/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_unexpected_error_returns_internal_error_without_details(
    db_path: Path,
) -> None:
    app = create_app(db_path)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "secret internal detail" not in response.text


# --- Feature 020: public, minimal health (contracts/api.md §2) -----------------------


@pytest.fixture
def installation(tmp_path: Path) -> FastAPI:
    return installation_app(
        installation_settings(tmp_path),
        scheduler_settings=SchedulerSettings(autostart=True, wait=lambda _: None),
        credential_probe=CredentialStoreProbe(check=_never_probe),
    )


def _never_probe() -> ProbeStatus:
    raise AssertionError("the public health must not probe the credential store")


def test_health_is_public_and_minimal_in_installation(installation: FastAPI) -> None:
    with installation_client(installation) as client:
        anonymous = client.get("/health")
    assert anonymous.status_code == 200
    assert anonymous.json() == {"status": "ok"}
    assert set(anonymous.json()) == {"status"}


def test_health_is_degraded_when_the_scheduler_stopped(installation: FastAPI) -> None:
    with installation_client(installation) as client:
        installation.state.scheduler.stop()
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "degraded"}


def test_health_is_degraded_when_the_database_fails(
    installation: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    with installation_client(installation) as client:

        def broken(self: Session, *args: object, **kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("disk I/O error"))

        monkeypatch.setattr(Session, "execute", broken)
        response = client.get("/health")
    assert response.json() == {"status": "degraded"}
    assert "disk" not in response.text


def test_paused_automation_is_not_degraded(installation: FastAPI) -> None:
    with installation_client(installation) as client:
        sign_in(client, installation)
        paused = client.put("/api/automation", json={"paused": True})
        assert paused.status_code == 200, paused.text
        assert client.get("/health").json() == {"status": "ok"}


def test_health_without_scheduler_autostart_is_ok(tmp_path: Path) -> None:
    app = installation_app(installation_settings(tmp_path))  # autostart off
    with installation_client(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
