"""Request and response bodies. Inputs are cleaned here before any validation."""

from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import MediaFormat, MediaType, Platform
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
