"""Request and response bodies. Inputs are cleaned here before any validation."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import (
    AttemptStage,
    AttemptStatus,
    AttemptTrigger,
    AutoPublishState,
    MediaFormat,
    MediaType,
    Platform,
    PublicationStatus,
    YouTubePrivacy,
)
from app.normalization import clean_handle, clean_text, normalize_key


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _clean_optional(value: Any) -> Any:
    return clean_text(value) if isinstance(value, str) else value


ProjectName = Annotated[
    str, BeforeValidator(_strip), StringConstraints(min_length=1, max_length=100)
]
ProjectDescription = Annotated[
    Annotated[str, StringConstraints(max_length=1000)] | None,
    BeforeValidator(_clean_optional),
]


def _clean_handle(value: Any) -> Any:
    return clean_handle(value) if isinstance(value, str) else value


Handle = Annotated[
    str, BeforeValidator(_clean_handle), StringConstraints(min_length=1, max_length=100)
]
DisplayName = Annotated[
    Annotated[str, StringConstraints(max_length=100)] | None,
    BeforeValidator(_clean_optional),
]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdateModel(InputModel):
    """Partial update: omitted fields keep their value; an empty body is rejected."""

    @model_validator(mode="after")
    def _require_a_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self


class ProjectCreate(InputModel):
    name: ProjectName
    description: ProjectDescription = None


class ProjectUpdate(UpdateModel):
    name: ProjectName | None = None
    description: ProjectDescription = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name_not_null(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Must not be empty.")
        return value

    @field_validator("is_active")
    @classmethod
    def _is_active_not_null(cls, value: bool | None) -> bool | None:
        if value is None:
            raise ValueError("Must be true or false.")
        return value


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AccountCreate(InputModel):
    platform: Platform
    handle: Handle
    display_name: DisplayName = None


class AccountUpdate(UpdateModel):
    handle: Handle | None = None
    display_name: DisplayName = None
    is_active: bool | None = None

    @field_validator("handle")
    @classmethod
    def _handle_not_null(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Must not be empty.")
        return value

    @field_validator("is_active")
    @classmethod
    def _is_active_not_null(cls, value: bool | None) -> bool | None:
        if value is None:
            raise ValueError("Must be true or false.")
        return value


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    platform: Platform
    handle: str
    display_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ContentRead(BaseModel):
    """Public view of a content; the storage path is deliberately not exposed."""

    id: int
    project_id: int
    media_type: MediaType
    media_format: MediaFormat
    original_filename: str
    title: str | None
    description: str | None
    hashtags: list[str]
    checksum: str
    size_bytes: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    file_url: str
    file_available: bool
    created_at: datetime
    updated_at: datetime


class ImportFileError(BaseModel):
    code: Literal[
        "empty_file",
        "file_too_large",
        "unsupported_format",
        "invalid_file",
        "storage_error",
    ]
    message: str


class ImportItemResult(BaseModel):
    filename: str
    status: Literal["imported", "duplicate", "rejected"]
    content: ContentRead | None = None
    existing_content: ContentRead | None = None
    error: ImportFileError | None = None


class ImportSummary(BaseModel):
    imported: int
    duplicates: int
    rejected: int


class ImportResult(BaseModel):
    results: list[ImportItemResult]
    summary: ImportSummary


ContentTitle = Annotated[
    Annotated[str, StringConstraints(max_length=200)] | None,
    BeforeValidator(_clean_optional),
]
ContentDescription = Annotated[
    Annotated[str, StringConstraints(max_length=5000)] | None,
    BeforeValidator(_clean_optional),
]

MAX_HASHTAGS = 30
MAX_HASHTAG_LENGTH = 100


def normalize_hashtags(values: list[str] | None) -> list[str]:
    """Strip one leading '#', validate each tag and drop repeats (case-insensitive)."""
    hashtags: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        tag = value.strip()
        if tag.startswith("#"):
            tag = tag[1:].strip()
        if not tag or any(char.isspace() for char in tag):
            raise ValueError("Hashtags cannot be empty or contain spaces.")
        if len(tag) > MAX_HASHTAG_LENGTH:
            raise ValueError(
                f"Each hashtag must be at most {MAX_HASHTAG_LENGTH} characters."
            )
        key = normalize_key(tag)
        if key not in seen:
            seen.add(key)
            hashtags.append(tag)
    if len(hashtags) > MAX_HASHTAGS:
        raise ValueError(f"At most {MAX_HASHTAGS} hashtags are allowed.")
    return hashtags


class ContentUpdate(UpdateModel):
    title: ContentTitle = None
    description: ContentDescription = None
    hashtags: list[str] | None = None

    @field_validator("hashtags")
    @classmethod
    def _normalize_hashtags(cls, value: list[str] | None) -> list[str]:
        return normalize_hashtags(value)


def _to_utc_minute(value: datetime) -> datetime:
    """Publications are scheduled to the minute, always stored as UTC."""
    return value.astimezone(UTC).replace(second=0, microsecond=0)


# A value without a time zone is rejected ("Include a time zone.").
ScheduledAt = Annotated[AwareDatetime, AfterValidator(_to_utc_minute)]


def _strip_keep_empty(value: Any) -> Any:
    """Strip an override but keep "" as an explicit empty override (None inherits)."""
    return value.strip() if isinstance(value, str) else value


TitleOverride = Annotated[
    Annotated[str, StringConstraints(max_length=200)] | None,
    BeforeValidator(_strip_keep_empty),
]
DescriptionOverride = Annotated[
    Annotated[str, StringConstraints(max_length=5000)] | None,
    BeforeValidator(_strip_keep_empty),
]

MAX_ACCOUNTS_PER_REQUEST = 50


class PublicationCreate(InputModel):
    account_ids: list[int] = Field(min_length=1, max_length=MAX_ACCOUNTS_PER_REQUEST)
    scheduled_at: ScheduledAt | None = None
    # Explicit consent to publish automatically at `scheduled_at` (Feature 007).
    auto_publish_enabled: bool = False


class PublicationUpdate(UpdateModel):
    """Omitted fields keep their value; null removes the date or an override."""

    scheduled_at: ScheduledAt | None = None
    # Omitted while changing the date means disarmed: consent is never implicit.
    auto_publish_enabled: bool = False
    title_override: TitleOverride = None
    description_override: DescriptionOverride = None
    hashtags_override: list[str] | None = None

    @field_validator("hashtags_override")
    @classmethod
    def _normalize_hashtags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_hashtags(value)


class PublicationContentSummary(BaseModel):
    id: int
    title: str | None
    original_filename: str
    media_type: MediaType
    file_url: str
    file_available: bool


class PublicationAccountSummary(BaseModel):
    id: int
    platform: Platform
    handle: str
    display_name: str | None
    is_active: bool


class PublicationAttemptErrorRead(BaseModel):
    code: str
    message: str


class PublicationWarningRead(BaseModel):
    code: str
    message: str


class PublicationAttemptRead(BaseModel):
    """One real execution; never contains tokens or upload session URLs."""

    id: int
    publication_id: int
    platform: Platform
    trigger: AttemptTrigger
    status: AttemptStatus
    stage: AttemptStage
    started_at: datetime
    finished_at: datetime | None
    bytes_sent: int
    total_bytes: int
    progress: float
    error: PublicationAttemptErrorRead | None
    # None while running; False when the remote outcome is uncertain.
    outcome_determined: bool | None
    requires_manual_review: bool
    external_id: str | None
    external_url: str | None
    submitted: dict[str, Any]
    details: dict[str, Any]
    warnings: list[PublicationWarningRead]


class AutoPublishErrorRead(BaseModel):
    """Why the last automatic start failed; safe code and message only."""

    code: str
    message: str
    failed_at: datetime


class PublicationRead(BaseModel):
    id: int
    project_id: int
    content_id: int
    account_id: int
    status: PublicationStatus
    scheduled_at: datetime | None
    title_override: str | None
    description_override: str | None
    hashtags_override: list[str] | None
    # Effective metadata: the override when set, otherwise the content's value.
    title: str | None
    description: str | None
    hashtags: list[str]
    content: PublicationContentSummary
    account: PublicationAccountSummary
    project_active: bool
    published_at: datetime | None
    latest_attempt: PublicationAttemptRead | None
    attempt_count: int
    # Automatic publishing (Feature 007); derived fields are null unless scheduled.
    auto_publish_enabled: bool
    auto_publish_state: AutoPublishState | None
    auto_publish_window_ends_at: datetime | None
    auto_publish_error: AutoPublishErrorRead | None
    created_at: datetime
    updated_at: datetime


class PublishRequest(InputModel):
    # Required to run again after an attempt whose remote outcome is uncertain.
    confirm_remote_checked: bool = False


class PublishProblemRead(BaseModel):
    code: str
    message: str
    field: str | None


class PublishSummaryItemRead(BaseModel):
    label: str
    value: str


class PublishCheckRead(BaseModel):
    """What "Publish now" would do, computed without contacting any platform."""

    eligible: bool
    problems: list[PublishProblemRead]
    requires_remote_check: bool
    summary: list[PublishSummaryItemRead]
    scheduled_at: datetime | None


class YouTubePublicationOptionsRead(BaseModel):
    privacy_status: YouTubePrivacy
    made_for_kids: bool | None
    contains_synthetic_media: bool | None
    notify_subscribers: bool
    complete: bool
    editable: bool


class YouTubePublicationOptionsWrite(InputModel):
    """All fields are required; null means "not declared yet"."""

    privacy_status: YouTubePrivacy
    made_for_kids: bool | None
    contains_synthetic_media: bool | None
    notify_subscribers: bool


YouTubeConnectionState = Literal["not_connected", "connected", "reconnect_required"]
OAuthAttemptState = Literal[
    "pending", "awaiting_confirmation", "completed", "failed", "cancelled", "expired"
]


class YouTubeChannelRead(BaseModel):
    id: str
    title: str
    handle: str | None
    thumbnail_url: str | None


class YouTubeConnectionRead(BaseModel):
    """Non-sensitive connection state; tokens are never part of any response."""

    status: YouTubeConnectionState
    channel: YouTubeChannelRead | None
    connected_at: datetime | None
    last_verified_at: datetime | None
    # Whether the local OAuth client configuration is usable (no details exposed).
    oauth_configured: bool


class AuthorizeRead(BaseModel):
    attempt_id: str
    authorization_url: str
    expires_at: datetime


class OAuthAttemptErrorRead(BaseModel):
    code: str
    message: str


class OAuthAttemptRead(BaseModel):
    attempt_id: str
    account_id: int
    status: OAuthAttemptState
    expires_at: datetime
    error: OAuthAttemptErrorRead | None
    current_channel: YouTubeChannelRead | None
    new_channel: YouTubeChannelRead | None
    connection: YouTubeConnectionRead | None


class AutomationStatusRead(BaseModel):
    paused: bool
    # Whether the scheduler thread of this process is alive.
    running: bool
    last_check_at: datetime | None
    check_interval_seconds: float
    window_minutes: int


class AutomationUpdate(InputModel):
    paused: bool
