"""The TikTok FILE_UPLOAD transfer shared by Direct Post and Upload to Inbox
(specs/014-tiktok-inbox-upload research §4), with its settings and error taxonomy.

What changes between modes is injected: the single `init` call and how a status is
interpreted. Everything else is mode-agnostic and keeps the anti-duplicate rules of
Feature 013 (research §11–§15):
- `init` is called at most once per attempt and never retried;
- the `publish_id` is committed before the first byte is sent;
- intermediate chunks are retried on the same buffer; a `416` is only accepted when
  TikTok confirms exactly the bytes of that chunk;
- the generic `final_chunk` stage and the run's `final_chunk_started_at` are
  committed before the last chunk (write-ahead), which is sent exactly once;
- afterwards only bounded status reads of the same `publish_id` settle the outcome.

The upload URL only lives in memory; nothing here writes it anywhere.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from app.credential_store import CredentialStore
from app.db import utc_now
from app.errors import AppError
from app.models import TikTokPublishPhase
from app.publishing import (
    ProgressReporter,
    PublishContext,
    PublishFailure,
    PublishOutcome,
)
from app.tiktok_connections import call_with_token, get_valid_credentials
from app.tiktok_gateway import (
    InitResult,
    PublishStatus,
    TikTokError,
    TikTokGateway,
    TikTokPostRejected,
    TikTokScopeMissing,
    TikTokTokenInvalid,
    TikTokUnavailable,
    TikTokUploadRangeMismatch,
    TikTokUploadRejected,
    UploadProgress,
    UploadUrl,
)
from app.tiktok_media import CHUNK_SIZE, SINGLE_CHUNK_MAX, ChunkPlan, UploadDigest

logger = logging.getLogger(__name__)

# --- Settings ------------------------------------------------------------------------


@dataclass(frozen=True)
class TikTokPublishSettings:
    """Waits and limits of a TikTok execution (research §9–§11, §15)."""

    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], datetime] = utc_now
    # Slices in which long waits are split, to notice a shutdown.
    sleep_slice: float = 1.0
    # Chunk plan (injectable so tests use files of a few KB).
    single_chunk_max: int = SINGLE_CHUNK_MAX
    chunk_size: int = CHUNK_SIZE
    # Retries of an intermediate chunk; the last chunk is never retried.
    chunk_retry_waits: tuple[float, ...] = (2.0, 5.0, 10.0)
    # One retry of Creator Info in the preflight (it has no effects).
    creator_info_retry_wait: float = 2.0
    # Status polling after the last chunk: first read, then these waits, then the
    # interval, up to the timeout counted from the last chunk.
    status_first_wait: float = 3.0
    status_waits: tuple[float, ...] = (3.0, 5.0, 5.0, 10.0, 10.0, 15.0, 15.0)
    status_interval: float = 30.0
    processing_timeout: timedelta = timedelta(minutes=10)
    # A 429 doubles the next wait, up to this value.
    rate_limited_wait_cap: float = 60.0
    # The upload URL is valid for one hour; the last chunk is only sent before this.
    upload_deadline: timedelta = timedelta(minutes=50)


# --- Error taxonomy (research §19) ----------------------------------------------------


class CallPhase(StrEnum):
    """Which TikTok call failed."""

    CREATOR_INFO = "creator_info"
    INIT = "init"
    CHUNK = "chunk"
    FINAL_CHUNK = "final_chunk"
    STATUS = "status"


class RetryPolicy(StrEnum):
    NONE = "none"
    # `call_with_token` renews the token once and repeats the read once.
    RENEW_ONCE = "renew_once"
    # Creator Info in the preflight: one retry after a short wait.
    ONCE = "once"
    # Intermediate chunk: bounded retries of the same buffer.
    CHUNK_RETRIES = "chunk_retries"
    # `416` of an intermediate chunk (research §12).
    RANGE_POLICY = "range_policy"
    # Status polling: keep reading within the processing window.
    KEEP_POLLING = "keep_polling"
    # Status polling after a 429: the next wait doubles.
    DOUBLE_WAIT = "double_wait"
    # Last chunk: never resent; only the status of the same `publish_id` is read.
    STATUS_ONLY = "status_only"


@dataclass(frozen=True)
class TikTokErrorMapping:
    code: str
    message: str
    determined: bool
    retry: RetryPolicy
    # Whether the connection must be marked `reconnect_required` (Feature 012).
    reconnect: bool


NOT_PUBLISHED = "Nothing was published."
RECONNECT_MESSAGE = "Reconnect this TikTok account before publishing."
UNAVAILABLE_MESSAGE = f"Could not reach TikTok. {NOT_PUBLISHED} Try again later."
RATE_LIMITED_MESSAGE = (
    f"TikTok is limiting requests right now. {NOT_PUBLISHED} Try again in a minute."
)
UNEXPECTED_MESSAGE = (
    f"TikTok returned an answer AutoPublisher does not understand. {NOT_PUBLISHED}"
)
SESSION_REJECTED_MESSAGE = f"TikTok rejected the session; try again. {NOT_PUBLISHED}"
INIT_FAILED_MESSAGE = f"TikTok rejected the post settings. {NOT_PUBLISHED}"
PRIVACY_INVALID_MESSAGE = (
    f"TikTok no longer accepts the chosen privacy for this account. {NOT_PUBLISHED}"
)
PRIVATE_ACCOUNT_MESSAGE = (
    "This TikTok app is not audited: TikTok only accepts posts to private accounts. "
    f"Set the TikTok account to private and try again. {NOT_PUBLISHED}"
)
CREATOR_MESSAGES = {
    "spam_risk_too_many_posts": (
        "This TikTok account reached its daily posting limit. Try again later."
    ),
    "spam_risk_user_banned_from_posting": (
        "TikTok does not allow this account to post right now."
    ),
    "reached_active_user_cap": (
        "This TikTok app reached its daily cap of active users. Try again later."
    ),
}
UPLOAD_FAILED_MESSAGE = f"TikTok did not accept the video upload. {NOT_PUBLISHED}"
UPLOAD_EXPIRED_MESSAGE = f"The TikTok upload link expired. {NOT_PUBLISHED}"
RESULT_UNCERTAIN_MESSAGE = (
    "TikTok did not confirm whether the video was published. Check your TikTok "
    "profile before publishing again."
)
PROCESSING_PENDING_MESSAGE = (
    "TikTok was still processing the video when AutoPublisher stopped waiting. Check "
    "again later or check your TikTok profile before publishing again."
)
AUTH_REMOVED_MESSAGE = (
    "TikTok access was removed while posting; reconnect the account. The video was "
    "not published."
)
VIDEO_REJECTED_MESSAGE = (
    "TikTok rejected the video (format, duration, frame rate or picture size). It "
    "was not published."
)
CONTENT_REJECTED_MESSAGE = "TikTok rejected the content. It was not published."
PUBLISH_FAILED_MESSAGE = "TikTok could not publish the video. It was not published."

_VIDEO_FAIL_REASONS = frozenset(
    {
        "file_format_check_failed",
        "duration_check_failed",
        "frame_rate_check_failed",
        "picture_size_check_failed",
    }
)


def _mapping(
    code: str,
    message: str,
    *,
    retry: RetryPolicy = RetryPolicy.NONE,
    reconnect: bool = False,
    determined: bool = True,
) -> TikTokErrorMapping:
    return TikTokErrorMapping(code, message, determined, retry, reconnect)


def _uncertain(retry: RetryPolicy, reconnect: bool = False) -> TikTokErrorMapping:
    return _mapping(
        "tiktok_result_uncertain",
        RESULT_UNCERTAIN_MESSAGE,
        retry=retry,
        reconnect=reconnect,
        determined=False,
    )


def map_gateway_error(
    error: TikTokError, phase: CallPhase, *, after_write_ahead: bool = False
) -> TikTokErrorMapping:
    """What a gateway error means for an attempt. After the write-ahead nothing but
    TikTok's own `FAILED` status is determined: every error stays uncertain."""
    if phase == CallPhase.FINAL_CHUNK:
        return _uncertain(RetryPolicy.STATUS_ONLY)
    mapping = _before_write_ahead(error, phase)
    if not after_write_ahead:
        return mapping
    if phase == CallPhase.STATUS and isinstance(error, TikTokPostRejected):
        return _uncertain(RetryPolicy.NONE)
    return _uncertain(mapping.retry, mapping.reconnect)


