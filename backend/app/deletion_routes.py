"""Deletion preview and DELETE routes (Feature 021, contracts/api.md §1).

Thin: the scope, the blockers, the token and the order live in `app.deletion`. The
preview reads with the request's session; a DELETE never uses it and runs in its
own `write_transaction` (research §4, usage rule).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app import deletion
from app.content_files import ContentFileGuard
from app.db import get_session
from app.schemas import DeletionKind, DeletionPreviewRead

router = APIRouter(prefix="/api", tags=["deletion"])


def get_deletion_context(request: Request) -> deletion.DeletionContext:
    state = request.app.state

    def invalidate_attempts(account_id: int) -> None:
        """A later provider redirect or login step is "Authorization not valid"."""
        for registry in (
            state.oauth_attempts,
            state.instagram_attempts,
            state.threads_attempts,
        ):
            registry.expire_for_account(account_id)
        # The pending credential of a TikTok account change is dropped in memory
        # only: deleting never revokes it on TikTok.
        state.tiktok_attempts.expire_for_account(account_id, revoke=False)
        state.telegram_logins.discard(account_id)

    return deletion.DeletionContext(
        session_factory=state.session_factory,
        file_guard=state.content_file_guard,
        storage=state.storage,
        credential_targets=state.credential_targets,
        probe_status=state.credential_probe.status,
        invalidate_attempts=invalidate_attempts,
    )


def get_file_guard(request: Request) -> ContentFileGuard:
    guard: ContentFileGuard = request.app.state.content_file_guard
    return guard


SessionDep = Annotated[Session, Depends(get_session)]
ContextDep = Annotated[deletion.DeletionContext, Depends(get_deletion_context)]
GuardDep = Annotated[ContentFileGuard, Depends(get_file_guard)]
ConfirmationQuery = Annotated[str, Query(min_length=1, max_length=100)]


def _deleted(
    ctx: deletion.DeletionContext,
    kind: DeletionKind,
    target_id: int,
    confirmation: str,
) -> Response:
    deletion.execute(ctx, kind, target_id, confirmation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/publications/{publication_id}/deletion-preview",
    response_model=DeletionPreviewRead,
)
def get_post_deletion_preview(
    publication_id: int, session: SessionDep, guard: GuardDep
) -> DeletionPreviewRead:
    return deletion.preview(session, "post", publication_id, guard)


@router.delete("/publications/{publication_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    publication_id: int, confirmation: ConfirmationQuery, ctx: ContextDep
) -> Response:
    """Removes the post from AutoPublisher only; no platform is contacted."""
    return _deleted(ctx, "post", publication_id, confirmation)


@router.get(
    "/contents/{content_id}/deletion-preview", response_model=DeletionPreviewRead
)
def get_media_deletion_preview(
    content_id: int, session: SessionDep, guard: GuardDep
) -> DeletionPreviewRead:
    return deletion.preview(session, "media", content_id, guard)


@router.delete("/contents/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(
    content_id: int, confirmation: ConfirmationQuery, ctx: ContextDep
) -> Response:
    """Removes the media, every post that uses it and, after the commit, its files.
    Content already published on platforms is not affected."""
    return _deleted(ctx, "media", content_id, confirmation)


@router.get(
    "/accounts/{account_id}/deletion-preview", response_model=DeletionPreviewRead
)
def get_account_deletion_preview(
    account_id: int, session: SessionDep, guard: GuardDep
) -> DeletionPreviewRead:
    return deletion.preview(session, "account", account_id, guard)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int, confirmation: ConfirmationQuery, ctx: ContextDep
) -> Response:
    """Removes the account, all its posts, its connection and, after the commit, its
    local credential. The account on the platform is not affected; a connection in
    progress never blocks it and can no longer complete. Also discards a
    provisional account."""
    return _deleted(ctx, "account", account_id, confirmation)


@router.get(
    "/projects/{project_id}/deletion-preview", response_model=DeletionPreviewRead
)
def get_project_deletion_preview(
    project_id: int, session: SessionDep, guard: GuardDep
) -> DeletionPreviewRead:
    return deletion.preview(session, "project", project_id, guard)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int, confirmation: ConfirmationQuery, ctx: ContextDep
) -> Response:
    """Removes everything of the project from AutoPublisher in one transaction.
    Global settings and content already published on platforms are not affected."""
    return _deleted(ctx, "project", project_id, confirmation)


@router.get(
    "/library-folders/{folder_id}/deletion-preview",
    response_model=DeletionPreviewRead,
)
def get_folder_deletion_preview(
    folder_id: int, session: SessionDep, guard: GuardDep
) -> DeletionPreviewRead:
    return deletion.preview(session, "folder", folder_id, guard)


@router.delete("/library-folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    folder_id: int, confirmation: ConfirmationQuery, ctx: ContextDep
) -> Response:
    """Removes the folder and its subfolders; their media move to Unsorted. No
    media, post or file is deleted, and nothing moves on disk."""
    return _deleted(ctx, "folder", folder_id, confirmation)
