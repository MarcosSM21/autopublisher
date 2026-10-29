from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    false,
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


# Ids that appear in URLs are never reused once deleted (Feature 021, research §11).
NEVER_REUSE_IDS = {"sqlite_autoincrement": True}


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = NEVER_REUSE_IDS

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String, unique=True)
    description: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("project_id", "platform", "handle_key"),
        CheckConstraint("(handle IS NULL) = (handle_key IS NULL)", name="handle_pair"),
        NEVER_REUSE_IDS,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    platform: Mapped[str] = mapped_column(String(20))
    # NULL only while the identity is unknown: a provisional account created with a
    # platform, until its first connection adopts the connected identity.
    handle: Mapped[str | None] = mapped_column(String(100))
    handle_key: Mapped[str | None] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DistributionPreset(Base):
    """A named set of destinations of a project; it stores no metadata or options.

    Unlike history tables it is disposable configuration: it goes with its project.
    """

    __tablename__ = "distribution_presets"
    __table_args__ = (UniqueConstraint("project_id", "name_key"), NEVER_REUSE_IDS)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DistributionPresetAccount(Base):
    """One destination of a preset; it goes with its preset or its account (a
    preset may end up empty and still exists)."""

    __tablename__ = "distribution_preset_accounts"

    preset_id: Mapped[int] = mapped_column(
        ForeignKey("distribution_presets.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True, index=True
    )


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


class MetadataStatus(StrEnum):
    """Metadata state of a content file. Keep in sync with frontend/src/types.ts."""

    # Never checked: the original is published as is.
    UNKNOWN = "unknown"
    # Remove metadata found nothing to remove: the original is published as is.
    CLEAN = "clean"
    # A clean copy exists and is always published instead of the original.
    SANITIZED = "sanitized"


SANITIZED_COPY_COLUMNS = (
    "sanitized_storage_path",
    "sanitized_checksum",
    "sanitized_size_bytes",
    "sanitized_at",
)


class LibraryFolder(Base):
    """A logical folder of a project's Library; files never move (Feature 021).

    `parent_id`, `project_id` and `depth` never change: folders are never moved, so
    cycles are impossible and `depth` stays exact.
    """

    __tablename__ = "library_folders"
    __table_args__ = (
        # Target of the composite keys that keep parents and media in the project.
        UniqueConstraint("id", "project_id"),
        ForeignKeyConstraint(
            ["parent_id", "project_id"],
            ["library_folders.id", "library_folders.project_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("depth BETWEEN 1 AND 5", name="depth_range"),
        CheckConstraint("(parent_id IS NULL) = (depth = 1)", name="root_depth"),
        # Sibling names are unique case-insensitively (`name_key`); SQLite treats
        # NULL parents as distinct, hence one index for roots and one for children.
        Index(
            "uq_library_folders_root_name",
            "project_id",
            "name_key",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
        ),
        Index(
            "uq_library_folders_child_name",
            "parent_id",
            "name_key",
            unique=True,
            sqlite_where=text("parent_id IS NOT NULL"),
        ),
        NEVER_REUSE_IDS,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    parent_id: Mapped[int | None]
    name: Mapped[str] = mapped_column(String(100))
    name_key: Mapped[str] = mapped_column(String)
    depth: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Content(Base):
    __tablename__ = "contents"
    __table_args__ = (
        UniqueConstraint("project_id", "checksum"),
        Index("ix_contents_project_id_created_at", "project_id", "created_at"),
        # A media item can only be in a folder of its own project.
        ForeignKeyConstraint(
            ["folder_id", "project_id"],
            ["library_folders.id", "library_folders.project_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "metadata_status IN ('unknown', 'clean', 'sanitized')",
            name="metadata_status_valid",
        ),
        CheckConstraint(
            "metadata_status != 'sanitized' OR ("
            + " AND ".join(f"{c} IS NOT NULL" for c in SANITIZED_COPY_COLUMNS)
            + ")",
            name="sanitized_copy_complete",
        ),
        CheckConstraint(
            "metadata_status = 'sanitized' OR ("
            + " AND ".join(f"{c} IS NULL" for c in SANITIZED_COPY_COLUMNS)
            + ")",
            name="sanitized_copy_only_sanitized",
        ),
        NEVER_REUSE_IDS,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    # NULL means Unsorted.
    folder_id: Mapped[int | None] = mapped_column(index=True)
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
    metadata_status: Mapped[str] = mapped_column(
        String(10), default=MetadataStatus.UNKNOWN, server_default="unknown"
    )
    # The clean copy (Remove metadata). Relative to the media root; never exposed
    # through the API. The original (`storage_path`, `checksum`) never changes.
    sanitized_storage_path: Mapped[str | None] = mapped_column(String(255), unique=True)
    sanitized_checksum: Mapped[str | None] = mapped_column(String(64))
    sanitized_size_bytes: Mapped[int | None]
    sanitized_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PublicationStatus(StrEnum):
    """Publication statuses. Keep in sync with frontend/src/types.ts."""

    UNSCHEDULED = "unscheduled"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    # The execution finished and the platform now waits for the user to finish the
    # post there (e.g. a draft in an inbox). Never `published_at`; never re-run.
    AWAITING_USER_ACTION = "awaiting_user_action"


class Publication(Base):
    """The intent to publish one content on one account of the same project."""

    __tablename__ = "publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unscheduled', 'scheduled', 'cancelled', 'publishing', "
            "'published', 'failed', 'awaiting_user_action')",
            name="status_valid",
        ),
        # Once executed, scheduled_at is only kept as history.
        CheckConstraint(
            "status IN ('cancelled', 'publishing', 'published', 'failed', "
            "'awaiting_user_action')"
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
        # Explicit consent for automatic publishing only exists while scheduled, so
        # leaving `scheduled` always disarms (Feature 007).
        CheckConstraint(
            "auto_publish_enabled = 0 OR status = 'scheduled'",
            name="auto_publish_only_scheduled",
        ),
        CheckConstraint(
            "auto_publish_enabled = 1 OR (auto_publish_error_code IS NULL"
            " AND auto_publish_error_message IS NULL"
            " AND auto_publish_failed_at IS NULL)",
            name="auto_publish_error_only_armed",
        ),
        CheckConstraint(
            "(auto_publish_error_code IS NULL) = (auto_publish_error_message IS NULL)"
            " AND (auto_publish_error_code IS NULL) = (auto_publish_failed_at IS NULL)",
            name="auto_publish_error_pair",
        ),
        Index(
            "ix_publications_status_auto_publish_scheduled_at",
            "status",
            "auto_publish_enabled",
            "scheduled_at",
        ),
        NEVER_REUSE_IDS,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    # NULL only for publications without media, on platforms whose publisher
    # accepts them (`Publisher.accepts_text_only`).
    content_id: Mapped[int | None] = mapped_column(
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
    auto_publish_enabled: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
    # Last failure to start automatically (safe code and message), if still current.
    auto_publish_error_code: Mapped[str | None] = mapped_column(String(40))
    auto_publish_error_message: Mapped[str | None] = mapped_column(String(500))
    auto_publish_failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AttemptStatus(StrEnum):
    """Publication attempt statuses. Keep in sync with frontend/src/types.ts."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AttemptStage(StrEnum):
    """How far an attempt got. Keep in sync with frontend/src/types.ts.

    `final_chunk` (YouTube) is committed before the request carrying the last byte is
    sent, and `finalizing` before the irreversible publishing call, so an attempt that
    ends in either may have created the remote item. `processing` means the platform
    is processing a prepared item and nothing is public yet.
    """

    PREPARING = "preparing"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    FINALIZING = "finalizing"
    FINAL_CHUNK = "final_chunk"
    DONE = "done"


# Stages after which an interrupted attempt may have published the content.
UNCERTAIN_STAGES = frozenset({AttemptStage.FINAL_CHUNK, AttemptStage.FINALIZING})


class AutoPublishState(StrEnum):
    """Derived automation state of a scheduled publication; never persisted (see
    app.automation). Keep in sync with AutoPublishState in frontend/src/types.ts."""

    DISABLED = "disabled"
    WAITING = "waiting"
    DUE = "due"
    PAUSED = "paused"
    OVERDUE = "overdue"


class AttemptTrigger(StrEnum):
    """How an attempt started. Keep in sync with frontend/src/types.ts."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"


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
            "stage IN ('preparing', 'uploading', 'processing', 'finalizing', "
            "'final_chunk', 'done')",
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
        CheckConstraint("trigger IN ('manual', 'scheduled')", name="trigger_valid"),
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
    trigger: Mapped[str] = mapped_column(
        String(20), default=AttemptTrigger.MANUAL, server_default="manual"
    )
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


class AutomationSettings(Base):
    """Global automation settings: a single row with id 1."""

    __tablename__ = "automation_settings"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    automation_paused: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
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


class InstagramConnectionStatus(StrEnum):
    """Stored Instagram connection statuses ("not_connected" means no row).

    Keep in sync with InstagramConnectionStatus in frontend/src/types.ts.
    """

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


class InstagramAccountType(StrEnum):
    """Instagram Professional account types (`/me.account_type`, upper-cased).

    Keep in sync with InstagramAccountType in frontend/src/types.ts.
    """

    BUSINESS = "BUSINESS"
    MEDIA_CREATOR = "MEDIA_CREATOR"


class InstagramConnection(Base):
    """Link between an Instagram account and a real Professional Instagram account.

    Tokens never live here: `credential_ref` only locates them in the system's secure
    credential storage. `Account` deliberately has no relationship back to this table.
    """

    __tablename__ = "instagram_connections"
    __table_args__ = (
        UniqueConstraint("account_id"),
        # One Instagram account per project, whether the holding account is active.
        UniqueConstraint("project_id", "instagram_user_id"),
        UniqueConstraint("credential_ref"),
        CheckConstraint("status IN ('connected', 'reconnect_required')", name="status"),
        CheckConstraint(
            "account_type IN ('BUSINESS', 'MEDIA_CREATOR')", name="account_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    # Copied from the account (accounts never change project) for the unique key.
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    # Instagram professional account ID (`/me.user_id`): the authoritative identity.
    instagram_user_id: Mapped[str] = mapped_column(String(64))
    # App-scoped ID (`/me.id`); informative only.
    app_scoped_id: Mapped[str | None] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(20))
    profile_picture_url: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20))
    credential_ref: Mapped[str] = mapped_column(String(64))
    # Expiry of the long-lived token; not sensitive, shown in the interface.
    credential_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ThreadsConnectionStatus(StrEnum):
    """Stored Threads connection statuses ("not_connected" means no row).

    Keep in sync with ThreadsConnectionStatus in frontend/src/types.ts.
    """

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


class ThreadsConnection(Base):
    """Link between a Threads account and a real Threads account.

    Tokens never live here: `credential_ref` only locates them in the system's secure
    credential storage, whose secret is the source of truth for the token, its
    `token_obtained_at`, its expiry and its scopes. `Account` deliberately has no
    relationship back to this table.
    """

    __tablename__ = "threads_connections"
    __table_args__ = (
        UniqueConstraint("account_id"),
        # One Threads account per project, whether the holding account is active.
        UniqueConstraint("project_id", "threads_user_id"),
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
    # Threads user ID (`/me.id`): the authoritative identity.
    threads_user_id: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str | None] = mapped_column(String(255))
    profile_picture_url: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20))
    credential_ref: Mapped[str] = mapped_column(String(64))
    # Mirror of the secret (repairable from it): when the current long-lived token was
    # received, only for Meta's 24 h refresh condition.
    token_obtained_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Mirror of the secret (repairable from it): expiry of the long-lived token, from
    # the official `expires_in`. Exposed in the API as `access_expires_at`.
    credential_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Last official `debug_token.data_access_expires_at`. Informational only: it may be
    # stale after a refresh and never changes the status on its own.
    data_access_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TikTokConnectionStatus(StrEnum):
    """Stored TikTok connection statuses ("not_connected" means no row).

    Keep in sync with TikTokConnectionStatus in frontend/src/types.ts.
    """

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


class TikTokConnection(Base):
    """Link between a TikTok account and a real TikTok account.

    Tokens never live here: `credential_ref` only locates the credential in the
    system's secure credential storage, whose secret is the source of truth for the
    tokens, their expiries and the granted scopes. `Account` deliberately has no
    relationship back to this table.
    """

    __tablename__ = "tiktok_connections"
    __table_args__ = (
        UniqueConstraint("account_id"),
        # One TikTok account per project, whether the holding account is active.
        UniqueConstraint("project_id", "open_id"),
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
    # TikTok `open_id` (token exchange == user/info): the authoritative identity.
    open_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(20))
    credential_ref: Mapped[str] = mapped_column(String(64))
    # Informational mirror of the secret's expiries (repairable from it); decisions
    # are always taken with the secret.
    access_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    refresh_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


# Platforms whose connections keep a secret in the credential store.
CREDENTIAL_PLATFORMS = ("youtube", "instagram", "threads", "tiktok", "telegram")


class PendingCredentialDeletion(Base):
    """A secret reference whose secret still has to be deleted from the store.

    Registered in the same transaction that stops using the reference (write-ahead);
    `platform` selects the store. Never holds a secret (Feature 021, research §15).
    """

    __tablename__ = "pending_credential_deletions"
    __table_args__ = (
        CheckConstraint(
            "platform IN ("
            + ", ".join(f"'{platform}'" for platform in CREDENTIAL_PLATFORMS)
            + ")",
            name="platform_valid",
        ),
    )

    credential_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    # Only for logs and the credential lock; no foreign key so the row never blocks
    # anything and survives its account.
    account_id: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PendingFileDeletion(Base):
    """A media file that still has to be deleted from disk.

    `storage_path` is relative to the media root, like `contents.storage_path`, so
    the queue stays valid when the data directory moves (Feature 021, research §8).
    """

    __tablename__ = "pending_file_deletions"

    storage_path: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


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


class InstagramPublicationOptions(Base):
    """Instagram-only settings of a publication; no row means the defaults.

    `Publication` deliberately has no relationship back to this table.
    """

    __tablename__ = "instagram_publication_options"
    __table_args__ = (
        CheckConstraint(
            "alt_text IS NULL OR length(alt_text) <= 1000", name="alt_text_length"
        ),
    )

    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), primary_key=True
    )
    # NULL means "not declared yet"; publishing requires an explicit answer.
    is_ai_generated: Mapped[bool | None]
    # Reels only; ignored for images.
    share_to_feed: Mapped[bool] = mapped_column(default=True, server_default=text("1"))
    # Images only.
    alt_text: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class InstagramMediaKind(StrEnum):
    """What an Instagram publication publishes. Keep in sync with types.ts."""

    IMAGE = "image"
    REEL = "reel"


class InstagramPublishPhase(StrEnum):
    """Instagram-specific progress of an attempt, used for recovery and diagnosis."""

    PREPARING = "preparing"
    DELIVERING_MEDIA = "delivering_media"
    CREATING_CONTAINER = "creating_container"
    PROCESSING_CONTAINER = "processing_container"
    PUBLISHING = "publishing"
    VERIFYING_RESULT = "verifying_result"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InstagramPublishRun(Base):
    """Remote Instagram state of one attempt; never holds tokens or signed URLs."""

    __tablename__ = "instagram_publish_runs"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('preparing', 'delivering_media', 'creating_container', "
            "'processing_container', 'publishing', 'verifying_result', 'succeeded', "
            "'failed')",
            name="phase_valid",
        ),
        CheckConstraint("media_kind IN ('image', 'reel')", name="media_kind_valid"),
        Index(
            "ix_instagram_publish_runs_publication_id_container_created_at",
            "publication_id",
            "container_created_at",
        ),
    )

    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("publication_attempts.id", ondelete="RESTRICT"), primary_key=True
    )
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT")
    )
    media_kind: Mapped[str] = mapped_column(String(10))
    fingerprint: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(30))
    container_id: Mapped[str | None] = mapped_column(String(64))
    container_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    container_status: Mapped[str | None] = mapped_column(String(20))
    reused_from_attempt_id: Mapped[int | None]
    # Committed just before `media_publish` (write-ahead); diagnosis and manual review.
    publish_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ThreadsPublicationOptions(Base):
    """Threads-only settings of a publication; no row means the defaults.

    `Publication` deliberately has no relationship back to this table.
    """

    __tablename__ = "threads_publication_options"
    __table_args__ = (
        CheckConstraint(
            "alt_text IS NULL OR length(alt_text) <= 1000", name="alt_text_length"
        ),
    )

    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), primary_key=True
    )
    # Images and videos only.
    alt_text: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ThreadsMediaKind(StrEnum):
    """What a Threads publication publishes. Keep in sync with types.ts."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"


class ThreadsPublishPhase(StrEnum):
    """Threads-specific progress of an attempt, used for recovery and diagnosis."""

    PREPARING = "preparing"
    DELIVERING_MEDIA = "delivering_media"
    CREATING_CONTAINER = "creating_container"
    PROCESSING_CONTAINER = "processing_container"
    PUBLISHING = "publishing"
    VERIFYING_RESULT = "verifying_result"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ThreadsPublishRun(Base):
    """Remote Threads state of one attempt; never holds tokens or signed URLs."""

    __tablename__ = "threads_publish_runs"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('preparing', 'delivering_media', 'creating_container', "
            "'processing_container', 'publishing', 'verifying_result', 'succeeded', "
            "'failed')",
            name="phase_valid",
        ),
        CheckConstraint(
            "media_kind IN ('text', 'image', 'video')", name="media_kind_valid"
        ),
        Index(
            "ix_threads_publish_runs_publication_id_container_created_at",
            "publication_id",
            "container_created_at",
        ),
    )

    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("publication_attempts.id", ondelete="RESTRICT"), primary_key=True
    )
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT")
    )
    media_kind: Mapped[str] = mapped_column(String(10))
    phase: Mapped[str] = mapped_column(String(30))
    # Committed right after the container is created.
    container_id: Mapped[str | None] = mapped_column(String(64))
    container_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    container_status: Mapped[str | None] = mapped_column(String(20))
    # Only documented `error_message` codes, never free text from Meta.
    container_error: Mapped[str | None] = mapped_column(String(40))
    # Committed just before `threads_publish` (write-ahead).
    publish_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TemporaryMediaObject(Base):
    """An object uploaded to the media delivery provider for one attempt.

    The row is committed before the upload starts, so every object can be found and
    deleted later. Only the random key is stored: it gives no access without a
    signature, and signed URLs are never persisted.
    """

    __tablename__ = "temporary_media_objects"
    __table_args__ = (
        UniqueConstraint("object_key"),
        CheckConstraint(
            "size_bytes >= 0 AND cleanup_failures >= 0", name="counters_valid"
        ),
        Index("ix_temporary_media_objects_pending", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    object_key: Mapped[str] = mapped_column(String(255))
    # NULL once its attempt was deleted with its post: the object is still pending
    # and only needs `object_key` and the delivery configuration to be cleaned up.
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("publication_attempts.id", ondelete="RESTRICT")
    )
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cleanup_failures: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_cleanup_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TikTokMode(StrEnum):
    """How a video is sent to TikTok. Keep in sync with frontend/src/types.ts."""

    DIRECT_POST = "DIRECT_POST"
    INBOX_UPLOAD = "INBOX_UPLOAD"


class TikTokPublicationOptions(Base):
    """TikTok-only settings of a publication and the consent given for them; no row
    means the initial values (nothing chosen, nothing consented).

    `Publication` deliberately has no relationship back to this table.
    """

    __tablename__ = "tiktok_publication_options"
    __table_args__ = (
        CheckConstraint(
            "privacy_level IS NULL OR privacy_level IN ('PUBLIC_TO_EVERYONE', "
            "'MUTUAL_FOLLOW_FRIENDS', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY')",
            name="privacy_valid",
        ),
        CheckConstraint(
            "commercial_disclosure_enabled = 1 OR "
            "(brand_organic_toggle = 0 AND brand_content_toggle = 0)",
            name="brand_toggles_need_disclosure",
        ),
        CheckConstraint(
            "NOT (brand_content_toggle = 1 AND privacy_level = 'SELF_ONLY')",
            name="branded_not_private",
        ),
        CheckConstraint(
            "(consent_fingerprint IS NULL) = (consent_declaration_version IS NULL) "
            "AND (consent_fingerprint IS NULL) = (consented_at IS NULL)",
            name="consent_complete",
        ),
        CheckConstraint(
            "mode IS NULL OR mode IN ('DIRECT_POST', 'INBOX_UPLOAD')",
            name="mode_valid",
        ),
    )

    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), primary_key=True
    )
    # NULL means "not chosen yet": there is never a default mode (Feature 014).
    mode: Mapped[str | None] = mapped_column(String(16))
    # NULL means "not chosen yet": there is never a default privacy.
    privacy_level: Mapped[str | None] = mapped_column(String(32))
    allow_comment: Mapped[bool] = mapped_column(default=False, server_default=false())
    allow_duet: Mapped[bool] = mapped_column(default=False, server_default=false())
    allow_stitch: Mapped[bool] = mapped_column(default=False, server_default=false())
    commercial_disclosure_enabled: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
    # "Your brand".
    brand_organic_toggle: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
    # "Branded content".
    brand_content_toggle: Mapped[bool] = mapped_column(
        default=False, server_default=false()
    )
    # NULL means "not declared yet"; publishing requires an explicit answer.
    is_aigc: Mapped[bool | None]
    # SHA-256 of what the user consented to, including the video digest.
    consent_fingerprint: Mapped[str | None] = mapped_column(String(64))
    consent_declaration_version: Mapped[str | None] = mapped_column(String(40))
    consented_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TikTokPublishPhase(StrEnum):
    """TikTok-specific progress of an attempt, used for recovery and diagnosis."""

    PREPARING = "preparing"
    INITIALIZING = "initializing"
    UPLOADING = "uploading"
    FINAL_CHUNK = "final_chunk"
    PROCESSING = "processing"
    # Upload to Inbox only: TikTok put the video in the user's inbox.
    DELIVERED = "delivered"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TikTokPublishRun(Base):
    """Remote TikTok state of one attempt. Never holds the upload URL, tokens or raw
    TikTok answers."""

    __tablename__ = "tiktok_publish_runs"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('preparing', 'initializing', 'uploading', 'final_chunk', "
            "'processing', 'delivered', 'succeeded', 'failed')",
            name="phase_valid",
        ),
        CheckConstraint("mode IN ('DIRECT_POST', 'INBOX_UPLOAD')", name="mode_valid"),
        CheckConstraint(
            "(phase <> 'delivered' AND delivered_to_inbox_at IS NULL) "
            "OR mode = 'INBOX_UPLOAD'",
            name="delivered_only_inbox",
        ),
        CheckConstraint(
            "user_published_at IS NULL OR mode = 'INBOX_UPLOAD'",
            name="user_published_only_inbox",
        ),
        CheckConstraint(
            "public_post_count IS NULL OR public_post_count >= 0",
            name="public_post_count_valid",
        ),
        CheckConstraint(
            "confirmed_bytes BETWEEN 0 AND video_size", name="confirmed_bytes_range"
        ),
        CheckConstraint(
            "total_chunk_count BETWEEN 1 AND 1000", name="total_chunk_count_range"
        ),
        CheckConstraint(
            "final_chunk_started_at IS NULL OR publish_id IS NOT NULL",
            name="write_ahead_needs_publish_id",
        ),
        Index("ix_tiktok_publish_runs_publication_id", "publication_id"),
    )

    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("publication_attempts.id", ondelete="RESTRICT"), primary_key=True
    )
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT")
    )
    # Frozen when the run is created.
    mode: Mapped[str] = mapped_column(String(16))
    phase: Mapped[str] = mapped_column(String(20))
    # Committed before the first byte is sent; never exposed through the API.
    publish_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    video_size: Mapped[int]
    chunk_size: Mapped[int]
    total_chunk_count: Mapped[int]
    confirmed_bytes: Mapped[int] = mapped_column(default=0)
    # Last `uploaded_bytes` read from TikTok (diagnosis only).
    remote_uploaded_bytes: Mapped[int | None]
    initialized_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Write-ahead of the last chunk.
    final_chunk_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # HTTP status of the last PUT (diagnosis only; never decides anything).
    final_chunk_http_status: Mapped[int | None]
    last_remote_status: Mapped[str | None] = mapped_column(String(32))
    # Only `^[a-z_]{1,64}$`, otherwise "unknown".
    fail_reason: Mapped[str | None] = mapped_column(String(64))
    last_log_id: Mapped[str | None] = mapped_column(String(64))
    last_status_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Upload to Inbox: first `SEND_TO_USER_INBOX` seen and `PUBLISH_COMPLETE` seen.
    delivered_to_inbox_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    user_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # How many public post ids TikTok reported (diagnosis only; never the ids).
    public_post_count: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TelegramConnectionStatus(StrEnum):
    """Stored Telegram connection statuses ("not_connected" means no row).

    Keep in sync with TelegramConnectionStatus in frontend/src/types.ts.
    """

    CONNECTED = "connected"
    RECONNECT_REQUIRED = "reconnect_required"


class TelegramConnection(Base):
    """Link between a Telegram account and a real Telegram user account (MTProto).

    The authorized session never lives here: `credential_ref` only locates it in the
    system's secure credential storage. The destination channel is kept as its id and
    `access_hash`, which together locate it again without any cached entity; the
    access hash is useless without the session and is never exposed through the API.
    `Account` deliberately has no relationship back to this table.
    """

    __tablename__ = "telegram_connections"
    __table_args__ = (
        UniqueConstraint("account_id"),
        UniqueConstraint("credential_ref"),
        CheckConstraint("status IN ('connected', 'reconnect_required')", name="status"),
        CheckConstraint(
            "(channel_id IS NULL AND channel_access_hash IS NULL "
            "AND channel_title IS NULL) OR (channel_id IS NOT NULL "
            "AND channel_access_hash IS NOT NULL AND channel_title IS NOT NULL)",
            name="channel_complete",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    # Copied from the account (accounts never change project).
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    # Telegram user ID (`get_me().id`): the authoritative identity.
    telegram_user_id: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    credential_ref: Mapped[str] = mapped_column(String(64))
    # Destination broadcast channel (MTProto id, without the -100 prefix).
    channel_id: Mapped[str | None] = mapped_column(String(32))
    channel_access_hash: Mapped[str | None] = mapped_column(String(32))
    channel_title: Mapped[str | None] = mapped_column(String(255))
    channel_username: Mapped[str | None] = mapped_column(String(100))
    # End of the last FloodWait received while publishing (local cooldown).
    flood_wait_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class InstallationAuth(Base):
    """The installation password (Feature 020): a single row with id 1.

    Only a self-describing scrypt hash (algorithm, parameters and salt included) is
    stored; it is portable state and travels with a backup.
    """

    __tablename__ = "installation_auth"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuthSession(Base):
    """A signed-in browser. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # Renews the idle deadline (7 days); written at most every 10 minutes.
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # created_at + 30 days: the absolute limit, never extended.
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MetricTrigger(StrEnum):
    """What started a metrics read (Feature 027)."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class MetricOrigin(StrEnum):
    """Where an original metric comes from: a public counter of the post or an
    insight that needs its own permission (Feature 027)."""

    PUBLIC_COUNTER = "public_counter"
    INSIGHT = "insight"


class MetricRefreshStatus(StrEnum):
    """Stored refresh states of a publication's metrics; there is no generic `error`
    (failure details live in `error_code`/`error_message`)."""

    PENDING = "pending"
    OK = "ok"
    STALE = "stale"
    RATE_LIMITED = "rate_limited"
    RECONNECT_REQUIRED = "reconnect_required"
    PERMISSION_REQUIRED = "permission_required"
    REMOTE_NOT_FOUND = "remote_not_found"
    REMOTE_DELETED = "remote_deleted"


class MetricSnapshot(Base):
    """One successful metrics read of one publication (Feature 027).

    Failures never create a snapshot; they only update the refresh state. It goes
    with its publication (`POST_DEPENDENTS`)."""

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        CheckConstraint("trigger IN ('automatic', 'manual')", name="trigger_valid"),
        Index(
            "ix_metric_snapshots_publication_id_captured_at",
            "publication_id",
            "captured_at",
        ),
        NEVER_REUSE_IDS,
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT")
    )
    # Platform at capture time.
    platform: Mapped[str] = mapped_column(String(20))
    # The `external_id` used for the read (traceability).
    remote_id: Mapped[str] = mapped_column(String(100))
    # When AutoPublisher received the answer.
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # API call identifier, e.g. `youtube.videos.list:statistics`.
    source: Mapped[str] = mapped_column(String(60))
    trigger: Mapped[str] = mapped_column(String(10))


class MetricValue(Base):
    """One original platform metric inside a snapshot, with its original name.

    A declared metric the platform did not return has no row: "not available" is
    never stored as 0. The common concept is not stored; it comes from the catalog."""

    __tablename__ = "metric_values"
    __table_args__ = (
        CheckConstraint("value >= 0", name="value_non_negative"),
        CheckConstraint("origin IN ('public_counter', 'insight')", name="origin_valid"),
    )

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("metric_snapshots.id", ondelete="RESTRICT"), primary_key=True
    )
    metric_name: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[int]
    origin: Mapped[str] = mapped_column(String(20))


class PublicationMetricState(Base):
    """Refresh state of one publication's metrics (Feature 027).

    Created when a manual request is accepted or on the first refresh attempt; it
    goes with its publication (`POST_DEPENDENTS`)."""

    __tablename__ = "publication_metric_states"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'ok', 'stale', 'rate_limited', "
            "'reconnect_required', 'permission_required', 'remote_not_found', "
            "'remote_deleted')",
            name="status_valid",
        ),
        CheckConstraint("failure_count >= 0", name="failure_count_non_negative"),
    )

    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(24))
    # `captured_at` of the latest snapshot.
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Earliest automatic attempt.
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # An accepted manual request not executed yet.
    manual_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Consecutive failures (backoff).
    failure_count: Mapped[int] = mapped_column(default=0, server_default="0")
    # Fixed, safe code and message of the last failure; never tokens or raw bodies.
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(300))
