from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    MetaData,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db import UTCDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Platform(StrEnum):
    """Recognised platforms. Keep in sync with PLATFORMS in frontend/src/types.ts."""

    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    X = "x"
    THREADS = "threads"
    TELEGRAM = "telegram"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("project_id", "platform", "handle_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    platform: Mapped[str] = mapped_column(String(20))
    handle: Mapped[str] = mapped_column(String(100))
    handle_key: Mapped[str] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MediaType(StrEnum):
    """Kinds of content. Keep in sync with MediaType in frontend/src/types.ts."""

    IMAGE = "image"
    VIDEO = "video"


class MediaFormat(StrEnum):
    """Supported formats. Keep in sync with MediaFormat in frontend/src/types.ts."""

    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    MP4 = "mp4"
    MOV = "mov"
    WEBM = "webm"


class Content(Base):
    __tablename__ = "contents"
    __table_args__ = (
        UniqueConstraint("project_id", "checksum"),
        Index("ix_contents_project_id_created_at", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    media_type: Mapped[str] = mapped_column(String(10))
    media_format: Mapped[str] = mapped_column(String(10))
    # Relative to the media root; never exposed through the API.
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]
    width: Mapped[int | None]
    height: Mapped[int | None]
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(5000))
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PublicationStatus(StrEnum):
    """Publication statuses. Keep in sync with frontend/src/types.ts."""

    UNSCHEDULED = "unscheduled"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class Publication(Base):
    """The intent to publish one content on one account of the same project."""

    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unscheduled', 'scheduled', 'cancelled', 'publishing', "
            "'published', 'failed')",
            name="status_valid",
        ),
        # Once executed, scheduled_at is only kept as history.
        CheckConstraint(
            "status IN ('cancelled', 'publishing', 'published', 'failed')"
            " OR (status = 'scheduled' AND scheduled_at IS NOT NULL)"
            " OR (status = 'unscheduled' AND scheduled_at IS NULL)",
            name="status_matches_schedule",
        ),
        CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL)",
            name="published_at_matches_status",
        ),
        # At most one active publication per content and account; cancelled and
        # published ones are history and do not count.
        Index(
            "uq_publications_active_content_account",
            "content_id",
            "account_id",
            unique=True,
            sqlite_where=text("status NOT IN ('cancelled', 'published')"),
        ),
        Index(
            "ix_publications_project_id_status_scheduled_at",
            "project_id",
            "status",
            "scheduled_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("contents.id", ondelete="RESTRICT")
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(20))
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # NULL means "use the content's value"; "" or [] is an explicit empty override.
    title_override: Mapped[str | None] = mapped_column(String(200))
    description_override: Mapped[str | None] = mapped_column(String(5000))
    hashtags_override: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AttemptStatus(StrEnum):
    """Publication attempt statuses. Keep in sync with frontend/src/types.ts."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AttemptStage(StrEnum):
    """How far an attempt got. Keep in sync with frontend/src/types.ts.

    `final_chunk` is committed before the request carrying the last byte is sent, so
    an attempt that ends in it may have created the remote item.
    """

    PREPARING = "preparing"
    UPLOADING = "uploading"
    FINAL_CHUNK = "final_chunk"
    DONE = "done"


class PublicationAttempt(Base):
    """One real execution of a publication, on any platform.

    Platform-specific, non-sensitive data lives in the opaque JSON columns. Tokens,
    authorization headers and upload session URLs are never stored here.
    """

    __tablename__ = "publication_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="status_valid"
        ),
        CheckConstraint(
            "stage IN ('preparing', 'uploading', 'final_chunk', 'done')",
            name="stage_valid",
        ),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name="finished_matches_status",
        ),
        CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="error_matches_status",
        ),
        CheckConstraint(
            "bytes_sent >= 0 AND total_bytes >= 0 AND bytes_sent <= total_bytes",
            name="bytes_valid",
        ),
        # At most one execution in progress per publication.
        Index(
            "uq_publication_attempts_running",
            "publication_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
        Index(
            "ix_publication_attempts_publication_id_started_at",
            "publication_id",
            "started_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT")
    )
    platform: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    progress_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    bytes_sent: Mapped[int]
    total_bytes: Mapped[int]
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    # NULL while running; False when the remote outcome is uncertain.
    outcome_determined: Mapped[bool | None]
    external_id: Mapped[str | None] = mapped_column(String(100))
    external_url: Mapped[str | None] = mapped_column(String(500))
    submitted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)


class YouTubeConnectionStatus(StrEnum):
    """Stored connection statuses ("not_connected" means no row).

    Keep in sync with YouTubeConnectionStatus in frontend/src/types.ts.
    """

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


class YouTubeConnection(Base):
    """Link between a YouTube account and a real channel.

    Tokens never live here: `credential_ref` only locates them in the system's secure
    credential storage. `Account` deliberately has no relationship back to this table.
    """

    __tablename__ = "youtube_connections"
    __table_args__ = (
        UniqueConstraint("account_id"),
        # One channel per project, whether the holding account is active or not.
        UniqueConstraint("project_id", "channel_id"),
        UniqueConstraint("credential_ref"),
        CheckConstraint("status IN ('connected', 'reconnect_required')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    # Copied from the account (accounts never change project) for the unique key.
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    channel_id: Mapped[str] = mapped_column(String(64))
    channel_title: Mapped[str] = mapped_column(String(200))
    channel_handle: Mapped[str | None] = mapped_column(String(100))
    channel_thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    credential_ref: Mapped[str] = mapped_column(String(64))
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class YouTubePrivacy(StrEnum):
    """Requested YouTube privacy. Keep in sync with frontend/src/types.ts."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class YouTubePublicationOptions(Base):
    """YouTube-only settings of a publication; no row means the safe defaults.

    `Publication` deliberately has no relationship back to this table.
    """

    __tablename__ = "youtube_publication_options"
    __table_args__ = (
        CheckConstraint(
            "privacy_status IN ('private', 'unlisted', 'public')", name="privacy_valid"
        ),
    )

    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), primary_key=True
    )
    privacy_status: Mapped[str] = mapped_column(String(10), default="private")
    # NULL means "not declared yet"; publishing requires an explicit answer.
    made_for_kids: Mapped[bool | None]
    contains_synthetic_media: Mapped[bool | None]
    notify_subscribers: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
