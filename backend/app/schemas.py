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
    MetadataStatus,
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
    # Optional (Feature 018): without it the account is provisional and adopts the
    # identity of its first connection. Legacy clients keep sending it.
    handle: Handle | None = None
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
    # Null while the account is provisional (identity not known yet).
    handle: str | None
    display_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# What the user sees about a post (Feature 018); single source: post_display_state.
PostDisplayState = Literal[
    "draft",
    "scheduled_automatic",
    "scheduled_manual",
    "scheduled_paused",
    "publishing",
    "published",
    "failed",
    "needs_review",
    "needs_action",
    "missed",
    "cancelled",
]


class ContentUsageRead(BaseModel):
    """Derived from the content's publications; never stored (research §1). The
    Feature 019 counts follow the visible state (`post_display_state`)."""

    used: bool = False
    publication_count: int = 0
    published_count: int = 0
    awaiting_count: int = 0
    scheduled_count: int = 0
    platforms: list[Platform] = []
    last_published_at: datetime | None = None
    draft_count: int = 0
    # Failed, needs review, needs action and missed: what needs the user.
    attention_count: int = 0
    # Publishing or scheduled (automatic, manual or paused).
    upcoming_count: int = 0
    next_scheduled_at: datetime | None = None
    cancelled_count: int = 0


class FieldInheritanceRead(BaseModel):
    """Per text field, whether the post follows the media's value (no override)."""

    title: bool
    description: bool
    hashtags: bool


class AssetPublicationRead(BaseModel):
    """One publication of a content in its usage history."""

    publication_id: int
    platform: Platform
    account_id: int
    account_name: str
    status: PublicationStatus
    scheduled_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # The latest attempt's outcome could not be determined (manual review).
    uncertain: bool
    external_url: str | None
    display_state: PostDisplayState
    inherits: FieldInheritanceRead
    # A TikTok Direct Post consent covers the caption: editing an inherited caption
    # field would make it stale.
    consent_covers_caption: bool = False


class AssetUsageRead(BaseModel):
    usage: ContentUsageRead
    publications: list[AssetPublicationRead]


MetadataCategory = Literal[
    "location",
    "device",
    "software",
    "dates",
    "exif",
    "xmp",
    "iptc",
    "comments",
    "container",
    "ai_generation",
    "comfyui",
    "other",
]


class MetadataFindingRead(BaseModel):
    """A kind of metadata found, with key names only (never values)."""

    category: MetadataCategory
    label: str
    keys: list[str]


class FileMetadataReportRead(BaseModel):
    inspected: bool
    reason: str | None
    findings: list[MetadataFindingRead]


class MetadataReportRead(BaseModel):
    original: FileMetadataReportRead
    # Only for a sanitized content: the clean copy that is published.
    publish_copy: FileMetadataReportRead | None


class PublishFileRead(BaseModel):
    """The file publications send: the original or its clean copy (no paths)."""

    version: Literal["original", "clean_copy"]
    available: bool
    checksum: str
    size_bytes: int
    sanitized_at: datetime | None


class ContentRead(BaseModel):
    """Public view of a content; the storage paths are deliberately not exposed."""

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
    metadata_status: MetadataStatus
    publish_file: PublishFileRead
    usage: ContentUsageRead
    # The Library folder it is in; None = Unsorted (Feature 021).
    folder_id: int | None


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


def _normalize_optional_hashtags(value: list[str] | None) -> list[str] | None:
    """None keeps "no override"; [] stays an explicit empty override."""
    return None if value is None else normalize_hashtags(value)


