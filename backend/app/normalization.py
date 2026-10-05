"""Input cleaning and uniqueness keys.

Uniqueness keys follow research.md decision 5: NFKC, then casefold, then NFKC again, so
that comparisons are case-insensitive and treat Unicode-equivalent forms as equal.
"""

import unicodedata


def normalize_key(value: str) -> str:
    """Return the key used to detect duplicate names and handles."""
    folded = unicodedata.normalize("NFKC", value).casefold()
    return unicodedata.normalize("NFKC", folded)


def clean_text(value: str | None) -> str | None:
    """Strip outer whitespace and turn empty values into None."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def clean_handle(value: str) -> str:
    """Strip outer whitespace and a single leading '@' from a handle."""
    stripped = value.strip()
    if stripped.startswith("@"):
        stripped = stripped[1:].strip()
    return stripped
