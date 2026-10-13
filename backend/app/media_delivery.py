"""Temporary public delivery of media files (see specs/009 research.md §16-§17).

Platform-independent: a provider stores a file privately and hands out a short-lived
signed URL that only the platform fetching the media should ever see. Every object
is registered in SQLite *before* it is uploaded, so nothing uploaded can be lost: a
failed cleanup or a crash leaves a row that `sweep()` deletes later. Signed URLs are
secrets: they only live in memory and are never stored, logged or returned by the API.
"""

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db import utc_now
from app.models import AttemptStatus, PublicationAttempt, TemporaryMediaObject

logger = logging.getLogger(__name__)

PROVIDER_S3_COMPATIBLE = "s3_compatible"
MIN_URL_TTL_SECONDS = 900
MAX_URL_TTL_SECONDS = 86_400
DEFAULT_URL_TTL_SECONDS = 3_600
DEFAULT_KEY_PREFIX = "autopublisher-tmp/"
EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
}
NOT_CONFIGURED_MESSAGE = (
    "Temporary media delivery is not configured. See docs/instagram-publishing.md to "
    "set up the storage that lets the platform fetch the media."
)


class MediaDeliveryNotConfigured(Exception):
    """No valid media delivery configuration; nothing can be published that needs it."""


class MediaDeliveryFailed(Exception):
    """The provider could not store, sign or delete an object. Never carries details:
    provider errors may contain URLs or credentials."""


@dataclass(frozen=True)
class MediaDeliveryConfig:
    provider: str
    endpoint_url: str
    bucket: str
    region: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    key_prefix: str = DEFAULT_KEY_PREFIX
    url_ttl_seconds: int = DEFAULT_URL_TTL_SECONDS