class PublicationOverrides(InputModel):
    """Metadata overrides; omitted or null means no override at this level."""

    title_override: TitleOverride = None
    description_override: DescriptionOverride = None
    hashtags_override: list[str] | None = None

    @field_validator("hashtags_override")
    @classmethod
    def _normalize_hashtags(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_optional_hashtags(value)


class PublicationCreate(PublicationOverrides):
    """The common overrides apply to every destination; `targets` overrides them
    per account (key = account id)."""

    account_ids: list[int] = Field(min_length=1, max_length=MAX_ACCOUNTS_PER_REQUEST)
    scheduled_at: ScheduledAt | None = None
    # Explicit consent to publish automatically at `scheduled_at` (Feature 007).
    auto_publish_enabled: bool = False
    targets: dict[int, PublicationOverrides] | None = None


class TextPublicationCreate(InputModel):
    """Publications without content (text posts): the text is stored as the
    description and hashtags overrides."""

    account_ids: list[int] = Field(min_length=1, max_length=MAX_ACCOUNTS_PER_REQUEST)
    description: DescriptionOverride = None
    hashtags: list[str] | None = None
    scheduled_at: ScheduledAt | None = None
    auto_publish_enabled: bool = False

    @field_validator("hashtags")
    @classmethod
    def _normalize_hashtags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_hashtags(value)


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
        return _normalize_optional_hashtags(value)


def _unique_account_ids(value: list[int] | None) -> list[int] | None:
    if value is not None and len(set(value)) != len(value):
        raise ValueError("Each destination can only be added once.")
    return value


PresetAccountIds = Annotated[
    list[int],
    Field(min_length=1, max_length=MAX_ACCOUNTS_PER_REQUEST),
    AfterValidator(_unique_account_ids),
]


class DistributionPresetCreate(InputModel):
    """A named set of destinations; it never stores metadata or options."""

    name: ProjectName
    account_ids: PresetAccountIds


class DistributionPresetUpdate(UpdateModel):
    """`account_ids` replaces the whole set of destinations."""

    name: ProjectName | None = None
    account_ids: PresetAccountIds | None = None

    @field_validator("name", "account_ids")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Must not be empty.")
        return value


class DistributionPresetRead(BaseModel):
    id: int
    project_id: int
    name: str
    account_ids: list[int]
    created_at: datetime
    updated_at: datetime


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
    handle: str | None
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
    # Null for publications without media (text posts).
    content_id: int | None
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
    content: PublicationContentSummary | None
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
    display_state: PostDisplayState
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


class TikTokDeliveryFailureRead(BaseModel):
    code: str
    message: str


class TikTokDeliveryRead(BaseModel):
    """Derived Upload to Inbox delivery state; never the `publish_id`."""

    mode: Literal["DIRECT_POST", "INBOX_UPLOAD"] | None
    state: (
        Literal[
            "not_sent",
            "scheduled",
            "uploading",
            "processing",
            "ready",
            "published",
            "failed",
        ]
        | None
    )
    delivered_at: datetime | None
    user_published_at: datetime | None
    # TikTok reported `FAILED` after the video reached the inbox.
    after_delivery_failure: TikTokDeliveryFailureRead | None
    instruction: str | None
    can_check_status: bool


class CheckStatusRead(BaseModel):
    """One check of a publication awaiting user action on the platform."""

    result: Literal["awaiting", "published", "failed"]
    message: str
    checked_at: datetime
    publication: "PublicationRead"


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


class InstagramCaptionLimitsRead(BaseModel):
    caption_characters: int
    caption_hashtags: int
    caption_mentions: int
    alt_text_characters: int


class InstagramPublicationOptionsRead(BaseModel):
    """Instagram options, the exact caption that will be sent and local problems.
    Never contains provider configuration, URLs or credentials."""

    media_kind: Literal["image", "reel"] | None
    caption: str
    caption_length: int
    caption_hashtags: int
    caption_mentions: int
    is_ai_generated: bool | None
    share_to_feed: bool | None
    alt_text: str | None
    complete: bool
    editable: bool
    media_delivery_configured: bool
    problems: list[PublishProblemRead]
    limits: InstagramCaptionLimitsRead


class InstagramPublicationOptionsWrite(InputModel):
    """`is_ai_generated` is required (null means "not declared yet");
    `share_to_feed` only applies to Reels and `alt_text` only to images."""

    is_ai_generated: bool | None
    share_to_feed: bool | None = None
    alt_text: str | None = Field(default=None, max_length=1000)


class ThreadsTextLimitsRead(BaseModel):
    text_characters: int
    text_links: int
    alt_text_characters: int


class ThreadsPublicationOptionsRead(BaseModel):
    """Threads options, the exact text that will be sent and local problems. Never
    contains provider configuration, URLs or credentials."""

    media_kind: Literal["text", "image", "video"] | None
    text: str
    text_length: int
    text_links: int
    alt_text: str | None
    editable: bool
    media_delivery_required: bool
    media_delivery_configured: bool
    problems: list[PublishProblemRead]
    limits: ThreadsTextLimitsRead


class ThreadsPublicationOptionsWrite(InputModel):
    """`alt_text` only applies to images and videos; empty means none."""

    alt_text: str | None = None


TikTokPrivacyLevel = Literal[
    "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"
]
# `missing`: never consented; `stale`: consented, then something material changed.
TikTokConsentState = Literal["missing", "valid", "stale"]


class TikTokDeclarationLinkRead(BaseModel):
    label: str
    url: str


class TikTokDeclarationRead(BaseModel):
    version: str
    text: str
    links: list[TikTokDeclarationLinkRead]


class TikTokConsentRead(BaseModel):
    state: TikTokConsentState
    consented_at: datetime | None


class TikTokIntegrityWarningRead(BaseModel):
    code: str
    message: str
    at: datetime


class TikTokVideoSummaryRead(BaseModel):
    format: str
    size_bytes: int
    duration_seconds: float | None
    width: int | None
    height: int | None
    frame_rate: float | None
    delegated_checks: list[str]
    chunk_count: int


TikTokModeName = Literal["DIRECT_POST", "INBOX_UPLOAD"]


class TikTokModeAvailabilityRead(BaseModel):
    available: bool
    # Why the mode cannot be used right now (None when available).
    reason: str | None


class TikTokPublicationOptionsRead(BaseModel):
    """TikTok options, the exact caption, the declaration and the consent state.
    Never contains tokens, the upload URL nor the `publish_id`."""

    # None means "not chosen yet": there is never a default mode.
    mode: TikTokModeName | None
    modes: dict[TikTokModeName, TikTokModeAvailabilityRead]
    privacy_level: TikTokPrivacyLevel | None
    allow_comment: bool
    allow_duet: bool
    allow_stitch: bool
    commercial_disclosure_enabled: bool
    brand_organic_toggle: bool
    brand_content_toggle: bool
    is_aigc: bool | None
    client_audited: bool
    allowed_privacy_levels: list[TikTokPrivacyLevel]
    caption: str
    caption_length: int
    caption_max_length: int
    declaration: TikTokDeclarationRead
    labels: list[str]
    fingerprint: str | None
    consent: TikTokConsentRead
    integrity_warning: TikTokIntegrityWarningRead | None
    problems: list[PublishProblemRead]
    video: TikTokVideoSummaryRead | None
    editable: bool


class TikTokPublicationOptionsWrite(InputModel):
    """Replaces every option: all fields are required (null mode, privacy or AIGC
    means "not chosen yet"). Direct Post options are kept in every mode and only
    checked in Direct Post."""

    mode: TikTokModeName | None
    privacy_level: TikTokPrivacyLevel | None
    allow_comment: bool
    allow_duet: bool
    allow_stitch: bool
    commercial_disclosure_enabled: bool
    brand_organic_toggle: bool
    brand_content_toggle: bool
    is_aigc: bool | None

    @model_validator(mode="after")
    def toggles_need_disclosure(self) -> Self:
        if not self.commercial_disclosure_enabled and (
            self.brand_organic_toggle or self.brand_content_toggle
        ):
            raise ValueError(
                "Your brand and Branded content need the commercial content "
                "disclosure turned on."
            )
        return self


class TikTokCreatorBlockedRead(BaseModel):
    code: str
    message: str


class TikTokCreatorInfoRead(BaseModel):
    """What TikTok reports now about the destination account (never stored). The
    avatar URL is only for display and expires after two hours."""

    nickname: str | None
    username: str | None
    avatar_url: str | None
    privacy_level_options: list[str] | None
    comment_disabled: bool | None
    duet_disabled: bool | None
    stitch_disabled: bool | None
    max_video_post_duration_sec: int | None
    can_post: bool
    blocked: TikTokCreatorBlockedRead | None
    account_appears_public: bool
    video_within_max_duration: bool | None


class TikTokConsentWrite(InputModel):
    """The fingerprint and declaration the user saw and accepted."""

    fingerprint: str = Field(min_length=64, max_length=64)
    declaration_version: str = Field(min_length=1, max_length=40)


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


InstagramConnectionState = Literal["not_connected", "connected", "reconnect_required"]
InstagramAccountTypeValue = Literal["BUSINESS", "MEDIA_CREATOR"]


class InstagramIdentityRead(BaseModel):
    instagram_user_id: str
    username: str
    account_type: InstagramAccountTypeValue
    profile_picture_url: str | None


class InstagramConnectionRead(BaseModel):
    """Non-sensitive Instagram connection state; tokens are never part of a response."""

    status: InstagramConnectionState
    identity: InstagramIdentityRead | None
    connected_at: datetime | None
    last_verified_at: datetime | None
    access_expires_at: datetime | None
    # Whether the local Meta App configuration is usable (no details exposed).
    oauth_configured: bool


class InstagramAuthorizeRead(BaseModel):
    attempt_id: str
    authorization_url: str
    expires_at: datetime


class InstagramOAuthAttemptRead(BaseModel):
    attempt_id: str
    account_id: int
    status: OAuthAttemptState
    expires_at: datetime
    error: OAuthAttemptErrorRead | None
    current_identity: InstagramIdentityRead | None
    new_identity: InstagramIdentityRead | None
    connection: InstagramConnectionRead | None


class InstagramCompleteWrite(InputModel):
    # The redirect URL the user pasted from the browser (code and state included).
    redirect_url: Annotated[str, StringConstraints(min_length=1, max_length=4096)]


ThreadsConnectionState = Literal["not_connected", "connected", "reconnect_required"]


class ThreadsIdentityRead(BaseModel):
    threads_user_id: str
    username: str
    display_name: str | None
    profile_picture_url: str | None


class ThreadsConnectionRead(BaseModel):
    """Non-sensitive Threads connection state; tokens are never part of a response."""

    status: ThreadsConnectionState
    identity: ThreadsIdentityRead | None
    connected_at: datetime | None
    last_verified_at: datetime | None
    token_obtained_at: datetime | None
    # API name of ThreadsConnection.credential_expires_at (long-lived token expiry).
    access_expires_at: datetime | None
    # Last official value from Meta; informational only, it never changes the status.
    data_access_expires_at: datetime | None
    # Whether the local Threads app configuration is usable (no details exposed).
    oauth_configured: bool


class ThreadsAuthorizeRead(BaseModel):
    attempt_id: str
    authorization_url: str
    expires_at: datetime


class ThreadsOAuthAttemptRead(BaseModel):
    attempt_id: str
    account_id: int
    status: OAuthAttemptState
    expires_at: datetime
    error: OAuthAttemptErrorRead | None
    current_identity: ThreadsIdentityRead | None
    new_identity: ThreadsIdentityRead | None
    connection: ThreadsConnectionRead | None


class ThreadsCompleteWrite(InputModel):
    # The redirect URL the user pasted from the browser (code and state included).
    redirect_url: Annotated[str, StringConstraints(min_length=1, max_length=4096)]


TikTokConnectionState = Literal["not_connected", "connected", "reconnect_required"]
TikTokOAuthAttemptState = Literal[
    "pending",
    "processing",
    "awaiting_confirmation",
    "completed",
    "failed",
    "cancelled",
    "expired",
]
TikTokScopesSource = Literal["token_exchange", "token_refresh"]
TikTokRevocation = Literal["revoked", "already_invalid", "not_revoked", "not_connected"]


class TikTokIdentityRead(BaseModel):
    open_id: str
    display_name: str | None
    avatar_url: str | None


class TikTokCapabilitiesRead(BaseModel):
    """What the granted scopes allow: Direct Post needs the base scopes, Upload to
    Inbox needs `video.upload` as well."""

    direct_post: bool
    inbox_upload: bool


class TikTokPermissionsRead(BaseModel):
    """Requested scopes granted according to TikTok's last token response; never a
    live check."""

    granted: list[str]
    source: TikTokScopesSource
    confirmed_at: datetime
    capabilities: TikTokCapabilitiesRead


class TikTokConnectionRead(BaseModel):
    """Non-sensitive TikTok connection state; tokens are never part of a response."""

    status: TikTokConnectionState
    identity: TikTokIdentityRead | None
    connected_at: datetime | None
    last_verified_at: datetime | None
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None
    # Null when the stored credential cannot be read.
    permissions: TikTokPermissionsRead | None
    # Whether the local TikTok app configuration is usable (no details exposed).
    oauth_configured: bool


class TikTokAuthorizeRead(BaseModel):
    attempt_id: str
    authorization_url: str
    expires_at: datetime


class TikTokAttemptIdentityRead(BaseModel):
    display_name: str | None
    avatar_url: str | None
    open_id_suffix: str


class TikTokOAuthAttemptRead(BaseModel):
    attempt_id: str
    account_id: int
    status: TikTokOAuthAttemptState
    expires_at: datetime
    error: OAuthAttemptErrorRead | None
    current_identity: TikTokAttemptIdentityRead | None
    new_identity: TikTokAttemptIdentityRead | None
    connection: TikTokConnectionRead | None


class TikTokDisconnectRead(BaseModel):
    connection: TikTokConnectionRead
    revocation: TikTokRevocation


class AutomationStatusRead(BaseModel):
    paused: bool
    # Whether the scheduler thread of this process is alive.
    running: bool
    last_check_at: datetime | None
    check_interval_seconds: float
    window_minutes: int


class AutomationUpdate(InputModel):
    paused: bool


# --- Telegram (specs/015-telegram-user-publishing, contracts/api.md) ---------------

TelegramConnectionState = Literal["not_connected", "connected", "reconnect_required"]
TelegramLoginStep = Literal["code", "password"]


class TelegramIdentityRead(BaseModel):
    telegram_user_id: str
    display_name: str
    username: str | None


class TelegramChannelRead(BaseModel):
    # The access hash is internal and never part of a response.
    channel_id: str
    title: str
    username: str | None


class TelegramLoginRead(BaseModel):
    step: TelegramLoginStep
    # Masked phone number; the full number is never returned.
    phone_hint: str
    expires_at: datetime


class TelegramConnectionRead(BaseModel):
    """Non-sensitive Telegram connection state; the session is never part of it."""

    account_id: int
    # Whether the local Telegram app configuration is usable (no details exposed).
    configured: bool
    status: TelegramConnectionState
    identity: TelegramIdentityRead | None
    channel: TelegramChannelRead | None
    # True while the account has Telegram publications scheduled or publishing.
    channel_change_blocked: bool
    login: TelegramLoginRead | None
    connected_at: datetime | None
    last_verified_at: datetime | None
    rate_limited_until: datetime | None


class TelegramChannelsRead(BaseModel):
    channels: list[TelegramChannelRead]


class TelegramLoginStartWrite(InputModel):
    phone: Annotated[str, StringConstraints(pattern=r"^\+[0-9]{6,15}$")]


class TelegramLoginCodeWrite(InputModel):
    code: Annotated[str, StringConstraints(pattern=r"^[0-9]{3,10}$")]


class TelegramLoginPasswordWrite(InputModel):
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class TelegramChannelWrite(InputModel):
    channel_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,20}$")]


