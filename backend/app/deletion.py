"""Permanent deletion (Feature 021, research §1–§3, §5, §7).

One place knows what a delete removes, in which order and what blocks it:

- `collect(session, kind, id)` reads the scope with set queries;
- `build_preview(scope)` turns it into counts, the human summary, the blocker and
  the `confirmation` token, without changing anything;
- `execute(ctx, kind, id, confirmation)` holds the media it removes away from
  Remove metadata, repeats the collection inside its own `write_transaction`
  (`BEGIN IMMEDIATE`), checks the blockers and the token, deletes, queues the files
  and secrets (write-ahead) and commits; only then are connection attempts
  invalidated, files unlinked and secrets deleted. A rejected delete changes
  nothing anywhere.

The `_delete_*` primitives work on sets of ids (or a subquery of them) inside a
transaction that is already open: they never commit and never touch files, the
keyring, the connection attempts or the network. No platform is ever contacted:
content already published stays where it is.
"""

import hashlib
import json
import logging
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import ColumnElement, Select, delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.cleanup import (
    CredentialTarget,
    PendingCredential,
    enqueue_credentials,
    enqueue_files,
    run_credential_cleanup,
    run_file_cleanup,
)
from app.content_files import ContentFileGuard
from app.db import write_transaction
from app.errors import ConflictError, NotFoundError
from app.models import (
    Account,
    AttemptStatus,
    Content,
    DistributionPreset,
    DistributionPresetAccount,
    InstagramConnection,
    InstagramPublicationOptions,
    InstagramPublishRun,
    LibraryFolder,
    Platform,
    Project,
    Publication,
    PublicationAttempt,
    PublicationStatus,
    TelegramConnection,
    TemporaryMediaObject,
    ThreadsConnection,
    ThreadsPublicationOptions,
    ThreadsPublishRun,
    TikTokConnection,
    TikTokPublicationOptions,
    TikTokPublishRun,
    YouTubeConnection,
    YouTubePublicationOptions,
)
from app.post_state import needs_manual_review
from app.publications import PLATFORM_LABELS, account_label, effective_metadata
from app.schemas import (
    MAX_FOLDER_DEPTH,
    DeletionBlockerRead,
    DeletionCountsRead,
    DeletionKind,
    DeletionPreviewRead,
)
from app.storage import MediaStorage

logger = logging.getLogger(__name__)

# Rows that belong to one attempt of a post, deleted before the attempts.
POST_ATTEMPT_DEPENDENTS = (InstagramPublishRun, ThreadsPublishRun, TikTokPublishRun)
# Rows that belong to one post, deleted before the post.
POST_DEPENDENTS = (
    YouTubePublicationOptions,
    InstagramPublicationOptions,
    ThreadsPublicationOptions,
    TikTokPublicationOptions,
)
# One connection per account and platform (Account delete).
CONNECTION_MODELS = (
    (Platform.YOUTUBE, YouTubeConnection),
    (Platform.INSTAGRAM, InstagramConnection),
    (Platform.THREADS, ThreadsConnection),
    (Platform.TIKTOK, TikTokConnection),
    (Platform.TELEGRAM, TelegramConnection),
)

TOKEN_VERSION = "v1"
NOT_FOUND_MESSAGES: dict[DeletionKind, str] = {
    "post": "Post not found.",
    "media": "Media not found.",
    "account": "Account not found.",
    "project": "Project not found.",
    "folder": "Folder not found.",
}
IN_PROGRESS_MESSAGES: dict[DeletionKind, str] = {
    "post": "This post is being published right now. Try again when it finishes.",
    "media": (
        "A post using this media is being published right now. Try again when it "
        "finishes."
    ),
    "account": (
        "A post of this account is being published right now. Try again when it "
        "finishes."
    ),
    "project": (
        "A post in this project is being published right now. Try again when it "
        "finishes."
    ),
}
METADATA_REMOVAL_MESSAGES: dict[DeletionKind, str] = {
    "media": "Metadata is being removed from this media. Try again when it finishes.",
    "project": (
        "Metadata is being removed from a media item in this project. Try again "
        "when it finishes."
    ),
}
CHANGED_MESSAGE = (
    "Something changed since you opened this. Review it again before deleting."
)
REMOTE_STATUSES = frozenset(
    {PublicationStatus.PUBLISHED, PublicationStatus.AWAITING_USER_ACTION}
)

