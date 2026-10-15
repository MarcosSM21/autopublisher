"""Fake Telegram boundary for offline tests (Feature 015).

Only AutoPublisher's own behaviour is tested: Telethon, MTProto and Telegram are never
simulated beyond what the `TelegramGateway` contract returns.
"""

import json
import threading
from collections.abc import Callable
from typing import Any

from app.telegram_gateway import (
    PasswordRequired,
    PendingLogin,
    SendResult,
    SendSpec,
    SignedIn,
    TelegramAppConfig,
    TelegramChannel,
    TelegramIdentity,
    TelegramLoginInvalid,
    TelegramStopped,
)

FAKE_API_ID = 1234567
FAKE_API_HASH = "fakeapihash0123456789abcdef0123"
FAKE_PHONE = "+34600111222"
FAKE_CODE = "24680"
FAKE_PASSWORD = "fake-2fa-password"
PARTIAL_SESSION = "PARTIAL-SESSION-SECRET"
PASSWORD_SESSION = "PASSWORD-SESSION-SECRET"
FINAL_SESSION = "FINAL-SESSION-SECRET"
SECRETS = (
    FAKE_API_HASH,
    FAKE_PHONE,
    FAKE_CODE,
    FAKE_PASSWORD,
    PARTIAL_SESSION,
    PASSWORD_SESSION,
    FINAL_SESSION,
)

CHANNEL = TelegramChannel(
    "1987654321", "5551112223334445556", "Test channel", "testchan"
)
PRIVATE_CHANNEL = TelegramChannel("1900000002", "8887776665554443332", "Private", None)


def telegram_app_config_json() -> str:
    return json.dumps({"api_id": FAKE_API_ID, "api_hash": FAKE_API_HASH})


class FakeTelegramGateway:
    """`TelegramGateway` double. `errors[name]` makes one operation raise once;
    `hold` keeps an operation open until released (to test the account lock)."""

    def __init__(self) -> None:
        self.identity = TelegramIdentity("111222333", "Test User", "tester")
        self.requires_password = False
        self.channels: list[TelegramChannel] = [CHANNEL, PRIVATE_CHANNEL]
        self.errors: dict[str, Exception] = {}
        self.calls: list[str] = []
        self.sessions_used: list[str] = []
        self.logged_out: list[str] = []
        self.configs: list[TelegramAppConfig] = []
        self.hold: threading.Event | None = None
        self.entered = threading.Event()
        # Publishing: what was sent, and scripted outcomes after `before_send()`
        # (a message ID or an exception), oldest first.
        self.sent: list[tuple[int, SendSpec, TelegramChannel]] = []
        self.publish_results: list[int | Exception] = []
        self.next_message_id = 1001
        self.current_channel: TelegramChannel | None = None
        self.on_send: Callable[[], None] | None = None

    def _call(self, name: str, config: TelegramAppConfig, session: str = "") -> None:
        self.calls.append(name)
        self.configs.append(config)
        if session:
            self.sessions_used.append(session)
        self.entered.set()
        if self.hold is not None:
            self.hold.wait(5)
        error = self.errors.pop(name, None)
        if error is not None:
            raise error

    def send_code(self, config: TelegramAppConfig, phone: str) -> PendingLogin:
        self._call("send_code", config)
        return PendingLogin(PARTIAL_SESSION, phone, "phone-code-hash")

    def sign_in_code(
        self, config: TelegramAppConfig, pending: PendingLogin, code: str
    ) -> SignedIn | PasswordRequired:
        self._call("sign_in_code", config, pending.session)
        if code != FAKE_CODE:
            raise TelegramLoginInvalid("The code is not correct.")
        if self.requires_password:
            return PasswordRequired(PASSWORD_SESSION)
        return SignedIn(FINAL_SESSION, self.identity)

    def sign_in_password(
        self, config: TelegramAppConfig, session: str, password: str
    ) -> SignedIn:
        self._call("sign_in_password", config, session)
        if password != FAKE_PASSWORD:
            raise TelegramLoginInvalid("The password is not correct.")
        return SignedIn(FINAL_SESSION, self.identity)

    def get_me(self, config: TelegramAppConfig, session: str) -> TelegramIdentity:
        self._call("get_me", config, session)
        return self.identity

    def log_out(self, config: TelegramAppConfig, session: str) -> None:
        self._call("log_out", config, session)
        self.logged_out.append(session)

    def list_channels(
        self, config: TelegramAppConfig, session: str
    ) -> list[TelegramChannel]:
        self._call("list_channels", config, session)
        return list(self.channels)

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
        """Errors in `errors["publish"]` happen before anything is sent."""
        self._call("publish", config, session)
        if spec.file_path is not None:
            on_progress(spec.file_path.stat().st_size)
        if not before_send():
            raise TelegramStopped()
        if self.on_send is not None:
            self.on_send()
        self.sent.append((random_id, spec, channel))
        if self.publish_results:
            outcome = self.publish_results.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            message_id = outcome
        else:
            message_id = self.next_message_id
            self.next_message_id += 1
        return SendResult(message_id, self.current_channel or channel)


def stored_secret(store: Any, ref: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(store.secrets[ref])
    return value
