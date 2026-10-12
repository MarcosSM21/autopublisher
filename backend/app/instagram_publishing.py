"""Instagram publisher: options, preflight, publishing and reconciliation of single
images and Reels (specs/009-instagram-media-publishing, contracts/api.md).

Everything Instagram-specific about running a publication lives here; the generic
core only talks to `InstagramPublisher` through the `Publisher` protocol.

Never publishing a duplicate is the main rule (research.md §11-§12):
- the phase `publishing` and the generic stage `finalizing` are committed before
  `media_publish` (write-ahead);
- `media_publish` and container creation are never retried automatically;
- after an inconclusive `media_publish`, only a container read as `PUBLISHED` settles
  the outcome; any other status keeps it uncertain;
- the media ID is never inferred, and recent posts are never listed.
"""

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import media
from app.contents import file_available
from app.credential_store import CredentialStore
from app.db import get_session, utc_now
from app.errors import AppError, ConflictError
from app.instagram_connections import (
    get_connection,
    get_valid_credentials,
    mark_reconnect_required,
    verify_identity,
)
from app.instagram_gateway import (
    InstagramGateway,
    MetaError,
    MetaPermissionDenied,
    MetaPublishRejected,
    MetaTokenInvalid,
    MetaUnavailable,
    MetaUnexpectedResponse,
)
from app.instagram_media import (
    ALT_TEXT_MAX_CHARACTERS,
    CAPTION_MAX_CHARACTERS,
    CAPTION_MAX_HASHTAGS,
    CAPTION_MAX_MENTIONS,
    CONTENT_TYPES,
    ImageIncompatible,
    build_caption,
    caption_problems,
    caption_stats,
    fingerprint,
    image_problems,
    media_kind_of,
    prepare_image,
    reel_problems,
)
from app.media_delivery import (
    NOT_CONFIGURED_MESSAGE as DELIVERY_NOT_CONFIGURED_MESSAGE,
)
from app.media_delivery import (
    MediaDeliveryFailed,
    MediaDeliveryNotConfigured,
    TemporaryMediaService,
)
from app.models import (
    Account,
    Content,
    InstagramConnectionStatus,
    InstagramMediaKind,
    InstagramPublicationOptions,
    InstagramPublishPhase,
    InstagramPublishRun,
    Platform,
    Publication,
    PublicationAttempt,
    PublicationStatus,
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
    Reconciliation,
)
from app.schemas import (
    InstagramCaptionLimitsRead,
    InstagramPublicationOptionsRead,
    InstagramPublicationOptionsWrite,
    PublishProblemRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["instagram"])

SessionDep = Annotated[Session, Depends(get_session)]

DEFAULT_SHARE_TO_FEED = True
EDITABLE_STATUSES = (
    PublicationStatus.UNSCHEDULED,
    PublicationStatus.SCHEDULED,
    PublicationStatus.FAILED,
)
CONNECTION_CODES = frozenset(
    {"instagram_not_connected", "instagram_reconnect_required"}
)

# Container status codes (IG Container reference).
FINISHED = "FINISHED"
IN_PROGRESS = "IN_PROGRESS"
ERROR = "ERROR"
EXPIRED = "EXPIRED"
PUBLISHED = "PUBLISHED"

# Error subcodes of Content Publishing (research.md §18).
SUBCODE_LIMIT = 2207042
SUBCODES_FETCH = frozenset({2207052, 2207003})
SUBCODES_MEDIA = frozenset({2207004, 2207005, 2207009, 2207010, 2207026})
SUBCODE_EXPIRED = 2207020
SUBCODES_RESTRICTED = frozenset({2207050, 2207051})

NOT_CONNECTED_MESSAGE = "Connect this Instagram account before publishing."
RECONNECT_MESSAGE = "Reconnect this Instagram account before publishing."
OPTIONS_INCOMPLETE_MESSAGE = "Declare whether the content is AI-generated."
UNSUPPORTED_MESSAGE = (
    "Instagram publishing supports single images (Image Post) and single videos (Reel)."
)
MEDIA_UNAVAILABLE_MESSAGE = (
    "The media file of this content is not available or has changed."
)
UNAVAILABLE_MESSAGE = (
    "Could not reach Instagram. Nothing was published; try again later."
)
LIMIT_MESSAGE = (
    "This Instagram account reached the publishing limit Instagram allows for the "
    "last 24 hours. Try again later."
)
ALREADY_PUBLISHED_MESSAGE = (
    "Instagram reports that the previous attempt of this publication was already "
    "published. Nothing new was created; check the account and cancel this "
    "publication."
)
IDENTITY_UNAVAILABLE_MESSAGE = (
    "Instagram confirmed the post was published but did not return its ID. Open "
    "@{username} on Instagram to find it (attempted around {time} UTC)."
)
PERMALINK_UNAVAILABLE_MESSAGE = (
    "Instagram did not return the link of the post; the button opens the profile."
)
CLEANUP_FAILED_MESSAGE = (
    "The temporary copy of the media could not be deleted yet. It stays private and "
    "AutoPublisher will delete it later."
)
UNCERTAIN_MESSAGE = (
    "Instagram did not confirm whether the post was published. Check @{username} on "
    'Instagram for a post around {time} UTC with the caption "{caption}" before '
    "publishing again."
)


