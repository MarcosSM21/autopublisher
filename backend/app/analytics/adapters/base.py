"""The common declaration every platform metrics adapter follows (FR-002, FR-024).

An adapter declares its original metrics, the documented exclusions, the permission
each metric group needs, which groups this version reads and its fixed engagement
formula. The analytics core never knows platform details beyond this declaration.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.models import MetricOrigin, Platform

FetchKind = Literal[
    "ok",
    "not_found",
    "rate_limited",
    "unauthorized",
    "permission_missing",
    "transient",
]


@dataclass(frozen=True)
class MetricDef:
    """One original platform metric, with its original name."""

    name: str
    label: str
    definition: str
    origin: MetricOrigin
    # Common catalog concept it aligns with, if any (never a comparison).
    concept: str | None
    group: str
    # False for a metric the platform only returns to some callers (e.g. YouTube
    # dislikes, owner only): a post lists it only when it was returned.
    listed_when_absent: bool = True


@dataclass(frozen=True)
class ExcludedMetric:
    """An officially deprecated or meaningless field, ignored on purpose (FR-006)."""

    name: str
    reason: str


@dataclass(frozen=True)
class EngagementFormula:
    """Fixed, per-platform engagement: sum of the numerators / the denominator."""

    numerator: tuple[str, ...]
    denominator: str

    @property
    def expression(self) -> str:
        return f"({' + '.join(self.numerator)}) / {self.denominator}"


@dataclass(frozen=True)
class FetchResult:
    """The outcome of reading one remote post; `values` only when `ok`."""

    kind: FetchKind
    values: Mapping[str, int] = field(default_factory=dict)
    retry_at: datetime | None = None

    @classmethod
    def ok(cls, values: Mapping[str, int]) -> "FetchResult":
        return cls("ok", dict(values))

    @classmethod
    def not_found(cls) -> "FetchResult":
        return cls("not_found")

    @classmethod
    def rate_limited(cls, retry_at: datetime | None = None) -> "FetchResult":
        return cls("rate_limited", retry_at=retry_at)

    @classmethod
    def unauthorized(cls) -> "FetchResult":
        return cls("unauthorized")

    @classmethod
    def permission_missing(cls) -> "FetchResult":
        return cls("permission_missing")

    @classmethod
    def transient(cls) -> "FetchResult":
        return cls("transient")


class MetricsAdapter(Protocol):
    """Declarations are read-only; implementations set them as class attributes."""

    @property
    def platform(self) -> Platform: ...

    @property
    def metrics(self) -> tuple[MetricDef, ...]: ...

    @property
    def excluded(self) -> tuple[ExcludedMetric, ...]: ...

    @property
    def groups(self) -> Mapping[str, str | None]:
        """Metric group → the permission it needs (None: no extra permission)."""
        ...

    @property
    def read_groups(self) -> frozenset[str]:
        """Groups this version actually reads. A group declared but not read (e.g.
        insights) is never fetched, whatever permissions the account has."""
        ...

    @property
    def engagement(self) -> EngagementFormula | None: ...

    @property
    def source(self) -> str:
        """The API call identifier recorded in each snapshot."""
        ...

    @property
    def batch_size(self) -> int:
        """Remote ids per fetch call."""
        ...

    def fetch(
        self, session: Session, account_id: int, remote_ids: Sequence[str]
    ) -> Mapping[str, FetchResult]: ...
