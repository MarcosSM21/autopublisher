import logging
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app import config, media
from app.db import get_session, utc_now
from app.errors import ConflictError, NotFoundError
from app.models import Content, MediaFormat, MediaType
from app.projects import get_project_or_404
from app.schemas import (
    ContentRead,
    ContentUpdate,
    ImportFileError,
    ImportItemResult,
    ImportResult,
    ImportSummary,
)
from app.storage import FileTooLargeError, MediaStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["contents"])

SessionDep = Annotated[Session, Depends(get_session)]

UNSUPPORTED_FORMAT_MESSAGE = (
    "Unsupported file format. Supported: JPEG, PNG, WebP, MP4, MOV, WebM."
)


def get_storage(request: Request) -> MediaStorage:
    storage: MediaStorage = request.app.state.storage
    return storage


StorageDep = Annotated[MediaStorage, Depends(get_storage)]


def _file_available(storage: MediaStorage, content: Content) -> bool:
    try:
        return storage.resolve(content.storage_path).is_file()
    except ValueError:
        return False


def content_to_read(content: Content, storage: MediaStorage) -> ContentRead:
    return ContentRead(
        id=content.id,
        project_id=content.project_id,
        media_type=MediaType(content.media_type),
        media_format=MediaFormat(content.media_format),
        original_filename=content.original_filename,
        title=content.title,
        description=content.description,
        hashtags=list(content.hashtags),
        checksum=content.checksum,
        size_bytes=content.size_bytes,
        width=content.width,
        height=content.height,
        duration_seconds=content.duration_seconds,
        file_url=f"/api/contents/{content.id}/file",
        file_available=_file_available(storage, content),
        created_at=content.created_at,
        updated_at=content.updated_at,
    )


def get_content_or_404(session: Session, content_id: int) -> Content:
    content = session.get(Content, content_id)
    if content is None:
        raise NotFoundError("Content not found.")
    return content


def find_duplicate(session: Session, project_id: int, checksum: str) -> Content | None:
    query = select(Content).where(
        Content.project_id == project_id, Content.checksum == checksum
    )
    return session.scalars(query).first()


def _duplicate(
    filename: str, existing: Content, storage: MediaStorage
) -> ImportItemResult:
    return ImportItemResult(
        filename=filename,
        status="duplicate",
        existing_content=content_to_read(existing, storage),
    )


def clean_filename(raw: str | None) -> str:
    """Keep only the base name the user sees; it is never used as a disk path."""
    name = (raw or "").replace("\\", "/").split("/")[-1].strip()
    if name in {"", ".", ".."}:
        return "unnamed"
    if len(name) <= config.MAX_FILENAME_LENGTH:
        return name
    stem, extension = os.path.splitext(name)
    if len(extension) >= config.MAX_FILENAME_LENGTH:
        return name[: config.MAX_FILENAME_LENGTH]
    return stem[: config.MAX_FILENAME_LENGTH - len(extension)] + extension


def _files_error(message: str) -> RequestValidationError:
    """Report a problem with the whole upload in the shared error format."""
    return RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "files"),
                "msg": message,
                "ctx": {"error": message},
            }
        ]
    )


def _rejected(filename: str, error: ImportFileError) -> ImportItemResult:
    return ImportItemResult(filename=filename, status="rejected", error=error)