# --- Options -----------------------------------------------------------------------


def get_options(session: Session, publication_id: int) -> InstagramPublicationOptions:
    """Stored options, or the defaults (not added to the session)."""
    stored = session.get(InstagramPublicationOptions, publication_id)
    if stored is not None:
        return stored
    return InstagramPublicationOptions(
        publication_id=publication_id,
        is_ai_generated=None,
        share_to_feed=DEFAULT_SHARE_TO_FEED,
        alt_text=None,
    )


def _instagram_publication(session: Session, publication_id: int) -> Publication:
    publication = get_publication_or_404(session, publication_id)
    account = session.get_one(Account, publication.account_id)
    if account.platform != Platform.INSTAGRAM:
        raise ConflictError(
            "platform_not_supported",
            "Instagram options only apply to publications of Instagram accounts.",
        )
    return publication


def get_instagram_publisher(request: Request) -> "InstagramPublisher":
    publisher = request.app.state.publishers.get(Platform.INSTAGRAM)
    assert isinstance(publisher, InstagramPublisher)
    return publisher


def get_publish_context(request: Request) -> PublishContext:
    ctx: PublishContext = request.app.state.publish_context
    return ctx


PublisherDep = Annotated["InstagramPublisher", Depends(get_instagram_publisher)]
ContextDep = Annotated[PublishContext, Depends(get_publish_context)]


def options_to_read(
    session: Session,
    publication: Publication,
    publisher: "InstagramPublisher",
    ctx: PublishContext,
) -> InstagramPublicationOptionsRead:
    content = session.get_one(Content, publication.content_id)
    options = get_options(session, publication.id)
    kind = media_kind_of(content)
    caption = build_caption(publication, content)
    stats = caption_stats(caption)
    problems = [
        problem
        for problem in publisher.check(session, publication, ctx).problems
        if problem.code not in CONNECTION_CODES
    ]
    return InstagramPublicationOptionsRead(
        media_kind=kind.value if kind is not None else None,
        caption=caption,
        caption_length=stats.length,
        caption_hashtags=stats.hashtags,
        caption_mentions=stats.mentions,
        is_ai_generated=options.is_ai_generated,
        share_to_feed=options.share_to_feed
        if kind == InstagramMediaKind.REEL
        else None,
        alt_text=options.alt_text if kind == InstagramMediaKind.IMAGE else None,
        complete=options.is_ai_generated is not None,
        editable=publication.status in EDITABLE_STATUSES,
        media_delivery_configured=publisher.delivery.configured(),
        problems=[
            PublishProblemRead(code=p.code, message=p.message, field=p.field)
            for p in problems
        ],
        limits=InstagramCaptionLimitsRead(
            caption_characters=CAPTION_MAX_CHARACTERS,
            caption_hashtags=CAPTION_MAX_HASHTAGS,
            caption_mentions=CAPTION_MAX_MENTIONS,
            alt_text_characters=ALT_TEXT_MAX_CHARACTERS,
        ),
    )


@router.get(
    "/publications/{publication_id}/instagram-options",
    response_model=InstagramPublicationOptionsRead,
)
def get_instagram_options(
    publication_id: int,
    session: SessionDep,
    publisher: PublisherDep,
    ctx: ContextDep,
) -> InstagramPublicationOptionsRead:
    """Options, exact caption and local problems; no network."""
    publication = _instagram_publication(session, publication_id)
    return options_to_read(session, publication, publisher, ctx)


def _not_applicable(field: str, message: str) -> AppError:
    return AppError(
        422,
        "instagram_option_not_applicable",
        message,
        fields=[{"field": field, "message": message}],
    )


