"""Generic temporary media delivery: configuration, crash-safe lifecycle, cleanup and
log redaction (research.md §16-§17, FR-007-FR-016a)."""

import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import create_db_engine, run_migrations
from app.media_delivery import (
    DeliverySettings,
    MediaDeliveryConfig,
    MediaDeliveryFailed,
    MediaDeliveryNotConfigured,
    RedactMediaDeliverySecrets,
    SecretUrl,
    TemporaryMediaService,
    load_media_delivery_config,
    redact_delivery_secrets,
)
from app.models import TemporaryMediaObject
from tests.fakes import (
    FAKE_DELIVERY_SECRET,
    FAKE_SIGNATURE,
    FakeMediaDeliveryProvider,
    media_delivery_config_json,
)

NOW = "2026-10-09 10:00:00"


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    db_path = tmp_path / "app.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    with engine.begin() as connection:
        for statement in (
            "INSERT INTO projects (id, name, name_key, is_active, created_at, "
            "updated_at) VALUES (1, 'P', 'p', 1, :now, :now)",
            "INSERT INTO accounts (id, project_id, platform, handle, handle_key, "
            "is_active, created_at, updated_at) VALUES (1, 1, 'instagram', 'h', 'h', "
            "1, :now, :now)",
            "INSERT INTO contents (id, project_id, media_type, media_format, "
            "storage_path, original_filename, checksum, size_bytes, hashtags, "
            "created_at, updated_at) VALUES (1, 1, 'image', 'jpeg', 'a.jpg', 'a.jpg', "
            "'c', 3, '[]', :now, :now)",
            "INSERT INTO publications (id, project_id, content_id, account_id, status, "
            "created_at, updated_at) VALUES (1, 1, 1, 1, 'publishing', :now, :now)",
            "INSERT INTO publication_attempts (id, publication_id, platform, status, "
            "stage, started_at, bytes_sent, total_bytes, submitted, details, warnings) "
            "VALUES (1, 1, 'instagram', 'running', 'uploading', :now, 0, 3, '{}', "
            "'{}', '[]')",
        ):
            connection.execute(text(statement), {"now": NOW})
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def _config() -> MediaDeliveryConfig:
    return MediaDeliveryConfig(
        provider="s3_compatible",
        endpoint_url="https://fake-account.r2.cloudflarestorage.com",
        bucket="b",
        region="auto",
        access_key_id="id",
        secret_access_key=FAKE_DELIVERY_SECRET,
    )


def _service(
    session_factory: sessionmaker[Session],
    provider: FakeMediaDeliveryProvider,
    sleeps: list[float] | None = None,
) -> TemporaryMediaService:
    recorded = sleeps if sleeps is not None else []
    return TemporaryMediaService(
        session_factory,
        lambda: (provider, _config()),
        DeliverySettings(sleep=recorded.append),
        clock=lambda: datetime(2026, 10, 9, 10, 0, tzinfo=UTC),
    )


def _rows(session_factory: sessionmaker[Session]) -> list[TemporaryMediaObject]:
    with session_factory() as session:
        return list(session.scalars(select(TemporaryMediaObject)))


def _finish_attempt(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE publication_attempts SET status = 'failed', "
                "finished_at = :now, error_code = 'x', outcome_determined = 1"
            ),
            {"now": NOW},
        )
        session.commit()


# --- Configuration -------------------------------------------------------------------


def test_loads_a_valid_configuration(tmp_path: Path) -> None:
    path = tmp_path / "media-delivery.json"
    path.write_text(media_delivery_config_json())

    config = load_media_delivery_config(path)

    assert config.bucket == "autopublisher-temp"
    assert config.key_prefix == "autopublisher-tmp/"
    assert config.url_ttl_seconds == 3600
    assert FAKE_DELIVERY_SECRET not in repr(config)


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "ftp"},
        {"endpoint_url": "http://fake-account.r2.cloudflarestorage.com"},
        {"endpoint_url": ""},
        {"bucket": ""},
        {"access_key_id": " "},
        {"secret_access_key": None},
        {"key_prefix": "autopublisher-tmp"},
        {"key_prefix": "/autopublisher-tmp/"},
        {"key_prefix": "a/../b/"},
        {"key_prefix": "/"},
        {"url_ttl_seconds": 60},
        {"url_ttl_seconds": 100_000},
        {"url_ttl_seconds": "3600"},
    ],
)
def test_rejects_invalid_configurations(tmp_path: Path, overrides: Any) -> None:
    path = tmp_path / "media-delivery.json"
    path.write_text(media_delivery_config_json(**overrides))

    with pytest.raises(MediaDeliveryNotConfigured):
        load_media_delivery_config(path)


