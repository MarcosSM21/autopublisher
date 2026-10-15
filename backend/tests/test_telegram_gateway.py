"""Own helpers of the Telegram gateway, with Telethon types built in memory and no
network (Feature 015). Telethon itself is not tested."""

import asyncio

from telethon import errors
from telethon.tl import types

from app.telegram_gateway import (
    CONFIRM_WAITS,
    FLOOD_SLEEP_THRESHOLD,
    TelegramAppConfig,
    TelegramChannelUnavailable,
    TelegramLoginInvalid,
    TelegramUnavailable,
    TelegramUnconfirmed,
    _client,
    _login_error,
    eligible_channel,
    send_with_confirmation,
)


def channel(**overrides: object) -> types.Channel:
    values: dict[str, object] = {
        "id": 1987654321,
        "title": "Test channel",
        "photo": types.ChatPhotoEmpty(),
        "date": None,
        "broadcast": True,
        "creator": True,
        "access_hash": 5551112223334445556,
        "username": "testchan",
    }
    values.update(overrides)
    return types.Channel(**values)


def test_only_broadcast_channels_where_the_user_can_post_are_eligible() -> None:
    owned = eligible_channel(channel())
    assert owned is not None
    assert (owned.channel_id, owned.access_hash, owned.username) == (
        "1987654321",
        "5551112223334445556",
        "testchan",
    )
    admin = eligible_channel(
        channel(creator=False, admin_rights=types.ChatAdminRights(post_messages=True))
    )
    assert admin is not None

    assert eligible_channel(channel(broadcast=False, megagroup=True)) is None
    assert eligible_channel(channel(left=True)) is None
    assert eligible_channel(channel(creator=False)) is None
    edit_only = types.ChatAdminRights(edit_messages=True)
    assert eligible_channel(channel(creator=False, admin_rights=edit_only)) is None
    assert eligible_channel(types.User(id=5)) is None


def test_private_channel_has_no_username() -> None:
    private = eligible_channel(channel(username=None))
    assert private is not None
    assert private.username is None


def test_client_waits_automatically_only_for_short_flood_waits() -> None:
    client = _client(TelegramAppConfig(1, "hash"), "")
    assert FLOOD_SLEEP_THRESHOLD == 5
    assert client.flood_sleep_threshold == 5


def test_login_errors_are_translated_without_telegram_text() -> None:
    invalid_app = _login_error(errors.ApiIdInvalidError(request=None))
    assert isinstance(invalid_app, TelegramLoginInvalid)
    assert "api_id" in invalid_app.reason
    wrong_code = _login_error(errors.PhoneCodeInvalidError(request=None))
    assert isinstance(wrong_code, TelegramLoginInvalid)
    assert isinstance(_login_error(ConnectionError()), TelegramUnavailable)


# --- Send confirmation (research §8) -------------------------------------------------


def _confirmed(random_id: int, message_id: int = 77) -> types.Updates:
    return types.Updates(
        updates=[types.UpdateMessageID(id=message_id, random_id=random_id)],
        users=[],
        chats=[],
        date=None,
        seq=0,
    )


def _run_send(outcomes: list[object]) -> tuple[object, list[int], list[float]]:
    """Run the confirmation loop against scripted send outcomes."""
    sent: list[int] = []
    waits: list[float] = []

    async def send(random_id: int) -> object:
        sent.append(random_id)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    try:
        result: object = asyncio.run(send_with_confirmation(send, 42, sleep=sleep))
    except Exception as error:
        result = error
    return result, sent, waits


def test_confirmed_send_returns_the_message_id() -> None:
    result, sent, waits = _run_send([_confirmed(42)])
    assert (result, sent, waits) == (77, [42], [])


def test_lost_response_is_repeated_with_the_same_random_id() -> None:
    result, sent, waits = _run_send([ConnectionError(), _confirmed(42)])
    assert (result, sent, waits) == (77, [42, 42], [3.0])


def test_random_id_duplicate_is_never_an_immediate_success() -> None:
    duplicate = errors.RandomIdDuplicateError(request=None)
    # The repetition returns the original message: success with its ID.
    result, sent, _ = _run_send([duplicate, _confirmed(42, 55)])
    assert (result, sent) == (55, [42, 42])
    # Still duplicate after the bounded repetitions: unconfirmed, never success.
    duplicates = [errors.RandomIdDuplicateError(request=None) for _ in range(3)]
    result, sent, waits = _run_send(duplicates)
    assert isinstance(result, TelegramUnconfirmed)
    assert (sent, waits) == ([42, 42, 42], list(CONFIRM_WAITS))


def test_a_response_without_our_update_message_id_is_unconfirmed() -> None:
    result, sent, _ = _run_send([_confirmed(999)])
    assert isinstance(result, TelegramUnconfirmed)
    assert sent == [42]


def test_rejections_are_determined_only_before_a_possible_landing() -> None:
    forbidden = errors.ChatWriteForbiddenError(request=None)
    result, sent, _ = _run_send([forbidden])
    assert isinstance(result, TelegramChannelUnavailable)
    assert sent == [42]

    flood = errors.FloodWaitError(request=None, capture=30)
    result, _, _ = _run_send([TimeoutError(), flood])
    assert isinstance(result, TelegramUnconfirmed)
    assert result.retry_after == 30
