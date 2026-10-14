"""Caption composition and TikTok's caption count (research §7).

The cases below are shared with `frontend/src/utils.test.ts`: TikTok's "2200 UTF-16
runes" is read as UTF-16 code units, so a character outside the BMP counts 2.
"""

import pytest

from app.models import Content, Publication
from app.tiktok_media import (
    TIKTOK_CAPTION_MAX,
    build_caption,
    caption_problems,
    tiktok_caption_length,
)

# (caption, UTF-16 code units) — keep in sync with frontend/src/utils.test.ts.
CAPTION_CASES: list[tuple[str, int]] = [
    ("", 0),
    ("a" * 2199, 2199),
    ("a" * 2200, 2200),
    ("a" * 2201, 2201),
    ("é", 1),
    ("中", 1),
    ("😀", 2),
    ("𝐀", 2),
    ("👨‍👩‍👧", 8),
    ("🇪🇸", 4),
    ("❤️", 2),
    ("😀" * 1100, 2200),
    ("😀" * 1100 + "a", 2201),
]


@pytest.mark.parametrize(("caption", "length"), CAPTION_CASES)
def test_caption_length_counts_utf16_code_units(caption: str, length: int) -> None:
    assert tiktok_caption_length(caption) == length


def test_caption_length_is_not_the_code_point_count() -> None:
    caption = "😀" * 1100 + "a"

    assert len(caption) == 1101
    assert tiktok_caption_length(caption) == 2201
    assert caption_problems(caption) != []


@pytest.mark.parametrize(("caption", "length"), CAPTION_CASES)
def test_caption_limit(caption: str, length: int) -> None:
    problems = caption_problems(caption)

    if length <= TIKTOK_CAPTION_MAX:
        assert problems == []
    else:
        [problem] = problems
        assert problem.code == "tiktok_caption_invalid"
        assert problem.field == "caption"
        # The limit and the real value are reported; nothing is truncated.
        assert str(length) in problem.message
        assert str(TIKTOK_CAPTION_MAX) in problem.message


def _publication(**overrides: object) -> Publication:
    values: dict[str, object] = {
        "content_id": 1,
        "title_override": "Generic title",
        "description_override": None,
        "hashtags_override": None,
    }
    values.update(overrides)
    return Publication(**values)


def _content(**values: object) -> Content:
    defaults: dict[str, object] = {
        "title": "Content title",
        "description": None,
        "hashtags": [],
    }
    defaults.update(values)
    return Content(**defaults)


@pytest.mark.parametrize(
    ("description", "hashtags", "caption"),
    [
        ("Summer drop.", ["cyber", "studio"], "Summer drop.\n\n#cyber #studio"),
        ("Summer drop.", [], "Summer drop."),
        (None, ["cyber"], "#cyber"),
        ("", ["cyber"], "#cyber"),
        (None, [], ""),
    ],
)
def test_caption_composition(
    description: str | None, hashtags: list[str], caption: str
) -> None:
    content = _content(description=description, hashtags=hashtags)

    assert build_caption(_publication(), content) == caption


def test_caption_uses_publication_overrides_and_never_the_title() -> None:
    content = _content(description="From content", hashtags=["content"])
    publication = _publication(
        title_override="Never sent",
        description_override="Override",
        hashtags_override=["override"],
    )

    caption = build_caption(publication, content)

    assert caption == "Override\n\n#override"
    assert "Never sent" not in caption
    assert "Content title" not in caption


def test_caption_is_never_trimmed_nor_normalised() -> None:
    # A decomposed "é" (e + combining acute) and surrounding spaces stay as typed.
    description = "  café @friend #Tag  "
    content = _content(description=description, hashtags=[])

    caption = build_caption(_publication(), content)

    assert caption == description
    assert tiktok_caption_length(caption) == len(description)
