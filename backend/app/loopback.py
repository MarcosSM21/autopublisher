"""Loopback checks from the real ASGI connection, never from HTTP headers.

`scope["client"]` is the peer address and `scope["server"]` the local socket address
set by uvicorn; there is no reverse proxy and `proxy_headers` stays off, so neither
can be forged by the client.
"""

from collections.abc import Mapping
from typing import Any

from fastapi import Request

from app.errors import AppError

# Exact literals uvicorn reports for loopback connections.
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1"})


def _address(entry: Any) -> str | None:
    if not entry:
        return None
    host = entry[0]
    return host if isinstance(host, str) else None


def is_loopback_client(scope: Mapping[str, Any]) -> bool:
    """The peer connected from this computer."""
    return _address(scope.get("client")) in LOOPBACK_ADDRESSES


def is_loopback_request(scope: Mapping[str, Any]) -> bool:
    """A host action: loopback client **and** loopback socket (research §15).

    Opening the app at the host's LAN address from the host itself is not enough:
    the socket address is then the LAN one.
    """
    return (
        is_loopback_client(scope)
        and _address(scope.get("server")) in LOOPBACK_ADDRESSES
    )


def require_host_action(request: Request) -> None:
    """Installation mode: starting YouTube/TikTok OAuth is a host-only action
    (contracts/api.md §5). Checked before any attempt is created."""
    deployment = request.app.state.deployment
    if deployment is None or not deployment.is_installation:
        return
    if not is_loopback_request(request.scope):
        raise AppError(
            409,
            "host_only_action",
            "Connect this account from the computer that runs AutoPublisher, at "
            f"http://127.0.0.1:{deployment.port}.",
        )