# Credential store states in which a delete never touches the keyring (no prompt,
# no unlock): the queued secrets wait for a later start-up (research §16).
SKIP_CREDENTIAL_CLEANUP = frozenset({"locked", "unavailable"})

Bucket = Literal["unpublished", "remote", "needs_review"]
# Ids to delete: a small set, or a subquery (an account's or a project's rows), so
# a large project never builds an `IN (...)` near SQLite's bind-parameter limit.
Ids = Collection[int] | Select[int]


@dataclass(frozen=True)
class DeletionContext:
    """The application services a delete needs; the request session is not one."""

    session_factory: sessionmaker[Session]
    file_guard: ContentFileGuard
    storage: MediaStorage
    credential_targets: Mapping[Platform, CredentialTarget]
    # The credential store status seen without any interaction (020 probe).
    probe_status: Callable[[], str]
    # Ends the in-memory connection attempts of a deleted account, without any
    # platform contact (TikTok's pending credential is never revoked).
    invalidate_attempts: Callable[[int], None]


@dataclass(frozen=True)
class PostEntry:
    """One post a delete removes. `status` is the persisted column, never a state
    derived from the clock (Missed, Overdue)."""

    id: int
    status: str
    needs_review: bool
    # `publishing`, or an attempt still running: the delete is blocked.
    in_progress: bool
    platform: Platform

    @property
    def bucket(self) -> Bucket | None:
        """What the summary says about it; None while publishing (a blocker)."""
        if self.status == PublicationStatus.PUBLISHING:
            return None
        if self.needs_review:
            return "needs_review"
        if self.status in REMOTE_STATUSES:
            return "remote"
        return "unpublished"


@dataclass(frozen=True)
class ConnectionEntry:
    """A connection a delete removes. Only `platform` and `id` enter the token: the
    reference just says which secret to queue."""

    platform: Platform
    id: int
    account_id: int
    credential_ref: str


@dataclass(frozen=True)
class DeletionScope:
    """Everything one delete removes, as read from the database."""

    kind: DeletionKind
    target_id: int
    name: str
    posts: tuple[PostEntry, ...]
    content_ids: tuple[int, ...] = ()
    account_ids: tuple[int, ...] = ()
    folder_ids: tuple[int, ...] = ()
    # Media a folder delete sends to Unsorted: they stay, only `folder_id` changes.
    unsorted_ids: tuple[int, ...] = ()
    preset_ids: tuple[int, ...] = ()
    connections: tuple[ConnectionEntry, ...] = ()
    # Files of the deleted contents, relative to the media root. Never part of the
    # token: they only say what to unlink after the commit.
    file_paths: tuple[str, ...] = ()
    # "Your … account on … is not affected." Display only, never in the token.
    unaffected: tuple[str, ...] = ()

    @property
    def in_progress(self) -> bool:
        return any(post.in_progress for post in self.posts)


def _post_entries(
    session: Session, where: ColumnElement[bool]
) -> tuple[PostEntry, ...]:
    """The posts matching `where` (a condition on `Publication`) with their bucket
    and blocker, in two set queries."""
    rows = session.execute(
        select(Publication.id, Publication.status, Account.platform)
        .join(Account, Account.id == Publication.account_id)
        .where(where)
    ).all()
    if not rows:
        return ()
    attempts = session.scalars(
        select(PublicationAttempt)
        .join(Publication, Publication.id == PublicationAttempt.publication_id)
        .where(where)
        .order_by(PublicationAttempt.started_at, PublicationAttempt.id)
    ).all()
    latest: dict[int, PublicationAttempt] = {}
    running: set[int] = set()
    for attempt in attempts:
        latest[attempt.publication_id] = attempt
        if attempt.status == AttemptStatus.RUNNING:
            running.add(attempt.publication_id)
    entries = []
    for post_id, status, platform in rows:
        last = latest.get(post_id)
        entries.append(
            PostEntry(
                id=post_id,
                status=status,
                needs_review=(
                    status == PublicationStatus.FAILED
                    and last is not None
                    and needs_manual_review(last)
                ),
                in_progress=(
                    status == PublicationStatus.PUBLISHING or post_id in running
                ),
                platform=Platform(platform),
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.id))


