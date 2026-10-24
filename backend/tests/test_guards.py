"""Development and installation guards (Feature 020 T008, contracts/api.md §1).

Lifespan is not started: the guards run before any route, and a probe route answers
every method without touching storage. `TestClient(base_url=…, client=…)` sets the
`Host` header, `scope["server"]` (the socket address) and `scope["client"]`.

In installation mode the probe is a private `/api` route: a request that passes the
Host and Origin guards reaches the session guard, which answers `401 auth_required`
without a cookie (the session layer itself is tested in test_auth_api.py).
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from app.deployment import DataLayout, DeploymentSettings, parse_host_config
from app.guards import (
    DEVELOPMENT_DOC_PATHS,
    PUBLIC_API_ROUTES,
    PUBLIC_NON_API_ROUTES,
    SECURITY_HEADERS,
    is_backend_path,
    parse_authority,
    requires_session,
)
from app.main import create_app

LOOPBACK = ("127.0.0.1", 50000)
LOOPBACK_V6 = ("::1", 50000)
LAN_CLIENT = ("192.168.1.50", 50000)
PROBE = "/api/probe"
UNSAFE = ("POST", "PUT", "PATCH", "DELETE")


def _with_probe(app: FastAPI) -> FastAPI:
    def probe() -> dict[str, bool]:
        return {"ok": True}

    app.add_api_route(
        PROBE, probe, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]
    )
    return app


@pytest.fixture
def dev_app(tmp_path: Path) -> FastAPI:
    return _with_probe(
        create_app(
            tmp_path / "db.sqlite",
            tmp_path / "media",
            deployment=DeploymentSettings.development(),
        )
    )


def _installation(tmp_path: Path, **values: object) -> DeploymentSettings:
    data = tmp_path / "data"
    host_config = parse_host_config(
        {"data_dir": str(data), **values}, tmp_path / "config.toml"
    )
    layout = DataLayout(
        data_dir=data,
        db_path=data / "autopublisher.db",
        media_dir=data / "media",
        platform_files={},
    )
    return DeploymentSettings.installation(host_config, layout)


def _installation_app(tmp_path: Path, **values: object) -> FastAPI:
    return _with_probe(create_app(deployment=_installation(tmp_path, **values)))


def _client(
    app: FastAPI,
    base_url: str = "http://127.0.0.1:8000",
    client: tuple[str, int] = LOOPBACK,
) -> TestClient:
    return TestClient(app, base_url=base_url, client=client)


def _code(response: object) -> str | None:
    body = response.json()  # type: ignore[attr-defined]
    return body.get("error", {}).get("code") if isinstance(body, dict) else None


def _reached_session_guard(response: object) -> bool:
    return (
        response.status_code == 401  # type: ignore[attr-defined]
        and _code(response) == "auth_required"
    )


# --- Development: loopback clients only ----------------------------------------------


@pytest.mark.parametrize("client", [LOOPBACK, LOOPBACK_V6], ids=["ipv4", "ipv6"])
def test_dev_accepts_loopback_clients(
    dev_app: FastAPI, client: tuple[str, int]
) -> None:
    response = _client(dev_app, client=client).get("/health")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "client",
    [LAN_CLIENT, ("10.0.0.7", 1), ("2001:db8::1", 1), ("127.0.0.1.evil", 1)],
    ids=["lan", "private", "ipv6-remote", "lookalike"],
)
def test_dev_rejects_remote_clients(dev_app: FastAPI, client: tuple[str, int]) -> None:
    response = _client(dev_app, client=client).get("/health")
    assert response.status_code == 403
    assert _code(response) == "loopback_only"


def test_dev_bound_to_all_interfaces_still_rejects_lan(dev_app: FastAPI) -> None:
    # `uvicorn --host 0.0.0.0`: the socket is the LAN address, the client remote,
    # and a loopback `Host` or forwarding headers change nothing.
    response = _client(
        dev_app, base_url="http://192.168.1.40:8000", client=LAN_CLIENT
    ).get(
        "/health",
        headers={
            "host": "localhost:8000",
            "x-forwarded-for": "127.0.0.1",
            "forwarded": "for=127.0.0.1",
        },
    )
    assert response.status_code == 403
    assert _code(response) == "loopback_only"


def test_dev_vite_proxy_post_is_accepted(dev_app: FastAPI) -> None:
    response = _client(dev_app).post(
        PROBE,
        headers={"host": "localhost:5173", "origin": "http://localhost:5173"},
    )
    assert response.status_code == 200


def test_dev_rejection_hides_details(dev_app: FastAPI) -> None:
    response = _client(dev_app, client=LAN_CLIENT).get("/health")
    assert response.json() == {
        "error": {
            "code": "loopback_only",
            "message": "AutoPublisher in development mode only accepts this computer.",
            "fields": [],
        }
    }


# --- Host validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("localhost", True),
        ("localhost:5173", True),
        ("LOCALHOST:8000", True),
        ("127.0.0.1:8000", True),
        ("[::1]:8000", True),
        ("[0:0:0:0:0:0:0:1]", True),
        ("192.168.1.40:8000", False),
        ("my-pc.local:8000", False),
        ("evil.example", False),
        ("localhost.evil.example:8000", False),
        ("127.0.0.1.nip.io:8000", False),
        ("::1", False),
        ("localhost:", False),
        ("localhost:abc", False),
        ("", False),
    ],
)
def test_dev_host(dev_app: FastAPI, host: str, allowed: bool) -> None:
    response = _client(dev_app).get("/health", headers={"host": host})
    assert response.status_code == (200 if allowed else 403)
    if not allowed:
        assert _code(response) == "host_not_allowed"


@pytest.mark.parametrize(
    ("socket", "host", "lan_enabled", "allowed"),
    [
        ("127.0.0.1", "localhost:8000", False, True),
        ("127.0.0.1", "127.0.0.1:8000", False, True),
        ("::1", "[::1]:8000", False, True),
        ("127.0.0.1", "my-pc.local:8000", False, True),  # allowed_hosts
        ("127.0.0.1", "MY-PC.LOCAL:8000", False, True),
        ("192.168.1.40", "192.168.1.40:8000", True, True),  # the socket's own IP
        ("192.168.1.40", "my-pc.local:8000", True, True),
        ("fe80::1", "[fe80::1]:8000", True, True),
        ("fe80::1", "[fe80:0::1]:8000", True, True),
        ("192.168.1.40", "192.168.1.40:8000", False, False),  # LAN IP, LAN off
        ("192.168.1.40", "192.168.1.41:8000", True, False),  # another IP
        ("192.168.1.40", "10.0.0.5:8000", True, False),
        ("127.0.0.1", "localhost:9000", False, False),  # wrong port
        ("127.0.0.1", "localhost", False, False),  # implicit port 80
        ("192.168.1.40", "evil.example:8000", True, False),
        ("192.168.1.40", "attacker.example:8000", True, False),  # rebinding
        ("192.168.1.40", "192.168.1.40.nip.io:8000", True, False),
        ("127.0.0.1", "other.local:8000", False, False),
        ("127.0.0.1", "[::1%eth0]:8000", False, False),
        ("127.0.0.1", "[::1:8000", False, False),
        ("127.0.0.1", "localhost:8000:1", False, False),
        ("127.0.0.1", "user@localhost:8000", False, False),
        ("127.0.0.1", "localhost:99999", False, False),
    ],
)
def test_installation_host(
    tmp_path: Path, socket: str, host: str, lan_enabled: bool, allowed: bool
) -> None:
    app = _installation_app(
        tmp_path, lan_enabled=lan_enabled, allowed_hosts=["my-pc.local"]
    )
    netloc = f"[{socket}]" if ":" in socket else socket
    client = (socket if socket in {"127.0.0.1", "::1"} else "192.168.1.50", 50000)
    response = _client(app, base_url=f"http://{netloc}:8000", client=client).get(
        PROBE, headers={"host": host}
    )
    if allowed:
        assert _reached_session_guard(response)
    else:
        assert response.status_code == 403
        assert _code(response) == "host_not_allowed"


def test_repeated_host_header_is_rejected(tmp_path: Path) -> None:
    app = _installation_app(tmp_path)
    response = _client(app).get(
        PROBE, headers=[("host", "localhost:8000"), ("host", "evil.example")]
    )
    assert response.status_code == 403
    assert _code(response) == "host_not_allowed"


@pytest.mark.parametrize(
    ("value", "parsed"),
    [
        ("localhost", ("localhost", None)),
        ("Example.LOCAL:8000", ("example.local", 8000)),
        ("[::1]", ("::1", None)),
        ("[0::1]:80", ("::1", 80)),
        ("::1", None),
        ("local host", None),
        ("localhost:0", None),
        ("-bad.example", None),
    ],
)
def test_parse_authority(value: str, parsed: object) -> None:
    assert parse_authority(value) == parsed


# --- Origin protection ---------------------------------------------------------------


@pytest.mark.parametrize("method", UNSAFE)
@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ({"origin": "http://localhost:8000"}, True),
        ({"origin": "http://LOCALHOST:8000"}, True),
        ({"sec-fetch-site": "same-origin"}, True),
        ({"origin": "http://evil.example"}, False),
        (
            {"origin": "http://evil.example", "sec-fetch-site": "same-origin"},
            False,
        ),
        ({"origin": "http://localhost:9000"}, False),
        ({"origin": "http://127.0.0.1:8000"}, False),  # a different origin
        ({"origin": "https://localhost:8000"}, False),
        ({"origin": "null"}, False),
        ({"origin": "http://localhost:8000/"}, False),
        ({"origin": "http://user@localhost:8000"}, False),
        ({"origin": "localhost:8000"}, False),
        ({"origin": ""}, False),
        ({"sec-fetch-site": "cross-site"}, False),
        ({"sec-fetch-site": "same-site"}, False),
        ({}, False),
    ],
)
def test_installation_origin(
    tmp_path: Path, method: str, headers: dict[str, str], allowed: bool
) -> None:
    app = _installation_app(tmp_path)
    response = _client(app).request(
        method, PROBE, headers={"host": "localhost:8000", **headers}
    )
    if allowed:
        assert _reached_session_guard(response)
    else:
        assert response.status_code == 403
        assert _code(response) == "origin_not_allowed"


def test_origin_matches_ipv6_and_lan_hosts(tmp_path: Path) -> None:
    app = _installation_app(tmp_path, lan_enabled=True)
    v6 = _client(app, base_url="http://[::1]:8000", client=LOOPBACK_V6).post(
        PROBE, headers={"origin": "http://[::1]:8000"}
    )
    lan = _client(app, base_url="http://192.168.1.40:8000", client=LAN_CLIENT).post(
        PROBE, headers={"origin": "http://192.168.1.40:8000"}
    )
    assert _reached_session_guard(v6) and _reached_session_guard(lan)


def test_repeated_origin_is_rejected(tmp_path: Path) -> None:
    app = _installation_app(tmp_path)
    response = _client(app).post(
        PROBE,
        headers=[
            ("origin", "http://127.0.0.1:8000"),
            ("origin", "http://evil.example"),
        ],
    )
    assert _code(response) == "origin_not_allowed"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_safe_methods_are_not_origin_checked(tmp_path: Path, method: str) -> None:
    app = _installation_app(tmp_path)
    response = _client(app).request(
        method, PROBE, headers={"origin": "http://evil.example"}
    )
    assert response.status_code == 401  # passed the Origin guard (HEAD has no body)


def test_dev_origin_is_checked(dev_app: FastAPI) -> None:
    response = _client(dev_app).delete(PROBE, headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert _code(response) == "origin_not_allowed"


def test_login_is_origin_checked(tmp_path: Path) -> None:
    # Public for the session guard only: login CSRF is rejected before any route.
    app = _installation_app(tmp_path)
    response = _client(app).post(
        "/api/auth/login", headers={"origin": "http://evil.example"}
    )
    assert _code(response) == "origin_not_allowed"


# --- Security headers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/health", {}, 200),
        ("/redoc", {}, 404),  # a backend 404 (never the SPA shell)
        (PROBE, {}, 401),
        (PROBE, {"host": "evil.example"}, 403),
    ],
    ids=["ok", "not-found", "no-session", "rejected"],
)
def test_installation_security_headers(
    tmp_path: Path, path: str, headers: dict[str, str], status: int
) -> None:
    response = _client(_installation_app(tmp_path)).get(path, headers=headers)
    assert response.status_code == status
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert "strict-transport-security" not in response.headers


def test_development_has_no_security_headers(dev_app: FastAPI) -> None:
    response = _client(dev_app).get("/health")
    assert not set(SECURITY_HEADERS) & set(response.headers)


# --- Public route contract -----------------------------------------------------------


def _routes(app: FastAPI) -> set[tuple[str, str]]:
    """Every (method, path), including the routes of included routers; HEAD
    follows GET in Starlette's routing, so it is not listed separately."""
    return {
        (method, route.path)
        for route in iter_route_contexts(app.routes)
        for method in route.methods or ()
        if method != "HEAD" and route.path is not None
    }


