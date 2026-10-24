"""Signed-in diagnostics `GET /api/system/status` (Feature 020 T021,
contracts/api.md §4). Scheduler state and the pause stay in `GET /api/automation`."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import auth, deployment
from app.credential_store import CredentialStoreProbe, ProbeStatus
from app.deployment import DeploymentSettings
from app.main import create_app
from tests.conftest import (
    installation_app,
    installation_client,
    installation_settings,
    sign_in,
)


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@pytest.fixture(autouse=True)
def network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deployment, "_primary_address", lambda: "192.168.1.40")
    monkeypatch.setattr("app.deployment.socket.gethostname", lambda: "my-pc")


def _app(
    tmp_path: Path, status: ProbeStatus = "available", **values: object
) -> FastAPI:
    return installation_app(
        installation_settings(tmp_path, **values),
        credential_probe=CredentialStoreProbe(check=lambda: status),
    )


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return _app(tmp_path, port=8000, lan_enabled=True, allowed_hosts=["my-pc.local"])


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with installation_client(app) as test_client:
        yield test_client


def test_requires_a_session(client: TestClient) -> None:
    response = client.get("/api/system/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_installation_shape(client: TestClient, app: FastAPI, tmp_path: Path) -> None:
    sign_in(client, app)
    response = client.get("/api/system/status")
    assert response.status_code == 200
    assert response.json() == {
        "mode": "installation",
        "database": {"status": "ok"},
        "credential_store": {"status": "available"},
        "deployment": {
            "port": 8000,
            "lan_enabled": True,
            "addresses": ["http://192.168.1.40:8000"],
            "suggested_names": ["http://my-pc.local:8000"],
            "allowed_hosts": ["my-pc.local"],
        },
    }
    # No paths, versions or secrets.
    assert str(tmp_path) not in response.text
    assert "version" not in response.text


def test_request_socket_address_is_listed(app: FastAPI) -> None:
    lan = installation_client(
        app, base_url="http://10.0.0.7:8000", client=("10.0.0.50", 1)
    )
    with lan:
        sign_in(lan, app)
        addresses = lan.get("/api/system/status").json()["deployment"]["addresses"]
    assert addresses == ["http://192.168.1.40:8000", "http://10.0.0.7:8000"]


@pytest.mark.parametrize("status", ["available", "locked", "unavailable", "unknown"])
def test_credential_store_states_are_reported_as_is(
    tmp_path: Path, status: ProbeStatus
) -> None:
    app = _app(tmp_path, status)
    with installation_client(app) as client:
        sign_in(client, app)
        body = client.get("/api/system/status").json()
    assert body["credential_store"] == {"status": status}


def test_database_error(
    client: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(client, app)
    original = Session.execute

    def failing(
        self: Session, statement: object, *args: object, **kwargs: object
    ) -> object:
        if str(statement) == "SELECT 1":
            raise OperationalError("SELECT 1", {}, Exception("database is locked"))
        return original(self, statement, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Session, "execute", failing)
    body = client.get("/api/system/status").json()
    assert body["database"] == {"status": "error"}
    assert "locked" not in str(body)


def test_scheduler_and_pause_stay_in_automation(
    client: TestClient, app: FastAPI
) -> None:
    sign_in(client, app)
    automation = client.get("/api/automation").json()
    assert {"paused", "running", "last_check_at"} <= set(automation)
    status = client.get("/api/system/status").json()
    assert not {"paused", "running", "last_check_at", "scheduler"} & set(status)


def test_development_shape(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "db.sqlite",
        tmp_path / "media",
        deployment=DeploymentSettings.development(),
        credential_probe=CredentialStoreProbe(check=lambda: "unknown"),
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1)
    ) as client:
        body = client.get("/api/system/status").json()
    assert body == {
        "mode": "development",
        "database": {"status": "ok"},
        "credential_store": {"status": "unknown"},
        "deployment": None,
    }
