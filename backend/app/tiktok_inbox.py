"""TikTok Upload to Inbox (specs/014-tiktok-inbox-upload): what TikTok's statuses
mean for a video sent to the user's inbox, its error wording and its local checks.

The video is uploaded with the shared FILE_UPLOAD transfer (`tiktok_transfer`);
`SEND_TO_USER_INBOX` ends the execution: the publication then awaits the user, who
finishes the post in TikTok's editor. The status is never polled after that.
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.credential_store import CredentialStore
from app.db import get_session
from app.errors import AppError, ConflictError
from app.models import (
    Account,
    AttemptStage,
    AttemptStatus,
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
from app.publications import get_publication_or_404
from app.publishing import (
    PublishOutcome,
    PublishProblem,
    UserActionCompleted,
    UserActionFailed,
)
from app.schemas import TikTokDeliveryFailureRead, TikTokDeliveryRead
from app.tiktok_connections import (
    call_with_token,
    can_upload_to_inbox,
    get_connection,
    mark_reconnect_required,
)
from app.tiktok_gateway import (
    PublishStatus,
    TikTokError,
    TikTokGateway,
    TikTokPostRejected,
    TikTokScopeMissing,
    TikTokUnavailable,
)
from app.tiktok_transfer import (
    FAILED,
    NOT_PUBLISHED,
    PROCESSING_UPLOAD,
    PUBLISH_COMPLETE,
    RATE_LIMITED_MESSAGE,
    RECONNECT_MESSAGE,
    UNEXPECTED_STATUS,
    CallPhase,
    RetryPolicy,
    StatusDecision,
    TikTokErrorMapping,
    map_fail_reason,
    map_gateway_error,
)

logger = logging.getLogger(__name__)

SEND_TO_USER_INBOX = "SEND_TO_USER_INBOX"

INBOX_PERMISSION_MISSING_MESSAGE = (
    "Upload to Inbox needs the video.upload permission. Reconnect the TikTok account."
)
READY_INSTRUCTION = "Open your TikTok inbox to review, edit and publish the video."
CHECK_UNAVAILABLE_MESSAGE = (
    "Could not reach TikTok to check this video. Nothing changed; try again later."
)
CHECK_RATE_LIMITED_MESSAGE = RATE_LIMITED_MESSAGE.replace(
    "Nothing was published.", "Nothing changed."
)
STATUS_UNAVAILABLE_MESSAGE = (
    "The connected TikTok account cannot check this upload (it may have been sent "
    "with another account). Nothing changed."
)
CHECK_UNEXPECTED_MESSAGE = (
    "TikTok returned an answer AutoPublisher does not understand. Nothing changed."
)
# Details of every Upload to Inbox attempt delivered to the inbox (contracts §5).
DELIVERED_DETAILS = {"tiktok_mode": "INBOX_UPLOAD", "delivered_to_inbox": True}


def inbox_problems(
    store: CredentialStore, connection: TikTokConnection | None
) -> list[PublishProblem]:
    """Upload to Inbox needs `video.upload`; without it only this mode is
    unavailable (connection problems are reported separately)."""
    if (
        connection is None
        or connection.status != TikTokConnectionStatus.CONNECTED
        or can_upload_to_inbox(store, connection)
    ):
        return []
    return [
        PublishProblem(
            "tiktok_upload_permission_missing", INBOX_PERMISSION_MISSING_MESSAGE, "mode"
        )
    ]


NOTHING_SENT = "Nothing was sent to TikTok."
TOO_MANY_PENDING_SHARES_MESSAGE = (
    "TikTok has too many uploads waiting for review in this account's inbox (at "
    "most 5 in 24 hours). Open TikTok, publish or discard the pending drafts, then "
    f"try again. {NOTHING_SENT}"
)
INBOX_INIT_FAILED_MESSAGE = f"TikTok rejected the upload request. {NOTHING_SENT}"


def map_inbox_gateway_error(error: TikTokError, phase: CallPhase) -> TikTokErrorMapping:
    """A gateway error of an Upload to Inbox (research §9): as in Direct Post,
    except that a missing `video.upload` never asks to reconnect the account, the
    pending-shares limit has its own code and nothing is called "published"."""
    if phase == CallPhase.INIT:
        if isinstance(error, TikTokScopeMissing):
            return TikTokErrorMapping(
                "tiktok_upload_permission_missing",
                f"{INBOX_PERMISSION_MISSING_MESSAGE} {NOTHING_SENT}",
                determined=True,
                retry=RetryPolicy.NONE,
                reconnect=False,
            )
        if isinstance(error, TikTokPostRejected):
            if error.code == "spam_risk_too_many_pending_share":
                return TikTokErrorMapping(
                    "tiktok_too_many_pending_shares",
                    TOO_MANY_PENDING_SHARES_MESSAGE,
                    determined=True,
                    retry=RetryPolicy.NONE,
                    reconnect=False,
                )
            if error.code == "invalid_param":
                return TikTokErrorMapping(
                    "tiktok_init_failed",
                    INBOX_INIT_FAILED_MESSAGE,
                    determined=True,
                    retry=RetryPolicy.NONE,
                    reconnect=False,
                )
    mapping = map_gateway_error(error, phase)
    return replace(
        mapping, message=mapping.message.replace(NOT_PUBLISHED, NOTHING_SENT)
    )


def map_inbox_fail_reason(reason: str | None) -> TikTokErrorMapping:
    """A `FAILED` status of an Upload to Inbox: as in Direct Post, worded for a
    video that was not delivered to the inbox."""
    mapping = map_fail_reason(reason)
    return replace(
        mapping,
        message=mapping.message.replace(
            "was not published", "was not delivered to your TikTok inbox"
        ),
    )


def delivered_outcome() -> PublishOutcome:
    """The video is in the user's inbox: the execution is over, the post is not."""
    return PublishOutcome(
        external_id=None,
        external_url=None,
        details=dict(DELIVERED_DETAILS),
        awaiting_user_action=True,
    )


