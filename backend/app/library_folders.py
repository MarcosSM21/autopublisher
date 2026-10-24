"""Library folders: logical organization of a project's media (Feature 021, US3/US4).

A folder is only a row: creating, renaming, deleting a folder or moving media never
moves, copies nor renames a file, and never changes a post. "Unsorted" (no folder)
and "All media" are views, not rows, so a user folder may carry either name.

Every write runs in its own `write_transaction` (`BEGIN IMMEDIATE`), so its checks
see the state no other writer can change before the commit; the constraints of
`library_folders` stay the safety net and their `IntegrityError` is never leaked.
Deleting a folder lives in `app.deletion` with the other deletes.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session, get_session_factory, utc_now, write_transaction
from app.errors import ConflictError, NotFoundError
from app.models import Content, LibraryFolder, Project
from app.normalization import normalize_key
from app.projects import get_project_or_404
from app.schemas import (
    MAX_FOLDER_DEPTH,
    ContentMove,
    ContentMoveResult,
    LibraryFolderCreate,
    LibraryFolderNodeRead,
    LibraryFolderRead,
    LibraryFoldersRead,
    LibraryFolderUpdate,
)

router = APIRouter(prefix="/api", tags=["library-folders"])

SessionDep = Annotated[Session, Depends(get_session)]
SessionFactoryDep = Annotated[sessionmaker[Session], Depends(get_session_factory)]

FOLDER_NOT_FOUND = "Folder not found."
NAME_TAKEN_MESSAGE = "A folder with this name already exists here."
TOO_DEEP_MESSAGE = f"Folders can be nested up to {MAX_FOLDER_DEPTH} levels."


def get_folder_in_project(
    session: Session, folder_id: int, project_id: int
) -> LibraryFolder:
    """The folder, or 404 if it does not exist or belongs to another project (the
    answer never reveals which)."""
    folder = session.get(LibraryFolder, folder_id)
    if folder is None or folder.project_id != project_id:
        raise NotFoundError(FOLDER_NOT_FOUND)
    return folder


def _get_folder_or_404(session: Session, folder_id: int) -> LibraryFolder:
    folder = session.get(LibraryFolder, folder_id)
    if folder is None:
        raise NotFoundError(FOLDER_NOT_FOUND)
    return folder


def _ensure_name_available(
    session: Session,
    project_id: int,
    parent_id: int | None,
    name_key: str,
    exclude_id: int | None = None,
) -> None:
    query = select(LibraryFolder.id).where(
        LibraryFolder.project_id == project_id,
        LibraryFolder.name_key == name_key,
        LibraryFolder.parent_id.is_(None)
        if parent_id is None
        else LibraryFolder.parent_id == parent_id,
    )
    if exclude_id is not None:
        query = query.where(LibraryFolder.id != exclude_id)
    if session.scalars(query).first() is not None:
        raise ConflictError("folder_name_taken", NAME_TAKEN_MESSAGE, field="name")


def _flush(session: Session) -> None:
    """Write the pending folder; the checks above already ran under the writer
    lock, so a constraint failure here is only mapped to the same answer."""
    try:
        session.flush()
    except IntegrityError as error:
        detail = str(error.orig)
        if "UNIQUE constraint failed" in detail:
            raise ConflictError(
                "folder_name_taken", NAME_TAKEN_MESSAGE, field="name"
            ) from None
        if "depth" in detail:
            raise ConflictError("folder_too_deep", TOO_DEEP_MESSAGE) from None
        raise


def _media_count(session: Session, folder_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Content)
            .where(Content.folder_id == folder_id)
        )
        or 0
    )


def _folder_read(folder: LibraryFolder, media_count: int) -> LibraryFolderRead:
    return LibraryFolderRead(
        id=folder.id,
        project_id=folder.project_id,
        parent_id=folder.parent_id,
        name=folder.name,
        depth=folder.depth,
        media_count=media_count,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.get("/projects/{project_id}/library-folders", response_model=LibraryFoldersRead)
def list_folders(project_id: int, session: SessionDep) -> LibraryFoldersRead:
    """The flat tree of the project with direct media counts, and the counts of
    Unsorted and All media (three queries)."""
    get_project_or_404(session, project_id)
    counts = dict(
        session.execute(
            select(Content.folder_id, func.count())
            .where(Content.project_id == project_id)
            .group_by(Content.folder_id)
        ).all()
    )
    folders = session.scalars(
        select(LibraryFolder)
        .where(LibraryFolder.project_id == project_id)
        .order_by(LibraryFolder.depth, LibraryFolder.name_key, LibraryFolder.id)
    )
    return LibraryFoldersRead(
        folders=[
            LibraryFolderNodeRead(
                id=folder.id,
                parent_id=folder.parent_id,
                name=folder.name,
                depth=folder.depth,
                media_count=counts.get(folder.id, 0),
            )
            for folder in folders
        ],
        unsorted_count=counts.get(None, 0),
        total_count=sum(counts.values()),
    )


@router.post(
    "/projects/{project_id}/library-folders",
    response_model=LibraryFolderRead,
    status_code=status.HTTP_201_CREATED,
)
def create_folder(
    project_id: int, body: LibraryFolderCreate, session_factory: SessionFactoryDep
) -> LibraryFolderRead:
    """Allowed in inactive projects: organizing never publishes."""
    with write_transaction(session_factory) as session:
        if session.get(Project, project_id) is None:
            raise NotFoundError("Project not found.")
        depth = 1
        if body.parent_id is not None:
            parent = get_folder_in_project(session, body.parent_id, project_id)
            depth = parent.depth + 1
            if depth > MAX_FOLDER_DEPTH:
                raise ConflictError("folder_too_deep", TOO_DEEP_MESSAGE)
        name_key = normalize_key(body.name)
        _ensure_name_available(session, project_id, body.parent_id, name_key)
        now = utc_now()
        folder = LibraryFolder(
            project_id=project_id,
            parent_id=body.parent_id,
            name=body.name,
            name_key=name_key,
            depth=depth,
            created_at=now,
            updated_at=now,
        )
        session.add(folder)
        _flush(session)
        return _folder_read(folder, 0)


@router.patch("/library-folders/{folder_id}", response_model=LibraryFolderRead)
def rename_folder(
    folder_id: int, body: LibraryFolderUpdate, session_factory: SessionFactoryDep
) -> LibraryFolderRead:
    """Only the name changes; renaming to the same key (another case) is allowed."""
    with write_transaction(session_factory) as session:
        folder = _get_folder_or_404(session, folder_id)
        name_key = normalize_key(body.name)
        _ensure_name_available(
            session, folder.project_id, folder.parent_id, name_key, exclude_id=folder.id
        )
        if body.name != folder.name:
            folder.name = body.name
            folder.name_key = name_key
            folder.updated_at = utc_now()
            _flush(session)
        return _folder_read(folder, _media_count(session, folder.id))


@router.post("/projects/{project_id}/contents/move", response_model=ContentMoveResult)
def move_contents(
    project_id: int, body: ContentMove, session_factory: SessionFactoryDep
) -> ContentMoveResult:
    """Move media to a folder or to Unsorted: all of them or none (404 if any id or
    the folder is missing or belongs to another project), with one UPDATE. Files
    and posts never change, so it is allowed while a post is being published."""
    with write_transaction(session_factory) as session:
        if session.get(Project, project_id) is None:
            raise NotFoundError("Project not found.")
        if body.folder_id is not None:
            get_folder_in_project(session, body.folder_id, project_id)
        found = session.scalar(
            select(func.count())
            .select_from(Content)
            .where(Content.id.in_(body.content_ids), Content.project_id == project_id)
        )
        if found != len(body.content_ids):
            raise NotFoundError("Media not found.")
        session.execute(
            update(Content)
            .where(Content.id.in_(body.content_ids), Content.project_id == project_id)
            .values(folder_id=body.folder_id)
            .execution_options(synchronize_session=False)
        )
    return ContentMoveResult(moved=len(body.content_ids))
