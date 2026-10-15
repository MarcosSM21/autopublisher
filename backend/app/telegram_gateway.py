"""Telegram user account over MTProto, through Telethon (see
specs/015-telegram-user-publishing/research.md).

This is the only module that imports Telethon. Every operation is synchronous: it runs
`asyncio.run` in the calling thread with a short-lived client built from the stored
`StringSession`, and translates Telethon errors into the exceptions below. Callers must
serialize operations of one account (`telegram_connections.account_session`): a
session is never used by two clients at the same time.

Nothing here logs or returns a session, a login code, a password or the `api_hash`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from telethon import TelegramClient, errors, functions
from telethon.sessions import StringSession
from telethon.tl import types

logger = logging.getLogger(__name__)

# Telethon logs request details at INFO; keep only its warnings.
logging.getLogger("telethon").setLevel(logging.WARNING)

# Explicit client options (research §2, §9); never Telethon's defaults.
FLOOD_SLEEP_THRESHOLD = 5
REQUEST_RETRIES = 3
CONNECTION_RETRIES = 2
DEVICE_MODEL = "AutoPublisher"

# --- Values ----------------------------------------------------------------------


@dataclass(frozen=True)
class TelegramAppConfig:
    api_id: int
    api_hash: str = field(repr=False)


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: str
    display_name: str
    username: str | None


@dataclass(frozen=True)
class TelegramChannel:
    channel_id: str
    # Internal: locates the channel without a cached entity; never exposed.
    access_hash: str = field(repr=False)
    title: str
    username: str | None


@dataclass(frozen=True)
class PendingLogin:
    """A login waiting for its code; secret, kept in memory only."""

    session: str = field(repr=False)
    phone: str = field(repr=False)
    phone_code_hash: str = field(repr=False)


@dataclass(frozen=True)
class PasswordRequired:
    """The code was accepted; the account asks for its 2FA password."""

    session: str = field(repr=False)


@dataclass(frozen=True)
class SignedIn:
    session: str = field(repr=False)
    identity: TelegramIdentity


@dataclass(frozen=True)
class SendSpec:
    """What one publication sends: text only, or one photo or one MP4 video."""

    kind: str  # "text" | "image" | "video"
    text: str
    file_path: Path | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class SendResult:
    message_id: int
    channel: TelegramChannel


# --- Errors ----------------------------------------------------------------------


class TelegramError(Exception):
    """Base of the Telegram errors; messages never contain secrets."""


class TelegramUnauthorized(TelegramError):
    """The session is no longer authorized (revoked, expired, account deactivated)."""


class TelegramChannelUnavailable(TelegramError):
    """The channel does not exist, is not accessible or does not allow posting."""


class TelegramTextRejected(TelegramError):
    pass


class TelegramMediaRejected(TelegramError):
    pass


class TelegramRateLimited(TelegramError):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"Telegram asks to wait {seconds} seconds.")
        self.seconds = seconds


class TelegramLoginInvalid(TelegramError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TelegramUnavailable(TelegramError):
    """Network or Telegram failure before anything could have been published."""


class TelegramUnconfirmed(TelegramError):
    """The message may have been sent but Telegram did not confirm it.
    `retry_after`: seconds of a FloodWait received while repeating, if any."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("Telegram did not confirm the message.")
        self.retry_after = retry_after


class TelegramStopped(TelegramError):
    """AutoPublisher is stopping; nothing was sent."""


# --- Gateway contract --------------------------------------------------------------


class TelegramGateway(Protocol):
    def send_code(self, config: TelegramAppConfig, phone: str) -> PendingLogin: ...

    def sign_in_code(
        self, config: TelegramAppConfig, pending: PendingLogin, code: str
    ) -> SignedIn | PasswordRequired: ...

    def sign_in_password(
        self, config: TelegramAppConfig, session: str, password: str
    ) -> SignedIn: ...

    def get_me(self, config: TelegramAppConfig, session: str) -> TelegramIdentity: ...

    def log_out(self, config: TelegramAppConfig, session: str) -> None: ...

    def list_channels(
        self, config: TelegramAppConfig, session: str
    ) -> list[TelegramChannel]: ...

    def publish(
        self,
        config: TelegramAppConfig,
        session: str,
        channel: TelegramChannel,
        spec: SendSpec,
        random_id: int,
        *,
        on_progress: Callable[[int], None],
        should_stop: Callable[[], bool],
        before_send: Callable[[], bool],
    ) -> SendResult:
        """Check the channel, upload the file if any, then send one message with
        `random_id` (research §8). `before_send()` commits the uncertain stage; when
        it returns False nothing is sent. Raises `TelegramUnconfirmed` when the
        message may exist but Telegram did not confirm it."""


