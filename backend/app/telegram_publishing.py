"""Telegram publisher: preflight and publishing of text posts, one image or one MP4
video with caption in the account's broadcast channel (specs/015-telegram-user-
publishing, contracts/api.md).

Everything Telegram-specific about running a publication lives here; the generic core
only talks to `TelegramPublisher` through the `Publisher` protocol.

Never publishing a duplicate (research §8):
- each attempt has a `random_id`, chosen in `prepare()` and persisted by the core in
  `submitted` before anything is sent;
- the next attempt of a publication whose last attempt is uncertain reuses that
  `random_id`, so Telegram returns the original message instead of a new one;
- only an `UpdateMessageID` for that `random_id` confirms a success; otherwise the
  attempt stays uncertain (`telegram_unconfirmed`).
"""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_telegram_app_file
from app.content_files import effective_size
from app.credential_store import CredentialStore, CredentialStoreUnavailable
from app.db import utc_now
from app.errors import AppError
from app.models import (
    Content,
    MediaFormat,
    MediaType,
    Platform,
    Publication,
    PublicationAttempt,
    TelegramConnection,
    TelegramConnectionStatus,
)
from app.publications import (
    description_with_hashtags,
    effective_metadata,
    needs_manual_review,
)
from app.publishing import (
    INTERRUPTED_MESSAGE,
    PreparedPublication,
    ProgressReporter,
    PublishCheck,
    PublishContext,
    PublishFailure,
    PublishOutcome,
    PublishProblem,
    Reconciliation,
    UserActionCompleted,
    UserActionFailed,
    check_publish_file,
    prepare_publish_file,
)
from app.telegram_connections import (
    NOT_CONFIGURED_MESSAGE,
    NOT_CONNECTED_MESSAGE,
    RATE_LIMITED_MESSAGE,
    RECONNECT_MESSAGE,
    SessionWaitStopped,
    TelegramNotConfigured,
    account_session,
    get_connection,
    load_session,
    load_telegram_app_config,
    mark_reconnect_required,
)
from app.telegram_gateway import (
    SendSpec,
    TelegramAppConfig,
    TelegramChannel,
    TelegramChannelUnavailable,
    TelegramError,
    TelegramGateway,
    TelegramMediaRejected,
    TelegramRateLimited,
    TelegramStopped,
    TelegramTextRejected,
    TelegramUnauthorized,
    TelegramUnconfirmed,
)

logger = logging.getLogger(__name__)

# Limits of a regular account (research §10); counted in UTF-16 code units.
TEXT_MAX = 4096
CAPTION_MAX = 1024
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_MAX_SIDES = 10000
PHOTO_MAX_RATIO = 20
VIDEO_MAX_BYTES = 2000 * 1024 * 1024
PHOTO_FORMATS = (MediaFormat.JPEG, MediaFormat.PNG, MediaFormat.WEBP)

POST_TYPES = {"text": "Text", "image": "Image", "video": "Video"}

UNSUPPORTED_MESSAGE = (
    "Telegram publishes text, one JPEG, PNG or WEBP image, or one MP4 video."
)
PHOTO_DIMENSIONS_MESSAGE = (
    "Telegram cannot publish this image as a photo: width plus height must be at "
    f"most {PHOTO_MAX_SIDES} pixels and the aspect ratio at most {PHOTO_MAX_RATIO}:1."
)
PHOTO_TOO_LARGE_MESSAGE = "Telegram photos can be at most 10 MB."
VIDEO_TOO_LARGE_MESSAGE = "Telegram videos can be at most 2000 MB."
FILE_UNAVAILABLE_MESSAGE = (
    "The media file of this content is missing. Import it again before publishing."
)
TEXT_EMPTY_MESSAGE = "A Telegram text post needs some text."
TEXT_TOO_LONG_MESSAGE = (
    "Telegram allows at most {limit} characters here; this text has {length}."
)
CHANNEL_REQUIRED_MESSAGE = "Choose the Telegram channel of this account first."
CHANNEL_UNAVAILABLE_MESSAGE = (
    "The Telegram channel is not accessible or this account can no longer post in "
    "it. Check the channel and choose it again."
)
TEXT_REJECTED_MESSAGE = "Telegram rejected the text or caption of this publication."
MEDIA_REJECTED_MESSAGE = "Telegram rejected the media file of this publication."
UNAVAILABLE_MESSAGE = (
    "Telegram could not be reached, so nothing was published. Try again later."
)
UNCONFIRMED_MESSAGE = (
    "Telegram did not confirm this message, so it may have been published. Check "
    "the channel before publishing again; publishing again reuses the same message "
    "identity, so Telegram will not duplicate it."
)
STORE_UNAVAILABLE_MESSAGE = (
    "The system's secure credential storage is not available. Unlock it and try again."
)


