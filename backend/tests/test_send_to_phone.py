"""POST /api/contents/{id}/send-to-phone (Feature 029): Taildrop is faked, so these
tests check the file chosen, the exact command, the errors, the guard and the logs."""

import logging
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import send_to_phone
from app.content_files import ContentFileGuard
from app.errors import ConflictError
from tests.conftest import create_project, import_one, stored_file
from tests.test_image_metadata import dirty_png

TAILSCALE = "/usr/bin/tailscale"
TARGET = "galaxy-test"
FILENAME = "holiday-photo.png"
STDERR = b"open /secret/media/projects/1/abc.png: failed sending to galaxy-test"


class FakeRun:
    """Records each call; `outcome` is a return code or an exception to raise."""

    def __init__(self, outcome: int | BaseException = 0) -> None:
        self.outcome = outcome
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.during: Any = None

    def __call__(
        self, args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((args, kwargs))
        if self.during is not None:
            self.during()
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return subprocess.CompletedProcess(args, self.outcome, b"progress", STDERR)


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> FakeRun:
    run = FakeRun()
    monkeypatch.setenv(send_to_phone.TARGET_ENV, TARGET)
    monkeypatch.setattr(
        "app.send_to_phone.shutil.which",
        lambda name: TAILSCALE if name == "tailscale" else None,
    )
    monkeypatch.setattr("app.send_to_phone.subprocess.run", run)
    return run


@pytest.fixture
def content(client: TestClient) -> dict[str, Any]:
    project = create_project(client, "Phone")
    result: dict[str, Any] = import_one(client, project["id"], FILENAME, dirty_png())[
        "content"
    ]
    return result


def _send(client: TestClient, content_id: int) -> Any:
    return client.post(f"/api/contents/{content_id}/send-to-phone")


def _guard(client: TestClient) -> ContentFileGuard:
    app = client.app
    assert isinstance(app, FastAPI)
    guard: ContentFileGuard = app.state.content_file_guard
    return guard


def _clean_copy(
    client: TestClient, content_id: int, media_dir: Path, db_path: Path
) -> Path:
    response = client.post(f"/api/contents/{content_id}/remove-metadata")
    assert response.status_code == 200, response.text
    assert response.json()["metadata_status"] == "sanitized"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT sanitized_storage_path FROM contents WHERE id = ?", (content_id,)
        ).fetchone()
    relative: str = row[0]
    return media_dir / relative


def _assert_safe(text: str, *paths: Path) -> None:
    for secret in (
        TARGET,
        FILENAME,
        "/secret/",
        "stderr",
        "progress",
        *map(str, paths),
    ):
        assert secret not in text


# --- US1: the file sent and the command ---------------------------------------------


def test_sends_the_original_with_its_name(
    client: TestClient,
    content: dict[str, Any],
    fake_run: FakeRun,
    media_dir: Path,
    db_path: Path,
) -> None:
    response = _send(client, content["id"])

    assert response.status_code == 204, response.text
    assert response.content == b""
    original = stored_file(media_dir, db_path, content["id"])
    [(args, kwargs)] = fake_run.calls
    assert args == [
        TAILSCALE,
        "file",
        "cp",
        "--name",
        FILENAME,
        str(original),
        f"{TARGET}:",
    ]
    assert kwargs["timeout"] == 300
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["capture_output"] is True
    assert "shell" not in kwargs


def test_sends_the_clean_copy_never_the_original(
    client: TestClient,
    content: dict[str, Any],
    fake_run: FakeRun,
    media_dir: Path,
    db_path: Path,
) -> None:
    copy = _clean_copy(client, content["id"], media_dir, db_path)

    response = _send(client, content["id"])

    assert response.status_code == 204, response.text
    [(args, _)] = fake_run.calls
    assert args[4:] == [FILENAME, str(copy), f"{TARGET}:"]
    assert str(stored_file(media_dir, db_path, content["id"])) not in args


# --- US2: errors --------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_target_not_configured(
    client: TestClient,
    content: dict[str, Any],
    fake_run: FakeRun,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(send_to_phone.TARGET_ENV)
    else:
        monkeypatch.setenv(send_to_phone.TARGET_ENV, value)

    response = _send(client, content["id"])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "phone_target_not_configured"
    assert fake_run.calls == []