def test_missing_configuration_is_not_configured(tmp_path: Path) -> None:
    with pytest.raises(MediaDeliveryNotConfigured):
        load_media_delivery_config(tmp_path / "missing.json")


# --- Lifecycle -----------------------------------------------------------------------


def test_reserve_commits_the_reference_before_the_upload(
    session_factory: sessionmaker[Session],
) -> None:
    provider = FakeMediaDeliveryProvider()
    seen: list[list[str]] = []
    provider.put_hook = lambda key: seen.append(
        [row.object_key for row in _rows(session_factory)]
    )
    service = _service(session_factory, provider)

    key = service.reserve(1, "image/jpeg", 3)
    service.upload(key, b"abc", lambda sent: None)

    assert seen == [[key]]
    row = _rows(session_factory)[0]
    assert row.uploaded_at is not None
    assert row.deleted_at is None
    assert provider.objects[key] == b"abc"
    assert provider.content_types[key] == "image/jpeg"


def test_keys_are_random_and_reveal_nothing(
    session_factory: sessionmaker[Session],
) -> None:
    service = _service(session_factory, FakeMediaDeliveryProvider())

    first = service.reserve(1, "image/jpeg", 3)
    second = service.reserve(1, "video/mp4", 3)

    assert first != second
    # Only the prefix, two random hex blocks and the extension: nothing from the
    # original file name or path can appear in a key.
    random_key = r"autopublisher-tmp/[0-9a-f]{32}/[0-9a-f]{32}\."
    assert re.fullmatch(random_key + "jpg", first)
    assert re.fullmatch(random_key + "mp4", second)


def test_upload_retries_then_fails(session_factory: sessionmaker[Session]) -> None:
    provider = FakeMediaDeliveryProvider(put_failures=2)
    sleeps: list[float] = []
    service = _service(session_factory, provider, sleeps)
    key = service.reserve(1, "image/jpeg", 3)

    service.upload(key, b"abc", lambda sent: None)

    assert len(provider.put_calls) == 3
    assert sleeps == [2.0, 5.0]

    provider.put_failures = 3
    with pytest.raises(MediaDeliveryFailed):
        service.upload(key, b"abc", lambda sent: None)


def test_upload_reports_progress(session_factory: sessionmaker[Session]) -> None:
    service = _service(session_factory, FakeMediaDeliveryProvider())
    key = service.reserve(1, "image/jpeg", 4)
    progress: list[int] = []

    service.upload(key, b"abcd", progress.append)

    assert progress == [2, 4]


def test_release_deletes_and_marks(session_factory: sessionmaker[Session]) -> None:
    provider = FakeMediaDeliveryProvider()
    service = _service(session_factory, provider)
    key = service.reserve(1, "image/jpeg", 3)
    service.upload(key, b"abc", lambda sent: None)

    assert service.release(key) is True

    assert key not in provider.objects
    assert _rows(session_factory)[0].deleted_at is not None


def test_failed_release_keeps_the_object_pending(
    session_factory: sessionmaker[Session],
) -> None:
    provider = FakeMediaDeliveryProvider(delete_failures=1)
    service = _service(session_factory, provider)
    key = service.reserve(1, "image/jpeg", 3)
    service.upload(key, b"abc", lambda sent: None)

    assert service.release(key) is False

    row = _rows(session_factory)[0]
    assert row.deleted_at is None
    assert row.cleanup_failures == 1
    assert row.last_cleanup_at is not None


