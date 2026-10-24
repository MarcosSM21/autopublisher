"""`/api/auth` and the session guard (Feature 020 T013, contracts/api.md §1, §3).

The installation app runs with its lifespan; every request comes from loopback with
a valid `Host` and `Origin`, so what is checked here is the session layer.
"""

import re
import threading
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth
from app.deployment import DataLayout, DeploymentSettings, parse_host_config
from app.guards import PUBLIC_API_ROUTES, PUBLIC_NON_API_ROUTES
from app.main import create_app
from app.models import AuthSession
from app.scheduler import SchedulerSettings
from tests.conftest import create_project, import_one, make_image, stop
from tests.fakes import FakeClock, InMemoryCredentialStore

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new passphrase"
BASE_URL = "http://127.0.0.1:8000"
ORIGIN = {"origin": BASE_URL}

# contracts/api.md §1: the closed list of /api routes exempt from the session guard.
CONTRACT_PUBLIC_API_ROUTES = {
    ("GET", "/api/auth/session"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/youtube/oauth/callback"),
    ("GET", "/api/tiktok/oauth/callback"),
    ("GET", "/api/tiktok/oauth/result"),
}


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "SCRYPT_N", 2**10)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path: Path) -> DeploymentSettings:
    data = tmp_path / "data"
    host_config = parse_host_config({"data_dir": str(data)}, tmp_path / "config.toml")
    layout = DataLayout(
        data_dir=data,
        db_path=data / "autopublisher.db",
        media_dir=data / "media",
        platform_files={},
    )
    return DeploymentSettings.installation(host_config, layout)


AppFactory = Callable[[], FastAPI]


@pytest.fixture
def make_app(settings: DeploymentSettings, clock: FakeClock) -> AppFactory:
    def build() -> FastAPI:
        return create_app(
            deployment=settings,
            clock=clock.now,
            scheduler_settings=SchedulerSettings(clock=clock.now, autostart=False),
            tiktok_credential_store=InMemoryCredentialStore(),
            instagram_credential_store=InMemoryCredentialStore(),
            threads_credential_store=InMemoryCredentialStore(),
        )

    return build


def _client(app: FastAPI) -> TestClient:
    return TestClient(
        app, base_url=BASE_URL, client=("127.0.0.1", 50000), headers=ORIGIN
    )


@pytest.fixture
def app(make_app: AppFactory) -> FastAPI:
    return make_app()


@pytest.fixture
def client(app: FastAPI, clock: FakeClock) -> Iterator[TestClient]:
    with _client(app) as test_client:
        with app.state.session_factory() as db:
            auth.set_password(db, PASSWORD, clock.now())
        yield test_client


def _login(client: TestClient, password: str = PASSWORD) -> httpx.Response:
    return client.post("/api/auth/login", json={"password": password})


@pytest.fixture
def signed_in(client: TestClient) -> TestClient:
    assert _login(client).status_code == 204
    return client


def _second_client(app: FastAPI) -> TestClient:
    """Another browser on the same running app (its own cookie jar)."""
    return _client(app)


def _code(response: httpx.Response) -> str:
    return str(response.json()["error"]["code"])


def _session_count(app: FastAPI) -> int:
    with app.state.session_factory() as db:
        return int(db.scalar(select(func.count()).select_from(AuthSession)) or 0)


# --- Login ---------------------------------------------------------------------------


def test_login_sets_the_session_cookie(client: TestClient) -> None:
    response = _login(client)
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    token = re.match(r"autopublisher_session=([^;]+);", cookie)
    assert token is not None and len(token.group(1)) >= 43
    lowered = cookie.lower()
    assert "httponly" in lowered and "path=/" in lowered and "samesite=lax" in lowered
    assert "max-age=2592000" in lowered
    assert "domain" not in lowered and "secure" not in lowered
    assert client.get("/api/projects").status_code == 200


@pytest.mark.parametrize("password", ["wrong password!", PASSWORD.upper(), "x"])
def test_wrong_password_is_a_generic_401(client: TestClient, password: str) -> None:
    response = _login(client, password)
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "invalid_credentials",
        "message": "Incorrect password.",
        "fields": [],
    }
    assert "set-cookie" not in response.headers


def test_rate_limit_blocks_before_checking_the_password(
    client: TestClient, clock: FakeClock
) -> None:
    for _ in range(auth.MAX_FAILURES_PER_IP):
        assert _login(client, "wrong password!").status_code == 401
    blocked = _login(client)  # even the right password
    assert blocked.status_code == 429
    assert _code(blocked) == "too_many_attempts"
    clock.advance(auth.RATE_WINDOW.total_seconds())
    assert _login(client).status_code == 204


