"""Request and response bodies. Inputs are cleaned here before any validation."""

from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import Platform
from app.normalization import clean_handle, clean_text


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