@router.put(
    "/publications/{publication_id}/instagram-options",
    response_model=InstagramPublicationOptionsRead,
)
def save_instagram_options(
    publication_id: int,
    body: InstagramPublicationOptionsWrite,
    session: SessionDep,
    publisher: PublisherDep,
    ctx: ContextDep,
) -> InstagramPublicationOptionsRead:
    publication = _instagram_publication(session, publication_id)
    ensure_editable(publication)
    content = session.get_one(Content, publication.content_id)
    kind = media_kind_of(content)
    if body.share_to_feed is not None and kind != InstagramMediaKind.REEL:
        raise _not_applicable("share_to_feed", "Share to feed only applies to Reels.")
    alt_text = (body.alt_text or "").strip() or None
    if alt_text is not None and kind != InstagramMediaKind.IMAGE:
        raise _not_applicable("alt_text", "Alt text only applies to images.")
    options = session.get(InstagramPublicationOptions, publication_id)
    values: dict[str, Any] = {"is_ai_generated": body.is_ai_generated}
    if kind == InstagramMediaKind.REEL and body.share_to_feed is not None:
        values["share_to_feed"] = body.share_to_feed
    if kind == InstagramMediaKind.IMAGE:
        values["alt_text"] = alt_text
    if options is None:
        # Defaults first, then the received values (share_to_feed may be among them).
        options = InstagramPublicationOptions(
            publication_id=publication_id,
            updated_at=utc_now(),
            **{"share_to_feed": DEFAULT_SHARE_TO_FEED, **values},
        )
        session.add(options)
        session.commit()
    elif any(getattr(options, key) != value for key, value in values.items()):
        for key, value in values.items():
            setattr(options, key, value)
        options.updated_at = utc_now()
        session.commit()
    return options_to_read(session, publication, publisher, ctx)


# --- Publisher ---------------------------------------------------------------------


@dataclass(frozen=True)
class InstagramPublishSettings:
    """Waits and limits of an Instagram execution (research.md §8, §11, §14)."""

    sleep: Callable[[float], None] = time.sleep
    # Waits between container status reads: these, then `poll_interval` repeatedly.
    poll_waits: tuple[float, ...] = (2.0, 5.0, 10.0, 20.0, 30.0)
    poll_interval: float = 60.0
    image_timeout: float = 5 * 60.0
    reel_timeout: float = 10 * 60.0
    # Read-only checks after an inconclusive media_publish (0, 5, 15, 30, 60 s).
    uncertain_waits: tuple[float, ...] = (0.0, 5.0, 10.0, 15.0, 30.0)
    permalink_waits: tuple[float, ...] = (2.0, 5.0)
    container_max_age: timedelta = timedelta(hours=23)
    # Slices in which long waits are split, to notice a shutdown.
    sleep_slice: float = 1.0
    clock: Callable[[], datetime] = utc_now


@dataclass(frozen=True)
class InstagramPayload:
    """What the core treats as an opaque payload. Contains no secrets."""

    account_id: int
    instagram_user_id: str
    username: str
    media_kind: InstagramMediaKind
    caption: str
    is_ai_generated: bool
    share_to_feed: bool
    alt_text: str | None
    content_type: str
    source: bytes | Path
    size: int
    fingerprint: str
    reuse_container_id: str | None = None
    reused_from_attempt_id: int | None = None


def _yes_no(value: bool | None) -> str:
    return "Not declared" if value is None else ("Yes" if value else "No")


def _file_label(content: Content, converted: bool) -> str:
    label = f"{content.original_filename} ({content.size_bytes / 1_000_000:.1f} MB)"
    return f"{label} → sent as JPEG" if converted else label