def _before_write_ahead(error: TikTokError, phase: CallPhase) -> TikTokErrorMapping:
    status_retry = (
        RetryPolicy.KEEP_POLLING if phase == CallPhase.STATUS else RetryPolicy.NONE
    )
    if isinstance(error, TikTokScopeMissing):
        return _mapping("tiktok_reconnect_required", RECONNECT_MESSAGE, reconnect=True)
    if isinstance(error, TikTokTokenInvalid):
        if phase == CallPhase.INIT:
            return _mapping("tiktok_unavailable", SESSION_REJECTED_MESSAGE)
        return _mapping(
            "tiktok_reconnect_required",
            RECONNECT_MESSAGE,
            retry=RetryPolicy.RENEW_ONCE,
            reconnect=True,
        )
    if phase == CallPhase.CHUNK:
        return _chunk_error(error)
    if isinstance(error, TikTokUnavailable):
        if phase == CallPhase.STATUS:
            retry = (
                RetryPolicy.DOUBLE_WAIT
                if error.rate_limited
                else RetryPolicy.KEEP_POLLING
            )
            return _mapping("tiktok_unavailable", UNAVAILABLE_MESSAGE, retry=retry)
        if error.rate_limited:
            return _mapping("tiktok_rate_limited", RATE_LIMITED_MESSAGE)
        retry = (
            RetryPolicy.ONCE if phase == CallPhase.CREATOR_INFO else RetryPolicy.NONE
        )
        return _mapping("tiktok_unavailable", UNAVAILABLE_MESSAGE, retry=retry)
    if isinstance(error, TikTokPostRejected):
        return _rejection(error.code)
    return _mapping(
        "tiktok_unexpected_response", UNEXPECTED_MESSAGE, retry=status_retry
    )


