"""Request guards for the development and installation modes (contracts/api.md §1).

Pure ASGI middlewares, applied only when `create_app` receives a `deployment`:

- development: loopback client → Host → Origin;
- installation: security headers → Host → Origin → session.

Host and Origin checks defend against DNS rebinding and cross-site requests; they
never authenticate anyone. Every decision uses the real ASGI connection
(`scope["client"]`, `scope["server"]`), never `X-Forwarded-*`/`Forwarded` headers:
there is no reverse proxy and uvicorn runs with `proxy_headers=False`.
"""

import ipaddress
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import auth
from app.deployment import AppMode, DeploymentSettings
from app.errors import error_response
from app.loopback import is_loopback_client

logger = logging.getLogger(__name__)

LOOPBACK_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
# Methods that never change anything in this API; every other method is checked.
SAFE_METHODS = frozenset({"GET", "HEAD"})
HTTP_DEFAULT_PORT = 80

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "same-origin",
}

# --- Public route contract (contracts/api.md §1) -------------------------------------
#
# The only `/api` routes reachable without a session in installation mode, as exact
# (method, path) pairs: never a prefix or a pattern. Any other `/api` route, present
# or future, requires a session. They still go through the Host and Origin guards.
PUBLIC_API_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # Minimal access contract: no data; logout only deletes its own session.
        ("GET", "/api/auth/session"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        # OAuth callbacks (research §16): state + PKCE (+ loopback).
        ("GET", "/api/youtube/oauth/callback"),
        ("GET", "/api/tiktok/oauth/callback"),
        ("GET", "/api/tiktok/oauth/result"),
    }
)
# The SPA shell catch-all (installation only, registered last): HTML, JS and CSS of
# the public repository, never data. Backend paths below answer a JSON 404 there.
SPA_SHELL_ROUTE = ("GET", "/{path:path}")
# The only routes outside `/api`; `/assets` is a static mount of the same build.
PUBLIC_NON_API_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("GET", "/health"), SPA_SHELL_ROUTE}
)
# FastAPI docs exist only in development (installation builds without them).
DEVELOPMENT_DOC_PATHS = ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json")
# First path segments owned by the backend: a miss answers a JSON 404, never the
# SPA shell (T015), including the docs paths disabled in installation mode.
BACKEND_PATH_ROOTS = frozenset({"api", "health", "docs", "redoc", "openapi.json"})


def requires_session(method: str, path: str) -> bool:
    """Whether an installation request needs a session.

    Every route below `/api/` does, except the exact `PUBLIC_API_ROUTES`. Other paths
    only reach `/health`, the SPA shell or a JSON 404 (`/api` itself is no resource);
    HEAD follows GET, as in Starlette's routing.
    """
    if not path.startswith("/api/"):
        return False
    effective = "GET" if method == "HEAD" else method
    return (effective, path) not in PUBLIC_API_ROUTES


def is_backend_path(path: str) -> bool:
    return path.lstrip("/").split("/", 1)[0] in BACKEND_PATH_ROOTS


# --- Host and Origin parsing ---------------------------------------------------------

_HOST_NAME = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$"
)
_PORT = re.compile(r"^[0-9]{1,5}$")


def parse_authority(value: str) -> tuple[str, int | None] | None:
    """`name[:port]` or `[ipv6][:port]` → (lowercase name, port); None if malformed.

    IPv6 names are returned without brackets, in their compressed form.
    """
    value = value.lower()
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        literal, rest = value[1:end], value[end + 1 :]
        if "%" in literal:
            return None
        try:
            name = str(ipaddress.IPv6Address(literal))
        except ValueError:
            return None
    else:
        name, separator, port_text = value.partition(":")
        if not _HOST_NAME.match(name):
            return None
        rest = separator + port_text
    if not rest:
        return name, None
    if not rest.startswith(":") or not _PORT.match(rest[1:]):
        return None
    port = int(rest[1:])
    if not 1 <= port <= 65535:
        return None
    return name, port


def parse_origin(value: str) -> tuple[str, int | None] | None:
    """`http://authority` with no path, query or credentials; None otherwise.

    There is no HTTPS in this feature, so any other scheme (or `null`) is foreign.
    """
    scheme = "http://"
    if not value.lower().startswith(scheme):
        return None
    authority = value[len(scheme) :]
    if any(char in authority for char in "/?#@\\"):
        return None
    return parse_authority(authority)


def _same_ip(name: str, address: str) -> bool:
    try:
        return ipaddress.ip_address(name) == ipaddress.ip_address(address)
    except ValueError:
        return False


def host_allowed(
    name: str, port: int | None, settings: DeploymentSettings, scope: Scope
) -> bool:
    """research §14: loopback names, the socket's own IP literal or `allowed_hosts`."""
    if settings.mode is AppMode.DEVELOPMENT:
        # Any port: Vite proxies with `Host: localhost:5173`.
        return name in LOOPBACK_HOST_NAMES
    if (port or HTTP_DEFAULT_PORT) != settings.port:
        return False
    if name in LOOPBACK_HOST_NAMES or name in settings.allowed_hosts:
        return True
    # A rebinding attack always uses a domain name, never the IP literal of the
    # interface the connection really arrived on.
    server = scope.get("server")
    if not settings.lan_enabled or not server:
        return False
    return isinstance(server[0], str) and _same_ip(name, server[0])


