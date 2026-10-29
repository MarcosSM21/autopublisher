"""Catalog and adapter declarations (Feature 027 T015, FR-006, FR-008–FR-010)."""

from dataclasses import fields

import pytest
from sqlalchemy.orm import Session

from app.analytics.adapters.base import MetricsAdapter
from app.analytics.adapters.registry import ADAPTERS, STATIC_CAPABILITIES
from app.analytics.adapters.threads import ThreadsMetricsAdapter
from app.analytics.catalog import CONCEPTS, CONCEPTS_BY_KEY, Concept
from app.models import Platform

DECLARED = list(ADAPTERS.values())


def test_only_likes_and_comments_are_alignable() -> None:
    assert {c.key for c in CONCEPTS} == {"views", "likes", "comments", "shares"}
    assert {c.key for c in CONCEPTS if c.alignable} == {"likes", "comments"}


def test_no_concept_exposes_comparability() -> None:
    names = {field.name for field in fields(Concept)}
    assert names == {"key", "label", "definition", "alignable"}
    assert not any("compar" in name for name in names)


def test_every_platform_has_an_adapter_or_a_static_capability() -> None:
    assert set(ADAPTERS) | set(STATIC_CAPABILITIES) == set(Platform)
    assert not set(ADAPTERS) & set(STATIC_CAPABILITIES)
    assert all(static.reason for static in STATIC_CAPABILITIES.values())


@pytest.mark.parametrize("adapter", DECLARED, ids=lambda a: str(a.platform))
def test_every_declared_metric_is_well_formed(adapter: MetricsAdapter) -> None:
    names = [metric.name for metric in adapter.metrics]
    assert len(names) == len(set(names))
    assert set(adapter.read_groups) <= set(adapter.groups)
    for metric in adapter.metrics:
        assert metric.definition.strip(), metric.name
        assert metric.label.strip(), metric.name
        assert metric.group in adapter.groups, metric.name
        assert metric.concept is None or metric.concept in CONCEPTS_BY_KEY
    # One metric per concept and platform, so alignment is never ambiguous.
    concepts = [m.concept for m in adapter.metrics if m.concept is not None]
    assert len(concepts) == len(set(concepts))
    # An excluded field is never also a declared metric.
    assert not {e.name for e in adapter.excluded} & set(names)
    assert adapter.batch_size >= 1


def test_youtube_declaration() -> None:
    youtube = ADAPTERS[Platform.YOUTUBE]
    assert {m.name: m.concept for m in youtube.metrics} == {
        "viewCount": "views",
        "likeCount": "likes",
        "commentCount": "comments",
        "dislikeCount": None,
    }
    assert [(e.name, e.reason) for e in youtube.excluded] == [
        ("favoriteCount", "deprecated by YouTube in 2015, always 0")
    ]
    assert dict(youtube.groups) == {
        "basic": "https://www.googleapis.com/auth/youtube.readonly"
    }
    assert youtube.batch_size == 50
    view_count = next(m for m in youtube.metrics if m.name == "viewCount")
    assert "2026-08-24" in view_count.definition
    assert "exactly as returned" in view_count.definition


def test_instagram_declares_basic_counters_and_unread_insights() -> None:
    instagram = ADAPTERS[Platform.INSTAGRAM]
    assert dict(instagram.groups) == {
        "basic": "instagram_business_basic",
        "insights": "instagram_business_manage_insights",
    }
    assert instagram.read_groups == {"basic"}
    by_group = {
        group: {m.name for m in instagram.metrics if m.group == group}
        for group in instagram.groups
    }
    assert by_group == {
        "basic": {"like_count", "comments_count"},
        "insights": {
            "views",
            "reach",
            "likes",
            "comments",
            "shares",
            "saved",
            "total_interactions",
        },
    }
    assert {m.origin for m in instagram.metrics if m.group == "basic"} == {
        "public_counter"
    }
    assert {m.origin for m in instagram.metrics if m.group == "insights"} == {"insight"}
    assert instagram.batch_size == 1


def test_threads_aligns_replies_under_comments_with_a_note() -> None:
    threads = ADAPTERS[Platform.THREADS]
    assert dict(threads.groups) == {"insights": "threads_manage_insights"}
    assert threads.read_groups == frozenset()
    assert {m.name for m in threads.metrics} == {
        "views",
        "likes",
        "replies",
        "reposts",
        "quotes",
        "shares",
    }
    replies = next(m for m in threads.metrics if m.name == "replies")
    assert replies.concept == "comments"
    assert "alignment" in replies.definition


def test_only_youtube_declares_engagement() -> None:
    formulas = {
        platform: adapter.engagement
        for platform, adapter in ADAPTERS.items()
        if adapter.engagement is not None
    }
    assert list(formulas) == [Platform.YOUTUBE]
    formula = formulas[Platform.YOUTUBE]
    assert formula.expression == "(likeCount + commentCount) / viewCount"
    declared = {m.name for m in ADAPTERS[Platform.YOUTUBE].metrics}
    assert {*formula.numerator, formula.denominator} <= declared


def test_threads_fetch_refuses_to_run() -> None:
    with pytest.raises(RuntimeError):
        ThreadsMetricsAdapter().fetch(Session(), 1, ["TH-1"])
