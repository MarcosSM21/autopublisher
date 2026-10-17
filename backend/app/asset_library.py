"""Asset Library: derived usage of contents and their metadata (Feature 016).

Usage is never stored: it is computed from the publications with two aggregate
queries per project (research §1), so listings never grow with N+1 queries.
"""

import hashlib
import logging
from collections.abc import Collection
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import ColumnElement, case, exists, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import config, media
from app.content_files import (
    ContentFileGuard,
    ContentFileUnavailable,
    clean_copy_relative_path,
    resolve_publish_file,
)
from app.contents import StorageDep, content_read, get_content_or_404
from app.db import UTCDateTime, get_session, utc_now
from app.errors import AppError, ConflictError
from app.image_metadata import FileMetadataReport, inspect_image, sanitize_image
from app.models import (
    Account,
    Content,
    MediaFormat,
    MediaType,
    MetadataStatus,
    Platform,
    Publication,
)
from app.models import PublicationStatus as Status
from app.post_state import needs_manual_review
from app.publications import account_label, latest_attempts
from app.schemas import (
    AssetPublicationRead,
    AssetUsageRead,
    ContentRead,
    ContentUsageRead,
    FileMetadataReportRead,
    MetadataFindingRead,
    MetadataReportRead,
)
from app.storage import MediaStorage
from app.video_metadata import (
    FfmpegMissing,
    SanitizeFailed,
    inspect_video_metadata,
    sanitize_video,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["asset-library"])

PUBLISHING_MESSAGE = (
    "This content is being published. Remove metadata after the upload finishes."
)
ORIGINAL_MISSING_MESSAGE = "The media file is not available."
INVALID_MEDIA_MESSAGE = (
    "The file structure is not valid, so its metadata cannot be removed safely."
)
STORAGE_ERROR_MESSAGE = "The clean copy could not be saved. Please try again."

SessionDep = Annotated[Session, Depends(get_session)]

# Statuses that count as "used": a confirmed publication, or a post handed to the
# platform that waits for the user there (never reported as published).
USED_STATUSES = (Status.PUBLISHED.value, Status.AWAITING_USER_ACTION.value)


def _count(status: Status) -> ColumnElement[int]:
    return func.sum(case((Publication.status == status.value, 1), else_=0))


def usage_by_content(
    session: Session, project_id: int, content_ids: Collection[int] | None = None
) -> dict[int, ContentUsageRead]:
    """Usage summary per content of the project; contents without publications are
    absent (their usage is the empty default)."""
    conditions = [
        Publication.project_id == project_id,
        Publication.content_id.is_not(None),
    ]
    if content_ids is not None:
        conditions.append(Publication.content_id.in_(content_ids))
    totals = session.execute(
        select(
            Publication.content_id,
            func.count(Publication.id),
            _count(Status.PUBLISHED),
            _count(Status.AWAITING_USER_ACTION),
            _count(Status.SCHEDULED),
            func.max(
                case(
                    (
                        Publication.status == Status.PUBLISHED.value,
                        Publication.published_at,
                    )
                ),
                type_=UTCDateTime(),
            ),
        )
        .where(*conditions)
        .group_by(Publication.content_id)
    ).all()
    # `content_id IS NOT NULL` is part of the conditions.
    platforms: dict[int | None, set[str]] = {}
    for content_id, platform in session.execute(
        select(Publication.content_id, Account.platform)
        .join(Account, Account.id == Publication.account_id)
        .where(*conditions, Publication.status.in_(USED_STATUSES))
        .distinct()
    ):
        platforms.setdefault(content_id, set()).add(platform)
    usage: dict[int, ContentUsageRead] = {}
    for content_id, total, published, awaiting, scheduled, last in totals:
        assert content_id is not None
        usage[content_id] = ContentUsageRead(
            used=published + awaiting > 0,
            publication_count=total,
            published_count=published,
            awaiting_count=awaiting,
            scheduled_count=scheduled,
            platforms=[Platform(p) for p in sorted(platforms.get(content_id, ()))],
            last_published_at=last,
        )
    return usage