def collect_post(session: Session, post_id: int) -> DeletionScope:
    publication = session.get(Publication, post_id)
    if publication is None:
        raise NotFoundError(NOT_FOUND_MESSAGES["post"])
    account = session.get_one(Account, publication.account_id)
    content = (
        session.get(Content, publication.content_id)
        if publication.content_id is not None
        else None
    )
    title = effective_metadata(publication, content)[0]
    return DeletionScope(
        kind="post",
        target_id=post_id,
        name=title or account_label(account),
        posts=_post_entries(session, Publication.id == post_id),
    )


def collect_media(session: Session, content_id: int) -> DeletionScope:
    """The media, every post that uses it (any state) and its own files: the
    original and, after Remove metadata, the clean copy. No filesystem access."""
    content = session.get(Content, content_id)
    if content is None:
        raise NotFoundError(NOT_FOUND_MESSAGES["media"])
    paths = [content.storage_path]
    if content.sanitized_storage_path is not None:
        paths.append(content.sanitized_storage_path)
    return DeletionScope(
        kind="media",
        target_id=content_id,
        name=content.original_filename,
        posts=_post_entries(session, Publication.content_id == content_id),
        content_ids=(content_id,),
        file_paths=tuple(paths),
    )


def _connections(
    session: Session, accounts: Select[int]
) -> tuple[ConnectionEntry, ...]:
    """The connections of `accounts` (a subquery of account ids), one query per
    platform table."""
    entries = [
        ConnectionEntry(platform, id_, account_id, ref)
        for platform, model in CONNECTION_MODELS
        for id_, account_id, ref in session.execute(
            select(model.id, model.account_id, model.credential_ref).where(
                model.account_id.in_(accounts)
            )
        )
    ]
    return tuple(sorted(entries, key=lambda entry: (entry.platform, entry.id)))


def _unaffected(account: Account) -> str:
    platform = PLATFORM_LABELS[Platform(account.platform)]
    if account.handle is not None:
        return f"Your @{account.handle} account on {platform} is not affected."
    return f"Your {platform} account is not affected."


def collect_account(session: Session, account_id: int) -> DeletionScope:
    """The account, every post of it (any state), its connection and the secret
    that goes with it. Preset memberships go too, but change nothing the user is
    told: they are not part of the scope."""
    account = session.get(Account, account_id)
    if account is None:
        raise NotFoundError(NOT_FOUND_MESSAGES["account"])
    return DeletionScope(
        kind="account",
        target_id=account_id,
        name=account_label(account),
        posts=_post_entries(session, Publication.account_id == account_id),
        account_ids=(account_id,),
        connections=_connections(
            session, select(Account.id).where(Account.id == account_id)
        ),
        unaffected=(_unaffected(account),),
    )


def collect_project(session: Session, project_id: int) -> DeletionScope:
    """Everything local of the project: accounts and their connections, posts,
    media and their files, folders and presets."""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(NOT_FOUND_MESSAGES["project"])
    accounts = select(Account.id).where(Account.project_id == project_id)
    contents = session.execute(
        select(Content.id, Content.storage_path, Content.sanitized_storage_path)
        .where(Content.project_id == project_id)
        .order_by(Content.id)
    ).all()
    paths = [
        path
        for _, original, clean in contents
        for path in (original, clean)
        if path is not None
    ]
    return DeletionScope(
        kind="project",
        target_id=project_id,
        name=project.name,
        posts=_post_entries(session, Publication.project_id == project_id),
        content_ids=tuple(row[0] for row in contents),
        account_ids=tuple(session.scalars(accounts.order_by(Account.id))),
        folder_ids=tuple(
            session.scalars(
                select(LibraryFolder.id)
                .where(LibraryFolder.project_id == project_id)
                .order_by(LibraryFolder.id)
            )
        ),
        preset_ids=tuple(
            session.scalars(
                select(DistributionPreset.id)
                .where(DistributionPreset.project_id == project_id)
                .order_by(DistributionPreset.id)
            )
        ),
        connections=_connections(session, accounts),
        file_paths=tuple(paths),
    )