# --- Helpers (own code, no network) --------------------------------------------------


def _client(config: TelegramAppConfig, session: str) -> Any:
    """A short-lived client with every relevant option set explicitly."""
    return TelegramClient(
        StringSession(session or None),
        config.api_id,
        config.api_hash,
        flood_sleep_threshold=FLOOD_SLEEP_THRESHOLD,
        request_retries=REQUEST_RETRIES,
        connection_retries=CONNECTION_RETRIES,
        raise_last_call_error=True,
        receive_updates=False,
        device_model=DEVICE_MODEL,
    )


def identity_of(user: Any) -> TelegramIdentity:
    names = [part for part in (user.first_name, user.last_name) if part]
    username = user.username
    return TelegramIdentity(
        user_id=str(user.id),
        display_name=" ".join(names) or username or str(user.id),
        username=username,
    )


def _public_username(entity: Any) -> str | None:
    if entity.username:
        return str(entity.username)
    for item in entity.usernames or []:
        if item.active:
            return str(item.username)
    return None


def eligible_channel(entity: Any) -> TelegramChannel | None:
    """A broadcast channel the user can post in, or None (research §7)."""
    if not isinstance(entity, types.Channel):
        return None
    if not entity.broadcast or entity.megagroup or entity.left:
        return None
    if entity.access_hash is None:
        return None
    rights = entity.admin_rights
    if not (entity.creator or (rights is not None and rights.post_messages)):
        return None
    return TelegramChannel(
        channel_id=str(entity.id),
        access_hash=str(entity.access_hash),
        title=str(entity.title),
        username=_public_username(entity),
    )


def _translate(error: Exception) -> Exception:
    """Telethon error → own error. Unknown errors are re-raised unchanged."""
    if isinstance(error, errors.FloodError) and hasattr(error, "seconds"):
        return TelegramRateLimited(int(error.seconds))
    if isinstance(error, (errors.UnauthorizedError, errors.AuthKeyError)):
        return TelegramUnauthorized()
    if isinstance(error, (OSError, ConnectionError, asyncio.TimeoutError)):
        return TelegramUnavailable()
    if isinstance(error, (errors.ServerError, errors.RPCError)):
        return TelegramUnavailable()
    return error


_LOGIN_REASONS: tuple[tuple[type[Exception], str], ...] = (
    (
        errors.ApiIdInvalidError,
        "Telegram does not accept the configured api_id and api_hash. Check the "
        "local Telegram app file.",
    ),
    (errors.PhoneNumberInvalidError, "Telegram does not accept this phone number."),
    (errors.PhoneNumberBannedError, "This phone number is banned by Telegram."),
    (
        errors.PhoneNumberUnoccupiedError,
        "There is no Telegram account with this phone number.",
    ),
    (errors.PhoneCodeInvalidError, "The code is not correct."),
    (errors.PhoneCodeEmptyError, "The code is not correct."),
    (errors.PhoneCodeExpiredError, "The code has expired. Start again."),
    (errors.PasswordHashInvalidError, "The password is not correct."),
)


def _login_error(error: Exception) -> Exception:
    for kind, reason in _LOGIN_REASONS:
        if isinstance(error, kind):
            return TelegramLoginInvalid(reason)
    return _translate(error)


async def _with_client[T](
    config: TelegramAppConfig,
    session: str,
    operation: Callable[[Any], Awaitable[T]],
) -> T:
    client = _client(config, session)
    try:
        await client.connect()
        return await operation(client)
    finally:
        await client.disconnect()


