"""Chunk planner for FILE_UPLOAD (research §9): pure, never touches a file."""

import random

import pytest

from app.tiktok_media import CHUNK_SIZE, SINGLE_CHUNK_MAX, ChunkPlan, plan_chunks

MIB = 1024 * 1024


def test_default_constants() -> None:
    assert SINGLE_CHUNK_MAX == 64_000_000
    assert CHUNK_SIZE == 33_554_432


@pytest.mark.parametrize(
    ("size", "chunk_size", "count", "last"),
    [
        (1 * MIB, 1_048_576, 1, 1_048_576),
        (5 * MIB, 5_242_880, 1, 5_242_880),
        (20 * MIB, 20_971_520, 1, 20_971_520),
        (64_000_000, 64_000_000, 1, 64_000_000),
        (64_000_001, 32_000_000, 2, 32_000_001),
        (64 * MIB, 33_554_432, 2, 33_554_432),
        (65 * MIB, 33_554_432, 2, 34_603_008),
        (128 * MIB, 33_554_432, 4, 33_554_432),
        (500 * MIB, 33_554_432, 15, 54_525_952),
        (4_000_000_000, 33_554_432, 119, 40_577_024),
    ],
)
def test_reference_table(size: int, chunk_size: int, count: int, last: int) -> None:
    plan = plan_chunks(size)

    assert plan == ChunkPlan(
        video_size=size, chunk_size=chunk_size, total_chunk_count=count
    )
    first, end = plan.chunk_range(count - 1)
    assert end - first + 1 == last
    assert end == size - 1


def test_ranges_and_content_range() -> None:
    plan = plan_chunks(65 * MIB)

    assert plan.ranges() == [(0, 33_554_431), (33_554_432, 68_157_439)]
    assert plan.content_range(0) == "bytes 0-33554431/68157440"
    assert plan.content_range(1) == "bytes 33554432-68157439/68157440"
    assert plan.is_last(1) and not plan.is_last(0)


def test_single_chunk_content_range() -> None:
    plan = plan_chunks(3_145_728)

    assert plan.ranges() == [(0, 3_145_727)]
    assert plan.content_range(0) == "bytes 0-3145727/3145728"


def _check_properties(size: int) -> None:
    plan = plan_chunks(size)
    ranges = plan.ranges()
    assert len(ranges) == plan.total_chunk_count
    # Contiguous and covering the whole file.
    assert ranges[0][0] == 0
    assert ranges[-1][1] == size - 1
    for (_, end), (start, _) in zip(ranges, ranges[1:], strict=False):
        assert start == end + 1
    if plan.total_chunk_count == 1:
        assert size <= 64_000_000
        assert plan.chunk_size == size
        return
    assert 5 * MIB <= plan.chunk_size <= 64_000_000
    assert plan.total_chunk_count == size // plan.chunk_size
    assert 2 <= plan.total_chunk_count <= 1000
    last = ranges[-1][1] - ranges[-1][0] + 1
    assert plan.chunk_size <= last < 2 * plan.chunk_size
    assert last < 128_000_000
    for start, end in ranges[:-1]:
        assert end - start + 1 == plan.chunk_size


@pytest.mark.parametrize(
    "size",
    [
        1,
        2,
        5 * MIB - 1,
        5 * MIB,
        63_999_999,
        64_000_000,
        64_000_001,
        64_000_002,
        67_108_863,
        67_108_864,
        67_108_865,
        100_663_295,
        100_663_296,
        3_999_999_999,
        4_000_000_000,
    ],
)
def test_properties_at_boundaries(size: int) -> None:
    _check_properties(size)


def test_properties_over_many_sizes() -> None:
    generator = random.Random(13)
    for _ in range(5000):
        _check_properties(generator.randint(1, 4_000_000_000))


@pytest.mark.parametrize("size", [0, -1])
def test_non_positive_size_is_rejected(size: int) -> None:
    with pytest.raises(ValueError):
        plan_chunks(size)


def test_injected_constants_for_small_test_files() -> None:
    plan = plan_chunks(10_000, single_chunk_max=4096, chunk_size=2048)

    assert plan.total_chunk_count == 4
    assert plan.chunk_size == 2048
    assert plan.ranges()[-1] == (6144, 9999)