def _read_header(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(media.HEADER_SIZE)


def import_one(
    session: Session, storage: MediaStorage, project_id: int, upload: UploadFile
) -> ImportItemResult:
    """Import one uploaded file; any failure is reported in the result."""
    filename = clean_filename(upload.filename)
    try:
        received = storage.receive_upload(upload.file, config.MAX_FILE_SIZE)
    except FileTooLargeError:
        return _rejected(
            filename,
            ImportFileError(
                code="file_too_large", message="The file exceeds the 2 GiB limit."
            ),
        )
    except OSError:
        logger.exception("Could not receive an uploaded file")
        return _rejected(filename, _storage_error())

    final_path: Path | None = None
    try:
        if received.size == 0:
            return _rejected(
                filename,
                ImportFileError(code="empty_file", message="The file is empty."),
            )
        media_format = media.detect_format(_read_header(received.path))
        if media_format is None:
            return _rejected(
                filename,
                ImportFileError(
                    code="unsupported_format", message=UNSUPPORTED_FORMAT_MESSAGE
                ),
            )
        media_type = media.media_type_of(media_format)
        width: int | None = None
        height: int | None = None
        duration: float | None = None
        if media_type is MediaType.IMAGE:
            try:
                width, height = media.read_image_info(received.path, media_format)
            except media.InvalidMediaError:
                return _rejected(
                    filename,
                    ImportFileError(
                        code="invalid_file",
                        message="The file is damaged or is not a valid image.",
                    ),
                )
        existing = find_duplicate(session, project_id, received.checksum)
        if existing is not None:
            return _duplicate(filename, existing, storage)
        if media_type is MediaType.VIDEO:
            info = media.probe_video(received.path)
            width, height, duration = info.width, info.height, info.duration_seconds

        now = utc_now()
        content = Content(
            project_id=project_id,
            media_type=media_type.value,
            media_format=media_format.value,
            storage_path=storage.final_relative_path(
                project_id, media.EXTENSIONS[media_format]
            ),
            original_filename=filename,
            checksum=received.checksum,
            size_bytes=received.size,
            width=width,
            height=height,
            duration_seconds=duration,
            title=None,
            description=None,
            hashtags=[],
            created_at=now,
            updated_at=now,
        )
        try:
            session.add(content)
            session.flush()
            # Only a validated file whose row can be stored reaches its final place.
            final_path = storage.commit(received.path, content.storage_path)
            session.commit()
        except IntegrityError:
            # Another import stored the same file first: report it as a duplicate.
            session.rollback()
            if final_path is not None:
                storage.discard(final_path)
            existing = find_duplicate(session, project_id, received.checksum)
            if existing is not None:
                return _duplicate(filename, existing, storage)
            logger.exception("Could not store an imported file")
            return _rejected(filename, _storage_error())
        except (OSError, SQLAlchemyError):
            session.rollback()
            if final_path is not None:
                storage.discard(final_path)
            logger.exception("Could not store an imported file")
            return _rejected(filename, _storage_error())
        return ImportItemResult(
            filename=filename,
            status="imported",
            content=content_to_read(content, storage),
        )
    finally:
        storage.discard(received.path)


def _storage_error() -> ImportFileError:
    return ImportFileError(
        code="storage_error", message="The file could not be saved. Please try again."
    )


@router.get("/projects/{project_id}/contents", response_model=list[ContentRead])
def list_contents(
    project_id: int, session: SessionDep, storage: StorageDep
) -> list[ContentRead]:
    get_project_or_404(session, project_id)
    query = (
        select(Content)
        .where(Content.project_id == project_id)
        .order_by(Content.created_at.desc(), Content.id.desc())
    )
    return [content_to_read(content, storage) for content in session.scalars(query)]


@router.post("/projects/{project_id}/contents", response_model=ImportResult)
def import_contents(
    project_id: int,
    files: Annotated[list[UploadFile], File()],
    session: SessionDep,
    storage: StorageDep,
) -> ImportResult:
    project = get_project_or_404(session, project_id)
    if not project.is_active:
        raise ConflictError(
            "project_inactive", "Reactivate the project before importing content."
        )
    # The whole request is checked before any file is processed.
    if not files:
        raise _files_error("Select at least one file.")
    if len(files) > config.MAX_FILES_PER_IMPORT:
        raise _files_error(
            f"At most {config.MAX_FILES_PER_IMPORT} files can be imported at once."
        )
    results = [import_one(session, storage, project_id, upload) for upload in files]
    return ImportResult(
        results=results,
        summary=ImportSummary(
            imported=sum(result.status == "imported" for result in results),
            duplicates=sum(result.status == "duplicate" for result in results),
            rejected=sum(result.status == "rejected" for result in results),
        ),
    )


@router.get("/contents/{content_id}", response_model=ContentRead)
def get_content(
    content_id: int, session: SessionDep, storage: StorageDep
) -> ContentRead:
    return content_to_read(get_content_or_404(session, content_id), storage)


@router.patch("/contents/{content_id}", response_model=ContentRead)
def update_content(
    content_id: int, body: ContentUpdate, session: SessionDep, storage: StorageDep
) -> ContentRead:
    """Apply only effective metadata changes; allowed whatever the project's state."""
    content = get_content_or_404(session, content_id)
    fields = body.model_fields_set
    changed = False

    if "title" in fields and body.title != content.title:
        content.title = body.title
        changed = True
    if "description" in fields and body.description != content.description:
        content.description = body.description
        changed = True
    if (
        "hashtags" in fields
        and body.hashtags is not None
        and body.hashtags != content.hashtags
    ):
        content.hashtags = body.hashtags
        changed = True

    if changed:
        content.updated_at = utc_now()
        session.commit()
    return content_to_read(content, storage)


@router.get("/contents/{content_id}/file", response_class=FileResponse)
def get_content_file(
    content_id: int, session: SessionDep, storage: StorageDep
) -> FileResponse:
    content = get_content_or_404(session, content_id)
    try:
        path = storage.resolve(content.storage_path)
    except ValueError:
        path = None
    if path is None or not path.is_file():
        raise NotFoundError("The media file is not available.")
    return FileResponse(
        path, media_type=media.MIME_TYPES[MediaFormat(content.media_format)]
    )
