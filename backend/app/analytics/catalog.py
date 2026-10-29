"""The small common metric catalog (FR-008, FR-009).

Concepts only align metrics of different platforms visually. No concept is
quantitatively comparable across platforms, so the catalog has no such field: only
`alignable` says whether a concept may be shown side by side at all.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Concept:
    key: str
    label: str
    definition: str
    alignable: bool


CONCEPTS = (
    Concept(
        key="views",
        label="Views",
        definition=(
            "How many times the post was viewed. Each platform counts a view "
            "differently, so views are never shown side by side."
        ),
        alignable=False,
    ),
    Concept(
        key="likes",
        label="Likes",
        definition="How many people liked the post on its platform.",
        alignable=True,
    ),
    Concept(
        key="comments",
        label="Comments",
        definition=(
            "How many comments or replies the post received on its platform. "
            "Platforms count nested replies differently."
        ),
        alignable=True,
    ),
    Concept(
        key="shares",
        label="Shares",
        definition=(
            "How many times the post was shared. Each platform defines a share "
            "differently, so shares are never shown side by side."
        ),
        alignable=False,
    ),
)

CONCEPTS_BY_KEY = {concept.key: concept for concept in CONCEPTS}