# --- Read-models (Feature 018): read only, computed on every request ----------------


class ProjectRefRead(BaseModel):
    id: int
    name: str


class AccountRefRead(BaseModel):
    id: int
    platform: Platform
    label: str


class AttentionPostRead(BaseModel):
    id: int
    display_state: PostDisplayState
    scheduled_at: datetime | None
    media_title: str | None
    excerpt: str | None


class AttentionTargetRead(BaseModel):
    type: Literal["post", "account", "settings"]
    project_id: int | None = None
    id: int | None = None


class AttentionActionRead(BaseModel):
    label: str
    target: AttentionTargetRead


AttentionKind = Literal[
    "manual_review",
    "failed",
    "missed",
    "needs_action",
    "reconnect",
    "incomplete",
    "expiring",
]


class AttentionItemRead(BaseModel):
    kind: AttentionKind
    priority: int
    project: ProjectRefRead
    account: AccountRefRead
    post: AttentionPostRead | None
    title: str
    detail: str | None
    at: datetime | None
    action: AttentionActionRead
    affected_posts: int = 0


class UpcomingPostRead(BaseModel):
    post_id: int
    project: ProjectRefRead
    account: AccountRefRead
    scheduled_at: datetime
    display_state: PostDisplayState
    media_title: str | None
    excerpt: str | None


