"""Metadata sent to YouTube (research.md §12)."""

import pytest

from app.youtube_publishing import build_description, build_resource, validate_metadata


@pytest.mark.parametrize(
    ("description", "hashtags", "expected"),
    [
        ("Intro.", ["cyber", "security"], "Intro.\n\n#cyber #security"),
        (None, ["cyber", "security"], "#cyber #security"),
        ("", ["cyber"], "#cyber"),
        ("Intro.", [], "Intro."),
        (None, [], ""),
    ],
)
def test_build_description(
    description: str | None, hashtags: list[str], expected: str
) -> None:
    assert build_description(description, hashtags) == expected


def _fields(title: str | None, description: str = "") -> set[str | None]:
    return {problem.field for problem in validate_metadata(title, description)}


def test_valid_metadata_has_no_problems() -> None:
    assert validate_metadata("A title", "A description") == []


@pytest.mark.parametrize("title", [None, "", "   "])
def test_title_is_required(title: str | None) -> None:
    assert _fields(title) == {"title"}


def test_title_length_counts_characters() -> None:
    assert _fields("x" * 100) == set()
    assert _fields("x" * 101) == {"title"}
    # Emoji are single code points: 100 of them still fit.
    assert _fields("🔒" * 100) == set()
    assert _fields("🔒" * 101) == {"title"}


@pytest.mark.parametrize("title", ["a < b", "a > b"])
def test_title_rejects_angle_brackets(title: str) -> None:
    assert _fields(title) == {"title"}


def test_description_limit_is_in_bytes() -> None:
    assert _fields("Title", "a" * 5000) == set()
    assert _fields("Title", "a" * 5001) == {"description"}
    assert _fields("Title", "é" * 2500) == set()
    assert _fields("Title", "é" * 2500 + "a") == {"description"}


@pytest.mark.parametrize("description", ["a < b", "a > b"])
def test_description_rejects_angle_brackets(description: str) -> None:
    assert _fields("Title", description) == {"description"}


def test_problem_messages_are_specific() -> None:
    (problem,) = validate_metadata("x" * 101, "")
    assert problem.code == "invalid_metadata"
    assert "100 characters" in problem.message


def test_resource_never_contains_tags_or_publish_at() -> None:
    resource = build_resource(
        title="Title",
        description="Intro.\n\n#cyber",
        privacy_status="unlisted",
        made_for_kids=True,
        contains_synthetic_media=False,
    )

    assert resource == {
        "snippet": {"title": "Title", "description": "Intro.\n\n#cyber"},
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": True,
            "containsSyntheticMedia": False,
        },
    }
