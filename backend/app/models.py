from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    MetaData,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db import UTCDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
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
