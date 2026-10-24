"""The entrypoint decides the mode (Feature 020 T007, research §4)."""

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.middleware import Middleware

from app import main
from app.deployment import (
    AppMode,
    DataLayout,
    DeploymentSettings,
    HostConfig,
    parse_host_config,
)
from app.guards import (
    HostGuard,
    LoopbackOnlyGuard,
    OriginGuard,
    SecurityHeaders,
    SessionGuard,
)
from app.main import create_app

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _layout(tmp_path: Path) -> DataLayout:
    return DataLayout(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "autopublisher.db",
        media_dir=tmp_path / "data" / "media",
        platform_files={},
    )


def _host_config(tmp_path: Path, **values: object) -> HostConfig:
    return parse_host_config(
        {"data_dir": str(tmp_path / "data"), **values}, tmp_path / "config.toml"
    )


def _middlewares(app: object) -> list[type]:
    stack: list[Middleware] = app.user_middleware  # type: ignore[attr-defined]
    return [entry.cls for entry in stack]  # type: ignore[misc]


def test_module_app_is_development() -> None:
    settings = main.app.state.deployment
    assert settings == DeploymentSettings.development()
    assert settings.mode is AppMode.DEVELOPMENT
    assert _middlewares(main.app) == [LoopbackOnlyGuard, HostGuard, OriginGuard]


def test_create_app_without_deployment_has_no_guards(tmp_path: Path) -> None:
    app = create_app(tmp_path / "db.sqlite", tmp_path / "media")
    assert app.state.deployment is None
    assert _middlewares(app) == []
    response = TestClient(app).get("/health")
    assert response.status_code == 200


def test_installation_is_built_from_host_config(tmp_path: Path) -> None:
    host_config = _host_config(
        tmp_path, port=8123, lan_enabled=True, allowed_hosts=["my-pc.local"]
    )
    layout = _layout(tmp_path)
    settings = DeploymentSettings.installation(host_config, layout)
    assert settings.mode is AppMode.INSTALLATION
    assert (settings.port, settings.lan_enabled, settings.allowed_hosts) == (
        8123,
        True,
        ("my-pc.local",),
    )
    assert settings.layout is layout
    app = create_app(deployment=settings)
    # Outermost first (Starlette's `user_middleware` order).
    assert _middlewares(app) == [SecurityHeaders, HostGuard, OriginGuard, SessionGuard]


@pytest.mark.parametrize(
    "build",
    [
        lambda tmp: DeploymentSettings(mode=AppMode.INSTALLATION),
        lambda tmp: DeploymentSettings.installation(
            {"port": 8000},  # type: ignore[arg-type]
            _layout(tmp),
        ),
        lambda tmp: DeploymentSettings(
            mode=AppMode.DEVELOPMENT, port=8000, lan_enabled=True
        ),
        lambda tmp: DeploymentSettings(
            mode=AppMode.DEVELOPMENT, allowed_hosts=("evil.example",)
        ),
    ],
    ids=["installation-without-config", "not-a-host-config", "dev-lan", "dev-hosts"],
)
def test_no_way_to_mix_modes(tmp_path: Path, build: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        build(tmp_path)  # type: ignore[operator]


def test_host_config_cannot_select_the_mode(tmp_path: Path) -> None:
    from app.deployment import HostConfigError

    with pytest.raises(HostConfigError, match="mode"):
        _host_config(tmp_path, mode="development")
    assert "mode" not in {field.name for field in dataclasses.fields(HostConfig)}


def test_installation_uses_its_layout(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    settings = DeploymentSettings.installation(_host_config(tmp_path), layout)
    app = create_app(deployment=settings, credential_store=None)
    # The lifespan opens the layout's database (locks + migrations included).
    with TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)
    ) as client:
        assert client.get("/health").status_code == 200
    assert layout.db_path.exists()


@pytest.mark.parametrize("path", DOC_PATHS)
def test_installation_has_no_docs(tmp_path: Path, path: str) -> None:
    settings = DeploymentSettings.installation(
        _host_config(tmp_path), _layout(tmp_path)
    )
    client = TestClient(
        create_app(deployment=settings),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50000),
    )
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", DOC_PATHS)
def test_development_keeps_docs(tmp_path: Path, path: str) -> None:
    client = TestClient(
        create_app(
            tmp_path / "db.sqlite",
            tmp_path / "media",
            deployment=DeploymentSettings.development(),
        ),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50000),
    )
    assert client.get(path).status_code == 200