def test_sweep_only_deletes_objects_of_finished_attempts(
    session_factory: sessionmaker[Session],
) -> None:
    provider = FakeMediaDeliveryProvider()
    service = _service(session_factory, provider)
    key = service.reserve(1, "image/jpeg", 3)
    service.upload(key, b"abc", lambda sent: None)

    assert service.sweep() == 0
    assert provider.delete_calls == []

    _finish_attempt(session_factory)
    assert service.sweep() == 0
    assert provider.delete_calls == [key]
    assert _rows(session_factory)[0].deleted_at is not None
    assert service.sweep() == 0
    assert provider.delete_calls == [key]


def test_sweep_resolves_a_crash_between_reserve_and_upload(
    session_factory: sessionmaker[Session],
) -> None:
    provider = FakeMediaDeliveryProvider()
    service = _service(session_factory, provider)
    key = service.reserve(1, "image/jpeg", 3)  # The process dies before uploading.
    _finish_attempt(session_factory)

    assert service.sweep() == 0

    assert provider.delete_calls == [key]
    assert _rows(session_factory)[0].deleted_at is not None


def test_sweep_cleans_up_an_object_whose_post_account_and_project_are_gone(
    session_factory: sessionmaker[Session],
) -> None:
    """Feature 021 (research §7, case A): deleting a post keeps its pending object
    with `attempt_id` NULL; the cleanup needs only the key and the delivery
    configuration. No account, connection, credential or keyring exists any more
    (the system keyring is a failing backend in every test)."""
    provider = FakeMediaDeliveryProvider()
    service = _service(session_factory, provider)
    key = service.reserve(1, "image/jpeg", 3)
    service.upload(key, b"abc", lambda sent: None)
    _finish_attempt(session_factory)
    with session_factory() as session:
        for statement in (
            "UPDATE temporary_media_objects SET attempt_id = NULL",
            "DELETE FROM publication_attempts",
            "DELETE FROM publications",
            "DELETE FROM accounts",
            "DELETE FROM contents",
            "DELETE FROM projects",
        ):
            session.execute(text(statement))
        session.commit()

    assert service.sweep() == 0

    assert provider.delete_calls == [key]
    (row,) = _rows(session_factory)
    assert row.attempt_id is None
    assert row.deleted_at is not None
    assert service.sweep() == 0  # nothing left to do
    assert provider.delete_calls == [key]


def test_not_configured_service(session_factory: sessionmaker[Session]) -> None:
    def factory() -> Any:
        raise MediaDeliveryNotConfigured()

    service = TemporaryMediaService(
        session_factory, factory, DeliverySettings(sleep=lambda seconds: None)
    )

    assert service.configured() is False
    with pytest.raises(MediaDeliveryNotConfigured):
        service.reserve(1, "image/jpeg", 3)


# --- Secrets -------------------------------------------------------------------------


def test_secret_url_never_shows_itself() -> None:
    url = SecretUrl(f"https://x.example/k?X-Amz-Signature={FAKE_SIGNATURE}")

    assert FAKE_SIGNATURE not in repr(url)
    assert FAKE_SIGNATURE not in str(url)
    assert FAKE_SIGNATURE not in f"{url}"
    assert url.reveal().endswith(FAKE_SIGNATURE)


@pytest.mark.parametrize(
    "message",
    [
        f"GET https://r2/k?X-Amz-Signature={FAKE_SIGNATURE}&X-Amz-Expires=1",
        f"X-Amz-Credential={FAKE_SIGNATURE}%2F2026",
        f"X-Amz-Security-Token={FAKE_SIGNATURE}",
        f"image_url=https%3A%2F%2Fr2%2Fk%3F{FAKE_SIGNATURE}",
        f"video_url=https://r2/k?{FAKE_SIGNATURE}",
        f"Authorization: AWS4-HMAC-SHA256 Credential=x, Signature={FAKE_SIGNATURE}",
    ],
)
def test_redaction_removes_signatures(message: str) -> None:
    assert FAKE_SIGNATURE not in redact_delivery_secrets(message)


def test_log_filter_redacts_records(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.delivery")
    logger.addFilter(RedactMediaDeliverySecrets())

    with caplog.at_level(logging.INFO, logger="test.delivery"):
        logger.info("fetch %s", f"https://r2/k?X-Amz-Signature={FAKE_SIGNATURE}")

    assert FAKE_SIGNATURE not in caplog.text
    assert "[redacted]" in caplog.text