def collect_folder(session: Session, folder_id: int) -> DeletionScope:
    """The folder, its whole subtree (recursive CTE, research §13) and the media
    directly in any of them, which move to Unsorted. No post nor file is part of
    it: a folder delete never removes media."""
    folder = session.get(LibraryFolder, folder_id)
    if folder is None:
        raise NotFoundError(NOT_FOUND_MESSAGES["folder"])
    subtree = (
        select(LibraryFolder.id)
        .where(LibraryFolder.id == folder_id)
        .cte("subtree", recursive=True)
    )
    subtree = subtree.union_all(
        select(LibraryFolder.id).join(
            subtree,
            (LibraryFolder.parent_id == subtree.c.id)
            & (LibraryFolder.project_id == folder.project_id),
        )
    )
    folder_ids = tuple(sorted(session.scalars(select(subtree.c.id))))
    return DeletionScope(
        kind="folder",
        target_id=folder_id,
        name=folder.name,
        posts=(),
        folder_ids=folder_ids,
        unsorted_ids=tuple(
            session.scalars(
                select(Content.id)
                .where(Content.folder_id.in_(folder_ids))
                .order_by(Content.id)
            )
        ),
    )


def collect(session: Session, kind: DeletionKind, target_id: int) -> DeletionScope:
    """The current scope of deleting `kind` `target_id`; 404 if it is gone."""
    if kind == "post":
        return collect_post(session, target_id)
    if kind == "media":
        return collect_media(session, target_id)
    if kind == "account":
        return collect_account(session, target_id)
    if kind == "project":
        return collect_project(session, target_id)
    if kind == "folder":
        return collect_folder(session, target_id)
    raise ValueError(f"Unknown deletion kind: {kind}")


