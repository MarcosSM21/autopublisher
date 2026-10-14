"""TikTok upload URLs and credentials never reach logs, the database, the API or
exception texts (spec FR-037, FR-060)."""

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app.tiktok_connections import (
    HTTP_LOGGERS,
    RedactTikTokSecrets,
    install_log_redaction,
)
from app.tiktok_gateway import TikTokError, TikTokGateway, UploadUrl
from tests.conftest import publish_tiktok, tiktok_ready_publication
from tests.fakes import (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_ERROR_TEXT,
    FAKE_TT_PUBLISH_ID_PREFIX,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_UPLOAD_ID,
    FAKE_TT_UPLOAD_TOKEN,
    TT_UPLOAD_BASE,
    FakeClock,
    FakeTikTok,
    UploadAction,
)

FAKE_UPLOAD_URL = (
    f"{TT_UPLOAD_BASE}?upload_id={FAKE_TT_UPLOAD_ID}"
    f"&upload_token={FAKE_TT_UPLOAD_TOKEN}"
)
REAL_SHAPE_URL = (
    "https://open-upload.tiktokapis.com/upload/?upload_id=7012345678901234567"
    "&upload_token=abcDEF123-secret-token-value"
)
SIGNED_URL = (
    "https://open-upload-i18n.tiktokapis.com/upload?upload_id=987&signature="
    "s1gn4tur3value&expires=1700000000"
)


def _redacted(message: str, *args: object) -> str:
    record = logging.LogRecord("httpx2", logging.INFO, __file__, 1, message, args, None)
    assert RedactTikTokSecrets().filter(record)
    return record.getMessage()


# Host and parameter names observed in V1 (values and path never recorded).
V1_SHAPE_URL = (
    "https://open-upload-i18n.tiktokapis.com/video/?upload_id=7012345678901234567"
    "&upload_token=abcDEF123-secret-token-value"
)


@pytest.mark.parametrize(
    "url", [FAKE_UPLOAD_URL, REAL_SHAPE_URL, SIGNED_URL, V1_SHAPE_URL]
)
def test_whole_upload_urls_are_redacted(url: str) -> None:
    for text in (
        _redacted('HTTP Request: PUT %s "HTTP/1.1 201 Created"', url),
        _redacted(f'HTTP Request: PUT {url} "HTTP/1.1 206 Partial Content"'),
        _redacted("send_request_headers.started request=<Request [b'PUT']> %s", url),
    ):
        assert "[redacted TikTok upload URL]" in text
        assert "tiktokapis" not in text
        for secret in (
            FAKE_TT_UPLOAD_TOKEN,
            FAKE_TT_UPLOAD_ID,
            "abcDEF123-secret-token-value",
            "7012345678901234567",
            "s1gn4tur3value",
            "/upload",
        ):
            assert secret not in text


@pytest.mark.parametrize(
    "fragment",
    [
        f"upload_token={FAKE_TT_UPLOAD_TOKEN}",
        f"upload_id={FAKE_TT_UPLOAD_ID}",
        "signature=s1gn4tur3value",
    ],
)
def test_loose_upload_parameters_are_redacted(fragment: str) -> None:
    text = _redacted("something went wrong near ?%s&x=1", fragment)

    assert fragment.split("=")[1] not in text
    assert "[redacted]" in text


def test_existing_redactions_still_apply() -> None:
    text = _redacted(
        "POST https://open.tiktokapis.com/v2/oauth/token/ access_token=%s "
        "Authorization: Bearer %s",
        FAKE_TT_ACCESS_TOKEN,
        FAKE_TT_ACCESS_TOKEN,
    )

    assert FAKE_TT_ACCESS_TOKEN not in text


def test_other_tiktok_urls_are_kept() -> None:
    text = _redacted(
        "HTTP Request: POST https://open.tiktokapis.com/v2/post/publish/video/init/ "
        '"HTTP/1.1 200 OK"'
    )

    assert "https://open.tiktokapis.com/v2/post/publish/video/init/" in text


def test_redaction_is_installed_on_the_http_loggers() -> None:
    install_log_redaction()

    for name in HTTP_LOGGERS:
        assert any(
            isinstance(f, RedactTikTokSecrets) for f in logging.getLogger(name).filters
        )


def test_upload_url_wrapper_never_reveals_its_value() -> None:
    url = UploadUrl(FAKE_UPLOAD_URL)

    for text in (str(url), repr(url), f"{url}", f"{url!s}", repr({"u": url})):
        assert FAKE_TT_UPLOAD_TOKEN not in text
        assert FAKE_TT_UPLOAD_ID not in text
    assert url.reveal() == FAKE_UPLOAD_URL


# --- End to end, single chunk (pre-V1) ------------------------------------------------