def _run[T](coro: Awaitable[T], translate: Callable[[Exception], Exception]) -> T:
    async def main() -> T:
        return await coro

    try:
        return asyncio.run(main())
    except TelegramError:
        raise
    except Exception as error:
        translated = translate(error)
        if translated is error:
            raise
        # Only the class name: Telegram messages may echo request data.
        logger.info("Telegram call failed (%s).", type(error).__name__)
        raise translated from None


# Waits before repeating the same send (research §8.4): two more tries at most.
CONFIRM_WAITS = (3.0, 10.0)
VIDEO_FILE_NAME = "video.mp4"

_TEXT_ERRORS = (
    errors.MessageTooLongError,
    errors.MediaCaptionTooLongError,
    errors.MessageEmptyError,
)
_MEDIA_ERRORS = (
    errors.PhotoInvalidDimensionsError,
    errors.PhotoSaveFileInvalidError,
    errors.PhotoExtInvalidError,
    errors.FilePartsInvalidError,
    errors.MediaInvalidError,
    errors.MediaEmptyError,
)
_CHANNEL_ERRORS = (
    errors.ChatWriteForbiddenError,
    errors.ChatAdminRequiredError,
    errors.ChannelPrivateError,
    errors.ChannelInvalidError,
)


def _publish_error(error: Exception) -> Exception:
    if isinstance(error, _CHANNEL_ERRORS):
        return TelegramChannelUnavailable()
    if isinstance(error, _TEXT_ERRORS):
        return TelegramTextRejected()
    if isinstance(error, _MEDIA_ERRORS):
        return TelegramMediaRejected()
    return _translate(error)


def _maybe_landed(error: Exception) -> bool:
    """Errors after which the message may exist: a lost response, a timeout, or
    RANDOM_ID_DUPLICATE (the previous send with this ID may still be running)."""
    return isinstance(
        error, (errors.ServerError, errors.TimedOutError, OSError, ConnectionError)
    )


def message_id_for(updates: Any, random_id: int) -> int | None:
    """The message ID Telegram paired with our `random_id`, or None."""
    for update in getattr(updates, "updates", None) or []:
        if isinstance(update, types.UpdateMessageID) and update.random_id == random_id:
            return int(update.id)
    return None