def confirmation_token(scope: DeletionScope) -> str:
    """`v1:` + SHA-256 of the canonical JSON of what the summary depends on
    (research §3): target, `(post_id, status, needs_review)` by id and the sorted
    ids of the other objects, and `(platform, connection_id)` of the connections
    whose secrets go. No names, handles, refs, paths, timestamps nor clock-derived
    state, so time passing alone never invalidates a confirmation."""
    canonical = {
        "kind": scope.kind,
        "id": scope.target_id,
        "posts": sorted(
            [post.id, str(post.status), post.needs_review] for post in scope.posts
        ),
        "contents": sorted(scope.content_ids),
        "accounts": sorted(scope.account_ids),
        "folders": sorted(scope.folder_ids),
        "to_unsorted": sorted(scope.unsorted_ids),
        "presets": sorted(scope.preset_ids),
        "connections": sorted(
            [str(connection.platform), connection.id]
            for connection in scope.connections
        ),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return f"{TOKEN_VERSION}:{hashlib.sha256(encoded.encode()).hexdigest()}"


def _counts(scope: DeletionScope) -> DeletionCountsRead:
    buckets = [post.bucket for post in scope.posts]
    return DeletionCountsRead(
        unpublished_posts=buckets.count("unpublished"),
        remote_posts=buckets.count("remote"),
        needs_review_posts=buckets.count("needs_review"),
        accounts=len(scope.account_ids),
        posts=len(scope.posts),
        media=len(scope.content_ids),
        # The target itself is not a subfolder.
        subfolders=len(scope.folder_ids) - 1 if scope.kind == "folder" else 0,
        media_to_unsorted=len(scope.unsorted_ids),
    )


def _post_summary(post: PostEntry) -> list[str]:
    platform = PLATFORM_LABELS[post.platform]
    if post.bucket == "needs_review":
        return [
            f"This post may have been published. Check {platform} before "
            "publishing this media again."
        ]
    if post.bucket == "remote":
        return [
            "It will only be removed from AutoPublisher. The content published on "
            f"{platform} is not affected."
        ]
    if post.status == PublicationStatus.SCHEDULED:
        return ["This post will not be published."]
    return []


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _review_line(posts: tuple[PostEntry, ...], *, generic: bool) -> list[str]:
    """The Needs review warning. A media names its platforms; an account or a
    project may hold text posts too, so it speaks of "content" and "the platforms"."""
    review = [post for post in posts if post.bucket == "needs_review"]
    if not review:
        return []
    if generic:
        return [
            f"{_plural(len(review), 'post')} may already have been published. Check "
            "the platforms before publishing this content again."
        ]
    platforms = sorted({PLATFORM_LABELS[post.platform] for post in review})
    return [
        f"{_plural(len(review), 'post')} may have been published. Check "
        f"{_join(platforms)} before publishing this media again."
    ]


def _has_remote(posts: tuple[PostEntry, ...]) -> bool:
    return any(post.bucket in ("remote", "needs_review") for post in posts)


def _posts_summary(posts: tuple[PostEntry, ...], *, generic: bool = False) -> list[str]:
    """What happens to the posts of a media or an account: counts per bucket, with
    "published" covering every post that may exist on a platform."""
    buckets = [post.bucket for post in posts]
    unpublished = buckets.count("unpublished")
    published = buckets.count("remote") + buckets.count("needs_review")
    parts = []
    if unpublished:
        parts.append(_plural(unpublished, "unpublished post"))
    if published:
        parts.append(_plural(published, "published post"))
    lines = []
    if parts:
        lines.append(f"{' and '.join(parts)} will also be removed from AutoPublisher.")
    if published:
        lines.append("Content already published on platforms is not affected.")
    return lines + _review_line(posts, generic=generic)


def _project_summary(scope: DeletionScope) -> list[str]:
    accounts, posts, media = (
        len(scope.account_ids),
        len(scope.posts),
        len(scope.content_ids),
    )
    if accounts == posts == media == 0:
        return []
    lines = [
        f"This project contains {_plural(accounts, 'account')}, "
        f"{_plural(posts, 'post')} and {_plural(media, 'media item')}. Everything "
        "will be removed from AutoPublisher."
    ]
    if _has_remote(scope.posts):
        lines.append("Content already published on platforms is not affected.")
    return lines + _review_line(scope.posts, generic=True)


def _folder_summary(scope: DeletionScope) -> list[str]:
    subfolders, media = len(scope.folder_ids) - 1, len(scope.unsorted_ids)
    lines = []
    if subfolders:
        lines.append(f"{_plural(subfolders, 'subfolder')} will also be removed.")
    if media:
        lines.append(f"{_plural(media, 'media item')} will move to Unsorted.")
    if lines:
        lines.append("No media is deleted.")
    return lines


def _summary(scope: DeletionScope) -> list[str]:
    if scope.kind == "post":
        return [line for post in scope.posts for line in _post_summary(post)]
    if scope.kind == "media":
        return _posts_summary(scope.posts)
    if scope.kind == "account":
        return _posts_summary(scope.posts, generic=True) + list(scope.unaffected)
    if scope.kind == "project":
        return _project_summary(scope)
    if scope.kind == "folder":
        return _folder_summary(scope)
    raise ValueError(f"Unknown deletion kind: {scope.kind}")


def build_preview(
    scope: DeletionScope, *, sanitizing: bool = False
) -> DeletionPreviewRead:
    """`sanitizing`: one of the scope's media is having its metadata removed."""
    blocker = None
    if sanitizing:
        blocker = DeletionBlockerRead(
            code="metadata_removal_in_progress",
            message=METADATA_REMOVAL_MESSAGES[scope.kind],
        )
    elif scope.in_progress:
        blocker = DeletionBlockerRead(
            code="post_in_progress", message=IN_PROGRESS_MESSAGES[scope.kind]
        )
    return DeletionPreviewRead(
        kind=scope.kind,
        id=scope.target_id,
        name=scope.name,
        counts=_counts(scope),
        summary=_summary(scope),
        blocker=blocker,
        confirmation=confirmation_token(scope),
    )


def preview(
    session: Session, kind: DeletionKind, target_id: int, file_guard: ContentFileGuard
) -> DeletionPreviewRead:
    """Read-only: never locks nor reserves anything."""
    scope = collect(session, kind, target_id)
    sanitizing = any(file_guard.is_sanitizing(id_) for id_ in scope.content_ids)
    return build_preview(scope, sanitizing=sanitizing)


def _nonempty(ids: Ids) -> bool:
    return isinstance(ids, Select) or bool(ids)


def _in(ids: Ids) -> Select[int] | list[int]:
    return ids if isinstance(ids, Select) else list(ids)


def _delete_posts(session: Session, post_ids: Ids) -> None:
    """Delete the posts and everything that hangs from them (research §7), inside
    the caller's transaction. Pending temporary delivery objects stay queued with
    `attempt_id` NULL: their cleanup needs only the key (`TemporaryMediaService
    .sweep`). The RESTRICT foreign keys reject the commit if a table is missed."""
    if not _nonempty(post_ids):
        return
    ids = _in(post_ids)
    attempt_ids = select(PublicationAttempt.id).where(
        PublicationAttempt.publication_id.in_(ids)
    )
    statements = [
        delete(TemporaryMediaObject).where(
            TemporaryMediaObject.attempt_id.in_(attempt_ids),
            TemporaryMediaObject.deleted_at.is_not(None),
        ),
        update(TemporaryMediaObject)
        .where(TemporaryMediaObject.attempt_id.in_(attempt_ids))
        .values(attempt_id=None),
        *(
            delete(model).where(model.publication_id.in_(ids))
            for model in POST_ATTEMPT_DEPENDENTS
        ),
        delete(PublicationAttempt).where(PublicationAttempt.publication_id.in_(ids)),
        *(
            delete(model).where(model.publication_id.in_(ids))
            for model in POST_DEPENDENTS
        ),
        delete(Publication).where(Publication.id.in_(ids)),
    ]
    for statement in statements:
        session.execute(statement.execution_options(synchronize_session=False))


def _delete_contents(
    session: Session, content_ids: Ids, file_paths: Collection[str]
) -> None:
    """Queue the media files (write-ahead, in the caller's transaction) and delete
    the contents. Their posts must be gone already; nothing is unlinked here."""
    if not _nonempty(content_ids):
        return
    enqueue_files(session, file_paths)
    session.execute(
        delete(Content)
        .where(Content.id.in_(_in(content_ids)))
        .execution_options(synchronize_session=False)
    )


def _delete_accounts(
    session: Session, account_ids: Ids, connections: Collection[ConnectionEntry]
) -> None:
    """Queue the secrets of the connections (write-ahead, in the caller's
    transaction), then delete preset memberships, connections and accounts. Their
    posts must be gone already; the keyring is never touched here. A preset left
    without destinations stays."""
    if not _nonempty(account_ids):
        return
    ids = _in(account_ids)
    enqueue_credentials(
        session,
        [
            PendingCredential(
                connection.platform, connection.credential_ref, connection.account_id
            )
            for connection in connections
        ],
    )
    statements = [
        delete(DistributionPresetAccount).where(
            DistributionPresetAccount.account_id.in_(ids)
        ),
        *(
            delete(model).where(model.account_id.in_(ids))
            for _, model in CONNECTION_MODELS
        ),
        delete(Account).where(Account.id.in_(ids)),
    ]
    for statement in statements:
        session.execute(statement.execution_options(synchronize_session=False))


def _delete_folders(session: Session, folder_ids: Ids) -> None:
    """Send the media of the folders to Unsorted, then delete the folders (a whole
    subtree), inside the caller's transaction. Media rows stay; no file moves."""
    if not _nonempty(folder_ids):
        return
    ids = _in(folder_ids)
    statements = [
        update(Content).where(Content.folder_id.in_(ids)).values(folder_id=None),
        # RESTRICT is checked row by row: children (deepest) before parents.
        *(
            delete(LibraryFolder).where(
                LibraryFolder.id.in_(ids), LibraryFolder.depth == depth
            )
            for depth in range(MAX_FOLDER_DEPTH, 0, -1)
        ),
    ]
    for statement in statements:
        session.execute(statement.execution_options(synchronize_session=False))


def _delete_project(session: Session, scope: DeletionScope) -> None:
    """Every local row of the project, children first; one transaction."""
    project_id = scope.target_id
    _delete_posts(
        session, select(Publication.id).where(Publication.project_id == project_id)
    )
    _delete_accounts(
        session,
        select(Account.id).where(Account.project_id == project_id),
        scope.connections,
    )
    presets = select(DistributionPreset.id).where(
        DistributionPreset.project_id == project_id
    )
    statements = [
        delete(DistributionPresetAccount).where(
            DistributionPresetAccount.preset_id.in_(presets)
        ),
        delete(DistributionPreset).where(DistributionPreset.project_id == project_id),
    ]
    for statement in statements:
        session.execute(statement.execution_options(synchronize_session=False))
    # Their media go too: detaching them lets the folders go first.
    _delete_folders(
        session,
        select(LibraryFolder.id).where(LibraryFolder.project_id == project_id),
    )
    _delete_contents(
        session,
        select(Content.id).where(Content.project_id == project_id),
        scope.file_paths,
    )
    session.execute(
        delete(Project)
        .where(Project.id == project_id)
        .execution_options(synchronize_session=False)
    )


def _delete(session: Session, scope: DeletionScope) -> None:
    if scope.kind == "project":
        _delete_project(session, scope)
        return
    if scope.kind == "folder":
        _delete_folders(session, scope.folder_ids)
        return
    _delete_posts(session, [post.id for post in scope.posts])
    _delete_contents(session, scope.content_ids, scope.file_paths)
    _delete_accounts(session, scope.account_ids, scope.connections)


@contextmanager
def _held_contents(
    ctx: DeletionContext, kind: DeletionKind, target_id: int
) -> Iterator[frozenset[int]]:
    """Keep the media a delete removes away from Remove metadata (research §6),
    from before the transaction until after it ends; yields the held ids.

    A project's media are read first in a short session of their own: one imported
    afterwards is not held, and the transaction then rejects the delete."""
    if kind == "media":
        ids: Collection[int] = [target_id]
    elif kind == "project":
        with ctx.session_factory() as session:
            ids = session.scalars(
                select(Content.id).where(Content.project_id == target_id)
            ).all()
    else:
        yield frozenset()
        return
    with ctx.file_guard.deleting(ids, blocked_message=METADATA_REMOVAL_MESSAGES[kind]):
        yield frozenset(ids)


def execute(
    ctx: DeletionContext,
    kind: DeletionKind,
    target_id: int,
    confirmation: str,
) -> None:
    """Delete `kind` `target_id` if its scope is still the one confirmed.

    Fixed order: hold its media (`metadata_removal_in_progress`) → one
    `write_transaction`: scope (a media not held → `deletion_changed`) → blocker
    (`post_in_progress`) → token (`deletion_changed`) → delete posts, queue files
    and delete media, queue secrets and delete accounts (and, for a project, its
    presets, folders and itself) → COMMIT → release the media → invalidate the
    deleted accounts' connection attempts → unlink the files → delete the secrets.

    Under SQLite's writer lock no scheduler or manual claim, and no final step of
    a connection flow, can commit in between (research §5, §9b): either it
    committed first and the delete sees it, or it finds no row. A connection
    attempt never blocks. A file or secret that cannot be deleted now stays queued
    for the next start; the delete still succeeded.
    """
    with _held_contents(ctx, kind, target_id) as held:
        with write_transaction(ctx.session_factory) as session:
            scope = collect(session, kind, target_id)
            if kind == "project" and not held.issuperset(scope.content_ids):
                raise ConflictError("deletion_changed", CHANGED_MESSAGE)
            if scope.in_progress:
                raise ConflictError("post_in_progress", IN_PROGRESS_MESSAGES[kind])
            if confirmation != confirmation_token(scope):
                raise ConflictError("deletion_changed", CHANGED_MESSAGE)
            _delete(session, scope)
    logger.info(
        "Deleted %s %s (%d posts, %d media, %d accounts, %d folders, %d media to "
        "Unsorted).",
        kind,
        target_id,
        len(scope.posts),
        len(scope.content_ids),
        len(scope.account_ids),
        len(scope.folder_ids),
        len(scope.unsorted_ids),
    )
    for account_id in scope.account_ids:
        ctx.invalidate_attempts(account_id)
    if scope.file_paths:
        run_file_cleanup(ctx.session_factory, ctx.storage, scope.file_paths)
    if scope.connections:
        _clean_credentials(ctx, [entry.credential_ref for entry in scope.connections])
    if kind == "project":
        _remove_project_dir(ctx.storage, target_id)


def _clean_credentials(ctx: DeletionContext, refs: Collection[str]) -> None:
    """Delete the secrets just queued, then retry the rest of the queue, unless
    the store is seen locked or unavailable: then they all wait (research §16)."""
    try:
        status = ctx.probe_status()
    except Exception as error:
        logger.warning(
            "Credential cleanup deferred (probe failed: %s).", type(error).__name__
        )
        return
    if status in SKIP_CREDENTIAL_CLEANUP:
        logger.info("Credential cleanup deferred (secure storage %s).", status)
        return
    run_credential_cleanup(ctx.session_factory, ctx.credential_targets, refs)
    run_credential_cleanup(ctx.session_factory, ctx.credential_targets)


def _remove_project_dir(storage: MediaStorage, project_id: int) -> None:
    """`projects/{id}` once empty; a file still queued keeps it for later."""
    try:
        (storage.projects_dir / str(project_id)).rmdir()
    except OSError:
        pass