def _chunk_error(error: TikTokError) -> TikTokErrorMapping:
    if isinstance(error, TikTokUploadRejected):
        if error.status == 403:
            return _mapping("tiktok_upload_expired", UPLOAD_EXPIRED_MESSAGE)
        return _mapping("tiktok_upload_failed", UPLOAD_FAILED_MESSAGE)
    if isinstance(error, TikTokUploadRangeMismatch):
        return _mapping(
            "tiktok_upload_failed",
            UPLOAD_FAILED_MESSAGE,
            retry=RetryPolicy.RANGE_POLICY,
        )
    if isinstance(error, TikTokUnavailable):
        return _mapping(
            "tiktok_upload_failed",
            UPLOAD_FAILED_MESSAGE,
            retry=RetryPolicy.CHUNK_RETRIES,
        )
    return _mapping("tiktok_upload_failed", UPLOAD_FAILED_MESSAGE)


def _confirms_chunk(progress: UploadProgress | None, last: int, total: int) -> bool:
    """Whether a `416` proves that TikTok already accepted the intermediate chunk
    ending at byte `last` (inclusive): its answer must report exactly `last + 1`
    accepted bytes of the expected total (research §12). Chunks are sent in order
    from the confirmed offset, so that value is also the only one that neither
    goes back nor skips ahead."""
    return (
        progress is not None
        and progress.total == total
        and progress.accepted_bytes == last + 1
    )


