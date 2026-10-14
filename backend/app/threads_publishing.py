"""Threads publisher: options, preflight and publishing of text posts, images and
videos (specs/011-threads-publisher, contracts/api.md).

Everything Threads-specific about running a publication lives here; the generic core
only talks to `ThreadsPublisher` through the `Publisher` protocol.

Never publishing a duplicate is the main rule (research.md §10-§12):
- one container per attempt, its id committed right after it is created, never
  reused and never created twice;
- the phase `publishing` and the generic stage `finalizing` are committed before
  `threads_publish` (write-ahead);
- `threads_publish` is called at most once per container and never retried;
- after an inconclusive `threads_publish`, only the original container read as
  `PUBLISHED` settles the outcome; anything else keeps it uncertain;
- the post ID is never inferred, and recent posts are never listed.
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
from app.media_delivery import (
    NOT_CONFIGURED_MESSAGE as DELIVERY_NOT_CONFIGURED_MESSAGE,
)
from app.media_delivery import (
    MediaDeliveryFailed,
    MediaDeliveryNotConfigured,
    SecretUrl,
    TemporaryMediaService,
)
from app.models import (
    Account,
    Content,
    Platform,
    Publication,
    PublicationAttempt,
    PublicationStatus,
    ThreadsConnectionStatus,
    ThreadsMediaKind,
    ThreadsPublicationOptions,
    ThreadsPublishPhase,
    ThreadsPublishRun,
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
    PublishProblemRead,
    ThreadsPublicationOptionsRead,
    ThreadsPublicationOptionsWrite,
    ThreadsTextLimitsRead,
)
from app.threads_connections import (
    get_connection,
    get_valid_credentials,
    mark_reconnect_required,
    verify_identity,
)
from app.threads_gateway import (
    PublishedMedia,
    ThreadsError,
    ThreadsGateway,
    ThreadsPermissionDenied,
    ThreadsRejected,
    ThreadsTokenInvalid,
    ThreadsUnavailable,
    ThreadsUnexpectedResponse,
)
from app.threads_media import (
    ALT_TEXT_MAX_CHARACTERS,
    CONTENT_TYPES,
    TEXT_MAX_CHARACTERS,
    TEXT_MAX_LINKS,
    ImageIncompatible,
    VideoCheck,
    build_text,
    image_problems,
    prepare_threads_image,
    text_length,
    text_links,
    text_problems,
    threads_media_kind,
    video_problems,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["threads"])

SessionDep = Annotated[Session, Depends(get_session)]

EDITABLE_STATUSES = (
    PublicationStatus.UNSCHEDULED,
    PublicationStatus.SCHEDULED,
    PublicationStatus.FAILED,
)
CONNECTION_CODES = frozenset({"threads_not_connected", "threads_reconnect_required"})
MEDIA_KINDS = (ThreadsMediaKind.IMAGE, ThreadsMediaKind.VIDEO)

# Container statuses (Threads troubleshooting guide).
FINISHED = "FINISHED"
IN_PROGRESS = "IN_PROGRESS"
PUBLISHED = "PUBLISHED"
ERROR = "ERROR"
EXPIRED = "EXPIRED"

# Product policy, not a documented API minimum (research §10): `FINISHED` is necessary
# but not sufficient. Meta recommends waiting about 30 s before publishing a
# container, and a real text container read `FINISHED` ~300 ms after its creation was
# rejected by `threads_publish`. A container is only published once it is FINISHED
# and at least this old, measured from its persisted creation time.
MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS = 30.0
# Extra lifetime the signed media URL keeps beyond the longest time Meta may need it
# (container creation + processing timeout), research §14.
URL_TTL_SAFETY_MARGIN_SECONDS = 5 * 60

MEDIA_TYPES = {
    ThreadsMediaKind.TEXT: "TEXT",
    ThreadsMediaKind.IMAGE: "IMAGE",
    ThreadsMediaKind.VIDEO: "VIDEO",
}
POST_TYPES = {
    ThreadsMediaKind.TEXT: "Text",
    ThreadsMediaKind.IMAGE: "Image",
    ThreadsMediaKind.VIDEO: "Video",
}

NOT_CONNECTED_MESSAGE = "Connect this Threads account before publishing."
RECONNECT_MESSAGE = "Reconnect this Threads account before publishing."
UNSUPPORTED_MESSAGE = (
    "Threads publishing supports text posts, single images and single videos."
)
MEDIA_UNAVAILABLE_MESSAGE = (
    "The media file of this content is not available or has changed."
)
ALT_TEXT_INVALID_MESSAGE = (
    f"The alt text can have at most {ALT_TEXT_MAX_CHARACTERS} characters."
)
UNAVAILABLE_MESSAGE = "Could not reach Threads. Nothing was published; try again later."
UNEXPECTED_LIMIT_MESSAGE = (
    "Threads answered the publishing limit in a format AutoPublisher does not "
    "understand; nothing was published."
)
LIMIT_MESSAGE = (
    "This Threads account reached the publishing limit Threads allows for the last "
    "24 hours. Try again later."
)
QUOTA_UNAVAILABLE_MESSAGE = (
    "Threads did not report the publishing limit; publishing continued."
)
ALREADY_PUBLISHED_MESSAGE = (
    "Threads reports that a previous attempt of this publication was already "
    "published. Nothing new was created; check the account and cancel this "
    "publication."
)
IDENTITY_UNAVAILABLE_MESSAGE = (
    "Threads confirmed the post was published but did not return its ID. Open "
    "@{username} on Threads to find it (attempted around {time} UTC)."
)
PERMALINK_UNAVAILABLE_MESSAGE = "Threads did not return the link of the post."
UNCERTAIN_MESSAGE = (
    "Threads did not confirm whether the post was published. Check @{username} on "
    'Threads for a post around {time} UTC starting with "{start}" before publishing '
    "again."
)
NOT_PUBLISHED = "Nothing was published."
WRITE_AHEAD_FAILED_MESSAGE = (
    "AutoPublisher could not save its progress, so it did not publish."
)
CLEANUP_FAILED_MESSAGE = (
    "The temporary copy of the media could not be deleted yet. It stays private and "
    "AutoPublisher will delete it later."
)


# --- Options -----------------------------------------------------------------------


def get_options(session: Session, publication_id: int) -> ThreadsPublicationOptions:
    """Stored options, or the defaults (not added to the session)."""
    stored = session.get(ThreadsPublicationOptions, publication_id)
    if stored is not None:
        return stored
    return ThreadsPublicationOptions(publication_id=publication_id, alt_text=None)


def _content_of(session: Session, publication: Publication) -> Content | None:
    if publication.content_id is None:
        return None
    return session.get_one(Content, publication.content_id)


def _threads_publication(session: Session, publication_id: int) -> Publication:
    publication = get_publication_or_404(session, publication_id)
    account = session.get_one(Account, publication.account_id)
    if account.platform != Platform.THREADS:
        raise ConflictError(
            "platform_not_supported",
            "Threads options only apply to publications of Threads accounts.",
        )
    return publication


def get_threads_publisher(request: Request) -> "ThreadsPublisher":
    publisher = request.app.state.publishers.get(Platform.THREADS)
    assert isinstance(publisher, ThreadsPublisher)
    return publisher


def get_publish_context(request: Request) -> PublishContext:
    ctx: PublishContext = request.app.state.publish_context
    return ctx


PublisherDep = Annotated["ThreadsPublisher", Depends(get_threads_publisher)]
ContextDep = Annotated[PublishContext, Depends(get_publish_context)]


def options_to_read(
    session: Session,
    publication: Publication,
    publisher: "ThreadsPublisher",
    ctx: PublishContext,
) -> ThreadsPublicationOptionsRead:
    content = _content_of(session, publication)
    kind = threads_media_kind(content)
    options = get_options(session, publication.id)
    text = build_text(publication, content)
    problems = [
        problem
        for problem in publisher.check(session, publication, ctx).problems
        if problem.code not in CONNECTION_CODES
    ]
    return ThreadsPublicationOptionsRead(
        media_kind=kind.value if kind is not None else None,
        text=text,
        text_length=text_length(text),
        text_links=text_links(text),
        alt_text=options.alt_text if kind in MEDIA_KINDS else None,
        editable=publication.status in EDITABLE_STATUSES,
        media_delivery_required=kind in MEDIA_KINDS,
        media_delivery_configured=publisher.delivery.configured(),
        problems=[
            PublishProblemRead(code=p.code, message=p.message, field=p.field)
            for p in problems
        ],
        limits=ThreadsTextLimitsRead(
            text_characters=TEXT_MAX_CHARACTERS,
            text_links=TEXT_MAX_LINKS,
            alt_text_characters=ALT_TEXT_MAX_CHARACTERS,
        ),
    )


@router.get(
    "/publications/{publication_id}/threads-options",
    response_model=ThreadsPublicationOptionsRead,
)
def get_threads_options(
    publication_id: int,
    session: SessionDep,
    publisher: PublisherDep,
    ctx: ContextDep,
) -> ThreadsPublicationOptionsRead:
    """Options, exact text and local problems; no network."""
    publication = _threads_publication(session, publication_id)
    return options_to_read(session, publication, publisher, ctx)


def _option_error(code: str, message: str) -> AppError:
    return AppError(
        422, code, message, fields=[{"field": "alt_text", "message": message}]
    )


@router.put(
    "/publications/{publication_id}/threads-options",
    response_model=ThreadsPublicationOptionsRead,
)
def save_threads_options(
    publication_id: int,
    body: ThreadsPublicationOptionsWrite,
    session: SessionDep,
    publisher: PublisherDep,
    ctx: ContextDep,
) -> ThreadsPublicationOptionsRead:
    publication = _threads_publication(session, publication_id)
    ensure_editable(publication)
    kind = threads_media_kind(_content_of(session, publication))
    alt_text = (body.alt_text or "").strip() or None
    if alt_text is not None and kind not in MEDIA_KINDS:
        raise _option_error(
            "threads_option_not_applicable",
            "Alt text only applies to images and videos.",
        )
    if alt_text is not None and len(alt_text) > ALT_TEXT_MAX_CHARACTERS:
        raise _option_error("threads_alt_text_invalid", ALT_TEXT_INVALID_MESSAGE)
    options = session.get(ThreadsPublicationOptions, publication_id)
    if options is None:
        if alt_text is not None:
            session.add(
                ThreadsPublicationOptions(
                    publication_id=publication_id,
                    alt_text=alt_text,
                    updated_at=utc_now(),
                )
            )
            session.commit()
    elif options.alt_text != alt_text:
        options.alt_text = alt_text
        options.updated_at = utc_now()
        session.commit()
    return options_to_read(session, publication, publisher, ctx)


# --- Publisher ---------------------------------------------------------------------


@dataclass(frozen=True)
class ThreadsPublishSettings:
    """Waits and limits of a Threads execution (research.md §10, §12, §13)."""

    sleep: Callable[[float], None] = time.sleep
    # Waits between container status reads after the immediate first read: these,
    # then the interval repeatedly, up to the timeout of each kind.
    text_waits: tuple[float, ...] = (2.0, 5.0, 10.0, 15.0)
    text_interval: float = 15.0
    text_timeout: float = 60.0
    image_waits: tuple[float, ...] = (2.0, 5.0, 10.0, 15.0)
    image_interval: float = 30.0
    image_timeout: float = 3 * 60.0
    video_waits: tuple[float, ...] = (10.0, 20.0, 30.0)
    video_interval: float = 60.0
    video_timeout: float = 5 * 60.0
    # Read-only checks after an inconclusive threads_publish (0, 5, 15, 30, 60 s).
    uncertain_waits: tuple[float, ...] = (0.0, 5.0, 10.0, 15.0, 30.0)
    # Retries of the permalink read only.
    permalink_waits: tuple[float, ...] = (2.0, 5.0)
    container_max_age: timedelta = timedelta(hours=23)
    # Slices in which long waits are split, to notice a shutdown.
    sleep_slice: float = 1.0
    clock: Callable[[], datetime] = utc_now


@dataclass(frozen=True)
class ThreadsPayload:
    """What the core treats as an opaque payload. Contains no secrets."""

    account_id: int
    threads_user_id: str
    username: str
    media_kind: ThreadsMediaKind
    text: str
    alt_text: str | None
    content_type: str | None
    source: bytes | Path | None
    size: int
    quota_unavailable: bool


@dataclass(frozen=True)
class DeliveredMedia:
    """The bytes media delivery uploads for an image or a video (no secrets)."""

    source: bytes | Path
    content_type: str
    size: int
    delivered_format: str
    converted: bool
    # Video requirements not verified locally and left to Threads.
    delegated_checks: list[str] | None


def _account_label(connection: Any) -> str:
    if connection is None:
        return "Not connected"
    return f"{connection.username} ({connection.threads_user_id})"


def _file_label(content: Content) -> str:
    label = f"{content.original_filename} ({content.size_bytes / 1_000_000:.1f} MB)"
    # A static WebP is sent as a lossless PNG copy (research §7).
    return f"{label} → sent as PNG" if content.media_format == "webp" else label


class ThreadsPublisher:
    # Threads publishes text posts without any media.
    accepts_text_only = True

    def __init__(
        self,
        gateway: ThreadsGateway,
        credential_store: CredentialStore,
        delivery: TemporaryMediaService,
        settings: ThreadsPublishSettings | None = None,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.delivery = delivery
        self.settings = settings or ThreadsPublishSettings()

    # --- Local checks (no network) ---------------------------------------------

    @staticmethod
    def _file_ready(ctx: PublishContext, content: Content) -> bool:
        if not file_available(ctx.storage, content):
            return False
        path = ctx.storage.resolve(content.storage_path)
        return path.stat().st_size == content.size_bytes

    @staticmethod
    def _video_check(path: Path, content: Content) -> VideoCheck:
        return video_problems(
            content.media_format,
            content.size_bytes,
            media.probe_video_streams(path),
            media.moov_before_mdat(path),
        )

    def _media_problems(
        self, ctx: PublishContext, content: Content, kind: ThreadsMediaKind
    ) -> list[PublishProblem]:
        """Local compatibility of the file that would really be sent."""
        if not self._file_ready(ctx, content):
            return [PublishProblem("media_unavailable", MEDIA_UNAVAILABLE_MESSAGE)]
        path = ctx.storage.resolve(content.storage_path)
        if kind == ThreadsMediaKind.IMAGE:
            return image_problems(path, content.media_format)
        return self._video_check(path, content).problems

    def check(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PublishCheck:
        content = _content_of(session, publication)
        kind = threads_media_kind(content)
        options = get_options(session, publication.id)
        connection = get_connection(session, publication.account_id)
        text = build_text(publication, content)
        problems: list[PublishProblem] = []
        if kind is None:
            problems.append(
                PublishProblem("threads_media_unsupported", UNSUPPORTED_MESSAGE)
            )
        else:
            if content is not None:
                problems.extend(self._media_problems(ctx, content, kind))
            problems.extend(text_problems(text, kind))
        if (
            options.alt_text is not None
            and len(options.alt_text) > ALT_TEXT_MAX_CHARACTERS
        ):
            problems.append(
                PublishProblem(
                    "threads_alt_text_invalid", ALT_TEXT_INVALID_MESSAGE, "alt_text"
                )
            )
        if kind in MEDIA_KINDS and not self.delivery.configured():
            problems.append(
                PublishProblem(
                    "media_delivery_not_configured",
                    DELIVERY_NOT_CONFIGURED_MESSAGE,
                    status_code=503,
                )
            )
        if connection is None:
            problems.append(
                PublishProblem("threads_not_connected", NOT_CONNECTED_MESSAGE)
            )
        elif connection.status != ThreadsConnectionStatus.CONNECTED:
            problems.append(
                PublishProblem("threads_reconnect_required", RECONNECT_MESSAGE)
            )
        summary = [
            ("Post type", POST_TYPES[kind] if kind is not None else "Unsupported"),
            ("Threads account", _account_label(connection)),
            ("Text", text or "(empty)"),
        ]
        if kind in MEDIA_KINDS and content is not None:
            summary.append(("Alt text", options.alt_text or "None"))
            summary.append(("File", _file_label(content)))
        return PublishCheck(problems, summary)

    # --- Preflight (reads allowed, no publishing effects) ----------------------

    def prepare(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PreparedPublication:
        """Credentials, identity, quota and the previous container are only read.
        Nothing is uploaded and no container is created here (FR-025)."""
        if get_connection(session, publication.account_id) is None:
            raise AppError(409, "threads_not_connected", NOT_CONNECTED_MESSAGE)
        verify_identity(
            session, self.credential_store, self.gateway, publication.account_id
        )
        connection = get_connection(session, publication.account_id)
        assert connection is not None
        token = get_valid_credentials(
            session, self.credential_store, self.gateway, publication.account_id
        )
        content = _content_of(session, publication)
        kind = threads_media_kind(content)
        if kind is None:
            raise AppError(409, "threads_media_unsupported", UNSUPPORTED_MESSAGE)
        text = build_text(publication, content)
        options = get_options(session, publication.id)
        alt_text = options.alt_text if kind in MEDIA_KINDS else None
        # Local preparation of what will really be sent; nothing leaves the process.
        delivered = self._delivered_media(ctx, content, kind)

        quota = self._check_quota(
            session, connection, token.access_token, publication.account_id
        )
        self._previous_container(session, publication, connection, token.access_token)
        payload = ThreadsPayload(
            account_id=publication.account_id,
            threads_user_id=connection.threads_user_id,
            username=connection.username,
            media_kind=kind,
            text=text,
            alt_text=alt_text,
            content_type=delivered.content_type if delivered else None,
            source=delivered.source if delivered else None,
            size=delivered.size if delivered else 0,
            quota_unavailable=quota is None,
        )
        submitted: dict[str, Any] = {
            "media_kind": kind.value,
            "text": text,
            "alt_text": alt_text,
            "threads_user_id": connection.threads_user_id,
            "username": connection.username,
            "quota_checked": quota is not None,
        }
        if quota is not None:
            submitted.update(quota)
        if delivered is not None and content is not None:
            submitted.update(
                {
                    "file_name": content.original_filename,
                    "file_size": content.size_bytes,
                    "delivered_format": delivered.delivered_format,
                    "delivered_size": delivered.size,
                    "converted": delivered.converted,
                }
            )
            if delivered.delegated_checks is not None:
                submitted["delegated_checks"] = delivered.delegated_checks
        return PreparedPublication(
            publication_id=publication.id,
            file_path=ctx.storage.resolve(content.storage_path)
            if content is not None
            else None,
            total_bytes=delivered.size if delivered else 0,
            submitted=submitted,
            payload=payload,
        )

    def _delivered_media(
        self, ctx: PublishContext, content: Content | None, kind: ThreadsMediaKind
    ) -> "DeliveredMedia | None":
        """What media delivery will upload: the original JPEG/PNG/video file or a PNG
        derived in memory from a static WebP. Raises before any upload."""
        if content is None or kind == ThreadsMediaKind.TEXT:
            return None
        if not self._file_ready(ctx, content):
            raise AppError(409, "media_unavailable", MEDIA_UNAVAILABLE_MESSAGE)
        path = ctx.storage.resolve(content.storage_path)
        if kind == ThreadsMediaKind.IMAGE:
            try:
                image = prepare_threads_image(path, content.media_format)
            except ImageIncompatible as error:
                raise AppError(
                    409, "threads_image_incompatible", error.message
                ) from None
            return DeliveredMedia(
                source=image.data if image.data is not None else path,
                content_type=image.content_type,
                size=image.size,
                delivered_format=image.delivered_format,
                converted=image.converted,
                delegated_checks=None,
            )
        check = self._video_check(path, content)
        if check.problems:
            first = check.problems[0]
            raise AppError(first.status_code, first.code, first.message)
        return DeliveredMedia(
            source=path,
            content_type=CONTENT_TYPES[content.media_format],  # type: ignore[index]
            size=content.size_bytes,
            delivered_format=content.media_format,
            converted=False,
            delegated_checks=list(check.delegated_checks),
        )

    def _mark_reconnect(self, session: Session, account_id: int) -> None:
        connection = get_connection(session, account_id)
        if connection is not None:
            mark_reconnect_required(session, connection, self.gateway.clock())

    def _check_quota(
        self, session: Session, connection: Any, access_token: str, account_id: int
    ) -> dict[str, Any] | None:
        """Meta's own numbers are the only source (research §9). None when the quota
        could not be read temporarily: publishing continues with a warning."""
        try:
            limit = self.gateway.publishing_limit(
                connection.threads_user_id, access_token
            )
        except (ThreadsTokenInvalid, ThreadsPermissionDenied):
            self._mark_reconnect(session, account_id)
            raise AppError(
                409, "threads_reconnect_required", RECONNECT_MESSAGE
            ) from None
        except ThreadsUnavailable:
            logger.warning("Could not read the Threads publishing limit (temporary).")
            return None
        except ThreadsError:
            # A shape not understood or a rejection of a documented read: possible
            # contract drift, never treated as "unavailable".
            raise AppError(
                502, "threads_unexpected_response", UNEXPECTED_LIMIT_MESSAGE
            ) from None
        if limit.usage >= limit.total:
            raise AppError(409, "threads_publishing_limit_reached", LIMIT_MESSAGE)
        quota: dict[str, Any] = {
            "quota_usage": limit.usage,
            "quota_total": limit.total,
        }
        if limit.duration is not None:
            quota["quota_duration"] = limit.duration
        return quota

    def _previous_container(
        self,
        session: Session,
        publication: Publication,
        connection: Any,
        access_token: str,
    ) -> None:
        """Read the latest recent container of this publication (research §11): a
        container already published blocks a new attempt."""
        since = self.settings.clock() - self.settings.container_max_age
        run = session.scalars(
            select(ThreadsPublishRun)
            .where(
                ThreadsPublishRun.publication_id == publication.id,
                ThreadsPublishRun.container_id.is_not(None),
                ThreadsPublishRun.container_created_at > since,
            )
            .order_by(
                ThreadsPublishRun.container_created_at.desc(),
                ThreadsPublishRun.attempt_id.desc(),
            )
            .limit(1)
        ).first()
        if run is None or run.container_id is None:
            return
        try:
            state = self.gateway.container_status(run.container_id, access_token)
        except (ThreadsTokenInvalid, ThreadsPermissionDenied):
            self._mark_reconnect(session, publication.account_id)
            raise AppError(
                409, "threads_reconnect_required", RECONNECT_MESSAGE
            ) from None
        except (ThreadsUnavailable, ThreadsUnexpectedResponse):
            # Never publish without being able to rule out a duplicate.
            raise AppError(503, "threads_unavailable", UNAVAILABLE_MESSAGE) from None
        except ThreadsError:
            return  # Unknown to Meta: a new container is created.
        if state.status == PUBLISHED:
            raise AppError(409, "threads_already_published", ALREADY_PUBLISHED_MESSAGE)

    # --- Execution -------------------------------------------------------------

    def _update_run(self, ctx: PublishContext, attempt_id: int, **values: Any) -> bool:
        values["updated_at"] = self.settings.clock()
        try:
            with ctx.session_factory() as session:
                run = session.get_one(ThreadsPublishRun, attempt_id)
                for key, value in values.items():
                    setattr(run, key, value)
                session.commit()
        except SQLAlchemyError:
            logger.warning("Could not save the Threads run of attempt %s.", attempt_id)
            return False
        return True

    def _create_run(
        self, ctx: PublishContext, attempt_id: int, prepared: PreparedPublication
    ) -> None:
        payload = prepared.payload
        assert isinstance(payload, ThreadsPayload)
        with ctx.session_factory() as session:
            session.add(
                ThreadsPublishRun(
                    attempt_id=attempt_id,
                    publication_id=prepared.publication_id,
                    media_kind=payload.media_kind.value,
                    phase=ThreadsPublishPhase.PREPARING,
                    updated_at=self.settings.clock(),
                )
            )
            session.commit()

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
            if error.code in ("threads_not_connected", "threads_reconnect_required"):
                raise PublishFailure(
                    "threads_reconnect_required", RECONNECT_MESSAGE, determined=True
                ) from None
            if error.code == "credential_store_unavailable":
                raise PublishFailure(
                    "credential_store_unavailable", error.message, determined=True
                ) from None
            raise PublishFailure(
                "threads_unavailable", UNAVAILABLE_MESSAGE, determined=True
            ) from None
        return token.access_token

    def _failure(
        self,
        ctx: PublishContext,
        payload: ThreadsPayload,
        error: ThreadsError,
        default_code: str,
        default_message: str,
    ) -> PublishFailure:
        """Map a gateway error before `threads_publish` succeeded to a determined
        failure."""
        if isinstance(error, (ThreadsTokenInvalid, ThreadsPermissionDenied)):
            self._mark_reconnect_new_session(ctx, payload.account_id)
            return PublishFailure(
                "threads_reconnect_required",
                f"Threads rejected the credentials; reconnect the account. "
                f"{NOT_PUBLISHED}",
                determined=True,
            )
        if isinstance(error, ThreadsUnavailable):
            return PublishFailure(
                "threads_unavailable", UNAVAILABLE_MESSAGE, determined=True
            )
        if isinstance(error, ThreadsRejected) and error.link_limit_exceeded:
            return PublishFailure(
                "threads_text_invalid",
                f"Threads rejected the text because it has more than "
                f"{TEXT_MAX_LINKS} links. {NOT_PUBLISHED}",
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

    def _poll_plan(self, kind: ThreadsMediaKind) -> tuple[Iterator[float], float]:
        settings = self.settings
        waits, interval, timeout = {
            ThreadsMediaKind.TEXT: (
                settings.text_waits,
                settings.text_interval,
                settings.text_timeout,
            ),
            ThreadsMediaKind.IMAGE: (
                settings.image_waits,
                settings.image_interval,
                settings.image_timeout,
            ),
            ThreadsMediaKind.VIDEO: (
                settings.video_waits,
                settings.video_interval,
                settings.video_timeout,
            ),
        }[kind]

        def plan() -> Iterator[float]:
            yield from waits
            while True:
                yield interval

        return plan(), timeout

    @staticmethod
    def _container_error(error_message: str | None) -> PublishFailure:
        """A container in `ERROR` (research §10); nothing was published."""
        if error_message == "FAILED_DOWNLOADING_VIDEO":
            return PublishFailure(
                "threads_media_fetch_failed",
                f"Threads could not download the media. {NOT_PUBLISHED}",
                determined=True,
            )
        if error_message is not None and error_message.startswith(
            ("INVALID_", "FAILED_PROCESSING_")
        ):
            return PublishFailure(
                "threads_media_rejected",
                f"Threads rejected the media. {NOT_PUBLISHED}",
                determined=True,
            )
        return PublishFailure(
            "threads_processing_failed",
            f"Threads could not process the post. {NOT_PUBLISHED}",
            determined=True,
        )

    def _wait_until_ready(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: ThreadsPayload,
        container_id: str,
        created_at: datetime,
        token: str,
        reporter: ProgressReporter,
    ) -> str:
        """Read the container at once and, only while Threads reports processing,
        again after bounded waits per kind. A container is publishable only when it
        is FINISHED *and* at least MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS old; a
        younger FINISHED container waits only the time it lacks and is read again,
        so an ERROR or EXPIRED during that wait still stops the publication."""
        waits, limit = self._poll_plan(payload.media_kind)
        while True:
            try:
                state = self.gateway.container_status(container_id, token)
                status = state.status
            except (ThreadsUnavailable, ThreadsUnexpectedResponse):
                status = None  # Read again after the next wait.
            except ThreadsError as error:
                raise self._failure(
                    ctx,
                    payload,
                    error,
                    "threads_processing_failed",
                    f"Threads could not process the post. {NOT_PUBLISHED}",
                ) from None
            if status is not None:
                self._update_run(
                    ctx,
                    attempt_id,
                    container_status=status[:20],
                    container_error=state.error_message,
                )
                if status == PUBLISHED:
                    return status
                if status == FINISHED:
                    missing = MIN_CONTAINER_AGE_BEFORE_PUBLISH_SECONDS - self._age(
                        created_at
                    )
                    if missing <= 0:
                        return status
                    self._wait_or_stop(missing, created_at, limit, reporter)
                    continue
                if status == ERROR:
                    raise self._container_error(state.error_message)
                if status == EXPIRED:
                    raise PublishFailure(
                        "threads_container_expired",
                        "The prepared Threads post expired before it was published.",
                        determined=True,
                    )
            self._wait_or_stop(next(waits), created_at, limit, reporter)

    def _age(self, created_at: datetime) -> float:
        return (self.settings.clock() - created_at).total_seconds()

    def _wait_or_stop(
        self,
        seconds: float,
        created_at: datetime,
        limit: float,
        reporter: ProgressReporter,
    ) -> None:
        """Wait before the next container read, within the processing timeout of
        the kind (measured from the container creation) and noticing a shutdown.
        `threads_publish` has not been called: both failures are determined."""
        if self._age(created_at) + seconds > limit:
            raise PublishFailure(
                "threads_processing_timeout",
                f"Threads took too long to prepare the post. {NOT_PUBLISHED}",
                determined=True,
            )
        if not self._wait(seconds, reporter):
            raise PublishFailure(
                "interrupted",
                "The publication was interrupted because AutoPublisher stopped. "
                f"{NOT_PUBLISHED}",
                determined=True,
            )

    def _read_status_once(self, container_id: str, token: str) -> str | None:
        try:
            return self.gateway.container_status(container_id, token).status
        except ThreadsError:
            return None

    def _uncertain(self, payload: ThreadsPayload, started: datetime) -> PublishFailure:
        start = payload.text.replace("\n", " ").strip()
        if len(start) > 60:
            start = start[:57] + "..."
        message = UNCERTAIN_MESSAGE.format(
            username=payload.username,
            time=started.strftime("%Y-%m-%d %H:%M"),
            start=start or payload.media_kind.value,
        )
        return PublishFailure(
            "threads_publish_uncertain", message[:500], determined=False
        )

    def _publish(
        self,
        ctx: PublishContext,
        payload: ThreadsPayload,
        container_id: str,
        token: str,
        started: datetime,
    ) -> str | None:
        """`threads_publish`, called exactly once and never repeated. Returns the
        post ID, or None when only the container confirmed the publication."""
        try:
            return self.gateway.publish(payload.threads_user_id, container_id, token)
        except (ThreadsUnavailable, ThreadsUnexpectedResponse):
            # Inconclusive: only read the original container, never publish again.
            for wait in self.settings.uncertain_waits:
                if wait:
                    self.settings.sleep(wait)
                if self._read_status_once(container_id, token) == PUBLISHED:
                    return None
            raise self._uncertain(payload, started) from None
        except ThreadsError as error:
            # An explicit rejection: confirm with one read before calling it final.
            if self._read_status_once(container_id, token) == PUBLISHED:
                return None
            raise self._failure(
                ctx,
                payload,
                error,
                "threads_publish_failed",
                f"Threads rejected the publication. {NOT_PUBLISHED}",
            ) from None

    def upload(
        self,
        prepared: PreparedPublication,
        reporter: ProgressReporter,
        ctx: PublishContext,
    ) -> PublishOutcome:
        payload = prepared.payload
        assert isinstance(payload, ThreadsPayload)
        attempt_id = reporter.attempt_id
        self._create_run(ctx, attempt_id, prepared)
        try:
            return self._run(ctx, attempt_id, payload, reporter)
        except BaseException:
            self._update_run(ctx, attempt_id, phase=ThreadsPublishPhase.FAILED)
            raise

    def _run(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: ThreadsPayload,
        reporter: ProgressReporter,
    ) -> PublishOutcome:
        token = self._token(ctx, payload.account_id)
        media_url = None
        if payload.media_kind in MEDIA_KINDS:
            media_url = self._deliver(ctx, attempt_id, payload, reporter)
        container_id, created_at = self._create_container(
            ctx, attempt_id, payload, token, reporter, media_url
        )
        status = self._wait_until_ready(
            ctx, attempt_id, payload, container_id, created_at, token, reporter
        )
        if status == PUBLISHED:
            # Never expected for a new container; never publish it again.
            self._update_run(ctx, attempt_id, phase=ThreadsPublishPhase.SUCCEEDED)
            return self._identity_unavailable(payload, self.settings.clock())

        started = self.settings.clock()
        if (
            not self._update_run(
                ctx,
                attempt_id,
                phase=ThreadsPublishPhase.PUBLISHING,
                publish_started_at=started,
            )
            or not reporter.enter_finalizing()
        ):
            raise PublishFailure(
                "internal_error", WRITE_AHEAD_FAILED_MESSAGE, determined=True
            )
        post_id = self._publish(ctx, payload, container_id, token, started)
        # From here the publication is determined: nothing can make it fail.
        self._update_run(ctx, attempt_id, phase=ThreadsPublishPhase.VERIFYING_RESULT)
        if post_id is None:
            outcome = self._identity_unavailable(payload, started)
        else:
            outcome = self._outcome(payload, post_id, token)
        self._update_run(
            ctx,
            attempt_id,
            phase=ThreadsPublishPhase.SUCCEEDED,
            container_status=PUBLISHED,
        )
        return outcome

    def _create_container(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: ThreadsPayload,
        token: str,
        reporter: ProgressReporter,
        media_url: SecretUrl | None,
    ) -> tuple[str, datetime]:
        """The single container of this attempt; its id and creation time are
        committed at once (the creation time is the origin of its minimum age). The
        signed media URL is only revealed into the form body of this request."""
        reporter.enter_processing()
        self._update_run(ctx, attempt_id, phase=ThreadsPublishPhase.CREATING_CONTAINER)
        url = media_url.reveal() if media_url is not None else None
        try:
            container_id = self.gateway.create_container(
                payload.threads_user_id,
                token,
                media_type=MEDIA_TYPES[payload.media_kind],
                text=payload.text,
                image_url=url if payload.media_kind == ThreadsMediaKind.IMAGE else None,
                video_url=url if payload.media_kind == ThreadsMediaKind.VIDEO else None,
                alt_text=payload.alt_text,
            )
        except ThreadsError as error:
            raise self._failure(
                ctx,
                payload,
                error,
                "threads_container_failed",
                f"Threads could not prepare the post. {NOT_PUBLISHED}",
            ) from None
        created_at = self.settings.clock()
        if not self._update_run(
            ctx,
            attempt_id,
            container_id=container_id,
            container_created_at=created_at,
            phase=ThreadsPublishPhase.PROCESSING_CONTAINER,
        ):
            # Without the id on record a later attempt could not rule out a
            # duplicate: never publish an unrecorded container.
            raise PublishFailure(
                "internal_error", WRITE_AHEAD_FAILED_MESSAGE, determined=True
            )
        return container_id, created_at

    def _deliver(
        self,
        ctx: PublishContext,
        attempt_id: int,
        payload: ThreadsPayload,
        reporter: ProgressReporter,
    ) -> SecretUrl:
        """Upload through the generic temporary media delivery: the object is
        registered (commit) before the upload, and the signed URL is created only
        after it finished, so the upload never consumes its lifetime."""
        self._update_run(ctx, attempt_id, phase=ThreadsPublishPhase.DELIVERING_MEDIA)
        assert payload.content_type is not None and payload.source is not None
        try:
            key = self.delivery.reserve(attempt_id, payload.content_type, payload.size)
            self.delivery.upload(key, payload.source, reporter.report_bytes)
            return self.delivery.public_url(key)
        except MediaDeliveryNotConfigured:
            raise PublishFailure(
                "media_delivery_not_configured",
                DELIVERY_NOT_CONFIGURED_MESSAGE,
                determined=True,
            ) from None
        except MediaDeliveryFailed:
            raise PublishFailure(
                "media_delivery_failed",
                f"The media could not be made available to Threads. {NOT_PUBLISHED}",
                determined=True,
            ) from None

    def _quota_warnings(self, payload: ThreadsPayload) -> list[dict[str, str]]:
        if not payload.quota_unavailable:
            return []
        return [{"code": "quota_unavailable", "message": QUOTA_UNAVAILABLE_MESSAGE}]

    def _identity_unavailable(
        self, payload: ThreadsPayload, started: datetime
    ) -> PublishOutcome:
        message = IDENTITY_UNAVAILABLE_MESSAGE.format(
            username=payload.username, time=started.strftime("%Y-%m-%d %H:%M")
        )
        return PublishOutcome(
            external_id=None,
            external_url=None,
            warnings=[
                {"code": "remote_identity_unavailable", "message": message},
                *self._quota_warnings(payload),
            ],
        )

    def _published_media(self, post_id: str, token: str) -> PublishedMedia | None:
        """Bounded retries of this read only; it never raises (research §13)."""
        waits = self.settings.permalink_waits
        for try_number in range(len(waits) + 1):
            try:
                return self.gateway.published_media(post_id, token)
            except (ThreadsUnavailable, ThreadsUnexpectedResponse):
                if try_number < len(waits):
                    self.settings.sleep(waits[try_number])
            except Exception as exc:  # The post is published: never fail here.
                logger.info("Could not read the Threads post (%s).", type(exc).__name__)
                return None
        return None

    @staticmethod
    def _details(media: PublishedMedia | None) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if media is not None and media.permalink is not None:
            details["permalink"] = media.permalink
        if media is not None and media.timestamp is not None:
            details["threads_timestamp"] = media.timestamp
        return details

    def _outcome(
        self, payload: ThreadsPayload, post_id: str, token: str
    ) -> PublishOutcome:
        """A post ID determines the success; the permalink is only best effort and a
        link is never built from the ID or the username."""
        media = self._published_media(post_id, token)
        permalink = media.permalink if media is not None else None
        warnings = self._quota_warnings(payload)
        if permalink is None:
            warnings.insert(
                0,
                {
                    "code": "permalink_unavailable",
                    "message": PERMALINK_UNAVAILABLE_MESSAGE,
                },
            )
        return PublishOutcome(
            external_id=post_id,
            external_url=permalink,
            details=self._details(media),
            warnings=warnings,
        )

    def refresh_details(
        self,
        prepared: PreparedPublication,
        outcome: PublishOutcome,
        ctx: PublishContext,
    ) -> PublishOutcome:
        """Try the permalink once more when it was missing (best effort). Only the
        details and warnings change; never the status nor `threads_publish`."""
        missing = any(w["code"] == "permalink_unavailable" for w in outcome.warnings)
        if outcome.external_id is None or not missing:
            return outcome
        payload = prepared.payload
        assert isinstance(payload, ThreadsPayload)
        token = self._token(ctx, payload.account_id)
        media = self.gateway.published_media(outcome.external_id, token)
        if media.permalink is None:
            return outcome
        return PublishOutcome(
            external_id=outcome.external_id,
            external_url=outcome.external_url,
            details={**outcome.details, **self._details(media)},
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
        """Delete temporary media after the outcome was saved, then sweep. A text
        post has no objects and gets no warning."""
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

    # --- Reconciliation ---------------------------------------------------------

    def arming_problems(
        self, session: Session, publication: Publication
    ) -> list[PublishProblem]:
        """Threads adds no rule to arming auto-publish."""
        return []

    def reconcile(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> Reconciliation | None:
        """One read of the original container of an uncertain attempt (research
        §12). Only `PUBLISHED` settles it, as published without remote identity;
        never publishes, never creates a container and never lists recent posts."""
        run = session.get(ThreadsPublishRun, attempt.id)
        if (
            run is None
            or run.container_id is None
            or run.publish_started_at is None
            or run.phase
            not in (
                ThreadsPublishPhase.PUBLISHING,
                ThreadsPublishPhase.VERIFYING_RESULT,
                ThreadsPublishPhase.FAILED,
            )
        ):
            return None
        token = get_valid_credentials(
            session, self.credential_store, self.gateway, publication.account_id
        )
        state = self.gateway.container_status(run.container_id, token.access_token)
        if state.status != PUBLISHED:
            return None
        connection = get_connection(session, publication.account_id)
        username = connection.username if connection is not None else "the account"
        run.phase = ThreadsPublishPhase.SUCCEEDED
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