class InstagramPublisher:
    def __init__(
        self,
        gateway: InstagramGateway,
        credential_store: CredentialStore,
        delivery: TemporaryMediaService,
        settings: InstagramPublishSettings | None = None,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.delivery = delivery
        self.settings = settings or InstagramPublishSettings()

    # --- Local checks (no network) ---------------------------------------------

    @staticmethod
    def _file_ready(ctx: PublishContext, content: Content) -> bool:
        if not file_available(ctx.storage, content):
            return False
        path = ctx.storage.resolve(content.storage_path)
        return path.stat().st_size == content.size_bytes

    def _media_problems(
        self, ctx: PublishContext, content: Content
    ) -> list[PublishProblem]:
        kind = media_kind_of(content)
        if kind is None:
            return [PublishProblem("instagram_media_unsupported", UNSUPPORTED_MESSAGE)]
        if not self._file_ready(ctx, content):
            return [PublishProblem("media_unavailable", MEDIA_UNAVAILABLE_MESSAGE)]
        path = ctx.storage.resolve(content.storage_path)
        if kind == InstagramMediaKind.IMAGE:
            return image_problems(path, content.media_format)
        return reel_problems(
            content.media_format,
            content.size_bytes,
            media.probe_video_streams(path),
            media.moov_before_mdat(path),
        )

    def check(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PublishCheck:
        content = session.get_one(Content, publication.content_id)
        options = get_options(session, publication.id)
        connection = get_connection(session, publication.account_id)
        kind = media_kind_of(content)
        problems = self._media_problems(ctx, content)
        caption = build_caption(publication, content)
        problems.extend(caption_problems(caption))
        if options.is_ai_generated is None:
            problems.append(
                PublishProblem(
                    "instagram_options_incomplete",
                    OPTIONS_INCOMPLETE_MESSAGE,
                    "is_ai_generated",
                )
            )
        if not self.delivery.configured():
            problems.append(
                PublishProblem(
                    "media_delivery_not_configured",
                    DELIVERY_NOT_CONFIGURED_MESSAGE,
                    status_code=503,
                )
            )
        if connection is None:
            problems.append(
                PublishProblem("instagram_not_connected", NOT_CONNECTED_MESSAGE)
            )
        elif connection.status != InstagramConnectionStatus.CONNECTED:
            problems.append(
                PublishProblem("instagram_reconnect_required", RECONNECT_MESSAGE)
            )
        account_label = (
            f"{connection.username} ({connection.instagram_user_id})"
            if connection is not None
            else "Not connected"
        )
        summary = [
            ("Post type", "Reel" if kind == InstagramMediaKind.REEL else "Image Post"),
            ("Instagram account", account_label),
            ("Caption", caption),
            ("AI-generated", _yes_no(options.is_ai_generated)),
        ]
        if kind == InstagramMediaKind.REEL:
            summary.append(("Share to feed", _yes_no(options.share_to_feed)))
        else:
            summary.append(("Alt text", options.alt_text or "None"))
        converted = kind == InstagramMediaKind.IMAGE and content.media_format != "jpeg"
        summary.append(("File", _file_label(content, converted)))
        return PublishCheck(problems, summary)

    # --- Preflight (reads allowed, no publishing effects) ----------------------

    def prepare(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PreparedPublication:
        """Credentials, identity, quota and the previous container are only read.
        Nothing is uploaded and no container is created here (FR-031a)."""
        if get_connection(session, publication.account_id) is None:
            raise AppError(409, "instagram_not_connected", NOT_CONNECTED_MESSAGE)
        verify_identity(
            session, self.credential_store, self.gateway, publication.account_id
        )
        connection = get_connection(session, publication.account_id)
        assert connection is not None
        token = get_valid_credentials(
            session, self.credential_store, self.gateway, publication.account_id
        )
        content = session.get_one(Content, publication.content_id)
        kind = media_kind_of(content)
        options = get_options(session, publication.id)
        if kind is None or options.is_ai_generated is None:
            raise AppError(
                409, "instagram_options_incomplete", OPTIONS_INCOMPLETE_MESSAGE
            )
        caption = build_caption(publication, content)
        path = ctx.storage.resolve(content.storage_path)
        source: bytes | Path
        converted = False
        if kind == InstagramMediaKind.IMAGE:
            try:
                image = prepare_image(path, content.media_format)
            except ImageIncompatible as error:
                raise AppError(
                    409, "instagram_image_incompatible", error.message
                ) from None
            source = image.data if image.data is not None else path
            size, content_type, converted = (
                image.size,
                image.content_type,
                image.converted,
            )
        else:
            source, size = path, content.size_bytes
            content_type = CONTENT_TYPES[content.media_format]  # type: ignore[index]
        sent_options: dict[str, Any] = {"is_ai_generated": options.is_ai_generated}
        if kind == InstagramMediaKind.REEL:
            sent_options["share_to_feed"] = options.share_to_feed
        else:
            sent_options["alt_text"] = options.alt_text
        print_ = fingerprint(content.checksum, kind.value, caption, sent_options)

        quota_checked = self._check_quota(
            session, connection.instagram_user_id, token.access_token, publication
        )
        reuse = self._previous_container(
            session, publication.id, print_, token.access_token
        )
        payload = InstagramPayload(
            account_id=publication.account_id,
            instagram_user_id=connection.instagram_user_id,
            username=connection.username,
            media_kind=kind,
            caption=caption,
            is_ai_generated=options.is_ai_generated,
            share_to_feed=options.share_to_feed,
            alt_text=options.alt_text if kind == InstagramMediaKind.IMAGE else None,
            content_type=content_type,
            source=source,
            size=size,
            fingerprint=print_,
            reuse_container_id=reuse[0] if reuse else None,
            reused_from_attempt_id=reuse[1] if reuse else None,
        )
        submitted: dict[str, Any] = {
            "media_kind": kind.value,
            "caption": caption,
            "is_ai_generated": options.is_ai_generated,
            "alt_text": payload.alt_text,
            "share_to_feed": options.share_to_feed
            if kind == InstagramMediaKind.REEL
            else None,
            "instagram_user_id": connection.instagram_user_id,
            "username": connection.username,
            "file_name": content.original_filename,
            "file_size": content.size_bytes,
            "delivered_format": "jpeg"
            if kind == InstagramMediaKind.IMAGE
            else (content.media_format),
            "delivered_size": size,
            "converted": converted,
            "container_reused": reuse is not None,
            "quota_checked": quota_checked,
        }
        return PreparedPublication(
            publication_id=publication.id,
            file_path=path,
            total_bytes=size,
            submitted=submitted,
            payload=payload,
        )

    def _check_quota(
        self,
        session: Session,
        ig_user_id: str,
        access_token: str,
        publication: Publication,
    ) -> bool:
        """Meta's own numbers are the only source; an unreadable quota never blocks
        (Meta rejects media_publish with a determined error instead)."""
        try:
            limit = self.gateway.publishing_limit(ig_user_id, access_token)
        except (MetaTokenInvalid, MetaPermissionDenied):
            self._mark_reconnect(session, publication.account_id)
            raise AppError(
                409, "instagram_reconnect_required", RECONNECT_MESSAGE
            ) from None
        except MetaError:
            logger.warning("Could not read the Instagram publishing limit.")
            return False
        if limit is None:
            return False
        usage, total = limit
        if usage >= total:
            raise AppError(409, "instagram_publishing_limit_reached", LIMIT_MESSAGE)
        return True

    def _previous_container(
        self, session: Session, publication_id: int, print_: str, access_token: str
    ) -> tuple[str, int] | None:
        """Read the latest recent container of this publication (research.md §12):
        block if it was published, reuse it if it is ready for the same content."""
        since = self.settings.clock() - self.settings.container_max_age
        run = session.scalars(
            select(InstagramPublishRun)
            .where(
                InstagramPublishRun.publication_id == publication_id,
                InstagramPublishRun.container_id.is_not(None),
                InstagramPublishRun.container_created_at > since,
            )
            .order_by(
                InstagramPublishRun.container_created_at.desc(),
                InstagramPublishRun.attempt_id.desc(),
            )
            .limit(1)
        ).first()
        if run is None or run.container_id is None:
            return None
        try:
            status = self.gateway.container_status(run.container_id, access_token)
        except (MetaTokenInvalid, MetaPermissionDenied):
            raise AppError(
                409, "instagram_reconnect_required", RECONNECT_MESSAGE
            ) from None
        except (MetaUnavailable, MetaUnexpectedResponse):
            raise AppError(503, "instagram_unavailable", UNAVAILABLE_MESSAGE) from None
        except MetaError:
            return None  # Unknown to Meta: a new container is created.
        if status == PUBLISHED:
            raise AppError(
                409, "instagram_already_published", ALREADY_PUBLISHED_MESSAGE
            )
        if status == FINISHED and run.fingerprint == print_:
            return run.container_id, run.attempt_id
        return None

    # --- Execution -------------------------------------------------------------

    def _update_run(self, ctx: PublishContext, attempt_id: int, **values: Any) -> bool:
        values["updated_at"] = self.settings.clock()
        try:
            with ctx.session_factory() as session:
                run = session.get_one(InstagramPublishRun, attempt_id)
                for key, value in values.items():
                    setattr(run, key, value)
                session.commit()
        except SQLAlchemyError:
            logger.warning(
                "Could not save the Instagram run of attempt %s.", attempt_id
            )
            return False
        return True

    def _create_run(
        self, ctx: PublishContext, attempt_id: int, prepared: PreparedPublication
    ) -> None:
        payload = prepared.payload
        assert isinstance(payload, InstagramPayload)
        with ctx.session_factory() as session:
            session.add(
                InstagramPublishRun(
                    attempt_id=attempt_id,
                    publication_id=prepared.publication_id,
                    media_kind=payload.media_kind.value,
                    fingerprint=payload.fingerprint,
                    phase=InstagramPublishPhase.PREPARING,
                    reused_from_attempt_id=payload.reused_from_attempt_id,
                    updated_at=self.settings.clock(),
                )
            )
            session.commit()

    def _mark_reconnect(self, session: Session, account_id: int) -> None:
        connection = get_connection(session, account_id)
        if connection is not None:
            mark_reconnect_required(session, connection, self.gateway.clock())

    def _mark_reconnect_new_session(self, ctx: PublishContext, account_id: int) -> None:
        with ctx.session_factory() as session:
            self._mark_reconnect(session, account_id)

    def _token(self, ctx: PublishContext, account_id: int) -> str:
        """A valid token; credential problems become determined failures."""
        try:
            with ctx.session_factory() as session:
                token = get_valid_credentials(
                    session, self.credential_store, self.gateway, account_id
                )
        except AppError as error:
            if error.code in (
                "instagram_not_connected",
                "instagram_reconnect_required",
            ):
                raise PublishFailure(
                    "instagram_reconnect_required", RECONNECT_MESSAGE, determined=True
                ) from None
            if error.code == "credential_store_unavailable":
                raise PublishFailure(
                    "credential_store_unavailable", error.message, determined=True
                ) from None
            raise PublishFailure(
                "instagram_unavailable", UNAVAILABLE_MESSAGE, determined=True
            ) from None
        return token.access_token

    def _failure(
        self,
        ctx: PublishContext,
        payload: InstagramPayload,
        error: MetaError,
        default_code: str,
        default_message: str,
    ) -> PublishFailure:
        """Map a gateway error before `media_publish` to a determined failure."""
        if isinstance(error, (MetaTokenInvalid, MetaPermissionDenied)):
            self._mark_reconnect_new_session(ctx, payload.account_id)
            return PublishFailure(
                "instagram_reconnect_required",
                "Instagram rejected the credentials; reconnect the account. Nothing "
                "was published.",
                determined=True,
            )
        if isinstance(error, MetaUnavailable):
            return PublishFailure(
                "instagram_unavailable", UNAVAILABLE_MESSAGE, determined=True
            )
        if isinstance(error, MetaPublishRejected):
            subcode = error.subcode
            if subcode == SUBCODE_LIMIT:
                return PublishFailure(
                    "instagram_publishing_limit_reached", LIMIT_MESSAGE, determined=True
                )
            if subcode in SUBCODES_FETCH:
                return PublishFailure(
                    "instagram_media_fetch_failed",
                    "Instagram could not download the media. Nothing was published.",
                    determined=True,
                )
            if subcode in SUBCODES_MEDIA:
                return PublishFailure(
                    "instagram_media_rejected",
                    "Instagram rejected the media (format, size or aspect ratio). "
                    "Nothing was published.",
                    determined=True,
                )
            if subcode == SUBCODE_EXPIRED:
                return PublishFailure(
                    "instagram_container_expired",
                    "The prepared Instagram post expired before it was published.",
                    determined=True,
                )
            if subcode in SUBCODES_RESTRICTED:
                return PublishFailure(
                    "instagram_account_restricted",
                    "Instagram is restricting this account. Check the Instagram app; "
                    "nothing was published.",
                    determined=True,
                )
        return PublishFailure(default_code, default_message, determined=True)

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

    def _poll_waits(self) -> Iterator[float]:
        yield from self.settings.poll_waits
        while True:
            yield self.settings.poll_interval

    def _wait_until_ready(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: InstagramPayload,
        container_id: str,
        token: str,
        reporter: ProgressReporter,
    ) -> str:
        """Poll the container with bounded waits until it is FINISHED (research §8)."""
        limit = (
            self.settings.reel_timeout
            if payload.media_kind == InstagramMediaKind.REEL
            else self.settings.image_timeout
        )
        elapsed = 0.0
        waits = self._poll_waits()
        while True:
            try:
                status: str | None = self.gateway.container_status(container_id, token)
            except (MetaUnavailable, MetaUnexpectedResponse):
                status = None  # Read again on the next wait.
            except MetaError as error:
                raise self._failure(
                    ctx,
                    payload,
                    error,
                    "instagram_processing_failed",
                    "Instagram could not process the media. Nothing was published.",
                ) from None
            if status is not None:
                self._update_run(ctx, attempt_id, container_status=status[:20])
                if status in (FINISHED, PUBLISHED):
                    return status
                if status == ERROR:
                    raise PublishFailure(
                        "instagram_processing_failed",
                        "Instagram could not process the media. Nothing was published.",
                        determined=True,
                    )
                if status == EXPIRED:
                    raise PublishFailure(
                        "instagram_container_expired",
                        "The prepared Instagram post expired before it was published.",
                        determined=True,
                    )
            wait = next(waits)
            if elapsed + wait > limit:
                raise PublishFailure(
                    "instagram_processing_timeout",
                    "Instagram took too long to process the media. Nothing was "
                    "published.",
                    determined=True,
                )
            if not self._wait(wait, reporter):
                raise PublishFailure(
                    "interrupted",
                    "The publication was interrupted because AutoPublisher stopped. "
                    "Nothing was published.",
                    determined=True,
                )
            elapsed += wait

    def _read_status_once(self, container_id: str, token: str) -> str | None:
        try:
            return self.gateway.container_status(container_id, token)
        except MetaError:
            return None

    def _uncertain(
        self, payload: InstagramPayload, started: datetime
    ) -> PublishFailure:
        caption = payload.caption.replace("\n", " ")
        if len(caption) > 60:
            caption = caption[:57] + "..."
        message = UNCERTAIN_MESSAGE.format(
            username=payload.username,
            time=started.strftime("%Y-%m-%d %H:%M"),
            caption=caption,
        )
        return PublishFailure(
            "instagram_publish_uncertain", message[:500], determined=False
        )

    def _publish(
        self,
        ctx: PublishContext,
        payload: InstagramPayload,
        container_id: str,
        token: str,
        started: datetime,
    ) -> str | None:
        """`media_publish`, called exactly once. Returns the media ID, or None when
        only the container confirmed the publication (research.md §11)."""
        try:
            return self.gateway.publish(payload.instagram_user_id, container_id, token)
        except (MetaUnavailable, MetaUnexpectedResponse):
            # Inconclusive: only read the original container, never publish again.
            for wait in self.settings.uncertain_waits:
                if wait:
                    self.settings.sleep(wait)
                if self._read_status_once(container_id, token) == PUBLISHED:
                    return None
            raise self._uncertain(payload, started) from None
        except MetaError as error:
            # An explicit rejection: confirm with one read before calling it final.
            if self._read_status_once(container_id, token) == PUBLISHED:
                return None
            raise self._failure(
                ctx,
                payload,
                error,
                "instagram_publish_failed",
                "Instagram rejected the publication. Nothing was published.",
            ) from None

    def _permalink(self, media_id: str, token: str) -> str | None:
        for try_number in range(len(self.settings.permalink_waits) + 1):
            try:
                return self.gateway.media_permalink(media_id, token)
            except (MetaUnavailable, MetaUnexpectedResponse):
                if try_number < len(self.settings.permalink_waits):
                    self.settings.sleep(self.settings.permalink_waits[try_number])
            except MetaError:
                return None
        return None

    def upload(
        self,
        prepared: PreparedPublication,
        reporter: ProgressReporter,
        ctx: PublishContext,
    ) -> PublishOutcome:
        payload = prepared.payload
        assert isinstance(payload, InstagramPayload)
        attempt_id = reporter.attempt_id
        self._create_run(ctx, attempt_id, prepared)
        try:
            return self._run(ctx, attempt_id, payload, reporter)
        except BaseException:
            self._update_run(ctx, attempt_id, phase=InstagramPublishPhase.FAILED)
            raise

    def _run(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: InstagramPayload,
        reporter: ProgressReporter,
    ) -> PublishOutcome:
        token = self._token(ctx, payload.account_id)
        container_id = payload.reuse_container_id
        if container_id is None:
            container_id = self._deliver_and_create(
                ctx, attempt_id, payload, token, reporter
            )
            status = self._wait_until_ready(
                ctx, attempt_id, payload, container_id, token, reporter
            )
            if status == PUBLISHED:
                # Never expected for a new container; never publish it again.
                return self._identity_unavailable(payload, self.settings.clock())
        else:
            self._update_run(
                ctx,
                attempt_id,
                container_id=container_id,
                container_created_at=self.settings.clock(),
                container_status=FINISHED,
            )

        started = self.settings.clock()
        if (
            not self._update_run(
                ctx,
                attempt_id,
                phase=InstagramPublishPhase.PUBLISHING,
                publish_started_at=started,
            )
            or not reporter.enter_finalizing()
        ):
            raise PublishFailure(
                "internal_error",
                "AutoPublisher could not save its progress, so it did not publish.",
                determined=True,
            )
        media_id = self._publish(ctx, payload, container_id, token, started)
        self._update_run(ctx, attempt_id, phase=InstagramPublishPhase.VERIFYING_RESULT)
        if media_id is None:
            outcome = self._identity_unavailable(payload, started)
        else:
            outcome = self._outcome(payload, media_id, token)
        self._update_run(
            ctx,
            attempt_id,
            phase=InstagramPublishPhase.SUCCEEDED,
            container_status=PUBLISHED,
        )
        return outcome

    def _deliver_and_create(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: InstagramPayload,
        token: str,
        reporter: ProgressReporter,
    ) -> str:
        self._update_run(ctx, attempt_id, phase=InstagramPublishPhase.DELIVERING_MEDIA)
        try:
            key = self.delivery.reserve(attempt_id, payload.content_type, payload.size)
            self.delivery.upload(key, payload.source, reporter.report_bytes)
            url = self.delivery.public_url(key)
        except MediaDeliveryNotConfigured:
            raise PublishFailure(
                "media_delivery_not_configured",
                DELIVERY_NOT_CONFIGURED_MESSAGE,
                determined=True,
            ) from None
        except MediaDeliveryFailed:
            raise PublishFailure(
                "media_delivery_failed",
                "The media could not be made available to Instagram. Nothing was "
                "published.",
                determined=True,
            ) from None
        reporter.enter_processing()
        self._update_run(
            ctx, attempt_id, phase=InstagramPublishPhase.CREATING_CONTAINER
        )
        try:
            if payload.media_kind == InstagramMediaKind.REEL:
                container_id = self.gateway.create_reel_container(
                    payload.instagram_user_id,
                    token,
                    video_url=url.reveal(),
                    caption=payload.caption,
                    share_to_feed=payload.share_to_feed,
                    is_ai_generated=payload.is_ai_generated,
                )
            else:
                container_id = self.gateway.create_image_container(
                    payload.instagram_user_id,
                    token,
                    image_url=url.reveal(),
                    caption=payload.caption,
                    alt_text=payload.alt_text,
                    is_ai_generated=payload.is_ai_generated,
                )
        except MetaError as error:
            raise self._failure(
                ctx,
                payload,
                error,
                "instagram_container_failed",
                "Instagram could not prepare the post. Nothing was published.",
            ) from None
        self._update_run(
            ctx,
            attempt_id,
            container_id=container_id,
            container_created_at=self.settings.clock(),
            phase=InstagramPublishPhase.PROCESSING_CONTAINER,
        )
        return container_id

    def _identity_unavailable(
        self, payload: InstagramPayload, started: datetime
    ) -> PublishOutcome:
        message = IDENTITY_UNAVAILABLE_MESSAGE.format(
            username=payload.username, time=started.strftime("%Y-%m-%d %H:%M")
        )
        return PublishOutcome(
            external_id=None,
            external_url=None,
            warnings=[{"code": "remote_identity_unavailable", "message": message}],
        )

    def _outcome(
        self, payload: InstagramPayload, media_id: str, token: str
    ) -> PublishOutcome:
        permalink = self._permalink(media_id, token)
        if permalink is not None:
            return PublishOutcome(
                external_id=media_id,
                external_url=permalink,
                details={"permalink": permalink},
            )
        return PublishOutcome(
            external_id=media_id,
            external_url=f"https://www.instagram.com/{payload.username}/",
            warnings=[
                {
                    "code": "permalink_unavailable",
                    "message": PERMALINK_UNAVAILABLE_MESSAGE,
                }
            ],
        )

    def refresh_details(
        self,
        prepared: PreparedPublication,
        outcome: PublishOutcome,
        ctx: PublishContext,
    ) -> PublishOutcome:
        """Try the permalink once more when it was missing (best effort)."""
        missing = any(w["code"] == "permalink_unavailable" for w in outcome.warnings)
        if outcome.external_id is None or not missing:
            return outcome
        payload = prepared.payload
        assert isinstance(payload, InstagramPayload)
        token = self._token(ctx, payload.account_id)
        permalink = self.gateway.media_permalink(outcome.external_id, token)
        if permalink is None:
            return outcome
        return PublishOutcome(
            external_id=outcome.external_id,
            external_url=outcome.external_url,
            details={**outcome.details, "permalink": permalink},
            warnings=[
                w for w in outcome.warnings if w["code"] != "permalink_unavailable"
            ],
        )

    def release(
        self,
        prepared: PreparedPublication,
        ctx: PublishContext,
        *,
        attempt_id: int,
        succeeded: bool,
    ) -> list[dict[str, str]]:
        """Delete the temporary copy after the outcome was saved, then sweep."""
        released = self.delivery.release_attempt(attempt_id)
        self.delivery.sweep()
        if released:
            return []
        return [
            {
                "code": "temporary_media_cleanup_failed",
                "message": CLEANUP_FAILED_MESSAGE,
            }
        ]

    # --- Reconciliation (research.md §11b) --------------------------------------

    def reconcile(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> Reconciliation | None:
        """One read of the original container of an uncertain attempt. Only
        `PUBLISHED` settles it; never publishes, never creates a container and never
        lists recent posts."""
        run = session.get(InstagramPublishRun, attempt.id)
        if (
            run is None
            or run.container_id is None
            or run.publish_started_at is None
            or run.phase
            not in (
                InstagramPublishPhase.PUBLISHING,
                InstagramPublishPhase.VERIFYING_RESULT,
                InstagramPublishPhase.FAILED,
            )
        ):
            return None
        token = get_valid_credentials(
            session, self.credential_store, self.gateway, publication.account_id
        )
        status = self.gateway.container_status(run.container_id, token.access_token)
        if status != PUBLISHED:
            return None
        connection = get_connection(session, publication.account_id)
        username = connection.username if connection is not None else "the account"
        run.phase = InstagramPublishPhase.SUCCEEDED
        run.container_status = PUBLISHED
        run.updated_at = self.settings.clock()
        message = IDENTITY_UNAVAILABLE_MESSAGE.format(
            username=username,
            time=run.publish_started_at.strftime("%Y-%m-%d %H:%M"),
        )
        return Reconciliation(
            published_at=run.publish_started_at,
            outcome=PublishOutcome(
                external_id=None,
                external_url=None,
                warnings=[{"code": "remote_identity_unavailable", "message": message}],
            ),
        )