class NextPostRead(BaseModel):
    post_id: int
    scheduled_at: datetime
    display_state: PostDisplayState


class OnboardingRead(BaseModel):
    account_ready: bool
    media_imported: bool
    post_created: bool
    complete: bool


class ProjectSummaryRead(BaseModel):
    id: int
    name: str
    is_active: bool
    accounts_active: int
    accounts_ready: int
    attention_count: int
    next_post: NextPostRead | None
    onboarding: OnboardingRead


class OverviewAutomationRead(BaseModel):
    paused: bool
    running: bool
    # Armed future posts that will not publish while automation stays paused.
    paused_automatic_posts: int


class OverviewRead(BaseModel):
    generated_at: datetime
    automation: OverviewAutomationRead
    attention: list[AttentionItemRead]
    upcoming: list[UpcomingPostRead]
    projects: list[ProjectSummaryRead]


AccountHealthState = Literal[
    "ready", "reconnect_needed", "setup_required", "not_connected", "inactive"
]
Capability = Literal["text", "images", "videos"]


class AccountIdentityRead(BaseModel):
    # Never platform ids, tokens or credential references.
    name: str
    username: str | None = None
    avatar_url: str | None = None


class AccountIssueRead(BaseModel):
    code: str
    message: str


class AccountHealthRead(BaseModel):
    account_id: int
    platform: Platform
    label: str
    display_name: str | None
    is_active: bool
    state: AccountHealthState
    identity: AccountIdentityRead | None
    expires_at: datetime | None
    expiring: bool
    capabilities: list[Capability]
    issue: AccountIssueRead | None
    can_discard: bool