def test_login_csrf_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"password": PASSWORD},
        headers={"origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert _code(response) == "origin_not_allowed"


def test_sessions_are_stored_hashed(signed_in: TestClient, app: FastAPI) -> None:
    token = signed_in.cookies.get(auth.SESSION_COOKIE)
    assert token
    with app.state.session_factory() as db:
        stored = list(db.scalars(select(AuthSession.token_hash)))
    assert stored == [auth.hash_token(token)]


# --- Session guard -------------------------------------------------------------------


def _routes(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in iter_route_contexts(app.routes)
        for method in route.methods or ()
        if method != "HEAD" and route.path is not None
    }


def test_public_api_routes_match_the_contract(make_app: AppFactory) -> None:
    assert PUBLIC_API_ROUTES == CONTRACT_PUBLIC_API_ROUTES
    assert PUBLIC_API_ROUTES <= _routes(make_app())


def test_no_api_route_is_public_by_accident(make_app: AppFactory) -> None:
    """Every /api route outside the contract's list needs a session. A new route
    fails here unless it is added to the allowlist and the contract."""
    app = make_app()  # no lifespan: without a cookie the guard needs no database
    routes = _routes(app)
    assert {route for route in routes if not route[1].startswith("/api/")} == (
        PUBLIC_NON_API_ROUTES
    )
    client = _client(app)
    private = sorted(routes - PUBLIC_API_ROUTES - PUBLIC_NON_API_ROUTES)
    assert len(private) > 50
    for method, path in private:
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url)
        assert response.status_code == 401, (method, path)
        assert _code(response) == "auth_required"


def test_media_requires_a_session(client: TestClient, app: FastAPI) -> None:
    assert _login(client).status_code == 204
    project = create_project(client, "Cyber")
    content = import_one(client, project["id"], "photo.png", make_image())["content"]
    url = f"/api/contents/{content['id']}/file"
    assert client.get(url).status_code == 200

    anonymous = _second_client(app)
    response = anonymous.get(url)
    assert response.status_code == 401
    assert _code(response) == "auth_required"


def test_unsafe_private_request_without_session(client: TestClient) -> None:
    response = client.post("/api/projects", json={"name": "Cyber"})
    assert response.status_code == 401
    assert _code(response) == "auth_required"


def test_invalid_cookie_is_rejected_and_cleared(client: TestClient) -> None:
    client.cookies.set(auth.SESSION_COOKIE, "forged")
    response = client.get("/api/projects")
    assert response.status_code == 401
    assert _code(response) == "auth_required"
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_idle_and_absolute_expiry(signed_in: TestClient, clock: FakeClock) -> None:
    for _ in range(4):  # activity every 6 days keeps it alive...
        clock.advance(timedelta(days=6).total_seconds())
        assert signed_in.get("/api/projects").status_code == 200
    clock.advance(timedelta(days=6).total_seconds())  # ...but never past day 30
    assert signed_in.get("/api/projects").status_code == 401


def test_idle_expiry(signed_in: TestClient, clock: FakeClock) -> None:
    clock.advance(timedelta(days=7).total_seconds())
    assert signed_in.get("/api/projects").status_code == 401


def test_session_survives_a_restart(
    signed_in: TestClient, make_app: AppFactory
) -> None:
    token = signed_in.cookies.get(auth.SESSION_COOKIE)
    stop(signed_in)
    with _client(make_app()) as restarted:
        restarted.cookies.set(auth.SESSION_COOKIE, token or "")
        assert restarted.get("/api/projects").status_code == 200


# --- Session endpoint and logout ------------------------------------------------------


def test_session_endpoint(client: TestClient) -> None:
    anonymous = client.get("/api/auth/session")
    assert anonymous.json() == {
        "mode": "installation",
        "auth_required": True,
        "authenticated": False,
    }
    _login(client)
    assert client.get("/api/auth/session").json()["authenticated"] is True


