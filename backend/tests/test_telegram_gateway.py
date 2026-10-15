"""Own helpers of the Telegram gateway, with Telethon types built in memory and no
network (Feature 015). Telethon itself is not tested."""

from telethon import errors
from telethon.tl import types

from app.telegram_gateway import (
    FLOOD_SLEEP_THRESHOLD,
    TelegramAppConfig,
    TelegramLoginInvalid,
    TelegramUnavailable,
    _client,
    _login_error,
    eligible_channel,
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
