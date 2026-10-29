"""Engagement with the fixed formula an adapter declares (FR-019).

Computed when reading, never stored: it is derived, not an original metric. It is
"not available" if any component is absent or the denominator is 0.
"""

from collections.abc import Mapping

from app.analytics.adapters.base import EngagementFormula
from app.analytics.schemas import EngagementRead


def engagement_of(
    formula: EngagementFormula, values: Mapping[str, int]
) -> EngagementRead:
    names = (*formula.numerator, formula.denominator)
    components = {name: values.get(name) for name in names}
    denominator = components[formula.denominator]
    numerator = [components[name] for name in formula.numerator]
    available = (
        denominator is not None
        and denominator > 0
        and all(value is not None for value in numerator)
    )
    value = (
        sum(v for v in numerator if v is not None) / denominator
        if available and denominator is not None
        else None
    )
    return EngagementRead(
        available=available,
        value=value,
        formula=formula.expression,
        components=components,
    )
