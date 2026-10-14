"""Error taxonomy of research §19, as one table: TikTok signal and phase →
AutoPublisher code, safe message, determined flag, retry policy and connection effect.
Before the write-ahead every failure is determined; after it, only TikTok's own
`FAILED` is."""

import pytest

from app.tiktok_gateway import (
    TikTokError,
    TikTokPostRejected,
    TikTokScopeMissing,
    TikTokTokenInvalid,
    TikTokUnavailable,
    TikTokUnexpectedResponse,
    TikTokUploadRangeMismatch,
    TikTokUploadRejected,
    UploadProgress,
)
from app.tiktok_publishing import (
    CallPhase,
    RetryPolicy,
    TikTokErrorMapping,
    map_fail_reason,
    map_gateway_error,
)
from tests.fakes import FAKE_TT_ERROR_TEXT, FAKE_TT_LOG_ID

R = True  # The connection must be reconnected (Feature 012).
N = False

# (phase, error, after write-ahead) -> (code, determined, retry, reconnect)
GATEWAY_ROWS: list[
    tuple[CallPhase, TikTokError, bool, tuple[str, bool, RetryPolicy, bool]]
] = [
    (
        CallPhase.CREATOR_INFO,
        TikTokTokenInvalid(),
        False,
        ("tiktok_reconnect_required", True, RetryPolicy.RENEW_ONCE, R),
    ),
    (
        CallPhase.STATUS,
        TikTokTokenInvalid(),
        True,
        ("tiktok_result_uncertain", False, RetryPolicy.RENEW_ONCE, R),
    ),
    (
        CallPhase.INIT,
        TikTokTokenInvalid(),
        False,
        ("tiktok_unavailable", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.CREATOR_INFO,
        TikTokScopeMissing("video.publish"),
        False,
        ("tiktok_reconnect_required", True, RetryPolicy.NONE, R),
    ),
    (
        CallPhase.INIT,
        TikTokScopeMissing("video.publish"),
        False,
        ("tiktok_reconnect_required", True, RetryPolicy.NONE, R),
    ),
    (
        CallPhase.STATUS,
        TikTokScopeMissing("video.publish"),
        True,
        ("tiktok_result_uncertain", False, RetryPolicy.NONE, R),
    ),
    (
        CallPhase.INIT,
        TikTokPostRejected("invalid_param"),
        False,
        ("tiktok_init_failed", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.INIT,
        TikTokPostRejected("privacy_level_option_mismatch"),
        False,
        ("tiktok_privacy_invalid", True, RetryPolicy.NONE, N),
    ),
    *[
        (
            phase,
            TikTokPostRejected(code),
            False,
            ("tiktok_creator_cannot_post", True, RetryPolicy.NONE, N),
        )
        for phase in (CallPhase.CREATOR_INFO, CallPhase.INIT)
        for code in (
            "spam_risk_too_many_posts",
            "spam_risk_user_banned_from_posting",
            "reached_active_user_cap",
        )
    ],
    (
        CallPhase.INIT,
        TikTokPostRejected("unaudited_client_can_only_post_to_private_accounts"),
        False,
        ("tiktok_private_account_required", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.INIT,
        TikTokPostRejected("url_ownership_unverified"),
        False,
        ("tiktok_unexpected_response", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.CREATOR_INFO,
        TikTokUnavailable(rate_limited=True),
        False,
        ("tiktok_rate_limited", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.INIT,
        TikTokUnavailable(rate_limited=True),
        False,
        ("tiktok_rate_limited", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.STATUS,
        TikTokUnavailable(rate_limited=True),
        True,
        ("tiktok_result_uncertain", False, RetryPolicy.DOUBLE_WAIT, N),
    ),
    (
        CallPhase.CREATOR_INFO,
        TikTokUnavailable(),
        False,
        ("tiktok_unavailable", True, RetryPolicy.ONCE, N),
    ),
    (
        CallPhase.INIT,
        TikTokUnavailable(),
        False,
        ("tiktok_unavailable", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.STATUS,
        TikTokUnavailable(),
        True,
        ("tiktok_result_uncertain", False, RetryPolicy.KEEP_POLLING, N),
    ),
    *[
        (
            CallPhase.STATUS,
            TikTokPostRejected(code),
            True,
            ("tiktok_result_uncertain", False, RetryPolicy.NONE, N),
        )
        for code in (
            "invalid_publish_id",
            "token_not_authorized_for_specified_publish_id",
        )
    ],
    (
        CallPhase.CHUNK,
        TikTokUploadRejected(400),
        False,
        ("tiktok_upload_failed", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.CHUNK,
        TikTokUploadRejected(404),
        False,
        ("tiktok_upload_failed", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.CHUNK,
        TikTokUploadRejected(403),
        False,
        ("tiktok_upload_expired", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.CHUNK,
        TikTokUploadRangeMismatch(None),
        False,
        ("tiktok_upload_failed", True, RetryPolicy.RANGE_POLICY, N),
    ),
    (
        CallPhase.CHUNK,
        TikTokUnavailable(),
        False,
        ("tiktok_upload_failed", True, RetryPolicy.CHUNK_RETRIES, N),
    ),
    (
        CallPhase.CHUNK,
        TikTokUnavailable(rate_limited=True),
        False,
        ("tiktok_upload_failed", True, RetryPolicy.CHUNK_RETRIES, N),
    ),
    *[
        (
            CallPhase.FINAL_CHUNK,
            error,
            True,
            ("tiktok_result_uncertain", False, RetryPolicy.STATUS_ONLY, N),
        )
        for error in (
            TikTokUnavailable(),
            TikTokUnavailable(rate_limited=True),
            TikTokUploadRejected(400),
            TikTokUploadRejected(403),
            TikTokUploadRejected(404),
            TikTokUploadRangeMismatch(UploadProgress(4, 10)),
            TikTokUnexpectedResponse(),
        )
    ],
    (
        CallPhase.CREATOR_INFO,
        TikTokUnexpectedResponse(),
        False,
        ("tiktok_unexpected_response", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.INIT,
        TikTokUnexpectedResponse(),
        False,
        ("tiktok_unexpected_response", True, RetryPolicy.NONE, N),
    ),
    (
        CallPhase.STATUS,
        TikTokUnexpectedResponse(),
        True,
        ("tiktok_result_uncertain", False, RetryPolicy.KEEP_POLLING, N),
    ),
]

# fail_reason of a FAILED status -> (code, reconnect); always determined.
FAIL_REASON_ROWS: list[tuple[str | None, str, bool]] = [
    ("auth_removed", "tiktok_publish_failed", R),
    ("spam_risk_too_many_posts", "tiktok_creator_cannot_post", N),
    ("spam_risk_user_banned_from_posting", "tiktok_creator_cannot_post", N),
    ("reached_active_user_cap", "tiktok_creator_cannot_post", N),
    ("spam_risk_text", "tiktok_content_rejected", N),
    ("spam_risk", "tiktok_content_rejected", N),
    ("file_format_check_failed", "tiktok_video_rejected", N),
    ("duration_check_failed", "tiktok_video_rejected", N),
    ("frame_rate_check_failed", "tiktok_video_rejected", N),
    ("picture_size_check_failed", "tiktok_video_rejected", N),
    ("internal", "tiktok_publish_failed", N),
    ("publish_cancelled", "tiktok_publish_failed", N),
    ("video_pull_failed", "tiktok_publish_failed", N),
    ("photo_pull_failed", "tiktok_publish_failed", N),
    ("unknown", "tiktok_publish_failed", N),
    (None, "tiktok_publish_failed", N),
]


def _assert_safe(mapping: TikTokErrorMapping) -> None:
    assert mapping.message
    assert mapping.message.isascii()
    assert FAKE_TT_ERROR_TEXT not in mapping.message
    assert FAKE_TT_LOG_ID not in mapping.message
    assert len(mapping.message) <= 500


@pytest.mark.parametrize(("phase", "error", "after", "expected"), GATEWAY_ROWS)
def test_gateway_errors(
    phase: CallPhase,
    error: TikTokError,
    after: bool,
    expected: tuple[str, bool, RetryPolicy, bool],
) -> None:
    mapping = map_gateway_error(error, phase, after_write_ahead=after)

    code, determined, retry, reconnect = expected
    assert (mapping.code, mapping.determined, mapping.retry, mapping.reconnect) == (
        code,
        determined,
        retry,
        reconnect,
    )
    _assert_safe(mapping)


@pytest.mark.parametrize(("reason", "code", "reconnect"), FAIL_REASON_ROWS)
def test_fail_reasons_are_determined(
    reason: str | None, code: str, reconnect: bool
) -> None:
    mapping = map_fail_reason(reason)

    assert (mapping.code, mapping.determined, mapping.reconnect) == (
        code,
        True,
        reconnect,
    )
    assert mapping.retry == RetryPolicy.NONE
    _assert_safe(mapping)


def test_specific_messages() -> None:
    assert (
        "try again" in map_gateway_error(TikTokTokenInvalid(), CallPhase.INIT).message
    )
    assert "removed" in map_fail_reason("auth_removed").message
    assert "daily" in map_fail_reason("spam_risk_too_many_posts").message
    assert "cap" in map_fail_reason("reached_active_user_cap").message
    rate = map_gateway_error(TikTokUnavailable(rate_limited=True), CallPhase.INIT)
    unavailable = map_gateway_error(TikTokUnavailable(), CallPhase.INIT)
    assert rate.message != unavailable.message


def test_after_the_write_ahead_nothing_but_failed_is_determined() -> None:
    for phase, error, _, _ in GATEWAY_ROWS:
        mapping = map_gateway_error(error, phase, after_write_ahead=True)
        assert mapping.determined is False
        assert mapping.code in ("tiktok_result_uncertain", "tiktok_processing_pending")


def test_temporary_errors_never_reconnect() -> None:
    for phase in CallPhase:
        for error in (
            TikTokUnavailable(),
            TikTokUnavailable(rate_limited=True),
            TikTokUnexpectedResponse(),
        ):
            assert map_gateway_error(error, phase).reconnect is False
