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
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.content_files import EffectiveFile, effective_checksum, effective_size
from app.contents import StorageDep
from app.credential_store import CredentialStore
from app.db import get_session
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
    TikTokMode,
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
    UserActionCompleted,
    UserActionFailed,
    check_publish_file,
    prepare_publish_file,
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
    TikTokModeAvailabilityRead,
    TikTokPublicationOptionsRead,
    TikTokPublicationOptionsWrite,
    TikTokVideoSummaryRead,
)
from app.storage import MediaStorage
from app.tiktok_connections import (
    call_with_token,
    get_connection,
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
    TikTokUnavailable,
)
from app.tiktok_inbox import (
    INBOX_PERMISSION_MISSING_MESSAGE,
    SEND_TO_USER_INBOX,
    delivered_outcome,
    inbox_follow_up,
    inbox_problems,
    inbox_status_interpreter,
    map_inbox_fail_reason,
    map_inbox_gateway_error,
)
from app.tiktok_media import (
    MEDIA_UNAVAILABLE_MESSAGE,
    PHOTOS_UNSUPPORTED_MESSAGE,
    SELF_ONLY,
    TIKTOK_CAPTION_MAX,
    ChunkPlan,
    Declaration,
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
from app.tiktok_transfer import (
    CREATOR_MESSAGES,
    FAILED,
    PROCESSING_UPLOAD,
    PUBLISH_COMPLETE,
    RATE_LIMITED_MESSAGE,
    RECONNECT_MESSAGE,
    UNAVAILABLE_MESSAGE,
    UNEXPECTED_MESSAGE,
    FileUploadTransfer,
    StatusDecision,
    TransferFile,
)

# Re-exported: the error taxonomy and the settings moved to `tiktok_transfer`.
from app.tiktok_transfer import CallPhase as CallPhase
from app.tiktok_transfer import RetryPolicy as RetryPolicy
from app.tiktok_transfer import TikTokErrorMapping as TikTokErrorMapping
from app.tiktok_transfer import TikTokPublishSettings as TikTokPublishSettings
from app.tiktok_transfer import _confirms_chunk as _confirms_chunk
from app.tiktok_transfer import map_fail_reason as map_fail_reason
from app.tiktok_transfer import map_gateway_error as map_gateway_error

logger = logging.getLogger(__name__)

# The current TikTok app is not audited (research §4): only private posts. Enabling
# public posting needs TikTok's audit, another specification and new tests; this is
# deliberately not configurable.
CLIENT_AUDITED = False
UNAUDITED_PRIVACY_LEVEL = SELF_ONLY


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
MODE_REQUIRED_MESSAGE = "Choose how to send this video to TikTok."
CONSENT_NOT_APPLICABLE_MESSAGE = (
    "Upload to Inbox needs no declaration: you finish the post in TikTok."
)
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
        mode=None,
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


def _inspect_effective(storage: MediaStorage, content: Content) -> VideoCheck:
    """The TikTok video rules on the file really sent (original or clean copy)."""
    effective, problem = check_publish_file(storage, content, MEDIA_UNAVAILABLE_MESSAGE)
    if effective is None:
        assert problem is not None
        return VideoCheck([problem])
    return inspect_video(content, effective.path, effective.size)


def review_state(
    session: Session,
    publication: Publication,
    content: Content,
    storage: MediaStorage,
    settings: "TikTokPublishSettings",
    store: CredentialStore,
) -> ReviewState:
    """Local review of a TikTok publication: the consent fingerprint uses the
    effective checksum (original or clean copy); the effective file is only stat-ed
    and inspected (never hashed here). Upload to Inbox only needs the
    `video.upload` capability and a valid video: the post itself is finished in
    TikTok."""
    connection = get_connection(session, publication.account_id)
    options = get_options(session, publication.id)
    caption = build_caption(publication, content)
    video = _inspect_effective(storage, content)
    plan = None
    if video.summary is not None:
        try:
            plan = plan_chunks(
                effective_size(content), settings.single_chunk_max, settings.chunk_size
            )
        except ValueError:
            plan = None
    declaration = declaration_for(options)
    fingerprint = (
        consent_fingerprint(
            open_id=connection.open_id,
            video_sha256=effective_checksum(content),
            caption=caption,
            options=options,
        )
        if connection is not None
        else None
    )
    consent = consent_state(options, fingerprint, declaration)
    problems = list(video.problems)
    if options.mode != TikTokMode.DIRECT_POST:
        if options.mode is None:
            # Nothing else can be reviewed before the user chooses how to send it.
            problems.append(mode_required_problem())
        else:
            problems.extend(inbox_problems(store, connection))
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


def mode_required_problem() -> PublishProblem:
    return PublishProblem("tiktok_mode_required", MODE_REQUIRED_MESSAGE, "mode")


def mode_availability(
    store: CredentialStore, connection: TikTokConnection | None
) -> dict[str, TikTokModeAvailabilityRead]:
    """Which modes can be chosen. Upload to Inbox needs `video.upload`, known only
    once connected; connection problems are reported separately."""
    inbox = not inbox_problems(store, connection)
    return {
        TikTokMode.DIRECT_POST: TikTokModeAvailabilityRead(available=True, reason=None),
        TikTokMode.INBOX_UPLOAD: TikTokModeAvailabilityRead(
            available=inbox,
            reason=None if inbox else INBOX_PERMISSION_MISSING_MESSAGE,
        ),
    }


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
    store: CredentialStore,
) -> TikTokPublicationOptionsRead:
    state = review_state(session, publication, content, storage, settings, store)
    options = state.options
    summary = state.video.summary
    return TikTokPublicationOptionsRead(
        mode=options.mode,  # type: ignore[arg-type]
        modes=mode_availability(store, state.connection),  # type: ignore[arg-type]
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
    store: StoreDep,
) -> TikTokPublicationOptionsRead:
    """Options, exact caption, declaration, consent state and local problems; no
    network."""
    publication, content = _tiktok_publication(session, publication_id)
    return options_to_read(session, publication, content, storage, settings, store)


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
    store: StoreDep,
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
    options.mode = body.mode
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
    return options_to_read(session, publication, content, storage, settings, store)


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
    store: StoreDep,
) -> TikTokPublicationOptionsRead:
    """Record that the user accepted the declaration for exactly what they
    reviewed: the fingerprint is recomputed here and must match."""
    publication, content = _tiktok_publication(session, publication_id)
    ensure_editable(publication)
    if get_options(session, publication_id).mode == TikTokMode.INBOX_UPLOAD:
        raise AppError(
            409, "tiktok_consent_not_applicable", CONSENT_NOT_APPLICABLE_MESSAGE
        )
    problems = connection_problems(get_connection(session, publication.account_id))
    if problems:
        raise AppError(409, problems[0].code, problems[0].message)
    state = review_state(session, publication, content, storage, settings, store)
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
    return options_to_read(session, publication, content, storage, settings, store)


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
    video = _inspect_effective(storage, content)
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
PRIVACY_UNAVAILABLE_MESSAGE = (
    "TikTok no longer offers the chosen privacy for this account (this app can "
    "only post with 'Only me'). Review the TikTok options; nothing was sent to "
    "TikTok."
)
INTERACTION_UNAVAILABLE_MESSAGE = (
    "{name} is now turned off in this TikTok account's settings. Review the TikTok "
    "options; nothing was sent to TikTok."
)
PRIVATE_POST_NO_LINK_MESSAGE = (
    "TikTok does not return a link for private posts. Open your TikTok profile to "
    "see the video; it may take a few minutes to appear."
)


