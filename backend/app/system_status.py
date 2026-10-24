"""Public health and signed-in diagnostics (contracts/api.md §2, §4; research §17-18).

`/health` is a liveness check, not an operational oracle: only `ok`/`degraded`, no
keyring probe (it could prompt and is diagnostic information). The details are in
`GET /api/system/status`, behind the session guard; scheduler state and the pause
stay in `GET /api/automation`.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.credential_store import CredentialStoreProbe
from app.db import get_session
from app.deployment import DeploymentSettings, http_url, lan_addresses
from app.deployment import suggested_host_names as host_names
from app.loopback import LOOPBACK_ADDRESSES

router = APIRouter(prefix="/api/system", tags=["system"])

SessionDep = Annotated[Session, Depends(get_session)]


def _database_ok(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def health_status(app: FastAPI) -> Literal["ok", "degraded"]:
    """`degraded`: the database does not answer, or the scheduler thread is not
    alive although it should run (autostart). The pause is a choice, not a fault."""
    factory = getattr(app.state, "session_factory", None)
    if factory is None:
        return "degraded"
    with factory() as db:
        if not _database_ok(db):
            return "degraded"
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is None or (scheduler.settings.autostart and not scheduler.running):
        return "degraded"
    return "ok"


def _deployment(request: Request, settings: DeploymentSettings) -> dict[str, Any]:
    port = settings.port or 0
    server = request.scope.get("server")
    socket_address = (
        server[0] if server and server[0] not in LOOPBACK_ADDRESSES else None
    )
    return {
        "port": port,
        "lan_enabled": settings.lan_enabled,
        "addresses": [http_url(host, port) for host in lan_addresses([socket_address])],
        "suggested_names": [http_url(name, port) for name in host_names()],
        "allowed_hosts": list(settings.allowed_hosts),
    }


@router.get("/status")
def system_status(request: Request, db: SessionDep) -> dict[str, Any]:
    """No paths, versions or secrets; read-only."""
    settings: DeploymentSettings | None = request.app.state.deployment
    installation = settings is not None and settings.is_installation
    probe: CredentialStoreProbe = request.app.state.credential_probe
    return {
        "mode": "installation" if installation else "development",
        "database": {"status": "ok" if _database_ok(db) else "error"},
        "credential_store": {"status": probe.status()},
        "deployment": (
            _deployment(request, settings)
            if installation and settings is not None
            else None
        ),
    }
