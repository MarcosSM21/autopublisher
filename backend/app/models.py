from datetime import datetime
from enum import StrEnum

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


class Publication(Base):
    """The intent to publish one content on one account of the same project."""

    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unscheduled', 'scheduled', 'cancelled')", name="status_valid"
        ),
        CheckConstraint(
            "status = 'cancelled'"
            " OR (status = 'scheduled' AND scheduled_at IS NOT NULL)"
            " OR (status = 'unscheduled' AND scheduled_at IS NULL)",
            name="status_matches_schedule",
        ),
        # At most one active (not cancelled) publication per content and account.
        Index(
            "uq_publications_active_content_account",
            "content_id",
            "account_id",
            unique=True,
            sqlite_where=text("status != 'cancelled'"),
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


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