@dataclass(frozen=True)
class TikTokPayload:
    """What the core treats as an opaque payload. Contains no secrets."""

    account_id: int
    mode: TikTokMode
    # None in Upload to Inbox: the user finishes the post in TikTok.
    post_info: dict[str, Any] | None
    source_info: dict[str, Any]
    plan: ChunkPlan
    content_type: str
    # The effective checksum (original or clean copy): the digest consented to.
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
        """Auto-publish needs a mode and, for Direct Post, complete options, a
        valid caption and a consent for exactly the current content (research
        §20); Upload to Inbox only needs `video.upload`. Local only: the scheduler
        rechecks everything (Creator Info included for Direct Post) when it
        runs."""
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
        if options.mode is None:
            return [
                PublishProblem(
                    "tiktok_mode_required", f"{who}: {MODE_REQUIRED_MESSAGE}"
                )
            ]
        if options.mode == TikTokMode.INBOX_UPLOAD:
            # No post settings nor consent: only the capability is needed.
            connection = get_connection(session, publication.account_id)
            return [
                PublishProblem(problem.code, f"{who}: {problem.message}")
                for problem in inbox_problems(self.credential_store, connection)
            ]
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
                video_sha256=effective_checksum(content),
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
        """Every local rule, with the effective checksum for the consent: never
        reads the network nor hashes the file."""
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
        state = review_state(
            session,
            publication,
            content,
            ctx.storage,
            self.settings,
            self.credential_store,
        )
        problems.extend(state.problems)
        options = state.options
        file_label = (
            f"{content.original_filename} "
            f"({effective_size(content) / 1_000_000:.1f} MB)"
        )
        if options.mode != TikTokMode.DIRECT_POST:
            summary.append(("File", file_label))
            if options.mode == TikTokMode.INBOX_UPLOAD:
                summary.append(("Send", "Upload to your TikTok inbox"))
            return PublishCheck(problems, summary)
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
            ("File", file_label),
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
        """Local rules again, the real file digest and (Direct Post only) a fresh
        Creator Info read, right before the upload. Nothing is initialized here."""
        content = _content_of(session, publication)
        if content is None or content.media_type != MediaType.VIDEO:
            raise AppError(409, "tiktok_video_required", PHOTOS_UNSUPPORTED_MESSAGE)
        problems = connection_problems(get_connection(session, publication.account_id))
        state = review_state(
            session,
            publication,
            content,
            ctx.storage,
            self.settings,
            self.credential_store,
        )
        problems.extend(state.problems)
        if problems or state.plan is None or state.video.summary is None:
            first = problems[0] if problems else None
            raise AppError(
                first.status_code if first else 409,
                first.code if first else "tiktok_video_incompatible",
                first.message if first else UNEXPECTED_MESSAGE,
            )
        if state.options.mode == TikTokMode.INBOX_UPLOAD:
            return self._prepare_inbox(
                publication, content, state, self._verified_file(ctx, content)
            )
        info = self._creator_info(session, publication.account_id)
        self._check_creator(info, state)
        # Last local step, after the network preflight (research §3).
        effective = self._verified_file(ctx, content)
        options = state.options
        info_sent = post_info(options, state.caption)
        source = source_info(state.plan)
        payload = TikTokPayload(
            account_id=publication.account_id,
            mode=TikTokMode.DIRECT_POST,
            post_info=info_sent,
            source_info=source,
            plan=state.plan,
            content_type=video_mime(content.media_format),
            checksum=effective.checksum,
        )
        assert options.consented_at is not None
        submitted: dict[str, Any] = {
            "caption": state.caption,
            "post_info": info_sent,
            "source_info": source,
            "file_name": content.original_filename,
            "file_size": effective.size,
            "content_type": payload.content_type,
            "creator_nickname": info.nickname,
            "max_video_post_duration_sec": info.max_video_post_duration_sec,
            "delegated_checks": list(state.video.delegated_checks),
            "declaration_version": state.declaration.version,
            "consented_at": options.consented_at.isoformat(),
        }
        return PreparedPublication(
            publication_id=publication.id,
            file_path=effective.path,
            total_bytes=effective.size,
            submitted=submitted,
            payload=payload,
            file_checksum=effective.checksum,
        )

    @staticmethod
    def _verified_file(ctx: PublishContext, content: Content) -> EffectiveFile:
        """The effective file with its bytes verified in a single read: the
        resolver hashes a clean copy (`media_corrupt`); an original must still be
        the bytes consented to (research §6, `tiktok_video_changed`)."""
        effective = prepare_publish_file(
            ctx, content, "The video file is not available."
        )
        if not effective.clean_copy:
            try:
                digest = file_sha256(effective.path)
            except OSError:
                raise AppError(
                    409, "media_unavailable", "The video file is not available."
                ) from None
            if digest != effective.checksum:
                raise AppError(409, "tiktok_video_changed", VIDEO_CHANGED_MESSAGE)
        return effective

    @staticmethod
    def _prepare_inbox(
        publication: Publication,
        content: Content,
        state: ReviewState,
        effective: EffectiveFile,
    ) -> PreparedPublication:
        """Upload to Inbox sends the video only: no caption nor post settings."""
        assert state.plan is not None and state.video.summary is not None
        source = source_info(state.plan)
        video = state.video.summary
        payload = TikTokPayload(
            account_id=publication.account_id,
            mode=TikTokMode.INBOX_UPLOAD,
            post_info=None,
            source_info=source,
            plan=state.plan,
            content_type=video_mime(content.media_format),
            checksum=effective.checksum,
        )
        submitted: dict[str, Any] = {
            "mode": TikTokMode.INBOX_UPLOAD.value,
            "source_info": source,
            "video": {
                "file_name": content.original_filename,
                "content_type": payload.content_type,
                "format": video.format,
                "size_bytes": video.size_bytes,
                "duration_seconds": video.duration_seconds,
                "width": video.width,
                "height": video.height,
                "frame_rate": video.frame_rate,
                "delegated_checks": list(state.video.delegated_checks),
            },
        }
        return PreparedPublication(
            publication_id=publication.id,
            file_path=effective.path,
            total_bytes=effective.size,
            submitted=submitted,
            payload=payload,
            file_checksum=effective.checksum,
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
        self,
        ctx: PublishContext,
        attempt_id: int,
        publication_id: int,
        plan: ChunkPlan,
        mode: TikTokMode,
    ) -> None:
        now = self.settings.clock()
        with ctx.session_factory() as session:
            session.add(
                TikTokPublishRun(
                    attempt_id=attempt_id,
                    publication_id=publication_id,
                    mode=mode,
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
        if payload.mode == TikTokMode.INBOX_UPLOAD:
            mapping = map_inbox_gateway_error(error, phase)
        else:
            mapping = map_gateway_error(error, phase)
        if mapping.reconnect:
            self._mark_reconnect(ctx, payload.account_id, error)
        if error.log_id:
            logger.info("TikTok %s failed (log_id %s).", phase.value, error.log_id)
        return PublishFailure(
            mapping.code, mapping.message, determined=mapping.determined
        )

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
        self._create_run(
            ctx, attempt_id, prepared.publication_id, payload.plan, payload.mode
        )
        transfer = FileUploadTransfer(
            gateway=self.gateway,
            credential_store=self.credential_store,
            settings=self.settings,
            ctx=ctx,
            account_id=payload.account_id,
            attempt_id=attempt_id,
            reporter=reporter,
            update_run=self._update_run,
            failure=lambda error, phase: self._failure(ctx, payload, error, phase),
            reconnect=lambda error: self._mark_reconnect(
                ctx, payload.account_id, error
            ),
        )
        file = TransferFile(
            path=prepared.file_path,
            plan=payload.plan,
            content_type=payload.content_type,
            checksum=payload.checksum,
        )
        try:
            if payload.mode == TikTokMode.INBOX_UPLOAD:
                return transfer.run(
                    file,
                    lambda token: self.gateway.init_inbox_video(
                        token, payload.source_info
                    ),
                    inbox_status_interpreter(self.settings.clock),
                )
            post = payload.post_info
            assert post is not None
            return transfer.run(
                file,
                lambda token: self.gateway.init_video_post(
                    token, post, payload.source_info
                ),
                self._interpret_status,
            )
        except BaseException:
            self._update_run(ctx, attempt_id, phase=TikTokPublishPhase.FAILED)
            raise

    def _interpret_status(self, status: PublishStatus) -> StatusDecision:
        """Direct Post: only `PUBLISH_COMPLETE` is a success."""
        if status.status == PROCESSING_UPLOAD:
            return StatusDecision("keep_polling")
        if status.status == PUBLISH_COMPLETE:
            return StatusDecision(
                "done",
                outcome=self._outcome(status),
                run_values={"phase": TikTokPublishPhase.SUCCEEDED},
            )
        if status.status == FAILED:
            return StatusDecision("failed", mapping=map_fail_reason(status.fail_reason))
        return StatusDecision("unresolved", known=False)

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

    def follow_up(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> UserActionCompleted | UserActionFailed | None:
        """Check status of an Upload to Inbox delivered to the inbox."""
        return inbox_follow_up(
            session,
            self.credential_store,
            self.gateway,
            publication,
            attempt,
            self.settings.clock,
        )

    def reconcile(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> Reconciliation | ReconciledFailure | None:
        """One status read of the original publish_id of an attempt that reached
        the write-ahead (research §17): `PUBLISH_COMPLETE` settles it as published,
        `FAILED` as a confirmed failure and, in Upload to Inbox only,
        `SEND_TO_USER_INBOX` as delivered (awaiting the user); anything else keeps
        it uncertain. Never initializes, uploads nor lists posts."""
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
        inbox = run.mode == TikTokMode.INBOX_UPLOAD
        if inbox and status.status == SEND_TO_USER_INBOX:
            run.phase = TikTokPublishPhase.DELIVERED
            run.last_remote_status = SEND_TO_USER_INBOX
            run.delivered_to_inbox_at = now
            run.last_status_at = now
            run.updated_at = now
            return Reconciliation(published_at=None, outcome=delivered_outcome())
        if status.status == PUBLISH_COMPLETE:
            run.phase = TikTokPublishPhase.SUCCEEDED
            run.last_remote_status = PUBLISH_COMPLETE
            run.last_status_at = now
            run.updated_at = now
            if inbox:
                # Published by the user in TikTok: never a post identity.
                run.user_published_at = now
                if status.post_ids:
                    run.public_post_count = len(status.post_ids)
                return Reconciliation(
                    published_at=now,
                    outcome=PublishOutcome(
                        external_id=None,
                        external_url=None,
                        details={"tiktok_mode": TikTokMode.INBOX_UPLOAD.value},
                    ),
                )
            return Reconciliation(
                published_at=run.final_chunk_started_at,
                outcome=self._outcome(status),
            )
        if status.status == FAILED:
            mapping = (
                map_inbox_fail_reason(status.fail_reason)
                if inbox
                else map_fail_reason(status.fail_reason)
            )
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