def test_tailscale_not_installed(
    client: TestClient,
    content: dict[str, Any],
    fake_run: FakeRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.send_to_phone.shutil.which", lambda name: None)

    response = _send(client, content["id"])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tailscale_unavailable"
    assert fake_run.calls == []


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        (FileNotFoundError(2, "No such file", TAILSCALE), 503, "tailscale_unavailable"),
        (1, 502, "phone_send_failed"),
        (
            subprocess.TimeoutExpired(TAILSCALE, 300, b"progress", STDERR),
            504,
            "phone_send_timeout",
        ),
    ],
)
def test_taildrop_failures_are_safe_and_logged_safely(
    client: TestClient,
    content: dict[str, Any],
    fake_run: FakeRun,
    media_dir: Path,
    db_path: Path,
    caplog: pytest.LogCaptureFixture,
    outcome: int | BaseException,
    status: int,
    code: str,
) -> None:
    fake_run.outcome = outcome
    # The app logger may have been set to INFO by `configure_logging`.
    caplog.set_level(logging.DEBUG, logger="app")

    response = _send(client, content["id"])

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    original = stored_file(media_dir, db_path, content["id"])
    _assert_safe(response.text, original)
    records = [r for r in caplog.records if r.name == "app.send_to_phone"]
    assert records
    for record in records:
        _assert_safe(record.getMessage(), original)
        assert record.exc_info is None
    # The guard was released: the media can be held again.
    with _guard(client).sanitizing(content["id"], lambda: None):
        pass


def test_missing_original_is_not_sent(
    client: TestClient,
    content: dict[str, Any],
    fake_run: FakeRun,
    media_dir: Path,
    db_path: Path,
) -> None:
    stored_file(media_dir, db_path, content["id"]).unlink()

    response = _send(client, content["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "media_unavailable"
    assert error["message"] == "The media file is not available."
    assert fake_run.calls == []


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_damaged_clean_copy_is_not_sent_nor_the_original(
    client: TestClient,
    content: dict[str, Any],
    fake_run: FakeRun,
    media_dir: Path,
    db_path: Path,
    damage: str,
) -> None:
    copy = _clean_copy(client, content["id"], media_dir, db_path)
    if damage == "missing":
        copy.unlink()
    else:
        copy.write_bytes(bytes(len(copy.read_bytes())))

    response = _send(client, content["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == (
        "media_unavailable" if damage == "missing" else "media_corrupt"
    )
    assert "clean copy" in error["message"]
    _assert_safe(response.text, copy)
    assert fake_run.calls == []
    with _guard(client).sanitizing(content["id"], lambda: None):
        pass


def test_unknown_media(client: TestClient, fake_run: FakeRun) -> None:
    response = _send(client, 999)

    assert response.status_code == 404
    assert fake_run.calls == []


# --- Guard --------------------------------------------------------------------------


def test_refused_while_metadata_is_being_cleaned(
    client: TestClient, content: dict[str, Any], fake_run: FakeRun
) -> None:
    with _guard(client).sanitizing(content["id"], lambda: None):
        response = _send(client, content["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "metadata_removal_in_progress"
    assert fake_run.calls == []


def test_refused_while_the_media_is_being_deleted(
    client: TestClient, content: dict[str, Any], fake_run: FakeRun
) -> None:
    with _guard(client).deleting({content["id"]}):
        response = _send(client, content["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "content_deleting"
    assert fake_run.calls == []


def test_the_file_is_held_during_the_whole_send(
    client: TestClient, content: dict[str, Any], fake_run: FakeRun
) -> None:
    guard = _guard(client)
    refused: list[str] = []

    def during() -> None:
        with pytest.raises(ConflictError) as cleaning:
            with guard.sanitizing(content["id"], lambda: None):
                pass
        with pytest.raises(ConflictError) as deleting:
            with guard.deleting({content["id"]}):
                pass
        refused.extend([cleaning.value.code, deleting.value.code])

    fake_run.during = during

    assert _send(client, content["id"]).status_code == 204
    assert refused == ["metadata_removal_in_progress", "metadata_removal_in_progress"]
    # Released after success: Clean metadata and deletion can hold it again.
    with guard.sanitizing(content["id"], lambda: None):
        pass
    with guard.deleting({content["id"]}):
        pass


def test_guard_is_released_after_an_unexpected_exception(
    client: TestClient, content: dict[str, Any], fake_run: FakeRun
) -> None:
    fake_run.outcome = RuntimeError("boom")
    app = client.app
    assert isinstance(app, FastAPI)

    quiet = TestClient(app, raise_server_exceptions=False)
    assert _send(quiet, content["id"]).status_code == 500

    with _guard(client).sanitizing(content["id"], lambda: None):
        pass