E2E_SECRETS = (
    FAKE_TT_ACCESS_TOKEN,
    FAKE_TT_REFRESH_TOKEN,
    FAKE_TT_CLIENT_SECRET,
    FAKE_TT_UPLOAD_TOKEN,
    FAKE_TT_UPLOAD_ID,
    TT_UPLOAD_BASE,
    "open-upload.tiktokapis",
    FAKE_TT_ERROR_TEXT,
)


def _scenario_success(fake: FakeTikTok) -> None:
    fake.statuses = [{"status": "PROCESSING_UPLOAD"}, {"status": "PUBLISH_COMPLETE"}]


def _scenario_determined(fake: FakeTikTok) -> None:
    fake.faults["init"] = "api_invalid_param"


def _scenario_uncertain(fake: FakeTikTok) -> None:
    fake.upload_actions = [UploadAction(raise_="timeout")]
    fake.statuses = [{"status": "PROCESSING_UPLOAD"}]


@pytest.mark.parametrize(
    "scenario",
    [_scenario_success, _scenario_determined, _scenario_uncertain],
    ids=["success", "determined_failure", "uncertain_last_chunk"],
)
def test_publishing_leaks_no_secret(
    tiktok_publishing_client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_path: Path,
    scenario: Callable[[FakeTikTok], None],
) -> None:
    client = tiktok_publishing_client
    caplog.set_level(logging.DEBUG)
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    scenario(fake_tiktok)

    texts = [
        publish_tiktok(client, publication_id).text,
        client.get(f"/api/publications/{publication_id}").text,
        client.get(f"/api/publications/{publication_id}/attempts").text,
        client.get(f"/api/publications/{publication_id}/publish-check").text,
        client.get(f"/api/publications/{publication_id}/tiktok-options").text,
        client.get(f"/api/publications/{publication_id}/tiktok-creator-info").text,
    ]
    options = client.get(f"/api/publications/{publication_id}/tiktok-options").json()
    if options["editable"]:
        texts.append(
            client.post(
                f"/api/publications/{publication_id}/tiktok-consent",
                json={
                    "fingerprint": options["fingerprint"],
                    "declaration_version": options["declaration"]["version"],
                },
            ).text
        )
    # The upload really happened in the scenarios that reach it.
    if fake_tiktok.requests_to("upload"):
        assert FAKE_TT_UPLOAD_TOKEN in fake_tiktok.requests_to("upload")[0].url

    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
        messages = [
            row[0]
            for row in connection.execute(
                "SELECT error_message FROM publication_attempts"
            )
            if row[0]
        ]
    logs = "\n".join(
        [record.getMessage() for record in caplog.records]
        + [caplog.text]
        + [repr(record.args) for record in caplog.records]
    )
    for secret in E2E_SECRETS:
        assert secret not in dump, secret
        assert secret not in logs, secret
        for text in texts:
            assert secret not in text, secret
        for message in messages:
            assert secret not in message
    # The publish_id stays local: never in any API response.
    for text in texts:
        assert FAKE_TT_PUBLISH_ID_PREFIX not in text
        assert "publish_id" not in text
        assert "upload_url" not in text


def test_gateway_exceptions_never_carry_secrets(fake_clock: FakeClock) -> None:
    fake = FakeTikTok()
    for fault in ("transport", "timeout", "server_error", "bad_json", "api_x"):
        fake.faults = {"init": fault, "status": fault, "creator_info": fault}
        with httpx.Client(transport=fake.transport()) as http:
            gateway = TikTokGateway(http, fake_clock.now)
            calls: list[Callable[[TikTokGateway], object]] = [
                lambda g: g.query_creator_info(FAKE_TT_ACCESS_TOKEN),
                lambda g: g.init_video_post(FAKE_TT_ACCESS_TOKEN, {}, {}),
                lambda g: g.fetch_publish_status(FAKE_TT_ACCESS_TOKEN, "p"),
            ]
            for call in calls:
                with pytest.raises(TikTokError) as caught:
                    call(gateway)
                text = f"{caught.value} {caught.value!r}"
                for secret in E2E_SECRETS:
                    assert secret not in text
    url = UploadUrl(FAKE_UPLOAD_URL)
    for action in (
        UploadAction(raise_="transport"),
        UploadAction(raise_="timeout"),
        UploadAction(status=403),
        UploadAction(status=416),
        UploadAction(status=500),
        UploadAction(status=302),
    ):
        fake.upload_actions = [action]
        with httpx.Client(transport=fake.transport()) as http:
            gateway = TikTokGateway(http, fake_clock.now)
            with pytest.raises(TikTokError) as caught:
                gateway.upload_chunk(url, b"abc", 0, 2, 3, "video/mp4")
        text = f"{caught.value} {caught.value!r}"
        assert caught.value.__cause__ is None
        for secret in E2E_SECRETS:
            assert secret not in text