def utf16_length(text: str) -> int:
    """Length as Telegram counts it (UTF-16 code units)."""
    return len(text.encode("utf-16-le")) // 2


def post_type(content: Content | None) -> str | None:
    """ "text", "image" or "video"; None when Telegram cannot publish it."""
    if content is None:
        return "text"
    if content.media_type == MediaType.IMAGE and content.media_format in PHOTO_FORMATS:
        return "image"
    if (
        content.media_type == MediaType.VIDEO
        and content.media_format == MediaFormat.MP4
    ):
        return "video"
    return None


def build_text(publication: Publication, content: Content | None) -> str:
    """Effective description and hashtags, exactly as shown; the title is not sent."""
    _, description, hashtags = effective_metadata(publication, content)
    return description_with_hashtags(description, hashtags)


def _content_of(session: Session, publication: Publication) -> Content | None:
    if publication.content_id is None:
        return None
    return session.get(Content, publication.content_id)


def _media_problems(content: Content, kind: str) -> list[PublishProblem]:
    # Limits apply to the file really sent (the clean copy when sanitized).
    size = effective_size(content)
    if kind == "image":
        if size > PHOTO_MAX_BYTES:
            return [PublishProblem("telegram_file_too_large", PHOTO_TOO_LARGE_MESSAGE)]
        width, height = content.width or 0, content.height or 0
        if (
            width
            and height
            and (
                width + height > PHOTO_MAX_SIDES
                or max(width, height) > PHOTO_MAX_RATIO * min(width, height)
            )
        ):
            return [
                PublishProblem("telegram_media_unsupported", PHOTO_DIMENSIONS_MESSAGE)
            ]
    elif size > VIDEO_MAX_BYTES:
        return [PublishProblem("telegram_file_too_large", VIDEO_TOO_LARGE_MESSAGE)]
    return []


def _text_problems(text: str, kind: str) -> list[PublishProblem]:
    if kind == "text" and not text.strip():
        return [PublishProblem("telegram_text_invalid", TEXT_EMPTY_MESSAGE)]
    limit = TEXT_MAX if kind == "text" else CAPTION_MAX
    length = utf16_length(text)
    if length > limit:
        message = TEXT_TOO_LONG_MESSAGE.format(limit=limit, length=length)
        return [PublishProblem("telegram_text_too_long", message)]
    return []


def _channel_of(connection: TelegramConnection) -> TelegramChannel | None:
    if connection.channel_id is None or connection.channel_access_hash is None:
        return None
    return TelegramChannel(
        channel_id=connection.channel_id,
        access_hash=connection.channel_access_hash,
        title=connection.channel_title or "",
        username=connection.channel_username,
    )


def message_url(channel: TelegramChannel, message_id: int) -> str | None:
    """A link only for a public channel; private channels get none (research §11)."""
    if channel.username is None:
        return None
    return f"https://t.me/{channel.username}/{message_id}"


@dataclass(frozen=True)
class TelegramPayload:
    account_id: int
    config: TelegramAppConfig
    # The authorized session, in memory only for this execution.
    session: str = field(repr=False)
    channel: TelegramChannel
    spec: SendSpec
    random_id: int