def _rejection(code: str) -> TikTokErrorMapping:
    if code in CREATOR_MESSAGES:
        return _mapping("tiktok_creator_cannot_post", CREATOR_MESSAGES[code])
    if code == "invalid_param":
        return _mapping("tiktok_init_failed", INIT_FAILED_MESSAGE)
    if code == "privacy_level_option_mismatch":
        return _mapping("tiktok_privacy_invalid", PRIVACY_INVALID_MESSAGE)
    if code == "unaudited_client_can_only_post_to_private_accounts":
        return _mapping("tiktok_private_account_required", PRIVATE_ACCOUNT_MESSAGE)
    # `url_ownership_unverified` (no URL is ever used) and `publish_id` errors.
    return _mapping("tiktok_unexpected_response", UNEXPECTED_MESSAGE)


def map_fail_reason(reason: str | None) -> TikTokErrorMapping:
    """A `FAILED` status: TikTok says the video was not published (determined)."""
    if reason == "auth_removed":
        return _mapping("tiktok_publish_failed", AUTH_REMOVED_MESSAGE, reconnect=True)
    if reason in CREATOR_MESSAGES:
        return _mapping(
            "tiktok_creator_cannot_post",
            f"{CREATOR_MESSAGES[reason]} The video was not published.",
        )
    if reason in ("spam_risk_text", "spam_risk"):
        return _mapping("tiktok_content_rejected", CONTENT_REJECTED_MESSAGE)
    if reason in _VIDEO_FAIL_REASONS:
        return _mapping("tiktok_video_rejected", VIDEO_REJECTED_MESSAGE)
    return _mapping("tiktok_publish_failed", PUBLISH_FAILED_MESSAGE)


# --- Statuses and messages of the transfer ---------------------------------------

PROCESSING_UPLOAD = "PROCESSING_UPLOAD"
PUBLISH_COMPLETE = "PUBLISH_COMPLETE"
FAILED = "FAILED"
UNEXPECTED_STATUS = "UNEXPECTED"
STOP_POLLING_CODES = frozenset(
    {"tiktok_not_connected", "tiktok_reconnect_required", "tiktok_identity_mismatch"}
)
WRITE_AHEAD_FAILED_MESSAGE = (
    f"AutoPublisher could not save its progress, so it did not publish. {NOT_PUBLISHED}"
)
INTERRUPTED_MESSAGE = (
    f"The upload was interrupted because AutoPublisher stopped. {NOT_PUBLISHED}"
)
VIDEO_CHANGED_DURING_UPLOAD_MESSAGE = (
    "The video file changed while it was being uploaded, so its last part was not "
    f"sent. {NOT_PUBLISHED}"
)


# --- Transfer ------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusDecision:
    """What one status read means for the attempt (per mode).

    - `keep_polling`: TikTok is still working; read again within the window;
    - `done`: success with `outcome`; `run_values` are saved on the run first;
    - `failed`: TikTok says it failed (`mapping`, always determined);
    - `unresolved`: a status of another flow or an unknown one: never a success.

    `known` decides whether the status itself is recorded on the run (otherwise it
    is recorded as unexpected).
    """

    kind: Literal["keep_polling", "done", "failed", "unresolved"]
    known: bool = True
    outcome: PublishOutcome | None = None
    run_values: dict[str, Any] = field(default_factory=dict)
    mapping: "TikTokErrorMapping | None" = None


StatusInterpreter = Callable[[PublishStatus], StatusDecision]
# Saves values on the attempt's run; False when they could not be committed.
RunUpdater = Callable[..., bool]
# Turns a gateway error of a phase into the attempt's failure (marking the
# connection for reconnection when the mode says so).
FailureMapper = Callable[[TikTokError, "CallPhase"], PublishFailure]
# Marks the connection for reconnection after a definitive status signal.
Reconnector = Callable[[TikTokError], None]


@dataclass(frozen=True)
class TransferFile:
    """The local file and what was consented to; contains no secrets."""

    path: Path
    plan: ChunkPlan
    content_type: str
    # `Content.checksum`: the digest the user consented to.
    checksum: str