# The exact allowlist is compared with the contract in test_auth_api.py.
def test_public_api_routes_are_exact_paths() -> None:
    assert all("{" not in path and "*" not in path for _, path in PUBLIC_API_ROUTES)


def test_every_other_route_is_private(tmp_path: Path) -> None:
    routes = _routes(create_app(deployment=_installation(tmp_path)))
    # Outside /api there is only the health check: a new backend route outside
    # /api fails here instead of becoming public.
    assert {route for route in routes if not route[1].startswith("/api/")} == (
        PUBLIC_NON_API_ROUTES
    )
    private = routes - PUBLIC_API_ROUTES - PUBLIC_NON_API_ROUTES
    assert private
    for method, path in private:
        assert requires_session(method, path), (method, path)


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/youtube/oauth/callback", False),
        ("HEAD", "/api/tiktok/oauth/result", False),
        ("GET", "/api/auth/session", False),
        ("POST", "/api/auth/login", False),
        ("POST", "/api/auth/logout", False),
        ("GET", "/api/auth/login", True),
        ("POST", "/api/auth/password", True),
        ("POST", "/api/auth/setup", True),
        ("POST", "/api/auth/", True),
        ("POST", "/api/youtube/oauth/callback", True),
        ("GET", "/api/youtube/oauth/callback/", True),
        ("GET", "/api/youtube/oauth/other", True),
        ("GET", "/api/accounts/1/youtube-connection/authorize", True),
        ("POST", "/api/accounts/1/tiktok-connection/authorize", True),
        ("GET", "/api/contents/1/file", True),
        ("GET", "/api", False),  # no resource: the backend's JSON 404
        ("GET", "/api/", True),
        ("GET", "/health", False),
        ("GET", "/calendar", False),
    ],
)
def test_requires_session(method: str, path: str, expected: bool) -> None:
    assert requires_session(method, path) is expected


def test_development_docs_are_the_only_extra_routes(dev_app: FastAPI) -> None:
    paths = {path for _, path in _routes(dev_app)}
    non_api = {path for path in paths if not path.startswith("/api/")}
    assert non_api == {"/health", *DEVELOPMENT_DOC_PATHS}


@pytest.mark.parametrize(
    ("path", "backend"),
    [
        ("/api", True),
        ("/api/nope", True),
        ("/health", True),
        ("/docs", True),
        ("/redoc", True),
        ("/openapi.json", True),
        ("/", False),
        ("/calendar/week", False),
        ("/apidocs", False),
    ],
)
def test_backend_paths_never_reach_the_spa(path: str, backend: bool) -> None:
    assert is_backend_path(path) is backend