@router.get("/contents/{content_id}/usage", response_model=AssetUsageRead)
def get_content_usage(content_id: int, session: SessionDep) -> AssetUsageRead:
    """Every publication of the content, most recently changed first."""
    content = get_content_or_404(session, content_id)
    rows = session.execute(
        select(Publication, Account)
        .join(Account, Account.id == Publication.account_id)
        .where(Publication.content_id == content.id)
        .order_by(Publication.updated_at.desc(), Publication.id.desc())
    ).all()
    attempts = latest_attempts(session, [publication.id for publication, _ in rows])
    publications = []
    for publication, account in rows:
        latest = attempts.get(publication.id)
        attempt = latest[0] if latest is not None else None
        publications.append(
            AssetPublicationRead(
                publication_id=publication.id,
                platform=Platform(account.platform),
                account_id=account.id,
                account_name=account.display_name
                or account.handle
                or account_label(account),
                status=Status(publication.status),
                scheduled_at=publication.scheduled_at,
                published_at=publication.published_at,
                created_at=publication.created_at,
                updated_at=publication.updated_at,
                uncertain=attempt is not None and needs_manual_review(attempt),
                external_url=attempt.external_url if attempt is not None else None,
            )
        )
    usage = usage_by_content(session, content.project_id, [content.id])
    return AssetUsageRead(
        usage=usage.get(content.id, ContentUsageRead()), publications=publications
    )


# --- Inspect metadata (research §9) -------------------------------------------------

COPY_MISSING_REASON = "The clean copy is missing."


def _inspect(path: Path, content: Content) -> FileMetadataReportRead:
    if content.media_type == MediaType.IMAGE:
        try:
            with path.open("rb") as src:
                report = inspect_image(src, MediaFormat(content.media_format))
        except OSError:
            report = FileMetadataReport(False, "The file could not be read.")
    else:
        report = inspect_video_metadata(path)
    return FileMetadataReportRead(
        inspected=report.inspected,
        reason=report.reason,
        findings=[
            MetadataFindingRead(
                category=finding.category,  # type: ignore[arg-type]
                label=finding.label,
                keys=finding.keys,
            )
            for finding in report.findings
        ],
    )


@router.get("/contents/{content_id}/metadata", response_model=MetadataReportRead)
def inspect_content_metadata(
    content_id: int, session: SessionDep, storage: StorageDep
) -> MetadataReportRead:
    """What metadata the original and the published clean copy carry, on demand.
    Only categories and key names: values are never returned nor logged."""
    content = get_content_or_404(session, content_id)
    original = _inspect(_original_path(storage, content), content)
    publish_copy = None
    if content.metadata_status == MetadataStatus.SANITIZED:
        try:
            copy = resolve_publish_file(storage, content, verify=False)
            publish_copy = _inspect(copy.path, content)
        except ContentFileUnavailable:
            publish_copy = FileMetadataReportRead(
                inspected=False, reason=COPY_MISSING_REASON, findings=[]
            )
    return MetadataReportRead(original=original, publish_copy=publish_copy)


# --- Remove metadata (research §5) -------------------------------------------------


def get_file_guard(request: Request) -> ContentFileGuard:
    guard: ContentFileGuard = request.app.state.content_file_guard
    return guard


GuardDep = Annotated[ContentFileGuard, Depends(get_file_guard)]


def _publishing_exists(content_id: int) -> ColumnElement[bool]:
    return exists().where(
        Publication.content_id == content_id,
        Publication.status == Status.PUBLISHING.value,
    )


def _original_path(storage: MediaStorage, content: Content) -> Path:
    try:
        path = storage.resolve(content.storage_path)
        if path.is_file() and path.stat().st_size == content.size_bytes:
            return path
    except (ValueError, OSError):
        pass
    raise AppError(404, "media_unavailable", ORIGINAL_MISSING_MESSAGE)


