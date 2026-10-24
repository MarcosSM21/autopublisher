import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app import config, media
from app.automation import Clock, get_clock
from app.content_files import (
    ContentFileUnavailable,
    effective_checksum,
    effective_size,
    resolve_publish_file,
)
from app.db import get_session, get_session_factory, utc_now, write_transaction
from app.errors import ConflictError, NotFoundError, field_errors
from app.library_folders import get_folder_in_project
from app.models import (
    Content,
    LibraryFolder,
    MediaFormat,
    MediaType,
    MetadataStatus,
    Project,
)
from app.projects import get_project_or_404
from app.schemas import (
    ContentRead,
    ContentUpdate,
    ContentUsageRead,
    ImportFileError,
    ImportItemResult,
    ImportResult,
    ImportSummary,
    PublishFileRead,
)
from app.storage import FileTooLargeError, MediaStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["contents"])

SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]

UNSUPPORTED_FORMAT_MESSAGE = (
    "Unsupported file format. Supported: JPEG, PNG, WebP, MP4, MOV, WebM."
)


def get_storage(request: Request) -> MediaStorage:
    storage: MediaStorage = request.app.state.storage
    return storage


StorageDep = Annotated[MediaStorage, Depends(get_storage)]


def file_available(storage: MediaStorage, content: Content) -> bool:
    try:
        return storage.resolve(content.storage_path).is_file()
    except ValueError:
        return False


def publish_file_read(storage: MediaStorage, content: Content) -> PublishFileRead:
    """The effective file, checked cheaply (existence + size, no hashing)."""
    sanitized = content.metadata_status == MetadataStatus.SANITIZED
    try:
        effective = resolve_publish_file(storage, content, verify=False)
    except ContentFileUnavailable:
        effective = None
    return PublishFileRead(
        version="clean_copy" if sanitized else "original",
        available=effective is not None,
        checksum=effective_checksum(content),
        size_bytes=effective_size(content),
        sanitized_at=content.sanitized_at if sanitized else None,
    )


def content_to_read(
    content: Content,
    storage: MediaStorage,
    usage: ContentUsageRead | None = None,
) -> ContentRead:
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
        file_available=file_available(storage, content),
        created_at=content.created_at,
        updated_at=content.updated_at,
        metadata_status=MetadataStatus(content.metadata_status),
        publish_file=publish_file_read(storage, content),
        usage=usage if usage is not None else ContentUsageRead(),
        folder_id=content.folder_id,
    )


def content_usage(
    session: Session, content: Content, now: datetime | None = None
) -> ContentUsageRead:
    # Imported here: the Asset Library builds on this module.
    from app.asset_library import usage_by_content

    usage = usage_by_content(session, content.project_id, [content.id], now=now)
    return usage.get(content.id, ContentUsageRead())


def content_read(
    session: Session,
    content: Content,
    storage: MediaStorage,
    now: datetime | None = None,
) -> ContentRead:
    """A single content with its usage (one aggregate for that content only)."""
    return content_to_read(content, storage, content_usage(session, content, now))


def get_content_or_404(session: Session, content_id: int) -> Content:
    content = session.get(Content, content_id)
    if content is None:
        raise NotFoundError("Content not found.")
    return content


def find_duplicate(session: Session, project_id: int, checksum: str) -> Content | None:
    # A file identical to a clean copy is the same asset too (FR-043).
    query = select(Content).where(
        Content.project_id == project_id,
        or_(Content.checksum == checksum, Content.sanitized_checksum == checksum),
    )
    return session.scalars(query).first()