def inbox_status_interpreter(
    clock: Callable[[], datetime],
) -> Callable[[PublishStatus], StatusDecision]:
    """How the transfer reads statuses in Upload to Inbox."""

    def interpret(status: PublishStatus) -> StatusDecision:
        if status.status == PROCESSING_UPLOAD:
            return StatusDecision("keep_polling")
        if status.status == SEND_TO_USER_INBOX:
            return StatusDecision(
                "done",
                outcome=delivered_outcome(),
                run_values={
                    "phase": TikTokPublishPhase.DELIVERED,
                    "delivered_to_inbox_at": clock(),
                },
            )
        if status.status == PUBLISH_COMPLETE:
            # The user already published it in TikTok. Several posts may come
            # from one upload: only their number is kept, never an identity.
            return StatusDecision(
                "done",
                outcome=PublishOutcome(
                    external_id=None,
                    external_url=None,
                    details={"tiktok_mode": "INBOX_UPLOAD"},
                ),
                run_values={
                    "phase": TikTokPublishPhase.SUCCEEDED,
                    "user_published_at": clock(),
                    "public_post_count": len(status.post_ids)
                    if status.post_ids
                    else None,
                },
            )
        if status.status == FAILED:
            return StatusDecision(
                "failed", mapping=map_inbox_fail_reason(status.fail_reason)
            )
        # `PROCESSING_DOWNLOAD` belongs to another flow; unknown statuses too.
        return StatusDecision("unresolved", known=False)

    return interpret


# --- Check status ---------------------------------------------------------------------


def inbox_follow_up(
    session: Session,
    store: CredentialStore,
    gateway: TikTokGateway,
    publication: Publication,
    attempt: PublicationAttempt,
    clock: Callable[[], datetime],
) -> UserActionCompleted | UserActionFailed | None:
    """One status read of the `publish_id` delivered to the inbox (research §8).
    Only the run is updated (staged in `session`); the attempt never changes.
    Errors leave everything as it was."""
    run = session.get(TikTokPublishRun, attempt.id)
    if (
        run is None
        or run.mode != TikTokMode.INBOX_UPLOAD
        or run.phase != TikTokPublishPhase.DELIVERED
        or run.publish_id is None
    ):
        raise AppError(409, "tiktok_status_unavailable", STATUS_UNAVAILABLE_MESSAGE)
    publish_id = run.publish_id
    try:
        status = call_with_token(
            session,
            store,
            gateway,
            publication.account_id,
            lambda token: gateway.fetch_publish_status(token, publish_id),
        )
    except TikTokUnavailable as error:
        if error.rate_limited:
            raise AppError(
                503, "tiktok_rate_limited", CHECK_RATE_LIMITED_MESSAGE
            ) from None
        raise AppError(503, "tiktok_unavailable", CHECK_UNAVAILABLE_MESSAGE) from None
    except TikTokPostRejected:
        raise AppError(
            409, "tiktok_status_unavailable", STATUS_UNAVAILABLE_MESSAGE
        ) from None
    except TikTokScopeMissing:
        raise AppError(409, "tiktok_reconnect_required", RECONNECT_MESSAGE) from None
    except TikTokError:
        raise AppError(
            502, "tiktok_unexpected_response", CHECK_UNEXPECTED_MESSAGE
        ) from None
    now = clock()
    known = status.status in (SEND_TO_USER_INBOX, PUBLISH_COMPLETE, FAILED)
    run.last_remote_status = status.status if known else UNEXPECTED_STATUS
    run.last_status_at = now
    run.updated_at = now
    if status.status == PUBLISH_COMPLETE:
        run.phase = TikTokPublishPhase.SUCCEEDED
        run.user_published_at = now
        if status.post_ids:
            run.public_post_count = len(status.post_ids)
        return UserActionCompleted(published_at=now)
    if status.status == FAILED:
        mapping = map_inbox_fail_reason(status.fail_reason)
        run.phase = TikTokPublishPhase.FAILED
        run.fail_reason = status.fail_reason
        if mapping.reconnect:
            connection = get_connection(session, publication.account_id)
            if connection is not None:
                mark_reconnect_required(session, connection, now)
        return UserActionFailed(mapping.code, mapping.message)
    if status.status != SEND_TO_USER_INBOX:
        logger.warning(
            "Unexpected TikTok status while checking publication %s; it keeps waiting.",
            publication.id,
        )
    return None