def test_logout_is_immediate_and_idempotent(
    signed_in: TestClient, app: FastAPI
) -> None:
    response = signed_in.post("/api/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert _session_count(app) == 0
    assert signed_in.get("/api/projects").status_code == 401
    assert signed_in.post("/api/auth/logout").status_code == 204


def test_logout_only_ends_its_own_session(signed_in: TestClient, app: FastAPI) -> None:
    other = _second_client(app)
    assert _login(other).status_code == 204
    assert other.post("/api/auth/logout").status_code == 204
    assert signed_in.get("/api/projects").status_code == 200


def test_development_shapes(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "db.sqlite",
        tmp_path / "media",
        deployment=DeploymentSettings.development(),
        tiktok_credential_store=InMemoryCredentialStore(),
    )
    with _client(app) as client:
        assert client.get("/api/auth/session").json() == {
            "mode": "development",
            "auth_required": False,
            "authenticated": True,
        }
        response = _login(client)
        assert response.status_code == 409
        assert _code(response) == "auth_not_enabled"
        password = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert _code(password) == "auth_not_enabled"
        assert client.get("/api/projects").status_code == 200  # no session needed


# --- Password change -----------------------------------------------------------------


def _change(
    client: TestClient, current: str = PASSWORD, new: str = NEW_PASSWORD
) -> httpx.Response:
    return client.post(
        "/api/auth/password", json={"current_password": current, "new_password": new}
    )


def test_change_requires_a_session(client: TestClient) -> None:
    assert _code(_change(client)) == "auth_required"


def test_change_signs_out_everyone_else(signed_in: TestClient, app: FastAPI) -> None:
    other = _second_client(app)
    assert _login(other).status_code == 204
    old_token = signed_in.cookies.get(auth.SESSION_COOKIE)

    response = _change(signed_in)

    assert response.status_code == 204
    assert signed_in.cookies.get(auth.SESSION_COOKIE) != old_token  # new session
    assert signed_in.get("/api/projects").status_code == 200
    assert other.get("/api/projects").status_code == 401
    assert _session_count(app) == 1
    assert _login(other).status_code == 401
    assert _login(other, NEW_PASSWORD).status_code == 204


def test_change_with_wrong_current_password(signed_in: TestClient) -> None:
    response = _change(signed_in, current="not the password")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Current password is incorrect."
    assert signed_in.get("/api/projects").status_code == 200


@pytest.mark.parametrize("new", ["short", "x" * 1025])
def test_change_validates_the_new_password(signed_in: TestClient, new: str) -> None:
    response = _change(signed_in, new=new)
    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "new_password"


def test_change_is_rate_limited(signed_in: TestClient) -> None:
    for _ in range(auth.MAX_FAILURES_PER_IP):
        assert _change(signed_in, current="not the password").status_code == 401
    assert _code(_change(signed_in)) == "too_many_attempts"


# --- Races (M2): a barrier between the scrypt verification and persistence --------


class _Gate:
    """Wraps `verify_password`: the gated calls stop after verifying until released."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, gated_calls: int) -> None:
        self._real = auth.verify_password
        self._lock = threading.Lock()
        self._remaining = gated_calls
        self.verified = threading.Barrier(gated_calls + 1, timeout=10)
        self.release = threading.Event()
        monkeypatch.setattr(auth, "verify_password", self)

    def __call__(self, password: str, encoded: str) -> bool:
        result = self._real(password, encoded)
        with self._lock:
            gated = self._remaining > 0
            self._remaining -= 1
        if gated:
            self.verified.wait()
            assert self.release.wait(10)
        return result


def _in_thread(call: Callable[[], httpx.Response]) -> Callable[[], httpx.Response]:
    result: dict[str, Any] = {}
    thread = threading.Thread(target=lambda: result.setdefault("response", call()))
    thread.start()

    def join() -> httpx.Response:
        thread.join(10)
        assert not thread.is_alive()
        response: httpx.Response = result["response"]
        return response

    return join


def test_login_racing_a_local_reset(
    client: TestClient, app: FastAPI, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _Gate(monkeypatch, gated_calls=1)
    login = _in_thread(lambda: _login(client))
    gate.verified.wait()  # the old password was verified...
    with app.state.session_factory() as db:  # ...then `set-password` runs
        auth.set_password(db, NEW_PASSWORD, clock.now())
    gate.release.set()

    response = login()
    assert response.status_code == 401
    assert _code(response) == "invalid_credentials"
    assert _session_count(app) == 0


def test_login_racing_a_password_change(
    signed_in: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _second_client(app)
    gate = _Gate(monkeypatch, gated_calls=1)
    login = _in_thread(lambda: _login(other))
    gate.verified.wait()
    assert _change(signed_in).status_code == 204  # not gated: the second call
    gate.release.set()

    assert login().status_code == 401
    assert _session_count(app) == 1  # only the changer's new session
    assert other.get("/api/projects").status_code == 401


def test_two_concurrent_changes(
    signed_in: TestClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _second_client(app)
    assert _login(other).status_code == 204
    gate = _Gate(monkeypatch, gated_calls=2)
    first = _in_thread(lambda: _change(signed_in, new="first new password"))
    second = _in_thread(lambda: _change(other, new="second new password"))
    gate.verified.wait()  # both verified the same current password
    gate.release.set()

    statuses = sorted([first().status_code, second().status_code])
    assert statuses == [204, 401]
    assert _session_count(app) == 1
    winners = [
        new
        for new in ("first new password", "second new password")
        if _login(_second_client(app), new).status_code == 204
    ]
    assert len(winners) == 1