class PlatformAvailabilityRead(BaseModel):
    platform: Platform
    label: str
    integration_available: bool
    status: Literal["configured", "partial", "not_configured", "coming_soon"]
    can_connect: bool
    missing: list[Literal["app_credentials", "media_delivery"]]
    message: str | None


# --- Library folders (Feature 021) -------------------------------------------------

# Folders nest up to this depth (the root level is 1).
MAX_FOLDER_DEPTH = 5
MAX_CONTENTS_PER_MOVE = 500

FolderName = ProjectName


class LibraryFolderCreate(InputModel):
    """`parent_id` null creates a top-level folder."""

    name: FolderName
    parent_id: int | None = None


class LibraryFolderUpdate(InputModel):
    """Only the name changes: a folder never moves."""

    name: FolderName


class LibraryFolderNodeRead(BaseModel):
    """One folder of the flat tree; `media_count` counts its own media only."""

    id: int
    parent_id: int | None
    name: str
    depth: int
    media_count: int


class LibraryFolderRead(LibraryFolderNodeRead):
    project_id: int
    created_at: datetime
    updated_at: datetime


class LibraryFoldersRead(BaseModel):
    """The whole tree of a project, ordered by `depth, name_key`, plus the counts of
    the two virtual entries: Unsorted (no folder) and All media."""

    folders: list[LibraryFolderNodeRead]
    unsorted_count: int
    total_count: int