def _sanitize_to(original: Path, temp: Path, content: Content) -> None:
    """Write the clean version of the original to `temp` (the original is only
    ever opened for reading)."""
    media_format = MediaFormat(content.media_format)
    try:
        if content.media_type == MediaType.IMAGE:
            with original.open("rb") as src, temp.open("xb") as dst:
                sanitize_image(src, dst, media_format)
        else:
            sanitize_video(original, temp, media_format)
    except media.InvalidMediaError:
        raise AppError(422, "invalid_media", INVALID_MEDIA_MESSAGE) from None
    except FfmpegMissing as error:
        raise AppError(503, "ffmpeg_required", error.message) from None
    except SanitizeFailed as error:
        raise AppError(500, "sanitize_failed", error.message) from None
    except OSError:
        logger.warning("Could not write a clean copy.")
        raise AppError(500, "storage_error", STORAGE_ERROR_MESSAGE) from None


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as file:
        while chunk := file.read(config.CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _copy_is_valid(storage: MediaStorage, content: Content) -> bool:
    try:
        resolve_publish_file(storage, content, verify=True)
    except ContentFileUnavailable:
        return False
    return True


@router.post("/contents/{content_id}/remove-metadata", response_model=ContentRead)
def remove_metadata(
    content_id: int, session: SessionDep, storage: StorageDep, guard: GuardDep
) -> ContentRead:
    """Create the clean copy that every later publication sends (or mark the
    content clean when nothing had to be removed). Idempotent; never changes the
    original; allowed in inactive projects since nothing is published."""
    content = get_content_or_404(session, content_id)
    if content.metadata_status == MetadataStatus.CLEAN or (
        content.metadata_status == MetadataStatus.SANITIZED
        and _copy_is_valid(storage, content)
    ):
        return content_read(session, content, storage)
    original = _original_path(storage, content)

    def check() -> None:
        if session.scalar(select(_publishing_exists(content.id))):
            raise ConflictError("content_publishing", PUBLISHING_MESSAGE)

    with guard.sanitizing(content.id, check):
        _remove(session, storage, content, original)
    session.refresh(content)
    return content_read(session, content, storage)


def _remove(
    session: Session, storage: MediaStorage, content: Content, original: Path
) -> None:
    status_before = content.metadata_status
    copy_before = content.sanitized_storage_path
    extension = media.EXTENSIONS[MediaFormat(content.media_format)]
    temp = storage.tmp_dir / f"{uuid4().hex}.sanitize{extension}"
    final: Path | None = None
    try:
        _sanitize_to(original, temp, content)
        checksum, size = _digest(temp)
        # Only the state read at the start may change, never during a publication.
        conditions = [
            Content.id == content.id,
            Content.metadata_status == status_before,
            ~_publishing_exists(content.id),
        ]
        conditions.append(
            Content.sanitized_storage_path.is_(None)
            if copy_before is None
            else Content.sanitized_storage_path == copy_before
        )
        if status_before == MetadataStatus.UNKNOWN and checksum == content.checksum:
            values: dict[str, object] = {"metadata_status": MetadataStatus.CLEAN.value}
        else:
            relative = clean_copy_relative_path(content.project_id, extension)
            final = storage.commit(temp, relative)
            values = {
                "metadata_status": MetadataStatus.SANITIZED.value,
                "sanitized_storage_path": relative,
                "sanitized_checksum": checksum,
                "sanitized_size_bytes": size,
                "sanitized_at": utc_now(),
            }
        result = session.execute(
            update(Content)
            .where(*conditions)
            .values(**values, updated_at=utc_now())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            session.rollback()
            raise ConflictError("content_publishing", PUBLISHING_MESSAGE)
        session.commit()
    except OSError:
        session.rollback()
        logger.warning("Could not store a clean copy.")
        if final is not None:
            storage.discard(final)
        raise AppError(500, "storage_error", STORAGE_ERROR_MESSAGE) from None
    except SQLAlchemyError:
        session.rollback()
        logger.warning("Could not save the metadata state of a content.")
        if final is not None:
            storage.discard(final)
        raise AppError(500, "storage_error", STORAGE_ERROR_MESSAGE) from None
    except BaseException:
        if final is not None:
            storage.discard(final)
        raise
    finally:
        storage.discard(temp)
    if copy_before is not None and final is not None:
        # The regenerated copy replaced a missing or damaged one.
        try:
            storage.discard(storage.resolve(copy_before))
        except (ValueError, OSError):
            logger.warning("Could not delete a replaced clean copy.")
