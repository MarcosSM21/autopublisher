"""Content Publishing calls of the Instagram gateway against the fake Meta (research
§1, §18). Like test_instagram_gateway.py, the only place that looks at Meta's
numbers."""

from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest

from app.instagram_gateway import (
    GRAPH_API_VERSION,
    InstagramGateway,
    MetaError,
    MetaPermissionDenied,
    MetaPublishRejected,
    MetaRejected,
    MetaTokenInvalid,
    MetaUnavailable,
    MetaUnexpectedResponse,
)
from tests.fakes import (
    FAKE_IG_LONG_TOKEN,
    FAKE_META_ERROR_TEXT,
    FAKE_SIGNATURE,
    IG_USER_ID,
    FakeClock,
    FakeMeta,
)

SIGNED_URL = f"https://r2.example/k.jpg?X-Amz-Signature={FAKE_SIGNATURE}"


@pytest.fixture
def meta() -> FakeMeta:
    return FakeMeta()


@pytest.fixture
def gateway(meta: FakeMeta) -> Iterator[InstagramGateway]:
    with httpx.Client(transport=meta.transport()) as client:
        yield InstagramGateway(client, FakeClock().now)


def _image(gateway: InstagramGateway, **overrides: Any) -> str:
    values: dict[str, Any] = {
        "image_url": SIGNED_URL,
        "caption": "Hi #a",
        "alt_text": "A sign",
        "is_ai_generated": False,
    }
    values.update(overrides)
    return gateway.create_image_container(IG_USER_ID, FAKE_IG_LONG_TOKEN, **values)


def test_image_container_request_shape(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    container_id = _image(gateway)

    [request] = meta.requests_for("create")
    assert request.method == "POST"
    assert request.url == (
        f"https://graph.instagram.com/{GRAPH_API_VERSION}/{IG_USER_ID}/media"
    )
    assert FAKE_SIGNATURE not in request.url
    assert request.form == {
        "image_url": SIGNED_URL,
        "caption": "Hi #a",
        "alt_text": "A sign",
        "is_ai_generated": "false",
        "access_token": FAKE_IG_LONG_TOKEN,
    }
    assert container_id in meta.containers


def test_empty_caption_and_alt_text_are_omitted(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    _image(gateway, caption="", alt_text=None, is_ai_generated=True)

    form = meta.requests_for("create")[0].form
    assert "caption" not in form
    assert "alt_text" not in form
    assert form["is_ai_generated"] == "true"


def test_reel_container_request_shape(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    gateway.create_reel_container(
        IG_USER_ID,
        FAKE_IG_LONG_TOKEN,
        video_url=SIGNED_URL,
        caption="Reel",
        share_to_feed=False,
        is_ai_generated=True,
    )

    form = meta.requests_for("create")[0].form
    assert form["media_type"] == "REELS"
    assert form["video_url"] == SIGNED_URL
    assert form["share_to_feed"] == "false"
    assert form["is_ai_generated"] == "true"
    assert "alt_text" not in form


def test_status_publish_permalink_and_quota(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    meta.status_script = ["IN_PROGRESS", "FINISHED"]
    meta.quota = (3, 50)
    container_id = _image(gateway)

    assert gateway.container_status(container_id, FAKE_IG_LONG_TOKEN) == "IN_PROGRESS"
    assert gateway.container_status(container_id, FAKE_IG_LONG_TOKEN) == "FINISHED"
    media_id = gateway.publish(IG_USER_ID, container_id, FAKE_IG_LONG_TOKEN)
    assert gateway.container_status(container_id, FAKE_IG_LONG_TOKEN) == "PUBLISHED"
    assert gateway.media_permalink(media_id, FAKE_IG_LONG_TOKEN) == (
        f"https://www.instagram.com/p/{media_id}/"
    )
    assert gateway.publishing_limit(IG_USER_ID, FAKE_IG_LONG_TOKEN) == (3, 50)
    publish = meta.requests_for("publish")[0]
    assert publish.form["creation_id"] == container_id
    assert "creation_id" not in publish.url


def test_unexpected_quota_shape_is_none(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    meta.quota = None

    assert gateway.publishing_limit(IG_USER_ID, FAKE_IG_LONG_TOKEN) is None


def test_missing_permalink_is_none(gateway: InstagramGateway, meta: FakeMeta) -> None:
    meta.permalinks = False

    assert gateway.media_permalink("1", FAKE_IG_LONG_TOKEN) is None


@pytest.mark.parametrize(
    ("fault", "expected", "numbers"),
    [
        ("transport", MetaUnavailable, None),
        ("server_error", MetaUnavailable, None),
        ("rate_limited", MetaUnavailable, None),
        ("graph_2", MetaUnavailable, None),
        ("graph_190", MetaTokenInvalid, None),
        ("graph_10", MetaPermissionDenied, None),
        ("graph_9_2207042", MetaPublishRejected, (9, 2207042)),
        ("graph_9004_2207052", MetaPublishRejected, (9004, 2207052)),
        ("graph_-2_2207003", MetaPublishRejected, (-2, 2207003)),
        ("graph_4_2207051", MetaPublishRejected, (4, 2207051)),
        ("graph_9007_2207027", MetaPublishRejected, (9007, 2207027)),
        ("graph_100", MetaRejected, None),
        ("bad_json", MetaUnexpectedResponse, None),
        ("missing_fields", MetaUnexpectedResponse, None),
    ],
)
def test_publish_error_classification(
    gateway: InstagramGateway,
    meta: FakeMeta,
    fault: str,
    expected: type[MetaError],
    numbers: tuple[int, int] | None,
) -> None:
    container_id = _image(gateway)
    meta.faults["publish"] = fault

    with pytest.raises(expected) as raised:
        gateway.publish(IG_USER_ID, container_id, FAKE_IG_LONG_TOKEN)

    error = raised.value
    assert type(error) is expected
    if numbers is not None:
        assert isinstance(error, MetaPublishRejected)
        assert (error.code, error.subcode) == numbers
    assert error.__cause__ is None
    for secret in (FAKE_IG_LONG_TOKEN, FAKE_META_ERROR_TEXT, FAKE_SIGNATURE):
        assert secret not in str(error)
        assert secret not in repr(error)


@pytest.mark.parametrize(
    "call",
    [
        lambda g: _image(g),
        lambda g: g.container_status("1", FAKE_IG_LONG_TOKEN),
        lambda g: g.publishing_limit(IG_USER_ID, FAKE_IG_LONG_TOKEN),
    ],
)
def test_bad_json_is_unexpected(
    gateway: InstagramGateway,
    meta: FakeMeta,
    call: Callable[[InstagramGateway], Any],
) -> None:
    meta.faults.update(create="bad_json", status="bad_json", limit="bad_json")

    with pytest.raises(MetaUnexpectedResponse):
        call(gateway)


def test_signed_url_never_appears_in_a_request_url(
    gateway: InstagramGateway, meta: FakeMeta
) -> None:
    container_id = _image(gateway)
    gateway.container_status(container_id, FAKE_IG_LONG_TOKEN)
    gateway.publish(IG_USER_ID, container_id, FAKE_IG_LONG_TOKEN)

    for request in meta.requests:
        assert FAKE_SIGNATURE not in request.url
        assert "image_url" not in parse_qs(request.url.partition("?")[2])
