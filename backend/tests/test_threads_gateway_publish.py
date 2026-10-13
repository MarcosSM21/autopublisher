"""Threads publishing calls of the gateway against the fake Threads API (research.md
§1, §9–§13): request shapes, parsing and safe errors."""

from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest

from app.threads_gateway import (
    PUBLISH_TIMEOUT_SECONDS,
    THREADS_API_VERSION,
    THREADS_GRAPH_HOST,
    ContainerState,
    PublishedMedia,
    PublishingLimit,
    ThreadsError,
    ThreadsGateway,
    ThreadsPermissionDenied,
    ThreadsRejected,
    ThreadsTokenInvalid,
    ThreadsUnavailable,
    ThreadsUnexpectedResponse,
)
from tests.fakes import (
    FAKE_META_ERROR_TEXT,
    FAKE_SIGNATURE,
    FAKE_TH_LONG_TOKEN,
    TH_USER_ID,
    FakeClock,
    FakeThreads,
)

ROOT = f"{THREADS_GRAPH_HOST}/{THREADS_API_VERSION}"
SIGNED_URL = f"https://fake.r2.example/key.jpg?X-Amz-Signature={FAKE_SIGNATURE}"
SECRETS = (FAKE_TH_LONG_TOKEN, FAKE_META_ERROR_TEXT, FAKE_SIGNATURE, "graph.threads")


@pytest.fixture
def threads() -> FakeThreads:
    return FakeThreads()


@pytest.fixture
def gateway(threads: FakeThreads) -> Iterator[ThreadsGateway]:
    with httpx.Client(transport=threads.transport()) as client:
        yield ThreadsGateway(client, FakeClock().now)


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _assert_safe(error: BaseException) -> None:
    text = f"{error!s} {error!r}"
    for secret in SECRETS:
        assert secret not in text
    # Never chained to httpx errors, whose text contains the URL.
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__


def _container(gateway: ThreadsGateway, text: str = "Hello") -> str:
    return gateway.create_container(
        TH_USER_ID, FAKE_TH_LONG_TOKEN, media_type="TEXT", text=text
    )


# --- Request shapes ------------------------------------------------------------------


