"""Consent fingerprint and video digests (research §6)."""

import hashlib
import random
from pathlib import Path
from typing import Any

import pytest

from app.models import TikTokPublicationOptions
from app.tiktok_media import (
    FILE_READ_SIZE,
    UploadDigest,
    consent_fingerprint,
    file_sha256,
)

BASE_OPTIONS: dict[str, Any] = {
    "privacy_level": "SELF_ONLY",
    "allow_comment": False,
    "allow_duet": False,
    "allow_stitch": False,
    "commercial_disclosure_enabled": False,
    "brand_organic_toggle": False,
    "brand_content_toggle": False,
    "is_aigc": False,
}
BASE: dict[str, Any] = {
    "open_id": "open-id-1",
    "video_sha256": "a" * 64,
    "caption": "Summer drop.\n\n#cyber",
}


def _fingerprint(options: dict[str, Any] | None = None, **inputs: Any) -> str | None:
    values = {**BASE_OPTIONS, **(options or {})}
    return consent_fingerprint(
        options=TikTokPublicationOptions(publication_id=1, **values),
        **{**BASE, **inputs},
    )


def test_same_inputs_same_fingerprint() -> None:
    first = _fingerprint()

    assert first is not None
    assert len(first) == 64
    assert first == _fingerprint()


@pytest.mark.parametrize(
    "inputs",
    [
        {"open_id": "open-id-2"},
        {"video_sha256": "b" * 64},
        {"caption": "Summer drop.\n\n#cyber "},
        {"caption": ""},
    ],
)
def test_material_inputs_change_it(inputs: dict[str, Any]) -> None:
    assert _fingerprint(**inputs) != _fingerprint()


@pytest.mark.parametrize(
    "options",
    [
        {"allow_comment": True},
        {"allow_duet": True},
        {"allow_stitch": True},
        {"commercial_disclosure_enabled": True, "brand_organic_toggle": True},
        {"is_aigc": True},
        # Privacy (an option not allowed for the unaudited client still differs).
        {"privacy_level": "FOLLOWER_OF_CREATOR"},
        # Branded content changes both the toggle and the declaration version.
        {
            "privacy_level": "FOLLOWER_OF_CREATOR",
            "commercial_disclosure_enabled": True,
            "brand_content_toggle": True,
        },
    ],
)
def test_each_option_changes_it(options: dict[str, Any]) -> None:
    assert _fingerprint(options) != _fingerprint()


def test_disclosure_flag_alone_changes_it() -> None:
    your_brand: dict[str, Any] = {
        "commercial_disclosure_enabled": True,
        "brand_organic_toggle": True,
    }
    both = {
        **your_brand,
        "brand_content_toggle": True,
        "privacy_level": "FOLLOWER_OF_CREATOR",
    }
    branded_only = {
        "privacy_level": "FOLLOWER_OF_CREATOR",
        "commercial_disclosure_enabled": True,
        "brand_content_toggle": True,
    }

    assert (
        len({_fingerprint(your_brand), _fingerprint(both), _fingerprint(branded_only)})
        == 3
    )


@pytest.mark.parametrize(
    "options",
    [
        {"privacy_level": None},
        {"is_aigc": None},
        {"commercial_disclosure_enabled": True},
    ],
)
def test_no_fingerprint_while_options_are_incomplete(options: dict[str, Any]) -> None:
    assert _fingerprint(options) is None


def test_schedule_and_title_are_not_inputs() -> None:
    # The function only takes the consented inputs: a date or a generic title
    # cannot change the fingerprint.
    import inspect

    parameters = set(inspect.signature(consent_fingerprint).parameters)

    assert parameters == {"open_id", "video_sha256", "caption", "options"}


def test_file_sha256_streams_bounded_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = random.Random(7).randbytes(3 * FILE_READ_SIZE + 123)
    path = tmp_path / "clip.mp4"
    path.write_bytes(data)
    sizes: list[int] = []
    original_open = Path.open

    class SpyFile:
        def __init__(self, file: Any) -> None:
            self.file = file

        def read(self, size: int = -1) -> bytes:
            sizes.append(size)
            return bytes(self.file.read(size))

        def __enter__(self) -> "SpyFile":
            return self

        def __exit__(self, *args: object) -> None:
            self.file.close()

    def spy_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        return SpyFile(original_open(self, *args, **kwargs))

    monkeypatch.setattr(Path, "open", spy_open)

    digest = file_sha256(path)

    assert digest == hashlib.sha256(data).hexdigest()
    assert FILE_READ_SIZE == 1024 * 1024
    assert sizes and all(0 < size <= FILE_READ_SIZE for size in sizes)


def test_incremental_digest_matches_the_full_digest() -> None:
    generator = random.Random(3)
    data = generator.randbytes(50_000)
    for _ in range(20):
        cuts = sorted(generator.sample(range(1, len(data)), 5))
        digest = UploadDigest()
        start = 0
        for cut in [*cuts, len(data)]:
            digest.update(data[start:cut])
            start = cut
        assert digest.hexdigest() == hashlib.sha256(data).hexdigest()