# --- Global: every advanced scenario (T068) -------------------------------------


def _scenario_multi_chunk_retries(
    client: TestClient, fake: FakeTikTok, pid: int, clock: FakeClock
) -> None:
    fake.upload_actions = [
        UploadAction(raise_="lost"),  # kept, answer lost: the retry gets a 416
        UploadAction(),
        UploadAction(status=503, store=False),
    ]
    publish_tiktok(client, pid)


def _scenario_reconciled(
    client: TestClient, fake: FakeTikTok, pid: int, clock: FakeClock
) -> None:
    fake.statuses = [{"status": "PROCESSING_UPLOAD"}]
    publish_tiktok(client, pid)
    fake.statuses = [{"status": "PUBLISH_COMPLETE"}]
    client.get(f"/api/publications/{pid}/publish-check")


def _scenario_recovered(
    client: TestClient, fake: FakeTikTok, pid: int, clock: FakeClock
) -> None:
    from fastapi import FastAPI

    from app.publishing import recover_interrupted_attempts

    fake.upload_actions = [UploadAction()] * 7 + [UploadAction(raise_="timeout")]
    fake.statuses = [{"status": "PROCESSING_UPLOAD"}]
    publish_tiktok(client, pid)
    app = client.app
    assert isinstance(app, FastAPI)
    recover_interrupted_attempts(app.state.session_factory)
    fake.statuses = [{"status": "FAILED", "fail_reason": "internal"}]
    client.get(f"/api/publications/{pid}/publish-check")


def _scenario_scheduled(
    client: TestClient, fake: FakeTikTok, pid: int, clock: FakeClock
) -> None:
    from tests.conftest import in_minutes, iso, run_tick, wait_idle

    at = in_minutes(clock, 5)
    response = client.patch(f"/api/publications/{pid}", json={"scheduled_at": iso(at)})
    assert response.status_code == 200, response.text
    options = client.get(f"/api/publications/{pid}/tiktok-options").json()
    client.post(
        f"/api/publications/{pid}/tiktok-consent",
        json={
            "fingerprint": options["fingerprint"],
            "declaration_version": options["declaration"]["version"],
        },
    )
    armed = client.patch(
        f"/api/publications/{pid}", json={"auto_publish_enabled": True}
    )
    assert armed.status_code == 200, armed.text
    clock.set(at)
    assert run_tick(client).started == [pid]
    wait_idle(client)
    attempts = client.get(f"/api/publications/{pid}/attempts").json()
    assert attempts[0]["trigger"] == "scheduled"


@pytest.mark.parametrize(
    "scenario",
    [
        _scenario_multi_chunk_retries,
        _scenario_reconciled,
        _scenario_recovered,
        _scenario_scheduled,
    ],
    ids=["multi_chunk_retries_416", "reconciled", "recovered", "scheduled"],
)
def test_advanced_scenarios_leak_no_secret(
    tiktok_chunked_client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_path: Path,
    fake_clock: FakeClock,
    scenario: Callable[[TestClient, FakeTikTok, int, FakeClock], None],
) -> None:
    from app import media_delivery

    delivery_calls: list[str] = []
    for name in ("reserve", "upload", "public_url"):
        monkeypatch.setattr(
            media_delivery.TemporaryMediaService,
            name,
            lambda *args, _name=name, **kwargs: delivery_calls.append(_name),
        )
    client = tiktok_chunked_client
    caplog.set_level(logging.DEBUG)
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    pid = created["publication"]["id"]

    scenario(client, fake_tiktok, pid, fake_clock)

    assert fake_tiktok.requests_to("upload"), "the scenario must upload"
    texts = [
        client.get(f"/api/publications/{pid}").text,
        client.get(f"/api/publications/{pid}/attempts").text,
        client.get(f"/api/publications/{pid}/publish-check").text,
        client.get(f"/api/publications/{pid}/tiktok-options").text,
        client.get(f"/api/publications/{pid}/tiktok-creator-info").text,
    ]
    with sqlite3.connect(db_path) as connection:
        dump = "\n".join(connection.iterdump())
    logs = caplog.text + "\n".join(repr(r.args) for r in caplog.records)
    for secret in E2E_SECRETS:
        assert secret not in dump, secret
        assert secret not in logs, secret
        for text in texts:
            assert secret not in text, secret
    for text in texts:
        assert "publish_id" not in text
        assert FAKE_TT_PUBLISH_ID_PREFIX not in text
    # FILE_UPLOAD only: no media delivery, no listing of posts.
    assert delivery_calls == []
    assert fake_tiktok.unexpected == []
    assert set(fake_tiktok.calls()) <= {
        "creator_info",
        "init",
        "upload",
        "status",
        "refresh",
    }