def _single_header(scope: Scope, name: bytes) -> tuple[bool, str | None]:
    """(well formed, value): a repeated header is malformed."""
    values = [value for key, value in scope["headers"] if key == name]
    if len(values) > 1:
        return False, None
    return True, values[0].decode("latin-1") if values else None


def request_host(scope: Scope) -> tuple[str, int | None] | None:
    ok, value = _single_header(scope, b"host")
    if not ok or value is None:
        return None
    return parse_authority(value)


def origin_allowed(scope: Scope) -> bool:
    """research §13: `Origin` equals `http://<Host>`; without it, only
    `Sec-Fetch-Site: same-origin`. The Host was validated by the outer guard."""
    host = request_host(scope)
    ok, origin = _single_header(scope, b"origin")
    if host is None or not ok:
        return False
    if origin is None:
        ok, fetch_site = _single_header(scope, b"sec-fetch-site")
        return ok and fetch_site == "same-origin"
    parsed = parse_origin(origin)
    if parsed is None:
        return False
    return (parsed[0], parsed[1] or HTTP_DEFAULT_PORT) == (
        host[0],
        host[1] or HTTP_DEFAULT_PORT,
    )


# --- Middlewares ---------------------------------------------------------------------

_REJECTIONS: Mapping[str, tuple[int, str]] = {
    "loopback_only": (
        403,
        "AutoPublisher in development mode only accepts this computer.",
    ),
    "host_not_allowed": (403, "This address is not allowed for AutoPublisher."),
    "origin_not_allowed": (403, "Request blocked: it did not come from AutoPublisher."),
    "auth_required": (401, "Sign in to continue."),
}


class _Guard:
    """Rejects a request before it reaches the application when `check` fails."""

    code: str

    def __init__(self, app: ASGIApp, settings: DeploymentSettings) -> None:
        self.app = app
        self.settings = settings

    def check(self, scope: Scope) -> bool:
        raise NotImplementedError

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or self.check(scope):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        logger.info(
            "Request rejected (%s) from %s", self.code, client[0] if client else "-"
        )
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        status_code, message = _REJECTIONS[self.code]
        await error_response(status_code, self.code, message)(scope, receive, send)


class LoopbackOnlyGuard(_Guard):
    """Development has no password: only this computer may use it, even when
    uvicorn is bound to `0.0.0.0` (FR-004, FR-030h)."""

    code = "loopback_only"

    def check(self, scope: Scope) -> bool:
        return is_loopback_client(scope)


class HostGuard(_Guard):
    code = "host_not_allowed"

    def check(self, scope: Scope) -> bool:
        host = request_host(scope)
        return host is not None and host_allowed(*host, self.settings, scope)


class OriginGuard(_Guard):
    """Cross-site and login CSRF protection for every unsafe method on every path."""

    code = "origin_not_allowed"

    def check(self, scope: Scope) -> bool:
        if scope["type"] == "http" and scope["method"] in SAFE_METHODS:
            return True
        return origin_allowed(scope)


def _session_token(scope: Scope) -> str | None:
    for key, value in scope["headers"]:
        if key == b"cookie":
            token = cookie_parser(value.decode("latin-1")).get(auth.SESSION_COOKIE)
            if token:
                return token
    return None


def _valid_session(app: Any, token: str) -> bool:
    with app.state.session_factory() as db:
        return auth.authenticate(db, token, app.state.clock())


class SessionGuard:
    """Installation: every `/api` route outside `PUBLIC_API_ROUTES` needs a valid
    session cookie; otherwise `401 auth_required` and the stale cookie is cleared."""

    code = "auth_required"

    def __init__(self, app: ASGIApp, settings: DeploymentSettings) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"} or not requires_session(
            scope.get("method", "GET"), scope["path"]
        ):
            await self.app(scope, receive, send)
            return
        token = _session_token(scope)
        if token is not None:
            # The database call is blocking: keep it off the event loop.
            valid: bool = await run_in_threadpool(_valid_session, scope["app"], token)
            if valid:
                await self.app(scope, receive, send)
                return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        status_code, message = _REJECTIONS[self.code]
        response = error_response(status_code, self.code, message)
        if token:
            auth.clear_session_cookie(response)
        await response(scope, receive, send)


class SecurityHeaders:
    """Adds the installation security headers to every response (research §26)."""

    def __init__(self, app: ASGIApp, settings: DeploymentSettings) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def guard_stack(settings: DeploymentSettings) -> Sequence[type[Any]]:
    """The middlewares of a mode, outermost first (contracts/api.md §1).

    The security headers wrap everything so guard rejections carry them too.
    """
    if settings.mode is AppMode.DEVELOPMENT:
        return (LoopbackOnlyGuard, HostGuard, OriginGuard)
    return (SecurityHeaders, HostGuard, OriginGuard, SessionGuard)


def install_guards(app: FastAPI, settings: DeploymentSettings) -> None:
    # Starlette wraps the last added middleware outermost.
    for middleware in reversed(guard_stack(settings)):
        app.add_middleware(middleware, settings=settings)
