"""TikTok option rules and their mapping to `post_info` (research §5, spec FR-014 to
FR-021): nothing is preselected, interactions are positive controls inverted into
`disable_*`, both commercial toggles are always sent and `is_aigc` is explicit."""

import itertools
from typing import Any

import pytest

from app.models import TikTokPublicationOptions
from app.tiktok_media import (
    BRANDED_DECLARATION_VERSION,
    DISCLOSURE_INCOMPLETE_MESSAGE,
    MUSIC_DECLARATION_VERSION,
    allowed_privacy_levels,
    declaration_for,
    disclosure_labels,
    option_problems,
    post_info,
    source_info,
)
from app.tiktok_media import plan_chunks as _plan

COMPLETE: dict[str, Any] = {
    "privacy_level": "SELF_ONLY",
    "allow_comment": False,
    "allow_duet": False,
    "allow_stitch": False,
    "commercial_disclosure_enabled": False,
    "brand_organic_toggle": False,
    "brand_content_toggle": False,
    "is_aigc": False,
}


def _options(**overrides: Any) -> TikTokPublicationOptions:
    return TikTokPublicationOptions(publication_id=1, **{**COMPLETE, **overrides})


def _codes(options: TikTokPublicationOptions, audited: bool = False) -> list[str]:
    return [p.code for p in option_problems(options, client_audited=audited)]


def test_complete_options_have_no_problems() -> None:
    assert _codes(_options()) == []


def test_unaudited_client_only_allows_self_only() -> None:
    assert allowed_privacy_levels(client_audited=False) == ("SELF_ONLY",)
    assert "PUBLIC_TO_EVERYONE" in allowed_privacy_levels(client_audited=True)


def test_privacy_is_required() -> None:
    assert _codes(_options(privacy_level=None)) == ["tiktok_privacy_required"]


@pytest.mark.parametrize(
    "privacy", ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"]
)
def test_other_privacy_is_not_allowed_for_the_unaudited_client(privacy: str) -> None:
    assert _codes(_options(privacy_level=privacy)) == ["tiktok_privacy_not_allowed"]


def test_aigc_is_required() -> None:
    assert _codes(_options(is_aigc=None)) == ["tiktok_aigc_required"]


@pytest.mark.parametrize("value", [True, False])
def test_aigc_is_sent_explicitly(value: bool) -> None:
    info = post_info(_options(is_aigc=value), "caption")

    assert info["is_aigc"] is value


def test_disclosure_without_any_toggle_is_not_publishable() -> None:
    problems = option_problems(
        _options(commercial_disclosure_enabled=True), client_audited=False
    )

    assert [p.code for p in problems] == ["tiktok_disclosure_incomplete"]
    assert problems[0].message == DISCLOSURE_INCOMPLETE_MESSAGE
    assert DISCLOSURE_INCOMPLETE_MESSAGE == (
        "You need to indicate if your content promotes yourself, a third party, or "
        "both."
    )


def test_branded_content_cannot_be_private() -> None:
    options = _options(commercial_disclosure_enabled=True, brand_content_toggle=True)

    assert "tiktok_branded_content_private" in _codes(options)


@pytest.mark.parametrize(
    ("disclosure", "organic", "branded", "content", "organic_sent"),
    [
        (False, False, False, False, False),
        (True, True, False, False, True),
        (True, False, True, True, False),
        (True, True, True, True, True),
    ],
)
def test_commercial_mapping_is_always_materialised(
    disclosure: bool, organic: bool, branded: bool, content: bool, organic_sent: bool
) -> None:
    options = _options(
        privacy_level="FOLLOWER_OF_CREATOR",
        commercial_disclosure_enabled=disclosure,
        brand_organic_toggle=organic,
        brand_content_toggle=branded,
    )

    info = post_info(options, "caption")

    assert info["brand_content_toggle"] is content
    assert info["brand_organic_toggle"] is organic_sent


@pytest.mark.parametrize(
    ("comment", "duet", "stitch"), list(itertools.product([False, True], repeat=3))
)
def test_interactions_are_inverted(comment: bool, duet: bool, stitch: bool) -> None:
    options = _options(allow_comment=comment, allow_duet=duet, allow_stitch=stitch)

    info = post_info(options, "caption")

    assert info["disable_comment"] is (not comment)
    assert info["disable_duet"] is (not duet)
    assert info["disable_stitch"] is (not stitch)
    # Interactions never block publishing, whatever their value.
    assert _codes(options) == []


def test_unchecked_interactions_disable_everything() -> None:
    info = post_info(_options(), "x")

    assert info["disable_comment"] is True
    assert info["disable_duet"] is True
    assert info["disable_stitch"] is True


def test_post_info_shape() -> None:
    info = post_info(_options(), "Summer drop.\n\n#cyber")

    assert info == {
        "title": "Summer drop.\n\n#cyber",
        "privacy_level": "SELF_ONLY",
        "disable_comment": True,
        "disable_duet": True,
        "disable_stitch": True,
        "brand_content_toggle": False,
        "brand_organic_toggle": False,
        "is_aigc": False,
    }
    # No cover and no other field.
    assert "video_cover_timestamp_ms" not in info


def test_title_is_omitted_when_the_caption_is_empty() -> None:
    assert "title" not in post_info(_options(), "")


def test_source_info_shape() -> None:
    assert source_info(_plan(3_145_728)) == {
        "source": "FILE_UPLOAD",
        "video_size": 3_145_728,
        "chunk_size": 3_145_728,
        "total_chunk_count": 1,
    }


def test_declarations() -> None:
    music = declaration_for(_options())
    with_your_brand = declaration_for(
        _options(commercial_disclosure_enabled=True, brand_organic_toggle=True)
    )
    branded = declaration_for(
        _options(
            privacy_level="FOLLOWER_OF_CREATOR",
            commercial_disclosure_enabled=True,
            brand_content_toggle=True,
        )
    )

    assert music.version == MUSIC_DECLARATION_VERSION == "music-usage-2026-10-14"
    assert music.text == "By posting, you agree to TikTok's Music Usage Confirmation."
    assert [link.label for link in music.links] == ["Music Usage Confirmation"]
    assert with_your_brand == music
    assert branded.version == BRANDED_DECLARATION_VERSION
    assert BRANDED_DECLARATION_VERSION == "branded-music-usage-2026-10-14"
    assert branded.text == (
        "By posting, you agree to TikTok's Branded Content Policy and Music Usage "
        "Confirmation."
    )
    assert [link.label for link in branded.links] == [
        "Branded Content Policy",
        "Music Usage Confirmation",
    ]
    for link in (*music.links, *branded.links):
        assert link.url.startswith("https://www.tiktok.com/legal/")


@pytest.mark.parametrize(
    ("organic", "branded", "labels"),
    [
        (False, False, []),
        (True, False, ["Your video will be labeled as 'Promotional content'"]),
        (False, True, ["Your video will be labeled as 'Paid partnership'"]),
        (True, True, ["Your video will be labeled as 'Paid partnership'"]),
    ],
)
def test_labels(organic: bool, branded: bool, labels: list[str]) -> None:
    options = _options(
        privacy_level="FOLLOWER_OF_CREATOR",
        commercial_disclosure_enabled=True,
        brand_organic_toggle=organic,
        brand_content_toggle=branded,
    )

    assert disclosure_labels(options) == labels


def test_no_labels_without_disclosure() -> None:
    assert disclosure_labels(_options()) == []