def _text(data: dict[str, object], key: str, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise MediaDeliveryNotConfigured(f"Missing or invalid '{key}'.")
    return value.strip()


def load_media_delivery_config(path: Path) -> MediaDeliveryConfig:
    """Read and validate the local configuration file (never sent to the frontend)."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        raise MediaDeliveryNotConfigured("The configuration file is missing.") from None
    if not isinstance(data, dict):
        raise MediaDeliveryNotConfigured("The configuration must be a JSON object.")
    provider = _text(data, "provider")
    if provider != PROVIDER_S3_COMPATIBLE:
        raise MediaDeliveryNotConfigured("Unsupported provider.")
    endpoint_url = _text(data, "endpoint_url")
    parts = urlsplit(endpoint_url)
    if parts.scheme != "https" or not parts.hostname:
        raise MediaDeliveryNotConfigured("The endpoint must be an https URL.")
    key_prefix = _text(data, "key_prefix", DEFAULT_KEY_PREFIX)
    if (
        not key_prefix.endswith("/")
        or key_prefix.startswith("/")
        or ".." in key_prefix
        or key_prefix == "/"
    ):
        raise MediaDeliveryNotConfigured("The key prefix must be a dedicated folder.")
    ttl = data.get("url_ttl_seconds", DEFAULT_URL_TTL_SECONDS)
    if (
        not isinstance(ttl, int)
        or isinstance(ttl, bool)
        or not MIN_URL_TTL_SECONDS <= ttl <= MAX_URL_TTL_SECONDS
    ):
        raise MediaDeliveryNotConfigured("The URL lifetime is out of range.")
    return MediaDeliveryConfig(
        provider=provider,
        endpoint_url=endpoint_url,
        bucket=_text(data, "bucket"),
        region=_text(data, "region", "auto"),
        access_key_id=_text(data, "access_key_id"),
        secret_access_key=_text(data, "secret_access_key"),
        key_prefix=key_prefix,
        url_ttl_seconds=ttl,
    )


class SecretUrl:
    """A signed URL. It hides itself from repr/str so it never reaches a log or an
    error by accident; only `reveal()` returns it, right where it is sent."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretUrl([redacted])"

    __str__ = __repr__


# Bytes or a file path, plus a callback receiving the bytes sent so far.
MediaSource = bytes | Path
ProgressCallback = Callable[[int], None]


class MediaDeliveryProvider(Protocol):
    name: str

    def put(
        self,
        key: str,
        source: MediaSource,
        content_type: str,
        size: int,
        on_progress: ProgressCallback,
    ) -> None:
        """Store a private object; raises `MediaDeliveryFailed`."""

    def signed_get_url(self, key: str, ttl_seconds: int) -> SecretUrl:
        """A GET URL that expires by itself; raises `MediaDeliveryFailed`."""

    def delete(self, key: str) -> None:
        """Delete the object; deleting a missing object succeeds."""


@dataclass(frozen=True)
class DeliverySettings:
    sleep: Callable[[float], None]
    upload_retry_waits: tuple[float, ...] = (2.0, 5.0)


ProviderFactory = Callable[[], tuple[MediaDeliveryProvider, MediaDeliveryConfig]]


class TemporaryMediaService:
    """Lifecycle of temporary objects: reserve → upload → signed URL → release."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider_factory: ProviderFactory,
        settings: DeliverySettings,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.provider_factory = provider_factory
        self.settings = settings
        self.clock = clock

    def configured(self) -> bool:
        try:
            self.provider_factory()
        except MediaDeliveryNotConfigured:
            return False
        return True

    def _provider(self) -> tuple[MediaDeliveryProvider, MediaDeliveryConfig]:
        return self.provider_factory()

    def reserve(self, attempt_id: int, content_type: str, size: int) -> str:
        """Register a random key before anything is uploaded (crash safety)."""
        provider, config = self._provider()
        extension = EXTENSIONS.get(content_type, "bin")
        key = f"{config.key_prefix}{uuid.uuid4().hex}/{uuid.uuid4().hex}.{extension}"
        with self.session_factory() as session:
            session.add(
                TemporaryMediaObject(
                    provider=provider.name,
                    object_key=key,
                    attempt_id=attempt_id,
                    content_type=content_type,
                    size_bytes=size,
                    created_at=self.clock(),
                    cleanup_failures=0,
                )
            )
            session.commit()
        return key

    def upload(
        self, key: str, source: MediaSource, on_progress: ProgressCallback
    ) -> None:
        """Upload with a few retries; the same key is overwritten (idempotent)."""
        provider, _ = self._provider()
        with self.session_factory() as session:
            row = self._row(session, key)
            content_type, size = row.content_type, row.size_bytes
        waits = self.settings.upload_retry_waits
        for try_number in range(len(waits) + 1):
            try:
                provider.put(key, source, content_type, size, on_progress)
                break
            except MediaDeliveryFailed:
                if try_number == len(waits):
                    raise
                logger.warning("Temporary media upload failed; retrying.")
                self.settings.sleep(waits[try_number])
        with self.session_factory() as session:
            self._row(session, key).uploaded_at = self.clock()
            session.commit()

    def public_url(self, key: str) -> SecretUrl:
        provider, config = self._provider()
        return provider.signed_get_url(key, config.url_ttl_seconds)

    def release(self, key: str) -> bool:
        """Delete the object and mark it; False (row kept pending) when it fails."""
        now = self.clock()
        try:
            provider, _ = self._provider()
            provider.delete(key)
        except (MediaDeliveryFailed, MediaDeliveryNotConfigured):
            with self.session_factory() as session:
                row = self._row(session, key)
                row.cleanup_failures += 1
                row.last_cleanup_at = now
                session.commit()
            logger.warning("Could not delete a temporary media object; kept pending.")
            return False
        with self.session_factory() as session:
            row = self._row(session, key)
            row.deleted_at = now
            row.last_cleanup_at = now
            session.commit()
        return True

    def release_attempt(self, attempt_id: int) -> bool:
        """Release every pending object of an attempt; True if all were deleted."""
        with self.session_factory() as session:
            keys = list(
                session.scalars(
                    select(TemporaryMediaObject.object_key).where(
                        TemporaryMediaObject.attempt_id == attempt_id,
                        TemporaryMediaObject.deleted_at.is_(None),
                    )
                )
            )
        return all([self.release(key) for key in keys])

    def sweep(self) -> int:
        """Delete abandoned objects: pending rows whose attempt is no longer running.
        Returns how many could not be deleted."""
        try:
            with self.session_factory() as session:
                keys = list(
                    session.scalars(
                        select(TemporaryMediaObject.object_key)
                        .join(
                            PublicationAttempt,
                            PublicationAttempt.id == TemporaryMediaObject.attempt_id,
                        )
                        .where(
                            TemporaryMediaObject.deleted_at.is_(None),
                            PublicationAttempt.status != AttemptStatus.RUNNING,
                        )
                    )
                )
        except SQLAlchemyError:
            logger.warning("Could not list pending temporary media objects.")
            return 0
        failures = 0
        for key in keys:
            if not self.release(key):
                failures += 1
        if keys:
            logger.info(
                "Swept %s temporary media object(s); %s still pending.",
                len(keys),
                failures,
            )
        return failures

    @staticmethod
    def _row(session: Session, key: str) -> TemporaryMediaObject:
        return session.scalars(
            select(TemporaryMediaObject).where(TemporaryMediaObject.object_key == key)
        ).one()


# --- Logging -----------------------------------------------------------------------

DELIVERY_LOGGERS = (
    "httpx2",
    "httpcore2.connection",
    "httpcore2.http11",
    "httpcore2.http2",
    "botocore",
    "boto3",
    "urllib3",
    "s3transfer",
)
# Libraries that log signed requests at DEBUG; they never need to say more than this.
QUIET_LOGGERS = ("botocore", "boto3", "urllib3", "s3transfer")

_SIGNATURE_PARAMS = re.compile(
    r"\b(X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|image_url|video_url)"
    r"=[^&\s'\"<>]+",
    re.IGNORECASE,
)
_AWS_AUTHORIZATION = re.compile(r"(AWS4-HMAC-SHA256\s+)[^'\"\n]+", re.IGNORECASE)


def redact_delivery_secrets(message: str) -> str:
    redacted = _SIGNATURE_PARAMS.sub(r"\1=[redacted]", message)
    return _AWS_AUTHORIZATION.sub(r"\1[redacted]", redacted)


class RedactMediaDeliverySecrets(logging.Filter):
    """Remove signatures, credentials and media URLs from client library logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # A broken record is left for logging to report.
            return True
        redacted = redact_delivery_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_media_delivery_log_redaction() -> None:
    for name in DELIVERY_LOGGERS:
        delivery_logger = logging.getLogger(name)
        if not any(
            isinstance(f, RedactMediaDeliverySecrets) for f in delivery_logger.filters
        ):
            delivery_logger.addFilter(RedactMediaDeliverySecrets())
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
