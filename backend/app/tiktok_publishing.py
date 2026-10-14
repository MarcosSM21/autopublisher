"""TikTok publisher: options, Creator Info, consent, preflight and Direct Post of a
local video with FILE_UPLOAD (specs/013-tiktok-direct-post, contracts/api.md).

Everything TikTok-specific about running a publication lives here; the generic core
only talks to `TikTokPublisher` through the `Publisher` protocol.

Never publishing a duplicate is the main rule (research §11–§14):
- `video/init/` is called at most once per attempt and never retried;
- the `publish_id` is committed before the first byte is sent;
- the generic `final_chunk` stage and the run's `final_chunk_started_at` are
  committed before the last chunk (write-ahead);
- the last chunk is sent exactly once; whatever its answer, only the status of the
  original `publish_id` settles the outcome; posts are never listed.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.contents import StorageDep
from app.credential_store import CredentialStore
from app.db import get_session, utc_now
from app.errors import AppError, ConflictError
from app.models import (
    Account,
    Content,
    MediaType,
    Platform,
    Publication,
    PublicationAttempt,
    PublicationStatus,
    TikTokConnection,
    TikTokConnectionStatus,
    TikTokPublicationOptions,
    TikTokPublishPhase,
    TikTokPublishRun,
)
from app.publications import ensure_editable, get_publication_or_404
from app.publishing import (
    PreparedPublication,
    ProgressReporter,
    PublishCheck,
    PublishContext,
    PublishFailure,
    PublishOutcome,
    PublishProblem,
    ReconciledFailure,
    Reconciliation,
)
from app.schemas import (
    PublishProblemRead,
    TikTokConsentRead,
    TikTokConsentWrite,
    TikTokCreatorBlockedRead,
    TikTokCreatorInfoRead,
    TikTokDeclarationLinkRead,
    TikTokDeclarationRead,
    TikTokIntegrityWarningRead,
    TikTokPublicationOptionsRead,
    TikTokPublicationOptionsWrite,
    TikTokVideoSummaryRead,
)
from app.storage import MediaStorage
from app.tiktok_connections import (
    call_with_token,
    get_connection,
    get_valid_credentials,
    mark_reconnect_required,
    mark_scope_not_authorized,
)
from app.tiktok_gateway import (
    CreatorInfo,
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
from app.tiktok_media import (
    CHUNK_SIZE,
    PHOTOS_UNSUPPORTED_MESSAGE,
    SELF_ONLY,
    SINGLE_CHUNK_MAX,
    TIKTOK_CAPTION_MAX,
    ChunkPlan,
    Declaration,
    UploadDigest,
    VideoCheck,
    allowed_privacy_levels,
    build_caption,
    caption_problems,
    consent_fingerprint,
    declaration_for,
    disclosure_labels,
    duration_problems,
    file_sha256,
    inspect_video,
    option_problems,
    plan_chunks,
    post_info,
    source_info,
    tiktok_caption_length,
    video_mime,
)

logger = logging.getLogger(__name__)

# The current TikTok app is not audited (research §4): only private posts. Enabling
# public posting needs TikTok's audit, another specification and new tests; this is
# deliberately not configurable.
CLIENT_AUDITED = False
UNAUDITED_PRIVACY_LEVEL = SELF_ONLY


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


# --- Review state (no network) --------------------------------------------------------

EDITABLE_STATUSES = (
    PublicationStatus.UNSCHEDULED,
    PublicationStatus.SCHEDULED,
    PublicationStatus.FAILED,
)
NOT_CONNECTED_MESSAGE = "Connect this TikTok account before publishing."
CONSENT_MISSING_MESSAGE = "Confirm the TikTok declaration before publishing."
CONSENT_STALE_MESSAGE = (
    "Your changes need a new confirmation before this video can be published."
)
CONSENT_STALE_ERROR_MESSAGE = (
    "The publication changed since it was reviewed. Review it and confirm the TikTok "
    "declaration again."
)
OPTIONS_INCOMPLETE_MESSAGE = (
    "Choose the privacy, say whether the video is AI-generated and complete the "
    "commercial content disclosure before confirming."
)
VIDEO_CHANGED_MESSAGE = (
    "The video file no longer matches the one you confirmed. Nothing was sent to "
    "TikTok."
)
CREATOR_BLOCKED_MESSAGE = "TikTok does not allow this account to post right now."
ARMING_REVIEW_MESSAGE = (
    "{who}: review the TikTok options and confirm the declaration before enabling "
    "auto-publish."
)

ConsentState = Literal["missing", "valid", "stale"]


def get_options(session: Session, publication_id: int) -> TikTokPublicationOptions:
    """Stored options, or the initial values (not added to the session)."""
    stored = session.get(TikTokPublicationOptions, publication_id)
    if stored is not None:
        return stored
    return TikTokPublicationOptions(
        publication_id=publication_id,
        privacy_level=None,
        allow_comment=False,
        allow_duet=False,
        allow_stitch=False,
        commercial_disclosure_enabled=False,
        brand_organic_toggle=False,
        brand_content_toggle=False,
        is_aigc=None,
    )


def _content_of(session: Session, publication: Publication) -> Content | None:
    if publication.content_id is None:
        return None
    return session.get_one(Content, publication.content_id)


@dataclass(frozen=True)
class ReviewState:
    """Everything the review, the consent and `check()` derive locally."""

    content: Content
    connection: TikTokConnection | None
    options: TikTokPublicationOptions
    caption: str
    video: VideoCheck
    plan: ChunkPlan | None
    declaration: Declaration
    fingerprint: str | None
    consent: ConsentState
    # Options, caption, video and consent problems; never connection problems.
    problems: list[PublishProblem]


def consent_state(
    options: TikTokPublicationOptions, fingerprint: str | None, declaration: Declaration
) -> ConsentState:
    if options.consent_fingerprint is None:
        return "missing"
    if (
        fingerprint is not None
        and options.consent_fingerprint == fingerprint
        and options.consent_declaration_version == declaration.version
    ):
        return "valid"
    return "stale"


def review_state(
    session: Session,
    publication: Publication,
    content: Content,
    storage: MediaStorage,
    settings: "TikTokPublishSettings",
) -> ReviewState:
    """Local review of a TikTok publication: the consent fingerprint uses
    `Content.checksum`; the file itself is only stat-ed and inspected (never hashed
    here)."""
    connection = get_connection(session, publication.account_id)
    options = get_options(session, publication.id)
    caption = build_caption(publication, content)
    video = inspect_video(content, storage.resolve(content.storage_path))
    plan = None
    if video.summary is not None:
        try:
            plan = plan_chunks(
                content.size_bytes, settings.single_chunk_max, settings.chunk_size
            )
        except ValueError:
            plan = None
    declaration = declaration_for(options)
    fingerprint = (
        consent_fingerprint(
            open_id=connection.open_id,
            video_sha256=content.checksum,
            caption=caption,
            options=options,
        )
        if connection is not None
        else None
    )
    consent = consent_state(options, fingerprint, declaration)
    problems = list(video.problems)
    problems.extend(caption_problems(caption))
    options_problems = option_problems(options, client_audited=CLIENT_AUDITED)
    problems.extend(options_problems)
    if not options_problems and consent != "valid":
        problems.append(
            PublishProblem(
                "tiktok_consent_required",
                CONSENT_STALE_MESSAGE
                if consent == "stale"
                else CONSENT_MISSING_MESSAGE,
                "consent",
            )
        )
    return ReviewState(
        content=content,
        connection=connection,
        options=options,
        caption=caption,
        video=video,
        plan=plan,
        declaration=declaration,
        fingerprint=fingerprint,
        consent=consent,
        problems=problems,
    )


def connection_problems(connection: TikTokConnection | None) -> list[PublishProblem]:
    if connection is None:
        return [PublishProblem("tiktok_not_connected", NOT_CONNECTED_MESSAGE)]
    if connection.status != TikTokConnectionStatus.CONNECTED:
        return [PublishProblem("tiktok_reconnect_required", RECONNECT_MESSAGE)]
    return []


def _integrity_warning(
    session: Session, publication: Publication, options: TikTokPublicationOptions
) -> TikTokIntegrityWarningRead | None:
    """The last attempt found a file that no longer matches the consented digest,
    and no consent was recorded after it."""
    latest = session.scalars(
        select(PublicationAttempt)
        .where(PublicationAttempt.publication_id == publication.id)
        .order_by(PublicationAttempt.started_at.desc(), PublicationAttempt.id.desc())
        .limit(1)
    ).first()
    if (
        latest is None
        or latest.error_code != "tiktok_video_changed"
        or latest.finished_at is None
    ):
        return None
    if options.consented_at is not None and options.consented_at > latest.finished_at:
        return None
    return TikTokIntegrityWarningRead(
        code="tiktok_video_changed",
        message=VIDEO_CHANGED_MESSAGE,
        at=latest.finished_at,
    )


# --- API ------------------------------------------------------------------------------

router = APIRouter(prefix="/api", tags=["tiktok"])

SessionDep = Annotated[Session, Depends(get_session)]


def get_tiktok_settings(request: Request) -> TikTokPublishSettings:
    settings: TikTokPublishSettings = request.app.state.tiktok_publish_settings
    return settings


def get_tiktok_gateway(request: Request) -> TikTokGateway:
    gateway: TikTokGateway = request.app.state.tiktok_gateway
    return gateway


def get_tiktok_store(request: Request) -> CredentialStore:
    store: CredentialStore = request.app.state.tiktok_credential_store
    return store


SettingsDep = Annotated[TikTokPublishSettings, Depends(get_tiktok_settings)]
GatewayDep = Annotated[TikTokGateway, Depends(get_tiktok_gateway)]
StoreDep = Annotated[CredentialStore, Depends(get_tiktok_store)]


def _tiktok_publication(
    session: Session, publication_id: int
) -> tuple[Publication, Content]:
    """A TikTok publication of a video (contracts: common errors)."""
    publication = get_publication_or_404(session, publication_id)
    account = session.get_one(Account, publication.account_id)
    if account.platform != Platform.TIKTOK:
        raise ConflictError(
            "platform_not_supported",
            "TikTok options only apply to publications of TikTok accounts.",
        )
    content = _content_of(session, publication)
    if content is None or content.media_type != MediaType.VIDEO:
        raise AppError(409, "tiktok_video_required", PHOTOS_UNSUPPORTED_MESSAGE)
    return publication, content


def options_to_read(
    session: Session,
    publication: Publication,
    content: Content,
    storage: MediaStorage,
    settings: TikTokPublishSettings,
) -> TikTokPublicationOptionsRead:
    state = review_state(session, publication, content, storage, settings)
    options = state.options
    summary = state.video.summary
    return TikTokPublicationOptionsRead(
        privacy_level=options.privacy_level,  # type: ignore[arg-type]
        allow_comment=bool(options.allow_comment),
        allow_duet=bool(options.allow_duet),
        allow_stitch=bool(options.allow_stitch),
        commercial_disclosure_enabled=bool(options.commercial_disclosure_enabled),
        brand_organic_toggle=bool(options.brand_organic_toggle),
        brand_content_toggle=bool(options.brand_content_toggle),
        is_aigc=options.is_aigc,
        client_audited=CLIENT_AUDITED,
        allowed_privacy_levels=list(
            allowed_privacy_levels(client_audited=CLIENT_AUDITED)  # type: ignore[arg-type]
        ),
        caption=state.caption,
        caption_length=tiktok_caption_length(state.caption),
        caption_max_length=TIKTOK_CAPTION_MAX,
        declaration=TikTokDeclarationRead(
            version=state.declaration.version,
            text=state.declaration.text,
            links=[
                TikTokDeclarationLinkRead(label=link.label, url=link.url)
                for link in state.declaration.links
            ],
        ),
        labels=disclosure_labels(options),
        fingerprint=state.fingerprint,
        consent=TikTokConsentRead(
            state=state.consent,
            consented_at=options.consented_at if state.consent != "missing" else None,
        ),
        integrity_warning=_integrity_warning(session, publication, options),
        problems=[
            PublishProblemRead(code=p.code, message=p.message, field=p.field)
            for p in state.problems
        ],
        video=TikTokVideoSummaryRead(
            format=summary.format,
            size_bytes=summary.size_bytes,
            duration_seconds=summary.duration_seconds,
            width=summary.width,
            height=summary.height,
            frame_rate=summary.frame_rate,
            delegated_checks=list(state.video.delegated_checks),
            chunk_count=state.plan.total_chunk_count if state.plan else 0,
        )
        if summary is not None
        else None,
        editable=publication.status in EDITABLE_STATUSES,
    )


@router.get(
    "/publications/{publication_id}/tiktok-options",
    response_model=TikTokPublicationOptionsRead,
)
def get_tiktok_options(
    publication_id: int,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> TikTokPublicationOptionsRead:
    """Options, exact caption, declaration, consent state and local problems; no
    network."""
    publication, content = _tiktok_publication(session, publication_id)
    return options_to_read(session, publication, content, storage, settings)


@router.put(
    "/publications/{publication_id}/tiktok-options",
    response_model=TikTokPublicationOptionsRead,
)
def save_tiktok_options(
    publication_id: int,
    body: TikTokPublicationOptionsWrite,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> TikTokPublicationOptionsRead:
    """Replace every option; the stored consent is kept (it becomes stale when the
    fingerprint changes)."""
    publication, content = _tiktok_publication(session, publication_id)
    ensure_editable(publication)
    if body.brand_content_toggle and body.privacy_level == SELF_ONLY:
        message = "Branded content visibility cannot be set to private."
        raise AppError(
            422,
            "tiktok_branded_content_private",
            message,
            fields=[{"field": "brand_content_toggle", "message": message}],
        )
    options = session.get(TikTokPublicationOptions, publication_id)
    if options is None:
        options = TikTokPublicationOptions(publication_id=publication_id)
        session.add(options)
    options.privacy_level = body.privacy_level
    options.allow_comment = body.allow_comment
    options.allow_duet = body.allow_duet
    options.allow_stitch = body.allow_stitch
    options.commercial_disclosure_enabled = body.commercial_disclosure_enabled
    options.brand_organic_toggle = body.brand_organic_toggle
    options.brand_content_toggle = body.brand_content_toggle
    options.is_aigc = body.is_aigc
    options.updated_at = settings.clock()
    session.commit()
    return options_to_read(session, publication, content, storage, settings)


@router.post(
    "/publications/{publication_id}/tiktok-consent",
    response_model=TikTokPublicationOptionsRead,
)
def confirm_tiktok_consent(
    publication_id: int,
    body: TikTokConsentWrite,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> TikTokPublicationOptionsRead:
    """Record that the user accepted the declaration for exactly what they
    reviewed: the fingerprint is recomputed here and must match."""
    publication, content = _tiktok_publication(session, publication_id)
    ensure_editable(publication)
    problems = connection_problems(get_connection(session, publication.account_id))
    if problems:
        raise AppError(409, problems[0].code, problems[0].message)
    state = review_state(session, publication, content, storage, settings)
    if (
        session.get(TikTokPublicationOptions, publication_id) is None
        or option_problems(state.options, client_audited=CLIENT_AUDITED)
        or state.fingerprint is None
    ):
        raise AppError(409, "tiktok_options_incomplete", OPTIONS_INCOMPLETE_MESSAGE)
    if (
        body.fingerprint != state.fingerprint
        or body.declaration_version != state.declaration.version
    ):
        raise AppError(409, "tiktok_consent_stale", CONSENT_STALE_ERROR_MESSAGE)
    options = state.options
    now = settings.clock()
    options.consent_fingerprint = state.fingerprint
    options.consent_declaration_version = state.declaration.version
    options.consented_at = now
    options.updated_at = now
    session.commit()
    return options_to_read(session, publication, content, storage, settings)


def read_creator_info(
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    account_id: int,
    *,
    retry_wait: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CreatorInfo:
    """One Creator Info read with Feature 012's credential lifecycle (plus one retry
    after `retry_wait` on a network or server error, never on a 429). TikTok errors
    become API errors; a creator who cannot post raises `TikTokPostRejected`."""
    tries = 1 if retry_wait is None else 2
    for number in range(tries):
        try:
            return call_with_token(
                session, store, gateway, account_id, gateway.query_creator_info
            )
        except TikTokScopeMissing:
            mark_scope_not_authorized(
                session, account_id, "video.publish", gateway.clock()
            )
            raise AppError(
                409, "tiktok_reconnect_required", RECONNECT_MESSAGE
            ) from None
        except TikTokUnavailable as error:
            if error.rate_limited:
                raise AppError(
                    429, "tiktok_rate_limited", RATE_LIMITED_MESSAGE
                ) from None
            if number + 1 < tries and retry_wait is not None:
                sleep(retry_wait)
                continue
            raise AppError(503, "tiktok_unavailable", UNAVAILABLE_MESSAGE) from None
        except TikTokPostRejected as error:
            if error.code in CREATOR_MESSAGES:
                raise
            raise AppError(
                502, "tiktok_unexpected_response", UNEXPECTED_MESSAGE
            ) from None
        except TikTokError:
            raise AppError(
                502, "tiktok_unexpected_response", UNEXPECTED_MESSAGE
            ) from None
    raise AssertionError("unreachable")


@router.get(
    "/publications/{publication_id}/tiktok-creator-info",
    response_model=TikTokCreatorInfoRead,
)
def get_tiktok_creator_info(
    publication_id: int,
    session: SessionDep,
    storage: StorageDep,
    gateway: GatewayDep,
    store: StoreDep,
) -> TikTokCreatorInfoRead:
    """A fresh Creator Info read for the review (read-only, never stored)."""
    publication, content = _tiktok_publication(session, publication_id)
    problems = connection_problems(get_connection(session, publication.account_id))
    if problems:
        raise AppError(409, problems[0].code, problems[0].message)
    try:
        info = read_creator_info(session, store, gateway, publication.account_id)
    except TikTokPostRejected as error:
        return TikTokCreatorInfoRead(
            nickname=None,
            username=None,
            avatar_url=None,
            privacy_level_options=None,
            comment_disabled=None,
            duet_disabled=None,
            stitch_disabled=None,
            max_video_post_duration_sec=None,
            can_post=False,
            blocked=TikTokCreatorBlockedRead(
                code="tiktok_creator_cannot_post",
                message=CREATOR_MESSAGES.get(error.code, CREATOR_BLOCKED_MESSAGE),
            ),
            account_appears_public=False,
            video_within_max_duration=None,
        )
    video = inspect_video(content, storage.resolve(content.storage_path))
    duration = video.summary.duration_seconds if video.summary is not None else None
    return TikTokCreatorInfoRead(
        nickname=info.nickname,
        username=info.username,
        avatar_url=info.avatar_url,
        privacy_level_options=list(info.privacy_level_options),
        comment_disabled=info.comment_disabled,
        duet_disabled=info.duet_disabled,
        stitch_disabled=info.stitch_disabled,
        max_video_post_duration_sec=info.max_video_post_duration_sec,
        can_post=True,
        blocked=None,
        account_appears_public="PUBLIC_TO_EVERYONE" in info.privacy_level_options,
        video_within_max_duration=(
            duration <= info.max_video_post_duration_sec
            if duration is not None
            else None
        ),
    )


# --- Publisher -----------------------------------------------------------------------

PRIVACY_LABELS = {
    "PUBLIC_TO_EVERYONE": "Everyone",
    "MUTUAL_FOLLOW_FRIENDS": "Friends",
    "FOLLOWER_OF_CREATOR": "Followers",
    SELF_ONLY: "Only me",
}
PROCESSING_UPLOAD = "PROCESSING_UPLOAD"
PUBLISH_COMPLETE = "PUBLISH_COMPLETE"
FAILED = "FAILED"
UNEXPECTED_STATUS = "UNEXPECTED"
STOP_POLLING_CODES = frozenset(
    {"tiktok_not_connected", "tiktok_reconnect_required", "tiktok_identity_mismatch"}
)

PRIVACY_UNAVAILABLE_MESSAGE = (
    "TikTok no longer offers the chosen privacy for this account (this app can "
    "only post with 'Only me'). Review the TikTok options; nothing was sent to "
    "TikTok."
)
INTERACTION_UNAVAILABLE_MESSAGE = (
    "{name} is now turned off in this TikTok account's settings. Review the TikTok "
    "options; nothing was sent to TikTok."
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
PRIVATE_POST_NO_LINK_MESSAGE = (
    "TikTok does not return a link for private posts. Open your TikTok profile to "
    "see the video; it may take a few minutes to appear."
)


@dataclass(frozen=True)
class TikTokPayload:
    """What the core treats as an opaque payload. Contains no secrets."""

    account_id: int
    post_info: dict[str, Any]
    source_info: dict[str, Any]
    plan: ChunkPlan
    content_type: str
    # `Content.checksum`: the digest the user consented to.
    checksum: str


def _commercial_label(options: TikTokPublicationOptions) -> str:
    if not options.commercial_disclosure_enabled:
        return "Off"
    if options.brand_organic_toggle and options.brand_content_toggle:
        return "Your brand and Branded content"
    if options.brand_content_toggle:
        return "Branded content"
    if options.brand_organic_toggle:
        return "Your brand"
    return "On (choose an option)"


def _yes_no(value: bool | None) -> str:
    return "Not decided" if value is None else ("Yes" if value else "No")


class TikTokPublisher:
    # TikTok Direct Post publishes a video; there are no text-only posts.
    accepts_text_only = False

    def __init__(
        self,
        gateway: TikTokGateway,
        credential_store: CredentialStore,
        settings: TikTokPublishSettings | None = None,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.settings = settings or TikTokPublishSettings()

    # --- Local checks (no network) ---------------------------------------------

    def arming_problems(
        self, session: Session, publication: Publication
    ) -> list[PublishProblem]:
        """Auto-publish needs complete options, a valid caption and a consent for
        exactly the current content (research §20). Local only: the scheduler
        rechecks everything, Creator Info included, when it runs."""
        account = session.get_one(Account, publication.account_id)
        who = f"TikTok @{account.handle}"
        content = _content_of(session, publication)
        if content is None or content.media_type != MediaType.VIDEO:
            return [
                PublishProblem(
                    "tiktok_video_required", f"{who}: {PHOTOS_UNSUPPORTED_MESSAGE}"
                )
            ]
        if publication.id is None:
            # A publication created armed was never reviewed nor consented.
            return [
                PublishProblem(
                    "tiktok_consent_required", ARMING_REVIEW_MESSAGE.format(who=who)
                )
            ]
        options = get_options(session, publication.id)
        if option_problems(options, client_audited=CLIENT_AUDITED):
            return [
                PublishProblem(
                    "tiktok_options_incomplete",
                    f"{who}: {OPTIONS_INCOMPLETE_MESSAGE}",
                )
            ]
        caption = build_caption(publication, content)
        invalid = caption_problems(caption)
        if invalid:
            return [
                PublishProblem("tiktok_caption_invalid", f"{who}: {invalid[0].message}")
            ]
        connection = get_connection(session, publication.account_id)
        fingerprint = (
            consent_fingerprint(
                open_id=connection.open_id,
                video_sha256=content.checksum,
                caption=caption,
                options=options,
            )
            if connection is not None
            else None
        )
        if consent_state(options, fingerprint, declaration_for(options)) != "valid":
            return [
                PublishProblem(
                    "tiktok_consent_required", ARMING_REVIEW_MESSAGE.format(who=who)
                )
            ]
        return []

    def check(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PublishCheck:
        """Every local rule, with `Content.checksum` for the consent: never reads
        the network nor hashes the file."""
        connection = get_connection(session, publication.account_id)
        problems = connection_problems(connection)
        account = connection.display_name if connection is not None else None
        summary = [("TikTok account", account or "Not connected")]
        content = _content_of(session, publication)
        if content is None or content.media_type != MediaType.VIDEO:
            problems.append(
                PublishProblem("tiktok_video_required", PHOTOS_UNSUPPORTED_MESSAGE)
            )
            return PublishCheck(problems, summary)
        state = review_state(session, publication, content, ctx.storage, self.settings)
        problems.extend(state.problems)
        options = state.options
        interactions = " · ".join(
            f"{name}: {'on' if allowed else 'off'}"
            for name, allowed in (
                ("Comments", options.allow_comment),
                ("Duet", options.allow_duet),
                ("Stitch", options.allow_stitch),
            )
        )
        if state.consent == "valid" and options.consented_at is not None:
            declaration = options.consented_at.strftime("%Y-%m-%d %H:%M UTC")
        else:
            declaration = "Not yet" if state.consent == "missing" else "Confirm again"
        summary += [
            (
                "File",
                f"{content.original_filename} ({content.size_bytes / 1_000_000:.1f} "
                "MB)",
            ),
            ("Caption", state.caption or "(empty)"),
            (
                "Privacy",
                PRIVACY_LABELS.get(options.privacy_level or "", "Not chosen"),
            ),
            ("Interactions", interactions),
            ("Commercial content", _commercial_label(options)),
            ("AI-generated", _yes_no(options.is_aigc)),
            ("Declaration accepted", declaration),
        ]
        return PublishCheck(problems, summary)

    # --- Preflight (reads allowed, no publishing effects) ----------------------

    def prepare(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PreparedPublication:
        """Local rules again, the real file digest and a fresh Creator Info read,
        right before the upload. Nothing is initialized here."""
        content = _content_of(session, publication)
        if content is None or content.media_type != MediaType.VIDEO:
            raise AppError(409, "tiktok_video_required", PHOTOS_UNSUPPORTED_MESSAGE)
        problems = connection_problems(get_connection(session, publication.account_id))
        state = review_state(session, publication, content, ctx.storage, self.settings)
        problems.extend(state.problems)
        if problems or state.plan is None or state.video.summary is None:
            first = problems[0] if problems else None
            raise AppError(
                first.status_code if first else 409,
                first.code if first else "tiktok_video_incompatible",
                first.message if first else UNEXPECTED_MESSAGE,
            )
        path = ctx.storage.resolve(content.storage_path)
        # The bytes on disk must still be the ones consented to (research §6).
        try:
            digest = file_sha256(path)
        except OSError:
            raise AppError(
                409, "media_unavailable", "The video file is not available."
            ) from None
        if digest != content.checksum:
            raise AppError(409, "tiktok_video_changed", VIDEO_CHANGED_MESSAGE)
        info = self._creator_info(session, publication.account_id)
        self._check_creator(info, state)
        options = state.options
        info_sent = post_info(options, state.caption)
        source = source_info(state.plan)
        payload = TikTokPayload(
            account_id=publication.account_id,
            post_info=info_sent,
            source_info=source,
            plan=state.plan,
            content_type=video_mime(content.media_format),
            checksum=content.checksum,
        )
        assert options.consented_at is not None
        submitted: dict[str, Any] = {
            "caption": state.caption,
            "post_info": info_sent,
            "source_info": source,
            "file_name": content.original_filename,
            "file_size": content.size_bytes,
            "content_type": payload.content_type,
            "creator_nickname": info.nickname,
            "max_video_post_duration_sec": info.max_video_post_duration_sec,
            "delegated_checks": list(state.video.delegated_checks),
            "declaration_version": state.declaration.version,
            "consented_at": options.consented_at.isoformat(),
        }
        return PreparedPublication(
            publication_id=publication.id,
            file_path=path,
            total_bytes=content.size_bytes,
            submitted=submitted,
            payload=payload,
        )

    def _creator_info(self, session: Session, account_id: int) -> CreatorInfo:
        try:
            return read_creator_info(
                session,
                self.credential_store,
                self.gateway,
                account_id,
                retry_wait=self.settings.creator_info_retry_wait,
                sleep=self.settings.sleep,
            )
        except TikTokPostRejected as error:
            raise AppError(
                409,
                "tiktok_creator_cannot_post",
                CREATOR_MESSAGES.get(error.code, CREATOR_BLOCKED_MESSAGE),
            ) from None

    @staticmethod
    def _check_creator(info: CreatorInfo, state: ReviewState) -> None:
        """The most recent Creator Info rules; saved options are never changed."""
        options = state.options
        if (
            options.privacy_level not in info.privacy_level_options
            or UNAUDITED_PRIVACY_LEVEL not in info.privacy_level_options
        ):
            raise AppError(
                409, "tiktok_privacy_unavailable", PRIVACY_UNAVAILABLE_MESSAGE
            )
        for name, allowed, disabled in (
            ("Comments", options.allow_comment, info.comment_disabled),
            ("Duet", options.allow_duet, info.duet_disabled),
            ("Stitch", options.allow_stitch, info.stitch_disabled),
        ):
            if allowed and disabled:
                raise AppError(
                    409,
                    "tiktok_interaction_unavailable",
                    INTERACTION_UNAVAILABLE_MESSAGE.format(name=name),
                )
        assert state.video.summary is not None
        too_long = duration_problems(
            state.video.summary.duration_seconds, info.max_video_post_duration_sec
        )
        if too_long:
            raise AppError(409, too_long[0].code, too_long[0].message)

    # --- Execution -------------------------------------------------------------

    def _update_run(self, ctx: PublishContext, attempt_id: int, **values: Any) -> bool:
        values["updated_at"] = self.settings.clock()
        try:
            with ctx.session_factory() as session:
                run = session.get_one(TikTokPublishRun, attempt_id)
                for key, value in values.items():
                    setattr(run, key, value)
                session.commit()
        except SQLAlchemyError:
            logger.warning("Could not save the TikTok run of attempt %s.", attempt_id)
            return False
        return True

    def _create_run(
        self, ctx: PublishContext, attempt_id: int, publication_id: int, plan: ChunkPlan
    ) -> None:
        now = self.settings.clock()
        with ctx.session_factory() as session:
            session.add(
                TikTokPublishRun(
                    attempt_id=attempt_id,
                    publication_id=publication_id,
                    phase=TikTokPublishPhase.PREPARING,
                    video_size=plan.video_size,
                    chunk_size=plan.chunk_size,
                    total_chunk_count=plan.total_chunk_count,
                    confirmed_bytes=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

    def _token(self, ctx: PublishContext, account_id: int) -> str:
        """A fresh token for `video/init/`; credential problems are determined."""
        try:
            with ctx.session_factory() as session:
                credential = get_valid_credentials(
                    session, self.credential_store, self.gateway, account_id
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

    def _mark_reconnect(
        self, ctx: PublishContext, account_id: int, error: TikTokError
    ) -> None:
        """Feature 012 decides what reconnecting means; never a temporary error."""
        try:
            with ctx.session_factory() as session:
                if isinstance(error, TikTokScopeMissing):
                    mark_scope_not_authorized(
                        session, account_id, "video.publish", self.gateway.clock()
                    )
                    return
                connection = get_connection(session, account_id)
                if connection is not None:
                    mark_reconnect_required(session, connection, self.gateway.clock())
        except SQLAlchemyError:
            logger.warning(
                "Could not mark TikTok account %s for reconnection.", account_id
            )

    def _failure(
        self,
        ctx: PublishContext,
        payload: TikTokPayload,
        error: TikTokError,
        phase: CallPhase,
    ) -> PublishFailure:
        mapping = map_gateway_error(error, phase)
        if mapping.reconnect:
            self._mark_reconnect(ctx, payload.account_id, error)
        if error.log_id:
            logger.info("TikTok %s failed (log_id %s).", phase.value, error.log_id)
        return PublishFailure(
            mapping.code, mapping.message, determined=mapping.determined
        )

    def _wait(self, seconds: float, reporter: ProgressReporter) -> bool:
        """Sleep in short slices; False when the application is shutting down."""
        remaining = seconds
        while remaining > 0:
            if reporter.should_stop():
                return False
            step = min(self.settings.sleep_slice, remaining)
            self.settings.sleep(step)
            remaining -= step
        return not reporter.should_stop()

    def upload(
        self,
        prepared: PreparedPublication,
        reporter: ProgressReporter,
        ctx: PublishContext,
    ) -> PublishOutcome:
        payload = prepared.payload
        assert isinstance(payload, TikTokPayload)
        assert prepared.file_path is not None
        attempt_id = reporter.attempt_id
        self._create_run(ctx, attempt_id, prepared.publication_id, payload.plan)
        try:
            return self._run(ctx, attempt_id, prepared.file_path, payload, reporter)
        except BaseException:
            self._update_run(ctx, attempt_id, phase=TikTokPublishPhase.FAILED)
            raise

    def _run(
        self,
        ctx: PublishContext,
        attempt_id: int,
        path: Path,
        payload: TikTokPayload,
        reporter: ProgressReporter,
    ) -> PublishOutcome:
        token = self._token(ctx, payload.account_id)
        self._update_run(ctx, attempt_id, phase=TikTokPublishPhase.INITIALIZING)
        # The only `video/init/` of this attempt: never repeated (research §13).
        try:
            init = self.gateway.init_video_post(
                token, payload.post_info, payload.source_info
            )
        except TikTokError as error:
            raise self._failure(ctx, payload, error, CallPhase.INIT) from None
        initialized = self.settings.clock()
        # The upload URL is valid one hour: the last chunk is only sent before this.
        deadline = initialized + self.settings.upload_deadline
        if not self._update_run(
            ctx,
            attempt_id,
            publish_id=init.publish_id,
            initialized_at=initialized,
            phase=TikTokPublishPhase.UPLOADING,
        ):
            # Without the publish_id on record, nothing is ever sent.
            raise PublishFailure(
                "internal_error", WRITE_AHEAD_FAILED_MESSAGE, determined=True
            )
        reporter.report_bytes(0)
        plan = payload.plan
        digest = UploadDigest()
        with path.open("rb") as file:
            for index in range(plan.total_chunk_count - 1):
                data = self._read_chunk(file, plan, index)
                digest.update(data)
                self._send_chunk(
                    ctx,
                    attempt_id,
                    init.upload_url,
                    data,
                    plan,
                    index,
                    payload,
                    reporter,
                    deadline,
                )
            last_index = plan.total_chunk_count - 1
            data = self._read_chunk(file, plan, last_index)
            grown = file.read(1)
        digest.update(data)
        if grown or digest.hexdigest() != payload.checksum:
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
        if not reporter.enter_final_chunk() or not self._update_run(
            ctx,
            attempt_id,
            phase=TikTokPublishPhase.FINAL_CHUNK,
            final_chunk_started_at=started,
        ):
            raise PublishFailure(
                "internal_error", WRITE_AHEAD_FAILED_MESSAGE, determined=True
            )
        status = self._send_last_chunk(attempt_id, init.upload_url, data, plan, payload)
        del data
        # Whatever the answer, only the status of this publish_id decides now.
        reporter.enter_finalizing()
        values: dict[str, Any] = {
            "phase": TikTokPublishPhase.PROCESSING,
            "final_chunk_http_status": status,
        }
        if status == 201:
            values["confirmed_bytes"] = plan.video_size
        self._update_run(ctx, attempt_id, **values)
        if status == 201:
            reporter.report_bytes(plan.video_size, confirmed=True)
        return self._poll(
            ctx, attempt_id, payload, init.publish_id, started, reporter, status
        )

    @staticmethod
    def _read_chunk(file: Any, plan: ChunkPlan, index: int) -> bytes:
        """One chunk buffer read once from the original file, in order."""
        first, last = plan.chunk_range(index)
        data = bytes(file.read(last - first + 1))
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
        ctx: PublishContext,
        attempt_id: int,
        upload_url: UploadUrl,
        data: bytes,
        plan: ChunkPlan,
        index: int,
        payload: TikTokPayload,
        reporter: ProgressReporter,
        deadline: datetime,
    ) -> None:
        """An intermediate chunk, retried on the same buffer after a temporary
        failure (research §11) and accepted after a `416` only when TikTok's
        `Content-Range` says it accepted exactly the bytes up to this chunk's end
        (§12). Before the write-ahead every failure is determined."""
        first, last = plan.chunk_range(index)
        waits = self.settings.chunk_retry_waits
        for try_number in range(len(waits) + 1):
            if reporter.should_stop():
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
                    payload.content_type,
                )
            except TikTokUploadRangeMismatch as error:
                if not _confirms_chunk(error.progress, last, plan.video_size):
                    raise self._failure(ctx, payload, error, CallPhase.CHUNK) from None
                break  # TikTok already holds exactly this chunk.
            except TikTokError as error:
                mapping = map_gateway_error(error, CallPhase.CHUNK)
                if mapping.retry != RetryPolicy.CHUNK_RETRIES or try_number == len(
                    waits
                ):
                    raise self._failure(ctx, payload, error, CallPhase.CHUNK) from None
                logger.info(
                    "TikTok chunk %s of attempt %s failed (%s); retrying.",
                    index + 1,
                    attempt_id,
                    type(error).__name__,
                )
                if not self._wait(waits[try_number], reporter):
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
        self._update_run(ctx, attempt_id, confirmed_bytes=last + 1)
        reporter.report_bytes(last + 1, confirmed=True)

    def _send_last_chunk(
        self,
        attempt_id: int,
        upload_url: UploadUrl,
        data: bytes,
        plan: ChunkPlan,
        payload: TikTokPayload,
    ) -> int | None:
        """The irreversible request, sent exactly once and never retried. Its HTTP
        status is only kept for diagnosis (None without an answer)."""
        first, last = plan.chunk_range(plan.total_chunk_count - 1)
        try:
            result = self.gateway.upload_chunk(
                upload_url, data, first, last, plan.video_size, payload.content_type
            )
        except TikTokError as error:
            logger.warning(
                "The last TikTok chunk of attempt %s was not confirmed (%s); only "
                "the status of the same post is read.",
                attempt_id,
                type(error).__name__,
            )
            return error.http_status
        return result.status

    def _read_status(
        self, ctx: PublishContext, account_id: int, publish_id: str
    ) -> PublishStatus:
        with ctx.session_factory() as session:
            return call_with_token(
                session,
                self.credential_store,
                self.gateway,
                account_id,
                lambda token: self.gateway.fetch_publish_status(token, publish_id),
            )

    @staticmethod
    def _unresolved(
        last_status: str | None, final_status: int | None = 201
    ) -> PublishFailure:
        """An outcome only TikTok's status could settle. The answer to the last
        chunk is only a diagnosis: it never makes the result determined."""
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
        return PublishFailure(
            "tiktok_result_uncertain", message[:500], determined=False
        )

    def _poll(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: TikTokPayload,
        publish_id: str,
        started: datetime,
        reporter: ProgressReporter,
        final_status: int | None = 201,
    ) -> PublishOutcome:
        """Bounded status reads of the original publish_id (research §15). Only
        `PUBLISH_COMPLETE` is a success and only `FAILED` is determined."""
        settings = self.settings
        deadline = started + settings.processing_timeout
        waits = iter(settings.status_waits)
        wait = settings.status_first_wait
        last_status: str | None = None
        reads = 0
        while True:
            if settings.clock() + timedelta(seconds=wait) > deadline:
                raise self._unresolved(last_status, final_status)
            if not self._wait(wait, reporter):
                raise self._unresolved(last_status, final_status)
            wait = next(waits, settings.status_interval)
            reads += 1
            try:
                status = self._read_status(ctx, payload.account_id, publish_id)
            except TikTokUnavailable as error:
                if error.rate_limited:
                    wait = min(wait * 2, settings.rate_limited_wait_cap)
                continue
            except TikTokScopeMissing as error:
                self._mark_reconnect(ctx, payload.account_id, error)
                raise self._unresolved(None, final_status) from None
            except TikTokPostRejected:
                raise self._unresolved(None, final_status) from None
            except TikTokError:
                continue
            except AppError as error:
                if error.code in STOP_POLLING_CODES:
                    raise self._unresolved(None, final_status) from None
                continue
            elapsed = (settings.clock() - started).total_seconds()
            logger.info(
                "TikTok status of attempt %s, read %s after %.0f s: %s.",
                attempt_id,
                reads,
                elapsed,
                status.status,
            )
            known = status.status in (PROCESSING_UPLOAD, PUBLISH_COMPLETE, FAILED)
            self._update_run(
                ctx,
                attempt_id,
                last_remote_status=status.status if known else UNEXPECTED_STATUS,
                remote_uploaded_bytes=status.uploaded_bytes,
                fail_reason=status.fail_reason,
                last_status_at=settings.clock(),
            )
            if status.status == PROCESSING_UPLOAD:
                last_status = PROCESSING_UPLOAD
                continue
            if status.status == PUBLISH_COMPLETE:
                self._update_run(ctx, attempt_id, phase=TikTokPublishPhase.SUCCEEDED)
                return self._outcome(status)
            if status.status == FAILED:
                mapping = map_fail_reason(status.fail_reason)
                if mapping.reconnect:
                    self._mark_reconnect(ctx, payload.account_id, TikTokTokenInvalid())
                raise PublishFailure(mapping.code, mapping.message, determined=True)
            # Statuses of other flows or unknown ones are never a success.
            raise self._unresolved(None, final_status)

    @staticmethod
    def _outcome(status: PublishStatus) -> PublishOutcome:
        """A public post ID only when TikTok returns exactly one; never a link."""
        if len(status.post_ids) == 1:
            return PublishOutcome(
                external_id=str(status.post_ids[0]), external_url=None
            )
        return PublishOutcome(
            external_id=None,
            external_url=None,
            warnings=[
                {
                    "code": "tiktok_private_post_no_link",
                    "message": PRIVATE_POST_NO_LINK_MESSAGE,
                }
            ],
        )

    def refresh_details(
        self,
        prepared: PreparedPublication,
        outcome: PublishOutcome,
        ctx: PublishContext,
    ) -> PublishOutcome:
        """Nothing to refine: posts are never listed for a link."""
        return outcome

    def release(
        self,
        prepared: PreparedPublication,
        ctx: PublishContext,
        *,
        attempt_id: int,
        succeeded: bool,
    ) -> list[dict[str, str]]:
        """No temporary resources exist: the original file is uploaded directly."""
        return []

    # --- Reconciliation ---------------------------------------------------------

    def reconcile(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> Reconciliation | ReconciledFailure | None:
        """One status read of the original publish_id of an attempt that reached
        the write-ahead (research §17): `PUBLISH_COMPLETE` settles it as published,
        `FAILED` as a confirmed failure; anything else keeps it uncertain. Never
        initializes, uploads nor lists posts."""
        run = session.get(TikTokPublishRun, attempt.id)
        if run is None or run.publish_id is None or run.final_chunk_started_at is None:
            return None
        publish_id = run.publish_id
        status = call_with_token(
            session,
            self.credential_store,
            self.gateway,
            publication.account_id,
            lambda token: self.gateway.fetch_publish_status(token, publish_id),
        )
        now = self.settings.clock()
        if status.status == PUBLISH_COMPLETE:
            run.phase = TikTokPublishPhase.SUCCEEDED
            run.last_remote_status = PUBLISH_COMPLETE
            run.last_status_at = now
            run.updated_at = now
            return Reconciliation(
                published_at=run.final_chunk_started_at,
                outcome=self._outcome(status),
            )
        if status.status == FAILED:
            mapping = map_fail_reason(status.fail_reason)
            if mapping.reconnect:
                connection = get_connection(session, publication.account_id)
                if connection is not None:
                    mark_reconnect_required(session, connection, now)
            run.phase = TikTokPublishPhase.FAILED
            run.last_remote_status = FAILED
            run.fail_reason = status.fail_reason
            run.last_status_at = now
            run.updated_at = now
            return ReconciledFailure(mapping.code, mapping.message)
        return None
