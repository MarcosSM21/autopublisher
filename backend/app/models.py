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


class TikTokCredentialOrphan(Base):
    """A TikTok secret reference whose secret still has to be deleted.

    Registered in the same transaction that stops using the reference; never holds a
    secret.
    """

    __tablename__ = "tiktok_credential_orphans"

    credential_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Only for logs; no foreign key so the row never blocks anything.
    account_id: Mapped[int | None]
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
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("publication_attempts.id", ondelete="RESTRICT")
    )
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cleanup_failures: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    last_cleanup_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


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
    )

    publication_id: Mapped[int] = mapped_column(
        ForeignKey("publications.id", ondelete="RESTRICT"), primary_key=True
    )
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
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TikTokPublishRun(Base):
    """Remote TikTok state of one attempt. Never holds the upload URL, tokens or raw
    TikTok answers."""

    __tablename__ = "tiktok_publish_runs"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('preparing', 'initializing', 'uploading', 'final_chunk', "
            "'processing', 'succeeded', 'failed')",
            name="phase_valid",
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