def _unique_content_ids(value: list[int]) -> list[int]:
    if len(set(value)) != len(value):
        raise ValueError("Each media item can only be listed once.")
    return value


class ContentMove(InputModel):
    """Move media to a folder of the same project, or to Unsorted (`folder_id`
    null). The key is required so a forgotten destination never means Unsorted."""

    content_ids: Annotated[
        list[int],
        Field(min_length=1, max_length=MAX_CONTENTS_PER_MOVE),
        AfterValidator(_unique_content_ids),
    ]
    folder_id: int | None


class ContentMoveResult(BaseModel):
    moved: int


# --- Deletion (Feature 021) ---------------------------------------------------------

DeletionKind = Literal["post", "media", "account", "project", "folder"]


class DeletionCountsRead(BaseModel):
    """What disappears with the object; every field is always present."""

    unpublished_posts: int = 0
    # Published and Awaiting user action.
    remote_posts: int = 0
    needs_review_posts: int = 0
    accounts: int = 0
    posts: int = 0
    media: int = 0
    subfolders: int = 0
    media_to_unsorted: int = 0


class DeletionBlockerRead(BaseModel):
    code: Literal["post_in_progress", "metadata_removal_in_progress"]
    message: str


class DeletionPreviewRead(BaseModel):
    """The confirmation of a delete (contracts/api.md §1). `confirmation` is an
    opaque, deterministic digest of the scope: never a secret nor a lock."""

    kind: DeletionKind
    id: int
    name: str
    counts: DeletionCountsRead
    summary: list[str]
    blocker: DeletionBlockerRead | None
    confirmation: str