def _duplicate(
    session: Session, filename: str, existing: Content, storage: MediaStorage
) -> ImportItemResult:
    return ImportItemResult(
        filename=filename,
        status="duplicate",
        existing_content=content_read(session, existing, storage),
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
    return field_errors([("files", message)])


def _rejected(filename: str, error: ImportFileError) -> ImportItemResult:
    return ImportItemResult(filename=filename, status="rejected", error=error)


def _read_header(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(media.HEADER_SIZE)


def _live_folder(
    session: Session, project_id: int, folder_id: int | None
) -> int | None:
    """The destination folder if it still exists; a folder deleted while a
    multi-file import runs sends the remaining files to Unsorted."""
    if folder_id is None:
        return None
    folder = session.get(LibraryFolder, folder_id)
    return folder_id if folder is not None and folder.project_id == project_id else None


def import_one(
    session: Session,
    session_factory: sessionmaker[Session],
    storage: MediaStorage,
    project_id: int,
    upload: UploadFile,
    folder_id: int | None = None,
) -> ImportItemResult:
    """Import one uploaded file; any failure is reported in the result.

    The row is written in its own `write_transaction`, which first checks that the
    project (404 if it was deleted meanwhile) and the folder still exist. The file
    reaches its final place only inside that transaction and is removed again if
    the row is not committed, so a failed import never leaves a file behind."""
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
            return _duplicate(session, filename, existing, storage)
        if media_type is MediaType.VIDEO:
            info = media.probe_video(received.path)
            width, height, duration = info.width, info.height, info.duration_seconds

        try:
            with write_transaction(session_factory) as transaction:
                if transaction.get(Project, project_id) is None:
                    raise NotFoundError("Project not found.")
                # Another import may have stored the same file first.
                existing = find_duplicate(transaction, project_id, received.checksum)
                if existing is not None:
                    duplicate_id = existing.id
                else:
                    duplicate_id = None
                    now = utc_now()
                    content = Content(
                        project_id=project_id,
                        folder_id=_live_folder(transaction, project_id, folder_id),
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
                    transaction.add(content)
                    transaction.flush()
                    # Only a validated file whose row can be stored reaches its
                    # final place; the commit follows on leaving the block.
                    final_path = storage.commit(received.path, content.storage_path)
        except NotFoundError:
            if final_path is not None:
                storage.discard(final_path)
            raise
        except (OSError, SQLAlchemyError):
            if final_path is not None:
                storage.discard(final_path)
            logger.exception("Could not store an imported file")
            return _rejected(filename, _storage_error())
        if duplicate_id is not None:
            duplicate = session.get(Content, duplicate_id)
            if duplicate is None:
                return _rejected(filename, _storage_error())
            return _duplicate(session, filename, duplicate, storage)
        return ImportItemResult(
            filename=filename,
            status="imported",
            # A new content has no publications yet.
            content=content_to_read(content, storage),
        )
    finally:
        storage.discard(received.path)


def _storage_error() -> ImportFileError:
    return ImportFileError(
        code="storage_error", message="The file could not be saved. Please try again."
    )


# A Library view: a folder id (its own media only) or `unsorted` (no folder).
FolderView = Annotated[
    str | None, Query(alias="folder", pattern=r"^(unsorted|[1-9][0-9]{0,17})$")
]


@router.get("/projects/{project_id}/contents", response_model=list[ContentRead])
def list_contents(
    project_id: int,
    session: SessionDep,
    storage: StorageDep,
    clock: ClockDep,
    folder: FolderView = None,
) -> list[ContentRead]:
    """All media (no `folder`), Unsorted, or the media directly in one folder
    (never those of its subfolders); 404 for a folder of another project."""
    from app.asset_library import usage_by_content

    get_project_or_404(session, project_id)
    query = (
        select(Content)
        .where(Content.project_id == project_id)
        .order_by(Content.created_at.desc(), Content.id.desc())
    )
    if folder == "unsorted":
        query = query.where(Content.folder_id.is_(None))
    elif folder is not None:
        query = query.where(
            Content.folder_id
            == get_folder_in_project(session, int(folder), project_id).id
        )
    usage = usage_by_content(session, project_id, now=clock())
    return [
        content_to_read(content, storage, usage.get(content.id))
        for content in session.scalars(query)
    ]


@router.post("/projects/{project_id}/contents", response_model=ImportResult)
def import_contents(
    project_id: int,
    files: Annotated[list[UploadFile], File()],
    session: SessionDep,
    session_factory: SessionFactoryDep,
    storage: StorageDep,
    folder_id: Annotated[int | None, Query(ge=1)] = None,
) -> ImportResult:
    """`folder_id`: the folder the new media go to; without it, Unsorted. Files
    never move on disk because of a folder."""
    project = get_project_or_404(session, project_id)
    if not project.is_active:
        raise ConflictError(
            "project_inactive", "Reactivate the project before importing content."
        )
    if folder_id is not None:
        get_folder_in_project(session, folder_id, project_id)
    # The whole request is checked before any file is processed.
    if not files:
        raise _files_error("Select at least one file.")
    if len(files) > config.MAX_FILES_PER_IMPORT:
        raise _files_error(
            f"At most {config.MAX_FILES_PER_IMPORT} files can be imported at once."
        )
    results = [
        import_one(session, session_factory, storage, project_id, upload, folder_id)
        for upload in files
    ]
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
    content_id: int, session: SessionDep, storage: StorageDep, clock: ClockDep
) -> ContentRead:
    return content_read(
        session, get_content_or_404(session, content_id), storage, clock()
    )


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
    return content_read(session, content, storage)


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
