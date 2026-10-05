"""Domain errors and the single error response format (see contracts/api.md)."""

import logging
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "An unexpected error occurred. Please try again."

# Maps uniqueness keys to the field the user typed.
_UNIQUE_KEY_FIELDS = {"name_key": "name", "handle_key": "handle"}


class NotFoundError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConflictError(Exception):
    def __init__(
        self,
        code: Literal["duplicate", "project_inactive"],
        message: str,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def error_response(
    status_code: int,
    code: str,
    message: str,
    fields: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "fields": fields or []}},
        headers=headers,
    )


def _validation_message(error: dict[str, Any]) -> str:
    error_type = error.get("type", "")
    ctx = error.get("ctx") or {}
    if error_type == "missing":
        return "This field is required."
    if error_type in {"string_too_short", "too_short"}:
        return "Must not be empty."
    if error_type in {"string_too_long", "too_long"}:
        return f"Must be at most {ctx.get('max_length')} characters."
    if error_type == "enum":
        return f"Must be one of {ctx.get('expected')}."
    if error_type == "extra_forbidden":
        return "This field cannot be set."
    if error_type == "string_type":
        return "Must be a text value."
    if error_type == "list_type":
        return "Must be a list of text values."
    if error_type == "bool_type":
        return "Must be true or false."
    if error_type == "value_error":
        return str(ctx.get("error", "Invalid value."))
    if error_type == "json_invalid":
        return "The request body is not valid JSON."
    if error_type in {"model_type", "model_attributes_type", "dict_type"}:
        return "The request body must be a JSON object."
    return "Invalid value."


async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields: list[dict[str, str]] = []
    general: list[str] = []
    for error in exc.errors():
        loc = [part for part in error.get("loc", ()) if part != "body"]
        message = _validation_message(error)
        if loc and isinstance(loc[0], str):
            fields.append({"field": loc[0], "message": message})
        else:
            general.append(message)
    message = general[0] if general else "The request contains invalid data."
    return error_response(422, "validation_error", message, fields)


async def _handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
    return error_response(404, "not_found", exc.message)


async def _handle_conflict(request: Request, exc: ConflictError) -> JSONResponse:
    fields = [{"field": exc.field, "message": exc.message}] if exc.field else []
    return error_response(409, exc.code, exc.message, fields)


async def _handle_integrity_error(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    # The request session is closed (and its transaction rolled back) by get_session.
    detail = str(exc.orig)
    if "UNIQUE constraint failed" in detail:
        field = next(
            (name for key, name in _UNIQUE_KEY_FIELDS.items() if key in detail), None
        )
        message = "This value is already in use."
        fields = [{"field": field, "message": message}] if field else []
        return error_response(409, "duplicate", message, fields)
    logger.error("Unexpected integrity error", exc_info=exc)
    return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)


async def _handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if exc.status_code == 404:
        code, message = "not_found", "The requested resource was not found."
    elif exc.status_code == 405:
        code, message = "method_not_allowed", "This operation is not allowed."
    else:
        code, message = "http_error", str(exc.detail)
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unexpected error", exc_info=exc)
    return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(NotFoundError, _handle_not_found)  # type: ignore[arg-type]
    app.add_exception_handler(ConflictError, _handle_conflict)  # type: ignore[arg-type]
    app.add_exception_handler(IntegrityError, _handle_integrity_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected_error)