def test_create_text_container(gateway: ThreadsGateway, threads: FakeThreads) -> None:
    text = "Héllo 🚀 https://example.com\n\n#cyber"

    container_id = _container(gateway, text)

    [request] = threads.requests_for("create")
    assert request.method == "POST"
    assert request.url == f"{ROOT}/{TH_USER_ID}/threads"
    assert urlsplit(request.url).query == ""
    assert request.headers["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )
    assert request.form == {
        "media_type": "TEXT",
        "text": text,
        "access_token": FAKE_TH_LONG_TOKEN,
    }
    assert threads.containers[container_id] == {"media_type": "TEXT", "text": text}


def test_create_media_container_keeps_url_in_body(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    gateway.create_container(
        TH_USER_ID,
        FAKE_TH_LONG_TOKEN,
        media_type="IMAGE",
        text="",
        image_url=SIGNED_URL,
        alt_text="A red square",
    )
    gateway.create_container(
        TH_USER_ID,
        FAKE_TH_LONG_TOKEN,
        media_type="VIDEO",
        text="Clip",
        video_url=SIGNED_URL,
        alt_text="",
    )

    image, video = threads.requests_for("create")
    assert image.form == {
        "media_type": "IMAGE",
        "image_url": SIGNED_URL,
        "alt_text": "A red square",
        "access_token": FAKE_TH_LONG_TOKEN,
    }
    assert video.form == {
        "media_type": "VIDEO",
        "text": "Clip",
        "video_url": SIGNED_URL,
        "access_token": FAKE_TH_LONG_TOKEN,
    }
    for request in (image, video):
        assert FAKE_SIGNATURE not in request.url
        assert "auto_publish_text" not in request.form


def test_publish_sends_creation_id_in_body(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    container_id = _container(gateway)

    post_id = gateway.publish(TH_USER_ID, container_id, FAKE_TH_LONG_TOKEN)

    [request] = threads.requests_for("publish")
    assert request.url == f"{ROOT}/{TH_USER_ID}/threads_publish"
    assert request.form == {
        "creation_id": container_id,
        "access_token": FAKE_TH_LONG_TOKEN,
    }
    assert threads.posts[post_id] == container_id


def test_posts_use_the_publish_timeout(
    gateway: ThreadsGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts: list[Any] = []
    original = gateway.client.request

    def spy(method: str, url: str, **kwargs: Any) -> httpx.Response:
        timeouts.append((method, kwargs.get("timeout")))
        return original(method, url, **kwargs)

    monkeypatch.setattr(gateway.client, "request", spy)
    container_id = _container(gateway)
    gateway.container_status(container_id, FAKE_TH_LONG_TOKEN)
    gateway.publish(TH_USER_ID, container_id, FAKE_TH_LONG_TOKEN)

    assert timeouts[0] == ("POST", PUBLISH_TIMEOUT_SECONDS)
    assert timeouts[1][0] == "GET" and timeouts[1][1] is None
    assert timeouts[2] == ("POST", PUBLISH_TIMEOUT_SECONDS)
    assert PUBLISH_TIMEOUT_SECONDS == 60


def test_reads_use_documented_fields(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    container_id = _container(gateway)
    post_id = gateway.publish(TH_USER_ID, container_id, FAKE_TH_LONG_TOKEN)

    gateway.container_status(container_id, FAKE_TH_LONG_TOKEN)
    gateway.published_media(post_id, FAKE_TH_LONG_TOKEN)
    gateway.publishing_limit(TH_USER_ID, FAKE_TH_LONG_TOKEN)

    [status] = threads.requests_for("status")
    [post] = threads.requests_for("post")
    [limit] = threads.requests_for("limit")
    assert status.url.split("?")[0] == f"{ROOT}/{container_id}"
    assert _query(status.url) == {
        "fields": "id,status,error_message",
        "access_token": FAKE_TH_LONG_TOKEN,
    }
    assert post.url.split("?")[0] == f"{ROOT}/{post_id}"
    assert _query(post.url)["fields"] == "id,permalink,timestamp"
    assert limit.url.split("?")[0] == f"{ROOT}/{TH_USER_ID}/threads_publishing_limit"
    assert _query(limit.url)["fields"] == "quota_usage,config"
    assert threads.post_list_requests == 0


# --- Parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("FINISHED", ContainerState("FINISHED", None)),
        ("IN_PROGRESS", ContainerState("IN_PROGRESS", None)),
        (
            "ERROR:FAILED_DOWNLOADING_VIDEO",
            ContainerState("ERROR", "FAILED_DOWNLOADING_VIDEO"),
        ),
        ("ERROR:INVALID_ASPEC_RATIO", ContainerState("ERROR", "INVALID_ASPEC_RATIO")),
        # Undocumented values are dropped, never kept as free text.
        (f"ERROR:{FAKE_META_ERROR_TEXT}", ContainerState("ERROR", None)),
        ("EXPIRED", ContainerState("EXPIRED", None)),
    ],
)
def test_container_status_parsing(
    gateway: ThreadsGateway,
    threads: FakeThreads,
    script: str,
    expected: ContainerState,
) -> None:
    threads.status_script = [script]
    container_id = _container(gateway)

    assert gateway.container_status(container_id, FAKE_TH_LONG_TOKEN) == expected


def test_container_status_without_status(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    container_id = _container(gateway)
    threads.fault_queue["status"] = ["missing_fields"]

    state = gateway.container_status(container_id, FAKE_TH_LONG_TOKEN)

    assert state == ContainerState(None, None)


def test_published_media(gateway: ThreadsGateway, threads: FakeThreads) -> None:
    container_id = _container(gateway)
    post_id = gateway.publish(TH_USER_ID, container_id, FAKE_TH_LONG_TOKEN)

    media = gateway.published_media(post_id, FAKE_TH_LONG_TOKEN)

    assert media == PublishedMedia(
        permalink=f"https://www.threads.com/@cyber.studio/post/{post_id}",
        timestamp="2026-10-13T10:00:00+0000",
    )


def test_published_media_without_permalink(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    threads.permalinks = False
    container_id = _container(gateway)
    post_id = gateway.publish(TH_USER_ID, container_id, FAKE_TH_LONG_TOKEN)

    media = gateway.published_media(post_id, FAKE_TH_LONG_TOKEN)

    assert media.permalink is None
    assert media.timestamp == "2026-10-13T10:00:00+0000"


def test_published_media_only_accepts_https_permalinks(
    gateway: ThreadsGateway, threads: FakeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        threads, "_post", lambda post_id: {"id": post_id, "permalink": "http://x.y/z"}
    )

    media = gateway.published_media("123", FAKE_TH_LONG_TOKEN)

    assert media == PublishedMedia(permalink=None, timestamp=None)


@pytest.mark.parametrize("wrap", [True, False])
def test_publishing_limit(
    gateway: ThreadsGateway, threads: FakeThreads, wrap: bool
) -> None:
    threads.quota = (4, 250)
    threads.quota_wrap_data = wrap

    limit = gateway.publishing_limit(TH_USER_ID, FAKE_TH_LONG_TOKEN)

    assert limit == PublishingLimit(usage=4, total=250, duration=86400)


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {"data": "x"},
        {"data": [{"quota_usage": -1, "config": {"quota_total": 250}}]},
        {"data": [{"quota_usage": "4", "config": {"quota_total": 250}}]},
        {"data": [{"quota_usage": 4, "config": {"quota_total": 0}}]},
        {"data": [{"quota_usage": True, "config": {"quota_total": 250}}]},
        {"data": [{"quota_usage": 4}]},
        {"quota_usage": 4, "config": "250"},
        {"unexpected": FAKE_META_ERROR_TEXT},
    ],
)
def test_publishing_limit_unexpected_shape(
    gateway: ThreadsGateway,
    threads: FakeThreads,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    monkeypatch.setattr(threads, "_limit", lambda: payload)

    with pytest.raises(ThreadsUnexpectedResponse) as raised:
        gateway.publishing_limit(TH_USER_ID, FAKE_TH_LONG_TOKEN)

    _assert_safe(raised.value)


def test_publishing_limit_without_duration(
    gateway: ThreadsGateway, threads: FakeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        threads,
        "_limit",
        lambda: {"data": [{"quota_usage": 1, "config": {"quota_total": 250}}]},
    )

    limit = gateway.publishing_limit(TH_USER_ID, FAKE_TH_LONG_TOKEN)

    assert limit == PublishingLimit(usage=1, total=250, duration=None)


@pytest.mark.parametrize("fault", ["missing_fields", "bad_json"])
def test_unexpected_ids_are_rejected(
    gateway: ThreadsGateway, threads: FakeThreads, fault: str
) -> None:
    threads.fault_queue["create"] = [fault]
    with pytest.raises(ThreadsUnexpectedResponse) as created:
        _container(gateway)
    container_id = _container(gateway)
    threads.fault_queue["publish"] = [fault]
    with pytest.raises(ThreadsUnexpectedResponse) as published:
        gateway.publish(TH_USER_ID, container_id, FAKE_TH_LONG_TOKEN)

    _assert_safe(created.value)
    _assert_safe(published.value)


# --- Errors --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("transport", ThreadsUnavailable),
        ("timeout", ThreadsUnavailable),
        ("server_error", ThreadsUnavailable),
        ("rate_limited", ThreadsUnavailable),
        ("graph_2", ThreadsUnavailable),
        ("graph_190", ThreadsTokenInvalid),
        ("graph_10", ThreadsPermissionDenied),
        ("graph_100", ThreadsRejected),
    ],
)
@pytest.mark.parametrize("endpoint", ["create", "status", "publish", "post", "limit"])
def test_errors_are_classified_safely(
    gateway: ThreadsGateway,
    threads: FakeThreads,
    endpoint: str,
    fault: str,
    expected: type[ThreadsError],
) -> None:
    container_id = _container(gateway)
    threads.fault_queue[endpoint] = [fault]
    calls: dict[str, Callable[[], object]] = {
        "create": lambda: _container(gateway),
        "status": lambda: gateway.container_status(container_id, FAKE_TH_LONG_TOKEN),
        "publish": lambda: gateway.publish(
            TH_USER_ID, container_id, FAKE_TH_LONG_TOKEN
        ),
        "post": lambda: gateway.published_media("123", FAKE_TH_LONG_TOKEN),
        "limit": lambda: gateway.publishing_limit(TH_USER_ID, FAKE_TH_LONG_TOKEN),
    }

    with pytest.raises(expected) as raised:
        calls[endpoint]()

    _assert_safe(raised.value)


def test_link_limit_rejection_is_flagged(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    threads.fault_queue["create"] = ["link_limit"]

    with pytest.raises(ThreadsRejected) as raised:
        _container(gateway)

    assert raised.value.link_limit_exceeded is True
    _assert_safe(raised.value)


def test_other_rejections_are_not_link_limit(
    gateway: ThreadsGateway, threads: FakeThreads
) -> None:
    threads.fault_queue["create"] = ["graph_100"]

    with pytest.raises(ThreadsRejected) as raised:
        _container(gateway)

    assert raised.value.link_limit_exceeded is False