async def send_with_confirmation(
    send: Callable[[int], Awaitable[Any]],
    random_id: int,
    *,
    waits: tuple[float, ...] = CONFIRM_WAITS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Send with `random_id` and repeat the very same send, at most `len(waits)`
    times, while the outcome may have landed. Only an `UpdateMessageID` for this
    `random_id` confirms; anything else after a possible landing is unconfirmed.
    A new `random_id` is never generated here."""
    landed = False
    for delay in (0.0, *waits):
        if delay:
            await sleep(delay)
        try:
            updates = await send(random_id)
        except Exception as error:
            if _maybe_landed(error):
                landed = True
                logger.info(
                    "Telegram send not confirmed yet (%s).", type(error).__name__
                )
                continue
            translated = _publish_error(error)
            if not landed:
                raise translated from None
            retry_after = (
                translated.seconds
                if isinstance(translated, TelegramRateLimited)
                else None
            )
            raise TelegramUnconfirmed(retry_after) from None
        message_id = message_id_for(updates, random_id)
        if message_id is None:
            raise TelegramUnconfirmed()
        return message_id
    raise TelegramUnconfirmed()


def _input_media(spec: SendSpec, uploaded: Any) -> Any:
    if spec.kind == "image":
        return types.InputMediaUploadedPhoto(file=uploaded)
    return types.InputMediaUploadedDocument(
        file=uploaded,
        mime_type=spec.mime_type or "video/mp4",
        attributes=[
            types.DocumentAttributeVideo(
                duration=spec.duration_seconds or 0,
                w=spec.width or 0,
                h=spec.height or 0,
                supports_streaming=True,
            ),
            # Never the original file name: it may be private.
            types.DocumentAttributeFilename(VIDEO_FILE_NAME),
        ],
    )


# --- Real gateway --------------------------------------------------------------------


class TelethonGateway:
    """`TelegramGateway` over Telethon; one client per operation."""

    def send_code(self, config: TelegramAppConfig, phone: str) -> PendingLogin:
        async def operation(client: Any) -> PendingLogin:
            sent = await client.send_code_request(phone)
            return PendingLogin(
                session=client.session.save(),
                phone=phone,
                phone_code_hash=sent.phone_code_hash,
            )

        return _run(_with_client(config, "", operation), _login_error)

    def sign_in_code(
        self, config: TelegramAppConfig, pending: PendingLogin, code: str
    ) -> SignedIn | PasswordRequired:
        async def operation(client: Any) -> SignedIn | PasswordRequired:
            try:
                user = await client.sign_in(
                    pending.phone, code, phone_code_hash=pending.phone_code_hash
                )
            except errors.SessionPasswordNeededError:
                return PasswordRequired(session=client.session.save())
            return SignedIn(client.session.save(), identity_of(user))

        return _run(_with_client(config, pending.session, operation), _login_error)

    def sign_in_password(
        self, config: TelegramAppConfig, session: str, password: str
    ) -> SignedIn:
        async def operation(client: Any) -> SignedIn:
            user = await client.sign_in(password=password)
            return SignedIn(client.session.save(), identity_of(user))

        return _run(_with_client(config, session, operation), _login_error)

    def get_me(self, config: TelegramAppConfig, session: str) -> TelegramIdentity:
        async def operation(client: Any) -> TelegramIdentity:
            user = await client.get_me()
            if user is None:  # Telethon returns None when not authorized.
                raise TelegramUnauthorized()
            return identity_of(user)

        return _run(_with_client(config, session, operation), _translate)

    def log_out(self, config: TelegramAppConfig, session: str) -> None:
        async def operation(client: Any) -> None:
            # The raw request: `client.log_out()` hides why it failed.
            await client(functions.auth.LogOutRequest())

        _run(_with_client(config, session, operation), _translate)

    def list_channels(
        self, config: TelegramAppConfig, session: str
    ) -> list[TelegramChannel]:
        async def operation(client: Any) -> list[TelegramChannel]:
            if not await client.is_user_authorized():
                raise TelegramUnauthorized()
            channels: list[TelegramChannel] = []
            async for dialog in client.iter_dialogs():
                channel = eligible_channel(dialog.entity)
                if channel is not None:
                    channels.append(channel)
            return channels

        return _run(_with_client(config, session, operation), _translate)

    def publish(
        self,
        config: TelegramAppConfig,
        session: str,
        channel: TelegramChannel,
        spec: SendSpec,
        random_id: int,
        *,
        on_progress: Callable[[int], None],
        should_stop: Callable[[], bool],
        before_send: Callable[[], bool],
    ) -> SendResult:
        async def operation(client: Any) -> SendResult:
            if not await client.is_user_authorized():
                raise TelegramUnauthorized()
            channel_id = int(channel.channel_id)
            access_hash = int(channel.access_hash)
            found = await client(
                functions.channels.GetChannelsRequest(
                    [types.InputChannel(channel_id, access_hash)]
                )
            )
            current = eligible_channel(found.chats[0]) if found.chats else None
            if current is None:
                raise TelegramChannelUnavailable()
            media = None
            if spec.kind != "text":

                def progress(sent: int, total: int) -> None:
                    if should_stop():
                        raise TelegramStopped()
                    on_progress(sent)

                uploaded = await client.upload_file(
                    str(spec.file_path), progress_callback=progress
                )
                media = _input_media(spec, uploaded)
            if not before_send():
                raise TelegramStopped()
            peer = types.InputPeerChannel(channel_id, access_hash)

            async def send(rid: int) -> Any:
                if media is None:
                    request = functions.messages.SendMessageRequest(
                        peer=peer, message=spec.text, random_id=rid
                    )
                else:
                    request = functions.messages.SendMediaRequest(
                        peer=peer, media=media, message=spec.text, random_id=rid
                    )
                return await client(request)

            message_id = await send_with_confirmation(send, random_id)
            return SendResult(message_id, current)

        return _run(_with_client(config, session, operation), _publish_error)