class FileUploadTransfer:
    """One FILE_UPLOAD transfer of one attempt, from `init` to a settled status."""

    def __init__(
        self,
        *,
        gateway: TikTokGateway,
        credential_store: CredentialStore,
        settings: TikTokPublishSettings,
        ctx: PublishContext,
        account_id: int,
        attempt_id: int,
        reporter: ProgressReporter,
        update_run: RunUpdater,
        failure: FailureMapper,
        reconnect: Reconnector,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.settings = settings
        self.ctx = ctx
        self.account_id = account_id
        self.attempt_id = attempt_id
        self.reporter = reporter
        self.update_run = update_run
        self.failure = failure
        self.reconnect = reconnect

    def _token(self) -> str:
        """A fresh token for `init`; credential problems are determined."""
        try:
            with self.ctx.session_factory() as session:
                credential = get_valid_credentials(
                    session, self.credential_store, self.gateway, self.account_id
                )
        except AppError as error:
            if error.code in STOP_POLLING_CODES:
                raise PublishFailure(
                    "tiktok_reconnect_required", RECONNECT_MESSAGE, determined=True
                ) from None
            if error.code == "credential_store_unavailable":
                raise PublishFailure(
                    "credential_store_unavailable", error.message, determined=True
                ) from None
            raise PublishFailure(
                "tiktok_unavailable", UNAVAILABLE_MESSAGE, determined=True
            ) from None
        return credential.access_token

    def _wait(self, seconds: float) -> bool:
        """Sleep in short slices; False when the application is shutting down."""
        remaining = seconds
        while remaining > 0:
            if self.reporter.should_stop():
                return False
            step = min(self.settings.sleep_slice, remaining)
            self.settings.sleep(step)
            remaining -= step
        return not self.reporter.should_stop()

    def run(
        self,
        file: TransferFile,
        init: Callable[[str], InitResult],
        interpret: StatusInterpreter,
    ) -> PublishOutcome:
        reporter = self.reporter
        attempt_id = self.attempt_id
        token = self._token()
        self.update_run(self.ctx, attempt_id, phase=TikTokPublishPhase.INITIALIZING)
        # The only `init` of this attempt: never repeated (research §13).
        try:
            started_upload = init(token)
        except TikTokError as error:
            raise self.failure(error, CallPhase.INIT) from None
        initialized = self.settings.clock()
        # The upload URL is valid one hour: the last chunk is only sent before this.
        deadline = initialized + self.settings.upload_deadline
        if not self.update_run(
            self.ctx,
            attempt_id,
            publish_id=started_upload.publish_id,
            initialized_at=initialized,
            phase=TikTokPublishPhase.UPLOADING,
        ):
            # Without the publish_id on record, nothing is ever sent.
            raise PublishFailure(
                "internal_error", WRITE_AHEAD_FAILED_MESSAGE, determined=True
            )
        reporter.report_bytes(0)
        plan = file.plan
        digest = UploadDigest()
        with file.path.open("rb") as handle:
            for index in range(plan.total_chunk_count - 1):
                data = self._read_chunk(handle, plan, index)
                digest.update(data)
                self._send_chunk(started_upload.upload_url, data, file, index, deadline)
            last_index = plan.total_chunk_count - 1
            data = self._read_chunk(handle, plan, last_index)
            grown = handle.read(1)
        digest.update(data)
        if grown or digest.hexdigest() != file.checksum:
            raise PublishFailure(
                "tiktok_video_changed",
                VIDEO_CHANGED_DURING_UPLOAD_MESSAGE,
                determined=True,
            )
        if reporter.should_stop():
            raise PublishFailure("interrupted", INTERRUPTED_MESSAGE, determined=True)
        self._check_deadline(deadline)
        started = self.settings.clock()
        # Write-ahead: both commits happen before the last chunk is sent.
        if not reporter.enter_final_chunk() or not self.update_run(
            self.ctx,
            attempt_id,
            phase=TikTokPublishPhase.FINAL_CHUNK,
            final_chunk_started_at=started,
        ):
            raise PublishFailure(
                "internal_error", WRITE_AHEAD_FAILED_MESSAGE, determined=True
            )
        status = self._send_last_chunk(started_upload.upload_url, data, file)
        del data
        # Whatever the answer, only the status of this publish_id decides now.
        reporter.enter_finalizing()
        values: dict[str, Any] = {
            "phase": TikTokPublishPhase.PROCESSING,
            "final_chunk_http_status": status,
        }
        if status == 201:
            values["confirmed_bytes"] = plan.video_size
        self.update_run(self.ctx, attempt_id, **values)
        if status == 201:
            reporter.report_bytes(plan.video_size, confirmed=True)
        return self._poll(started_upload.publish_id, started, interpret, status)

    @staticmethod
    def _read_chunk(handle: Any, plan: ChunkPlan, index: int) -> bytes:
        """One chunk buffer read once from the original file, in order."""
        first, last = plan.chunk_range(index)
        data = bytes(handle.read(last - first + 1))
        if len(data) != last - first + 1:
            raise PublishFailure(
                "tiktok_video_changed",
                VIDEO_CHANGED_DURING_UPLOAD_MESSAGE,
                determined=True,
            )
        return data

    def _check_deadline(self, deadline: datetime) -> None:
        if self.settings.clock() >= deadline:
            raise PublishFailure(
                "tiktok_upload_expired", UPLOAD_EXPIRED_MESSAGE, determined=True
            )

    def _send_chunk(
        self,
        upload_url: UploadUrl,
        data: bytes,
        file: TransferFile,
        index: int,
        deadline: datetime,
    ) -> None:
        """An intermediate chunk, retried on the same buffer after a temporary
        failure (research §11) and accepted after a `416` only when TikTok's
        `Content-Range` says it accepted exactly the bytes up to this chunk's end
        (§12). Before the write-ahead every failure is determined."""
        plan = file.plan
        first, last = plan.chunk_range(index)
        waits = self.settings.chunk_retry_waits
        for try_number in range(len(waits) + 1):
            if self.reporter.should_stop():
                raise PublishFailure(
                    "interrupted", INTERRUPTED_MESSAGE, determined=True
                )
            self._check_deadline(deadline)
            try:
                result = self.gateway.upload_chunk(
                    upload_url,
                    data,
                    first,
                    last,
                    plan.video_size,
                    file.content_type,
                )
            except TikTokUploadRangeMismatch as error:
                if not _confirms_chunk(error.progress, last, plan.video_size):
                    raise self.failure(error, CallPhase.CHUNK) from None
                break  # TikTok already holds exactly this chunk.
            except TikTokError as error:
                mapping = map_gateway_error(error, CallPhase.CHUNK)
                if mapping.retry != RetryPolicy.CHUNK_RETRIES or try_number == len(
                    waits
                ):
                    raise self.failure(error, CallPhase.CHUNK) from None
                logger.info(
                    "TikTok chunk %s of attempt %s failed (%s); retrying.",
                    index + 1,
                    self.attempt_id,
                    type(error).__name__,
                )
                if not self._wait(waits[try_number]):
                    raise PublishFailure(
                        "interrupted", INTERRUPTED_MESSAGE, determined=True
                    ) from None
                continue
            if result.status != 206:
                # "Every part received" before the last one: TikTok may be posting.
                raise PublishFailure(
                    "tiktok_result_uncertain",
                    RESULT_UNCERTAIN_MESSAGE,
                    determined=False,
                )
            break
        self.update_run(self.ctx, self.attempt_id, confirmed_bytes=last + 1)
        self.reporter.report_bytes(last + 1, confirmed=True)

    def _send_last_chunk(
        self, upload_url: UploadUrl, data: bytes, file: TransferFile
    ) -> int | None:
        """The irreversible request, sent exactly once and never retried. Its HTTP
        status is only kept for diagnosis (None without an answer)."""
        plan = file.plan
        first, last = plan.chunk_range(plan.total_chunk_count - 1)
        try:
            result = self.gateway.upload_chunk(
                upload_url, data, first, last, plan.video_size, file.content_type
            )
        except TikTokError as error:
            logger.warning(
                "The last TikTok chunk of attempt %s was not confirmed (%s); only "
                "the status of the same post is read.",
                self.attempt_id,
                type(error).__name__,
            )
            return error.http_status
        return result.status

    def _read_status(self, publish_id: str) -> PublishStatus:
        with self.ctx.session_factory() as session:
            return call_with_token(
                session,
                self.credential_store,
                self.gateway,
                self.account_id,
                lambda token: self.gateway.fetch_publish_status(token, publish_id),
            )

    def _poll(
        self,
        publish_id: str,
        started: datetime,
        interpret: StatusInterpreter,
        final_status: int | None = 201,
    ) -> PublishOutcome:
        """Bounded status reads of the original publish_id (research §15). Only the
        mode's success statuses end it well and only `FAILED` is determined."""
        settings = self.settings
        deadline = started + settings.processing_timeout
        waits = iter(settings.status_waits)
        wait = settings.status_first_wait
        last_status: str | None = None
        reads = 0
        while True:
            if settings.clock() + timedelta(seconds=wait) > deadline:
                raise unresolved_failure(last_status, final_status)
            if not self._wait(wait):
                raise unresolved_failure(last_status, final_status)
            wait = next(waits, settings.status_interval)
            reads += 1
            try:
                status = self._read_status(publish_id)
            except TikTokUnavailable as error:
                if error.rate_limited:
                    wait = min(wait * 2, settings.rate_limited_wait_cap)
                continue
            except TikTokScopeMissing as error:
                self.reconnect(error)
                raise unresolved_failure(None, final_status) from None
            except TikTokPostRejected:
                raise unresolved_failure(None, final_status) from None
            except TikTokError:
                continue
            except AppError as error:
                if error.code in STOP_POLLING_CODES:
                    raise unresolved_failure(None, final_status) from None
                continue
            elapsed = (settings.clock() - started).total_seconds()
            logger.info(
                "TikTok status of attempt %s, read %s after %.0f s: %s.",
                self.attempt_id,
                reads,
                elapsed,
                status.status,
            )
            decision = interpret(status)
            self.update_run(
                self.ctx,
                self.attempt_id,
                last_remote_status=status.status
                if decision.known
                else UNEXPECTED_STATUS,
                remote_uploaded_bytes=status.uploaded_bytes,
                fail_reason=status.fail_reason,
                last_status_at=settings.clock(),
            )
            if decision.kind == "keep_polling":
                last_status = status.status
                continue
            if decision.kind == "done":
                assert decision.outcome is not None
                if decision.run_values:
                    self.update_run(self.ctx, self.attempt_id, **decision.run_values)
                return decision.outcome
            if decision.kind == "failed":
                mapping = decision.mapping
                assert mapping is not None
                if mapping.reconnect:
                    self.reconnect(TikTokTokenInvalid())
                raise PublishFailure(mapping.code, mapping.message, determined=True)
            # Statuses of other flows or unknown ones are never a success.
            raise unresolved_failure(None, final_status)


def unresolved_failure(
    last_status: str | None, final_status: int | None = 201
) -> PublishFailure:
    """An outcome only TikTok's status could settle. The answer to the last chunk is
    only a diagnosis: it never makes the result determined."""
    if final_status == 201:
        diagnosis = ""
    elif final_status is None:
        diagnosis = " The last part of the video got no answer from TikTok."
    else:
        diagnosis = (
            f" TikTok answered the last part with HTTP {final_status}, which "
            "does not prove that nothing was published."
        )
    if last_status == PROCESSING_UPLOAD:
        message = PROCESSING_PENDING_MESSAGE + diagnosis
        return PublishFailure(
            "tiktok_processing_pending", message[:500], determined=False
        )
    message = RESULT_UNCERTAIN_MESSAGE + diagnosis
    return PublishFailure("tiktok_result_uncertain", message[:500], determined=False)
