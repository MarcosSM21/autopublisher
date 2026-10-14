"""Content Posting part of the TikTok gateway against FakeTikTok (research §2, §3,
§10, §16): strict DTOs, request shapes, error classification and the upload URL
that never appears in any exception, repr or log."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx
import pytest

from app.tiktok_gateway import (
    CreatorInfo,
    TikTokError,
    TikTokGateway,
    TikTokPostRejected,
    TikTokScopeMissing,
    TikTokTokenInvalid,
    TikTokUnavailable,
    TikTokUnexpectedResponse,
    TikTokUploadRangeMismatch,
    TikTokUploadRejected,
    UploadProgress,
    UploadUrl,
)
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_ERROR_TEXT,
    FAKE_TT_LOG_ID,
    FAKE_TT_PUBLISH_ID_PREFIX,
    FAKE_TT_UPLOAD_ID,
    FAKE_TT_UPLOAD_TOKEN,
    TT_UPLOAD_BASE,
    FakeClock,
    FakeTikTok,
    UploadAction,
    tiktok_creator_info,
)

SECRETS = (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_UPLOAD_TOKEN,
    FAKE_TT_UPLOAD_ID,
    FAKE_TT_ERROR_TEXT,
    "tiktokapis",
)
POST_INFO: dict[str, Any] = {
    "title": "Caption 😀",
    "privacy_level": "SELF_ONLY",
    "disable_comment": True,
    "disable_duet": True,
    "disable_stitch": True,
    "brand_content_toggle": False,
    "brand_organic_toggle": False,
    "is_aigc": False,
}
SOURCE_INFO: dict[str, Any] = {
    "source": "FILE_UPLOAD",
    "video_size": 10,
    "chunk_size": 10,
    "total_chunk_count": 1,
}


@pytest.fixture
def fake() -> FakeTikTok:
    return FakeTikTok()


@pytest.fixture
def gateway(fake: FakeTikTok) -> Iterator[TikTokGateway]:
    clock = FakeClock(datetime(2026, 10, 14, 10, tzinfo=UTC))
    with httpx.Client(transport=fake.transport()) as client:
        yield TikTokGateway(client, clock.now)


def _assert_clean(error: BaseException) -> None:
    text = f"{error} {error!r} {error.args!r}"
    for secret in SECRETS:
        assert secret not in text
    # Never chained to an httpx error (whose message contains the URL).
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__


def _raises(call: Any, kind: type[TikTokError]) -> TikTokError:
    with pytest.raises(kind) as caught:
        call()
    _assert_clean(caught.value)
    return caught.value


# --- Creator Info -------------------------------------------------------------------


def test_creator_info_is_parsed(gateway: TikTokGateway, fake: FakeTikTok) -> None:
    info = gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN)

    assert info == CreatorInfo(
        nickname="Cyber Studio",
        username="cyber.studio",
        avatar_url="https://p16-sign.tiktokcdn.example/creator.jpeg",
        privacy_level_options=(
            "FOLLOWER_OF_CREATOR",
            "MUTUAL_FOLLOW_FRIENDS",
            "SELF_ONLY",
        ),
        comment_disabled=False,
        duet_disabled=True,
        stitch_disabled=True,
        max_video_post_duration_sec=600,
    )
    [request] = fake.requests_to("creator_info")
    assert request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {FAKE_TT_ACCESS_TOKEN}"
    assert request.headers["content-type"].startswith("application/json")


def test_creator_info_optional_fields(gateway: TikTokGateway, fake: FakeTikTok) -> None:
    data = tiktok_creator_info()
    del data["creator_avatar_url"]
    del data["creator_username"]
    fake.creator_info_data = data

    info = gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN)

    assert info.avatar_url is None
    assert info.username is None


def test_unknown_privacy_options_are_kept(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.creator_info_data = tiktok_creator_info(
        privacy_level_options=["SELF_ONLY", "SOMETHING_NEW"]
    )

    info = gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN)

    assert info.privacy_level_options == ("SELF_ONLY", "SOMETHING_NEW")


@pytest.mark.parametrize(
    "overrides",
    [
        {"creator_nickname": None},
        {"creator_nickname": ""},
        {"creator_nickname": 3},
        {"comment_disabled": "false"},
        {"duet_disabled": None},
        {"stitch_disabled": 0},
        {"max_video_post_duration_sec": True},
        {"max_video_post_duration_sec": 0},
        {"max_video_post_duration_sec": -1},
        {"max_video_post_duration_sec": "600"},
        {"privacy_level_options": []},
        {"privacy_level_options": "SELF_ONLY"},
        {"privacy_level_options": ["SELF_ONLY", 3]},
    ],
)
def test_malformed_creator_info_is_unexpected(
    gateway: TikTokGateway, fake: FakeTikTok, overrides: dict[str, Any]
) -> None:
    fake.creator_info_data = tiktok_creator_info(**overrides)

    _raises(
        lambda: gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN),
        TikTokUnexpectedResponse,
    )


@pytest.mark.parametrize("field", ["creator_nickname", "comment_disabled"])
def test_missing_creator_info_fields_are_unexpected(
    gateway: TikTokGateway, fake: FakeTikTok, field: str
) -> None:
    data = tiktok_creator_info()
    del data[field]
    fake.creator_info_data = data

    _raises(
        lambda: gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN),
        TikTokUnexpectedResponse,
    )


@pytest.mark.parametrize(
    "code",
    [
        "spam_risk_too_many_posts",
        "spam_risk_user_banned_from_posting",
        "reached_active_user_cap",
    ],
)
def test_creator_cannot_post_with_http_200(
    gateway: TikTokGateway, fake: FakeTikTok, code: str
) -> None:
    fake.faults["creator_info"] = f"api200_{code}"

    error = _raises(
        lambda: gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN), TikTokPostRejected
    )

    assert isinstance(error, TikTokPostRejected)
    assert error.code == code
    assert error.log_id == FAKE_TT_LOG_ID


@pytest.mark.parametrize(
    ("fault", "kind"),
    [
        ("api_access_token_invalid", TikTokTokenInvalid),
        ("api_scope_not_authorized", TikTokScopeMissing),
        ("server_error", TikTokUnavailable),
        ("transport", TikTokUnavailable),
        ("timeout", TikTokUnavailable),
        ("bad_json", TikTokUnexpectedResponse),
        ("empty_body", TikTokUnexpectedResponse),
        ("missing_fields", TikTokUnexpectedResponse),
    ],
)
def test_creator_info_errors(
    gateway: TikTokGateway, fake: FakeTikTok, fault: str, kind: type[TikTokError]
) -> None:
    fake.faults["creator_info"] = fault

    _raises(lambda: gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN), kind)


def test_creator_info_scope_error_names_video_publish(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.faults["creator_info"] = "api_scope_not_authorized"

    error = _raises(
        lambda: gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN), TikTokScopeMissing
    )

    assert isinstance(error, TikTokScopeMissing)
    assert error.scope == "video.publish"


def test_rate_limit_is_flagged(gateway: TikTokGateway, fake: FakeTikTok) -> None:
    fake.faults["creator_info"] = "rate_limited"

    error = _raises(
        lambda: gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN), TikTokUnavailable
    )

    assert isinstance(error, TikTokUnavailable)
    assert error.rate_limited is True


def test_rate_limit_error_code_is_flagged(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.faults["init"] = "api_rate_limit_exceeded"

    error = _raises(
        lambda: gateway.init_video_post(FAKE_TT_ACCESS_TOKEN, POST_INFO, SOURCE_INFO),
        TikTokUnavailable,
    )

    assert isinstance(error, TikTokUnavailable)
    assert error.rate_limited is True


def test_server_error_is_not_flagged_as_rate_limit(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    fake.faults["creator_info"] = "server_error"

    error = _raises(
        lambda: gateway.query_creator_info(FAKE_TT_ACCESS_TOKEN), TikTokUnavailable
    )

    assert isinstance(error, TikTokUnavailable)
    assert error.rate_limited is False


# --- Init -----------------------------------------------------------------------------


def test_init_body_and_result(gateway: TikTokGateway, fake: FakeTikTok) -> None:
    result = gateway.init_video_post(FAKE_TT_ACCESS_TOKEN, POST_INFO, SOURCE_INFO)

    assert result.publish_id == f"{FAKE_TT_PUBLISH_ID_PREFIX}1"
    assert isinstance(result.upload_url, UploadUrl)
    assert result.upload_url.reveal().startswith(TT_UPLOAD_BASE)
    [request] = fake.requests_to("init")
    assert request.method == "POST"
    assert request.headers["content-type"] == "application/json; charset=UTF-8"
    assert request.headers["authorization"] == f"Bearer {FAKE_TT_ACCESS_TOKEN}"
    assert json.loads(request.content) == {
        "post_info": POST_INFO,
        "source_info": SOURCE_INFO,
    }
    # The caption travels exactly as given (UTF-8 JSON, no escaping surprises).
    assert "Caption 😀".encode() in request.content
    for text in (repr(result), str(result)):
        assert FAKE_TT_UPLOAD_TOKEN not in text
        assert FAKE_TT_UPLOAD_ID not in text


def test_upload_url_never_shows_its_value() -> None:
    url = UploadUrl(f"{TT_UPLOAD_BASE}?upload_token={FAKE_TT_UPLOAD_TOKEN}")

    for text in (repr(url), str(url), f"{url}", f"{url!r}", repr([url])):
        assert FAKE_TT_UPLOAD_TOKEN not in text
        assert "tiktokapis" not in text
    assert "redacted" in repr(url)
    assert not hasattr(url, "__dict__")


@pytest.mark.parametrize(
    "data",
    [
        {"publish_id": "", "upload_url": TT_UPLOAD_BASE},
        {"publish_id": 3, "upload_url": TT_UPLOAD_BASE},
        {"publish_id": "x" * 65, "upload_url": TT_UPLOAD_BASE},
        {"publish_id": "v_pub_1"},
        {"publish_id": "v_pub_1", "upload_url": ""},
        {"publish_id": "v_pub_1", "upload_url": "http://insecure.example/upload"},
        {"publish_id": "v_pub_1", "upload_url": "https://x.example/" + "a" * 3000},
    ],
)
def test_malformed_init_answer_is_unexpected(
    gateway: TikTokGateway, fake: FakeTikTok, data: dict[str, Any]
) -> None:
    fake.init_data = data

    _raises(
        lambda: gateway.init_video_post(FAKE_TT_ACCESS_TOKEN, POST_INFO, SOURCE_INFO),
        TikTokUnexpectedResponse,
    )


@pytest.mark.parametrize(
    "code",
    [
        "invalid_param",
        "privacy_level_option_mismatch",
        "spam_risk_too_many_posts",
        "spam_risk_user_banned_from_posting",
        "reached_active_user_cap",
        "unaudited_client_can_only_post_to_private_accounts",
        "url_ownership_unverified",
    ],
)
def test_documented_init_rejections(
    gateway: TikTokGateway, fake: FakeTikTok, code: str
) -> None:
    fake.faults["init"] = f"api_{code}"

    error = _raises(
        lambda: gateway.init_video_post(FAKE_TT_ACCESS_TOKEN, POST_INFO, SOURCE_INFO),
        TikTokPostRejected,
    )

    assert isinstance(error, TikTokPostRejected)
    assert error.code == code


@pytest.mark.parametrize(
    ("fault", "kind"),
    [
        ("api_some_new_code", TikTokUnexpectedResponse),
        ("api_access_token_invalid", TikTokTokenInvalid),
        ("api_scope_not_authorized", TikTokScopeMissing),
        ("rate_limited", TikTokUnavailable),
        ("server_error", TikTokUnavailable),
        ("transport", TikTokUnavailable),
        ("timeout", TikTokUnavailable),
    ],
)
def test_other_init_errors(
    gateway: TikTokGateway, fake: FakeTikTok, fault: str, kind: type[TikTokError]
) -> None:
    fake.faults["init"] = fault

    error = _raises(
        lambda: gateway.init_video_post(FAKE_TT_ACCESS_TOKEN, POST_INFO, SOURCE_INFO),
        kind,
    )

    # An undocumented code is never propagated as a business rejection.
    assert not isinstance(error, TikTokPostRejected)


# --- Upload ---------------------------------------------------------------------------


def _upload_url(gateway: TikTokGateway) -> UploadUrl:
    return gateway.init_video_post(
        FAKE_TT_ACCESS_TOKEN, POST_INFO, {**SOURCE_INFO, "video_size": 10}
    ).upload_url


def test_upload_chunk_headers_and_final_201(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    url = _upload_url(gateway)

    result = gateway.upload_chunk(url, b"0123456789", 0, 9, 10, "video/mp4")

    assert result.status == 201
    # The answer counts accepted bytes (end-exclusive): `bytes 0-10/10`.
    assert result.progress == UploadProgress(accepted_bytes=10, total=10)
    [request] = fake.requests_to("upload")
    assert request.method == "PUT"
    assert request.headers["content-type"] == "video/mp4"
    assert request.headers["content-length"] == "10"
    assert request.headers["content-range"] == "bytes 0-9/10"
    assert "authorization" not in {name.lower() for name in request.headers}
    assert request.content == b"0123456789"
    assert FAKE_TT_UPLOAD_TOKEN in request.url


def test_upload_chunk_206_with_and_without_content_range(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    url = _upload_url(gateway)
    fake.upload_actions = [UploadAction(), UploadAction(status=206, content_range=None)]

    first = gateway.upload_chunk(url, b"01234", 0, 4, 10, "video/mp4")
    second = gateway.upload_chunk(url, b"56", 5, 6, 10, "video/mp4")

    assert (first.status, first.progress) == (206, UploadProgress(5, 10))
    assert (second.status, second.progress) == (206, None)


def test_upload_chunk_progress_first_intermediate_and_final(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    # Request ranges are inclusive; TikTok's answers count accepted bytes.
    url = _upload_url(gateway)

    results = [
        gateway.upload_chunk(url, b"0123", 0, 3, 10, "video/mp4"),
        gateway.upload_chunk(url, b"4567", 4, 7, 10, "video/mp4"),
        gateway.upload_chunk(url, b"89", 8, 9, 10, "video/mp4"),
    ]

    assert [r.headers["content-range"] for r in fake.requests_to("upload")] == [
        "bytes 0-3/10",
        "bytes 4-7/10",
        "bytes 8-9/10",
    ]
    assert [(r.status, r.progress) for r in results] == [
        (206, UploadProgress(4, 10)),
        (206, UploadProgress(8, 10)),
        (201, UploadProgress(10, 10)),
    ]


def test_upload_chunk_real_v2_content_range_shape(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    """V2 real: the first 32 MiB chunk of a 67 686 392 B video was sent as
    `bytes 0-33554431/…` and answered `bytes 0-33554432/…`; the last one as
    `bytes 33554432-67686391/…` and answered `bytes 0-67686392/…`."""
    total = 67_686_392
    url = _upload_url(gateway)
    fake.upload_actions = [
        UploadAction(status=206, content_range=f"bytes 0-33554432/{total}"),
        UploadAction(status=201, content_range=f"bytes 0-{total}/{total}"),
    ]

    first = gateway.upload_chunk(url, b"a", 0, 33_554_431, total, "video/mp4")
    last = gateway.upload_chunk(url, b"b", 33_554_432, total - 1, total, "video/mp4")

    assert [r.headers["content-range"] for r in fake.requests_to("upload")] == [
        f"bytes 0-33554431/{total}",
        f"bytes 33554432-67686391/{total}",
    ]
    assert first.progress == UploadProgress(accepted_bytes=33_554_432, total=total)
    assert last.progress == UploadProgress(accepted_bytes=total, total=total)


@pytest.mark.parametrize("status", [400, 403, 404])
def test_upload_rejections(
    gateway: TikTokGateway, fake: FakeTikTok, status: int
) -> None:
    url = _upload_url(gateway)
    fake.upload_actions = [UploadAction(status=status)]

    error = _raises(
        lambda: gateway.upload_chunk(url, b"01234", 0, 4, 10, "video/mp4"),
        TikTokUploadRejected,
    )

    assert isinstance(error, TikTokUploadRejected)
    assert error.status == status


@pytest.mark.parametrize(
    ("content_range", "progress"),
    [
        ("bytes 0-5/10", UploadProgress(5, 10)),
        ("bytes 0-5/*", UploadProgress(5, None)),
        ("bytes 2-5/10", None),
        (None, None),
        ("garbage", None),
        ("bytes 0-x/10", None),
    ],
)
def test_upload_range_mismatch(
    gateway: TikTokGateway,
    fake: FakeTikTok,
    content_range: str | None,
    progress: UploadProgress | None,
) -> None:
    url = _upload_url(gateway)
    fake.upload_actions = [UploadAction(status=416, content_range=content_range)]

    error = _raises(
        lambda: gateway.upload_chunk(url, b"01234", 0, 4, 10, "video/mp4"),
        TikTokUploadRangeMismatch,
    )

    assert isinstance(error, TikTokUploadRangeMismatch)
    assert error.progress == progress


@pytest.mark.parametrize(
    ("action", "rate_limited"),
    [
        (UploadAction(status=500), False),
        (UploadAction(status=503), False),
        (UploadAction(status=429), True),
        (UploadAction(raise_="transport"), False),
        (UploadAction(raise_="timeout"), False),
        (UploadAction(raise_="lost"), False),
    ],
)
def test_upload_temporary_failures(
    gateway: TikTokGateway, fake: FakeTikTok, action: UploadAction, rate_limited: bool
) -> None:
    url = _upload_url(gateway)
    fake.upload_actions = [action]

    error = _raises(
        lambda: gateway.upload_chunk(url, b"01234", 0, 4, 10, "video/mp4"),
        TikTokUnavailable,
    )

    assert isinstance(error, TikTokUnavailable)
    assert error.rate_limited is rate_limited


def test_upload_unexpected_status(gateway: TikTokGateway, fake: FakeTikTok) -> None:
    url = _upload_url(gateway)
    fake.upload_actions = [UploadAction(status=302)]

    _raises(
        lambda: gateway.upload_chunk(url, b"01234", 0, 4, 10, "video/mp4"),
        TikTokUnexpectedResponse,
    )


# --- Status ---------------------------------------------------------------------------


def _publish_id(gateway: TikTokGateway) -> str:
    return gateway.init_video_post(
        FAKE_TT_ACCESS_TOKEN, POST_INFO, SOURCE_INFO
    ).publish_id


def test_status_request_and_parsing(gateway: TikTokGateway, fake: FakeTikTok) -> None:
    publish_id = _publish_id(gateway)
    fake.statuses = [
        {
            "status": "PUBLISH_COMPLETE",
            "publicaly_available_post_id": [7300000000000000001],
            "uploaded_bytes": 10,
        }
    ]

    status = gateway.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, publish_id)

    assert status.status == "PUBLISH_COMPLETE"
    assert status.fail_reason is None
    assert status.post_ids == (7300000000000000001,)
    assert status.uploaded_bytes == 10
    [request] = fake.requests_to("status")
    assert request.method == "POST"
    assert json.loads(request.content) == {"publish_id": publish_id}
    assert request.headers["authorization"] == f"Bearer {FAKE_TT_ACCESS_TOKEN}"


def test_status_ignores_non_integer_post_ids(
    gateway: TikTokGateway, fake: FakeTikTok
) -> None:
    publish_id = _publish_id(gateway)
    fake.statuses = [
        {
            "status": "PUBLISH_COMPLETE",
            "publicaly_available_post_id": ["73", 7, True, 1.5, None],
        }
    ]

    status = gateway.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, publish_id)

    assert status.post_ids == (7,)


@pytest.mark.parametrize(
    ("reason", "stored"),
    [
        ("frame_rate_check_failed", "frame_rate_check_failed"),
        ("internal", "internal"),
        ("Bad Reason!", "unknown"),
        ("a" * 65, "unknown"),
        (3, "unknown"),
        ("", "unknown"),
    ],
)
def test_status_fail_reason_is_sanitised(
    gateway: TikTokGateway, fake: FakeTikTok, reason: object, stored: str
) -> None:
    publish_id = _publish_id(gateway)
    fake.statuses = [{"status": "FAILED", "fail_reason": reason}]

    status = gateway.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, publish_id)

    assert status.status == "FAILED"
    assert status.fail_reason == stored


@pytest.mark.parametrize("value", [-1, "10", True, None])
def test_status_invalid_uploaded_bytes_is_none(
    gateway: TikTokGateway, fake: FakeTikTok, value: object
) -> None:
    publish_id = _publish_id(gateway)
    fake.statuses = [{"status": "PROCESSING_UPLOAD", "uploaded_bytes": value}]

    status = gateway.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, publish_id)

    assert status.uploaded_bytes is None


@pytest.mark.parametrize("data", [{}, {"status": ""}, {"status": 3}])
def test_status_without_status_is_unexpected(
    gateway: TikTokGateway, fake: FakeTikTok, data: dict[str, Any]
) -> None:
    publish_id = _publish_id(gateway)
    fake.statuses = [data]
    # The fake always adds uploaded_bytes; the status itself is what matters.

    _raises(
        lambda: gateway.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, publish_id),
        TikTokUnexpectedResponse,
    )


@pytest.mark.parametrize(
    "code", ["invalid_publish_id", "token_not_authorized_for_specified_publish_id"]
)
def test_status_publish_id_errors(
    gateway: TikTokGateway, fake: FakeTikTok, code: str
) -> None:
    publish_id = _publish_id(gateway)
    fake.faults["status"] = f"api_{code}"

    error = _raises(
        lambda: gateway.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, publish_id),
        TikTokPostRejected,
    )

    assert isinstance(error, TikTokPostRejected)
    assert error.code == code


@pytest.mark.parametrize(
    ("fault", "kind"),
    [
        ("api_access_token_invalid", TikTokTokenInvalid),
        ("api_scope_not_authorized", TikTokScopeMissing),
        ("rate_limited", TikTokUnavailable),
        ("api_internal_error", TikTokUnavailable),
        ("transport", TikTokUnavailable),
        ("bad_json", TikTokUnexpectedResponse),
    ],
)
def test_status_errors(
    gateway: TikTokGateway, fake: FakeTikTok, fault: str, kind: type[TikTokError]
) -> None:
    publish_id = _publish_id(gateway)
    fake.faults["status"] = fault

    _raises(
        lambda: gateway.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, publish_id), kind
    )
