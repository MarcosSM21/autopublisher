"""Metric capability per account and per metric group (FR-001, FR-024).

Derived only from local data, with no network call and no keyring read:

- the connection row and its status (no row → `not_connected`; any status other
  than `connected` → `reconnect_required`);
- the permissions a `connected` connection guarantees. SQLite does not store the
  granted scopes (only the keyring secret does), but every platform refuses to
  connect without its required scopes, and Instagram and Threads also mark the
  connection `reconnect_required` when a verification finds one missing. So a
  `connected` connection holds at least the platform's required scopes; any other
  permission (the insights ones) is never requested, hence never granted.

A group the adapter declares but does not read in this version is never
`supported`: without its permission it is `permission_required`, otherwise
`not_supported`.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.adapters.base import MetricsAdapter
from app.analytics.adapters.registry import ADAPTERS, STATIC_CAPABILITIES
from app.instagram_oauth import REQUIRED_PERMISSIONS as INSTAGRAM_PERMISSIONS
from app.models import (
    Account,
    InstagramConnection,
    Platform,
    ThreadsConnection,
    YouTubeConnection,
)
from app.threads_oauth import REQUIRED_SCOPES as THREADS_SCOPES
from app.youtube_oauth import REQUIRED_SCOPES as YOUTUBE_SCOPES

GroupState = Literal[
    "supported",
    "permission_required",
    "not_supported",
    "not_connected",
    "reconnect_required",
]
CapabilityState = Literal[
    "supported",
    "permission_required",
    "not_supported",
    "not_available_on_platform",
    "not_applicable",
    "not_connected",
    "reconnect_required",
]

ConnectionModel = (
    type[YouTubeConnection] | type[InstagramConnection] | type[ThreadsConnection]
)

# Connection table and the permissions a `connected` row guarantees.
CONNECTIONS: dict[Platform, tuple[ConnectionModel, frozenset[str]]] = {
    Platform.YOUTUBE: (YouTubeConnection, YOUTUBE_SCOPES),
    Platform.INSTAGRAM: (InstagramConnection, INSTAGRAM_PERMISSIONS),
    Platform.THREADS: (ThreadsConnection, THREADS_SCOPES),
}

NOT_CONNECTED = "Connect this account to read its metrics."
RECONNECT_REQUIRED = "Reconnect this account to read its metrics again."
PERMISSION_REQUIRED = (
    "These metrics need a permission AutoPublisher does not request yet."
)
NOT_SUPPORTED = "AutoPublisher does not read these metrics yet."


@dataclass(frozen=True)
class GroupCapability:
    group: str
    state: GroupState
    missing_permission: str | None


@dataclass(frozen=True)
class Capability:
    state: CapabilityState
    groups: tuple[GroupCapability, ...]
    reason: str | None

    @property
    def is_refreshable(self) -> bool:
        """At least one group can be read now."""
        return any(group.state == "supported" for group in self.groups)


def _connection_status(
    session: Session, platform: Platform, account_id: int
) -> tuple[str | None, frozenset[str]]:
    model, granted = CONNECTIONS[platform]
    status = session.scalars(
        select(model.status).where(model.account_id == account_id)
    ).first()
    return status, granted


def _group(
    adapter: MetricsAdapter, group: str, granted: frozenset[str]
) -> GroupCapability:
    permission = adapter.groups[group]
    if permission is not None and permission not in granted:
        return GroupCapability(group, "permission_required", permission)
    if group not in adapter.read_groups:
        return GroupCapability(group, "not_supported", None)
    return GroupCapability(group, "supported", None)


def account_capability(session: Session, account: Account) -> Capability:
    platform = Platform(account.platform)
    static = STATIC_CAPABILITIES.get(platform)
    if static is not None:
        return Capability(static.state, (), static.reason)
    adapter = ADAPTERS[platform]
    status, granted = _connection_status(session, platform, account.id)
    if status != "connected":
        state: GroupState = "not_connected" if status is None else "reconnect_required"
        return Capability(
            state,
            tuple(GroupCapability(group, state, None) for group in adapter.groups),
            NOT_CONNECTED if status is None else RECONNECT_REQUIRED,
        )
    groups = tuple(_group(adapter, group, granted) for group in adapter.groups)
    states = {group.state for group in groups}
    if "supported" in states:
        return Capability("supported", groups, None)
    if "permission_required" in states:
        return Capability("permission_required", groups, PERMISSION_REQUIRED)
    return Capability("not_supported", groups, NOT_SUPPORTED)


def is_refreshable(session: Session, account: Account) -> bool:
    return account_capability(session, account).is_refreshable