class TelegramPublisher:
    accepts_text_only = True

    def __init__(
        self,
        *,
        gateway: TelegramGateway,
        credential_store: CredentialStore,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.clock = clock

    # --- Local checks (no network) ----------------------------------------------

    def check(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PublishCheck:
        content = _content_of(session, publication)
        kind = post_type(content)
        text = build_text(publication, content)
        connection = get_connection(session, publication.account_id)
        problems: list[PublishProblem] = []
        if kind is None:
            problems.append(
                PublishProblem("telegram_media_unsupported", UNSUPPORTED_MESSAGE)
            )
        else:
            if content is not None:
                _, file_problem = check_publish_file(
                    ctx.storage, content, FILE_UNAVAILABLE_MESSAGE
                )
                if file_problem is not None:
                    problems.append(file_problem)
                problems.extend(_media_problems(content, kind))
            problems.extend(_text_problems(text, kind))
        try:
            load_telegram_app_config(get_telegram_app_file())
        except TelegramNotConfigured:
            problems.append(
                PublishProblem(
                    "telegram_not_configured", NOT_CONFIGURED_MESSAGE, status_code=503
                )
            )
        if connection is None:
            problems.append(
                PublishProblem("telegram_not_connected", NOT_CONNECTED_MESSAGE)
            )
        else:
            if connection.status != TelegramConnectionStatus.CONNECTED:
                problems.append(
                    PublishProblem("telegram_reconnect_required", RECONNECT_MESSAGE)
                )
            if connection.channel_id is None:
                problems.append(
                    PublishProblem(
                        "telegram_channel_required", CHANNEL_REQUIRED_MESSAGE
                    )
                )
            problems.extend(self._rate_limit_problems(connection))
        summary = [
            ("Post type", POST_TYPES[kind] if kind is not None else "Unsupported"),
            (
                "Telegram channel",
                connection.channel_title
                if connection is not None and connection.channel_title
                else "None",
            ),
            ("Text" if kind == "text" else "Caption", text or "(empty)"),
        ]
        if content is not None:
            summary.append(("File", content.original_filename))
        return PublishCheck(problems, summary)

    def _rate_limit_problems(
        self, connection: TelegramConnection
    ) -> list[PublishProblem]:
        until = connection.flood_wait_until
        now = self.clock()
        if until is None or until <= now:
            return []
        seconds = max(int((until - now).total_seconds()), 1)
        return [
            PublishProblem(
                "telegram_rate_limited",
                RATE_LIMITED_MESSAGE.format(seconds=seconds),
                status_code=429,
            )
        ]

    def arming_problems(
        self, session: Session, publication: Publication
    ) -> list[PublishProblem]:
        """Auto-publish needs a connected account with a channel."""
        connection = get_connection(session, publication.account_id)
        if connection is None:
            return [PublishProblem("telegram_not_connected", NOT_CONNECTED_MESSAGE)]
        if connection.channel_id is None:
            return [
                PublishProblem("telegram_channel_required", CHANNEL_REQUIRED_MESSAGE)
            ]
        return []

    # --- Preflight (no network) ----------------------------------------------------

    def _random_id(self, session: Session, publication: Publication) -> int:
        """Reuse the `random_id` of an uncertain last attempt (research §8.2)."""
        latest = session.scalars(
            select(PublicationAttempt)
            .where(PublicationAttempt.publication_id == publication.id)
            .order_by(
                PublicationAttempt.started_at.desc(), PublicationAttempt.id.desc()
            )
            .limit(1)
        ).first()
        if (
            latest is not None
            and latest.platform == Platform.TELEGRAM
            and needs_manual_review(latest)
        ):
            previous = (latest.submitted or {}).get("telegram_random_id")
            if isinstance(previous, int) and previous > 0:
                return previous
        return secrets.randbits(63) or 1

    def prepare(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PreparedPublication:
        """Everything local: configuration, session, channel and the message
        identity. Telegram is not contacted here."""
        connection = get_connection(session, publication.account_id)
        if connection is None:
            raise AppError(409, "telegram_not_connected", NOT_CONNECTED_MESSAGE)
        if connection.status != TelegramConnectionStatus.CONNECTED:
            raise AppError(409, "telegram_reconnect_required", RECONNECT_MESSAGE)
        channel = _channel_of(connection)
        if channel is None:
            raise AppError(409, "telegram_channel_required", CHANNEL_REQUIRED_MESSAGE)
        try:
            config = load_telegram_app_config(get_telegram_app_file())
        except TelegramNotConfigured:
            raise AppError(
                503, "telegram_not_configured", NOT_CONFIGURED_MESSAGE
            ) from None
        try:
            session_string = load_session(self.credential_store, connection)
        except CredentialStoreUnavailable:
            raise AppError(
                503, "credential_store_unavailable", STORE_UNAVAILABLE_MESSAGE
            ) from None
        if session_string is None:
            mark_reconnect_required(session, connection, self.clock())
            raise AppError(409, "telegram_reconnect_required", RECONNECT_MESSAGE)
        content = _content_of(session, publication)
        kind = post_type(content)
        if kind is None:
            raise AppError(409, "telegram_media_unsupported", UNSUPPORTED_MESSAGE)
        text = build_text(publication, content)
        # The effective file (original or verified clean copy); nothing after this
        # step contacts Telegram before the claim.
        effective = (
            prepare_publish_file(ctx, content, FILE_UNAVAILABLE_MESSAGE)
            if content is not None
            else None
        )
        spec = SendSpec(
            kind=kind,
            text=text,
            file_path=effective.path if effective is not None else None,
            mime_type="video/mp4" if kind == "video" else None,
            width=content.width if content is not None else None,
            height=content.height if content is not None else None,
            duration_seconds=content.duration_seconds if content is not None else None,
        )
        random_id = self._random_id(session, publication)
        submitted: dict[str, Any] = {
            "post_type": kind,
            "channel_id": channel.channel_id,
            "channel_title": channel.title,
            "text_length": utf16_length(text),
            "telegram_random_id": random_id,
        }
        if content is not None and effective is not None:
            submitted["file_name"] = content.original_filename
            submitted["file_size"] = effective.size
        return PreparedPublication(
            publication_id=publication.id,
            file_path=effective.path if effective is not None else None,
            total_bytes=effective.size if effective is not None else 0,
            file_checksum=effective.checksum if effective is not None else None,
            submitted=submitted,
            payload=TelegramPayload(
                account_id=publication.account_id,
                config=config,
                session=session_string,
                channel=channel,
                spec=spec,
                random_id=random_id,
            ),
        )

    # --- Execution -------------------------------------------------------------------

    def upload(
        self,
        prepared: PreparedPublication,
        reporter: ProgressReporter,
        ctx: PublishContext,
    ) -> PublishOutcome:
        payload = prepared.payload
        assert isinstance(payload, TelegramPayload)
        try:
            with account_session(
                payload.account_id, wait=True, should_stop=reporter.should_stop
            ):
                result = self.gateway.publish(
                    payload.config,
                    payload.session,
                    payload.channel,
                    payload.spec,
                    payload.random_id,
                    on_progress=reporter.report_bytes,
                    should_stop=reporter.should_stop,
                    before_send=reporter.enter_finalizing,
                )
        except (SessionWaitStopped, TelegramStopped):
            raise PublishFailure(
                "interrupted", INTERRUPTED_MESSAGE, determined=True
            ) from None
        except TelegramError as error:
            raise self._failure(ctx, payload, error) from None
        self._refresh_connection(ctx, payload.account_id, result.channel)
        return PublishOutcome(
            external_id=str(result.message_id),
            external_url=message_url(result.channel, result.message_id),
            details={
                "channel_id": result.channel.channel_id,
                "channel_title": result.channel.title,
            },
        )

    def _failure(
        self, ctx: PublishContext, payload: TelegramPayload, error: TelegramError
    ) -> PublishFailure:
        if isinstance(error, TelegramUnconfirmed):
            if error.retry_after is not None:
                self._set_flood_wait(ctx, payload.account_id, error.retry_after)
            return PublishFailure(
                "telegram_unconfirmed", UNCONFIRMED_MESSAGE, determined=False
            )
        if isinstance(error, TelegramRateLimited):
            self._set_flood_wait(ctx, payload.account_id, error.seconds)
            return PublishFailure(
                "telegram_rate_limited",
                RATE_LIMITED_MESSAGE.format(seconds=error.seconds),
                determined=True,
            )
        if isinstance(error, TelegramUnauthorized):
            self._mark_reconnect(ctx, payload.account_id)
            return PublishFailure(
                "telegram_reconnect_required", RECONNECT_MESSAGE, determined=True
            )
        if isinstance(error, TelegramChannelUnavailable):
            return PublishFailure(
                "telegram_channel_unavailable",
                CHANNEL_UNAVAILABLE_MESSAGE,
                determined=True,
            )
        if isinstance(error, TelegramTextRejected):
            return PublishFailure(
                "telegram_text_invalid", TEXT_REJECTED_MESSAGE, determined=True
            )
        if isinstance(error, TelegramMediaRejected):
            return PublishFailure(
                "telegram_media_rejected", MEDIA_REJECTED_MESSAGE, determined=True
            )
        return PublishFailure(
            "telegram_unavailable", UNAVAILABLE_MESSAGE, determined=True
        )

    def _update_connection(
        self, ctx: PublishContext, account_id: int, **values: Any
    ) -> None:
        """Best effort: the outcome of the attempt never depends on it."""
        try:
            with ctx.session_factory() as session:
                connection = get_connection(session, account_id)
                if connection is None:
                    return
                for name, value in values.items():
                    setattr(connection, name, value)
                connection.updated_at = self.clock()
                session.commit()
        except Exception as error:
            logger.warning(
                "Telegram connection of account %s not updated (%s).",
                account_id,
                type(error).__name__,
            )

    def _set_flood_wait(
        self, ctx: PublishContext, account_id: int, seconds: int
    ) -> None:
        self._update_connection(
            ctx,
            account_id,
            flood_wait_until=self.clock() + timedelta(seconds=seconds),
        )

    def _mark_reconnect(self, ctx: PublishContext, account_id: int) -> None:
        self._update_connection(
            ctx, account_id, status=TelegramConnectionStatus.RECONNECT_REQUIRED
        )

    def _refresh_connection(
        self, ctx: PublishContext, account_id: int, channel: TelegramChannel
    ) -> None:
        """Keep the channel title and public username current (same channel only)."""
        try:
            with ctx.session_factory() as session:
                connection = get_connection(session, account_id)
                if connection is None or connection.channel_id != channel.channel_id:
                    return
                connection.channel_title = channel.title
                connection.channel_username = channel.username
                connection.updated_at = self.clock()
                session.commit()
        except Exception as error:
            logger.warning(
                "Telegram channel of account %s not refreshed (%s).",
                account_id,
                type(error).__name__,
            )

    def refresh_details(
        self,
        prepared: PreparedPublication,
        outcome: PublishOutcome,
        ctx: PublishContext,
    ) -> PublishOutcome:
        return outcome

    def release(
        self,
        prepared: PreparedPublication,
        ctx: PublishContext,
        *,
        attempt_id: int,
        succeeded: bool,
    ) -> list[dict[str, str]]:
        """Nothing temporary is created for Telegram."""
        return []

    def reconcile(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> Reconciliation | None:
        """No read-only reconciliation: the next attempt reuses the `random_id`."""
        return None

    def follow_up(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> UserActionCompleted | UserActionFailed | None:
        """Never called: Telegram publications never await user action."""
        return None