# --- Delivery state (no network) ------------------------------------------------------

router = APIRouter(prefix="/api", tags=["tiktok"])

SessionDep = Annotated[Session, Depends(get_session)]

_UPLOADING_STAGES = (
    AttemptStage.PREPARING,
    AttemptStage.UPLOADING,
    AttemptStage.FINAL_CHUNK,
)


@router.get(
    "/publications/{publication_id}/tiktok-delivery",
    response_model=TikTokDeliveryRead,
)
def get_tiktok_delivery(publication_id: int, session: SessionDep) -> TikTokDeliveryRead:
    """The derived Upload to Inbox delivery state of a TikTok publication; reads
    nothing from TikTok."""
    publication = get_publication_or_404(session, publication_id)
    account = session.get_one(Account, publication.account_id)
    if account.platform != Platform.TIKTOK:
        raise ConflictError(
            "platform_not_supported",
            "TikTok delivery only applies to publications of TikTok accounts.",
        )
    options = session.get(TikTokPublicationOptions, publication.id)
    mode = options.mode if options is not None else None
    attempt = session.scalars(
        select(PublicationAttempt)
        .where(PublicationAttempt.publication_id == publication.id)
        .order_by(PublicationAttempt.started_at.desc(), PublicationAttempt.id.desc())
        .limit(1)
    ).first()
    run = session.get(TikTokPublishRun, attempt.id) if attempt is not None else None
    inbox_run = run is not None and run.mode == TikTokMode.INBOX_UPLOAD
    state = _delivery_state(publication, mode, attempt, inbox_run)
    failure = None
    if (
        state == "failed"
        and attempt is not None
        and attempt.status == AttemptStatus.SUCCEEDED
        and run is not None
    ):
        # TikTok reported the failure after the video reached the inbox.
        mapping = map_inbox_fail_reason(run.fail_reason)
        failure = TikTokDeliveryFailureRead(code=mapping.code, message=mapping.message)
    return TikTokDeliveryRead(
        mode=mode,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        delivered_at=run.delivered_to_inbox_at if inbox_run and run else None,
        user_published_at=run.user_published_at if inbox_run and run else None,
        after_delivery_failure=failure,
        instruction=READY_INSTRUCTION if state == "ready" else None,
        can_check_status=state == "ready",
    )


def _delivery_state(
    publication: Publication,
    mode: str | None,
    attempt: PublicationAttempt | None,
    inbox_run: bool,
) -> str | None:
    status = publication.status
    if status == PublicationStatus.AWAITING_USER_ACTION:
        return "ready"
    if not inbox_run and mode != TikTokMode.INBOX_UPLOAD:
        return None
    if status == PublicationStatus.PUBLISHING:
        if attempt is not None and attempt.stage in _UPLOADING_STAGES:
            return "uploading"
        return "processing"
    if inbox_run and status == PublicationStatus.PUBLISHED:
        return "published"
    if inbox_run and status == PublicationStatus.FAILED:
        return "failed"
    if status == PublicationStatus.SCHEDULED:
        return "scheduled"
    return "not_sent"
