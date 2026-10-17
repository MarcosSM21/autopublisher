"""Read-models of Feature 018: overview (attention, upcoming, project summaries) and
account health (research.md §6–§8, contracts/api.md §1–§2).

Read only: nothing here writes to the database, changes a connection, reconciles
an attempt or contacts a platform. The visible state of a post comes from
`post_state.post_display_state`, the health of an account from `account_health`,
and requirements from the existing `publishing.local_check`: no rule is rebuilt.
"""

import logging
import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import (
    instagram_connections,
    telegram_connections,
    threads_connections,
    tiktok_connections,
    youtube_connections,
)
from app.accounts import AccountIssue, ConnectionHealth
from app.automation import Clock, get_clock, is_paused
from app.db import get_session
from app.models import (
    Account,
    Content,
    InstagramConnection,
    Platform,
    Project,
    Publication,
    PublicationAttempt,
    TelegramConnection,
    ThreadsConnection,
    TikTokConnection,
    YouTubeConnection,
)
from app.models import PublicationStatus as Status
from app.post_state import needs_manual_review, post_display_state
from app.projects import get_project_or_404
from app.publications import PLATFORM_LABELS, account_label, effective_metadata
from app.publications import latest_attempts as load_latest_attempts
from app.publishing import PublishContext, Publisher, local_check
from app.schemas import (
    AccountHealthRead,
    AccountIdentityRead,
    AccountIssueRead,
    AccountRefRead,
    AttentionActionRead,
    AttentionItemRead,
    AttentionPostRead,
    AttentionTargetRead,
    Capability,
    NextPostRead,
    OnboardingRead,
    OverviewAutomationRead,
    OverviewRead,
    PostDisplayState,
    ProjectRefRead,
    ProjectSummaryRead,
    UpcomingPostRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["overview"])

SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]

# Attention horizon for upcoming requirements and expiring logins (research.md §7).
HORIZON = timedelta(days=7)
EXPIRING_WITHIN = timedelta(days=7)
UPCOMING_LIMIT = 5
EXCERPT_LENGTH = 80
COULD_NOT_VERIFY = "Couldn't verify requirements"
# The uncertain attempt's raw error stays in the post's attempts (Post detail);
# attention explains the situation instead.
MAY_HAVE_PUBLISHED = "This post may have published. Check it before trying again."

# What each platform can publish, in product language; "text" is added only when the
# publisher declares `accepts_text_only` (research.md §8).
MEDIA_CAPABILITIES: dict[Platform, list[Capability]] = {
    Platform.YOUTUBE: ["videos"],
    Platform.INSTAGRAM: ["images", "videos"],
    Platform.THREADS: ["images", "videos"],
    Platform.TIKTOK: ["videos"],
    Platform.TELEGRAM: ["images", "videos"],
    Platform.X: [],
}

_HealthOf = Callable[[Any, datetime], ConnectionHealth]
CONNECTIONS: tuple[tuple[Any, _HealthOf], ...] = (
    (YouTubeConnection, youtube_connections.health_of),
    (InstagramConnection, instagram_connections.health_of),
    (ThreadsConnection, threads_connections.health_of),
    (TikTokConnection, tiktok_connections.health_of),
    (TelegramConnection, telegram_connections.health_of),
)


def get_publishers(request: Request) -> Mapping[Platform, Publisher]:
    publishers: Mapping[Platform, Publisher] = request.app.state.publishers
    return publishers


PublishersDep = Annotated[Mapping[Platform, Publisher], Depends(get_publishers)]


# --- Account health -----------------------------------------------------------------


def capabilities(
    platform: Platform, publishers: Mapping[Platform, Publisher]
) -> list[Capability]:
    publisher = publishers.get(platform)
    text: list[Capability] = (
        ["text"] if getattr(publisher, "accepts_text_only", False) else []
    )
    return text + MEDIA_CAPABILITIES[platform]


def _expiring_issue(platform: str, expires_at: datetime, now: datetime) -> AccountIssue:
    days = max(1, math.ceil((expires_at - now) / timedelta(days=1)))
    unit = "day" if days == 1 else "days"
    return AccountIssue(
        "credential_expiring",
        f"The {platform} login expires in {days} {unit}. Reconnect to keep publishing.",
    )


def account_health(
    session: Session,
    accounts: Sequence[Account],
    now: datetime,
    publishers: Mapping[Platform, Publisher],
) -> dict[int, AccountHealthRead]:
    """Health of each account, in batch: one `IN` query per connection table.

    The only combination of states: inactive → not_connected → reconnect_needed →
    setup_required → ready, plus `expiring` on ready. Overview, attention and the
    account list all reuse it.
    """
    ids = [account.id for account in accounts]
    connections: dict[int, ConnectionHealth] = {}
    if ids:
        for model, health_of in CONNECTIONS:
            for row in session.scalars(select(model).where(model.account_id.in_(ids))):
                connections[row.account_id] = health_of(row, now)
    # Provisional accounts (no identity yet) are only possible after migration 0017;
    # the query runs only when one exists.
    provisional = [a.id for a in accounts if a.handle is None]
    used: set[int] = set()
    if provisional:
        used = set(
            session.scalars(
                select(Publication.account_id)
                .where(Publication.account_id.in_(provisional))
                .group_by(Publication.account_id)
            )
        )
    result: dict[int, AccountHealthRead] = {}
    for account in accounts:
        platform = Platform(account.platform)
        name = PLATFORM_LABELS[platform]
        connection = connections.get(account.id)
        identity = expires_at = None
        if connection is not None:
            identity = AccountIdentityRead(
                name=connection.identity.name,
                username=connection.identity.username,
                avatar_url=connection.identity.avatar_url,
            )
            expires_at = connection.expires_at
        expiring = False
        issue: AccountIssue | None
        if not account.is_active:
            state = "inactive"
            issue = AccountIssue(
                "account_inactive", "Reactivate this account to publish with it."
            )
        elif connection is None:
            state = "not_connected"
            issue = (
                AccountIssue(
                    "integration_unavailable", f"Publishing to {name} is coming soon."
                )
                if platform == Platform.X
                else AccountIssue(
                    "not_connected", f"Connect this {name} account to publish."
                )
            )
        else:
            state = connection.state
            issue = connection.issue
            if (
                state == "ready"
                and expires_at is not None
                and expires_at <= now + EXPIRING_WITHIN
            ):
                expiring = True
                issue = _expiring_issue(name, expires_at, now)
        result[account.id] = AccountHealthRead(
            account_id=account.id,
            platform=platform,
            label=account_label(account),
            display_name=account.display_name,
            is_active=account.is_active,
            state=state,  # type: ignore[arg-type]
            identity=identity,
            expires_at=expires_at,
            expiring=expiring,
            capabilities=capabilities(platform, publishers),
            issue=AccountIssueRead(code=issue.code, message=issue.message)
            if issue is not None
            else None,
            can_discard=account.handle is None
            and connection is None
            and account.id not in used,
        )
    return result


@router.get(
    "/projects/{project_id}/account-health", response_model=list[AccountHealthRead]
)
def get_account_health(
    project_id: int,
    session: SessionDep,
    clock: ClockDep,
    publishers: PublishersDep,
) -> list[AccountHealthRead]:
    """Health of every account of the project: active first, then by platform and
    label. Read only: no keyring, no network, no writes."""
    get_project_or_404(session, project_id)
    accounts = list(
        session.scalars(select(Account).where(Account.project_id == project_id))
    )
    health = account_health(session, accounts, clock(), publishers)
    return sorted(
        health.values(),
        key=lambda item: (not item.is_active, item.platform.value, item.label.lower()),
    )


# --- Overview -----------------------------------------------------------------------


@dataclass
class _Item:
    read: AttentionItemRead
    # Secondary order inside the same priority (research.md §7).
    order: tuple[Any, ...]


def _descending(value: datetime | None) -> float:
    return -value.timestamp() if value is not None else 0.0


def _ascending(value: datetime | None) -> float:
    return value.timestamp() if value is not None else math.inf


def _post_ref(
    publication: Publication,
    content: Content | None,
    display_state: PostDisplayState,
) -> AttentionPostRead:
    media_title, excerpt = _titles(publication, content)
    return AttentionPostRead(
        id=publication.id,
        display_state=display_state,
        scheduled_at=publication.scheduled_at,
        media_title=media_title,
        excerpt=excerpt,
    )


def _titles(
    publication: Publication, content: Content | None
) -> tuple[str | None, str | None]:
    """Media title for media posts, start of the text for text posts."""
    title, description, _ = effective_metadata(publication, content)
    if content is not None:
        return title or content.original_filename, None
    text = (description or "").strip()
    if len(text) > EXCERPT_LENGTH:
        text = text[: EXCERPT_LENGTH - 1].rstrip() + "…"
    return None, text or None


def _post_target(publication: Publication) -> AttentionTargetRead:
    return AttentionTargetRead(
        type="post", project_id=publication.project_id, id=publication.id
    )


def _is_connection_problem(code: str) -> bool:
    return code.endswith("_not_connected") or code.endswith("_reconnect_required")


class _Snapshot:
    """Everything the overview reads, loaded with a fixed number of queries."""

    def __init__(
        self,
        session: Session,
        project_id: int | None,
        now: datetime,
        publishers: Mapping[Platform, Publisher],
    ) -> None:
        self.session = session
        self.now = now
        self.paused = is_paused(session)
        project_query = select(Project).order_by(
            Project.is_active.desc(), Project.name_key
        )
        if project_id is not None:
            project_query = project_query.where(Project.id == project_id)
        self.projects = list(session.scalars(project_query))
        self.project_ids = [project.id for project in self.projects]
        self.projects_by_id = {project.id: project for project in self.projects}
        self.accounts = list(
            session.scalars(
                select(Account).where(Account.project_id.in_(self.project_ids))
            )
        )
        self.accounts_by_id = {account.id: account for account in self.accounts}
        self.health = account_health(session, self.accounts, now, publishers)
        # Posts that may need attention: failed, awaiting the user, or scheduled up
        # to the horizon (past ones included: they may be missed).
        candidates = session.execute(
            select(Publication, Content)
            .outerjoin(Content, Content.id == Publication.content_id)
            .where(
                Publication.project_id.in_(self.project_ids),
                (Publication.status.in_([Status.FAILED, Status.AWAITING_USER_ACTION]))
                | (
                    (Publication.status == Status.SCHEDULED)
                    & (Publication.scheduled_at <= now + HORIZON)
                ),
            )
        ).all()
        self.candidates: list[tuple[Publication, Content | None]] = [
            (publication, content) for publication, content in candidates
        ]
        failed_ids = [p.id for p, _ in self.candidates if p.status == Status.FAILED]
        self.latest: dict[int, PublicationAttempt] = {
            publication_id: attempt
            for publication_id, (attempt, _) in load_latest_attempts(
                session, failed_ids
            ).items()
        }

    def display_state(self, publication: Publication) -> PostDisplayState:
        return post_display_state(
            publication.status,
            publication.auto_publish_enabled,
            publication.scheduled_at,
            self.paused,
            self.latest.get(publication.id),
            self.now,
        )

    def project_ref(self, project_id: int) -> ProjectRefRead:
        project = self.projects_by_id[project_id]
        return ProjectRefRead(id=project.id, name=project.name)

    def account_ref(self, account: Account) -> AccountRefRead:
        return AccountRefRead(
            id=account.id,
            platform=Platform(account.platform),
            label=account_label(account),
        )


def derive_attention(
    snapshot: _Snapshot, ctx: PublishContext, publishers: Mapping[Platform, Publisher]
) -> list[AttentionItemRead]:
    """Rules 1–7 of research.md §7: at most one item per post (the most serious
    one) and one per account; ordered by priority, then by the rule's own order."""
    now = snapshot.now
    items: list[_Item] = []
    reconnect_items: dict[int, _Item] = {}

    # Accounts first: upcoming posts with only a connection problem fold into them.
    for account in snapshot.accounts:
        project = snapshot.projects_by_id[account.project_id]
        health = snapshot.health[account.id]
        if not project.is_active or not account.is_active:
            continue
        issue = health.issue.message if health.issue is not None else None
        order = (project.name.lower(), health.label.lower())
        if health.state == "reconnect_needed":
            item = _Item(
                AttentionItemRead(
                    kind="reconnect",
                    priority=5,
                    project=snapshot.project_ref(project.id),
                    account=snapshot.account_ref(account),
                    post=None,
                    title="Reconnect needed",
                    detail=issue,
                    at=health.expires_at,
                    action=_account_action(account),
                ),
                order,
            )
            items.append(item)
            reconnect_items[account.id] = item
        elif (
            health.state == "ready"
            and health.expires_at is not None
            and now < health.expires_at <= now + HORIZON
        ):
            items.append(
                _Item(
                    AttentionItemRead(
                        kind="expiring",
                        priority=7,
                        project=snapshot.project_ref(project.id),
                        account=snapshot.account_ref(account),
                        post=None,
                        title="Login expires soon",
                        detail=issue,
                        at=health.expires_at,
                        action=_account_action(account),
                    ),
                    (_ascending(health.expires_at),),
                )
            )

    for publication, content in snapshot.candidates:
        project = snapshot.projects_by_id[publication.project_id]
        account = snapshot.accounts_by_id[publication.account_id]
        post_item = _post_item(snapshot, publication, content, project, account)
        if post_item is None and project.is_active:
            post_item = _incomplete_item(
                snapshot,
                publication,
                content,
                account,
                ctx,
                publishers,
                reconnect_items,
            )
        if post_item is not None:
            items.append(post_item)

    items.sort(key=lambda item: (item.read.priority, item.order))
    return [item.read for item in items]


def _account_action(account: Account) -> AttentionActionRead:
    return AttentionActionRead(
        label="Reconnect",
        target=AttentionTargetRead(
            type="account", project_id=account.project_id, id=account.id
        ),
    )


def _post_item(
    snapshot: _Snapshot,
    publication: Publication,
    content: Content | None,
    project: Project,
    account: Account,
) -> _Item | None:
    """Rules 1–4. Inactive projects keep only 1, 2 and 4."""
    now = snapshot.now
    platform = PLATFORM_LABELS[Platform(account.platform)]
    display_state = snapshot.display_state(publication)

    def item(
        kind: str,
        priority: int,
        title: str,
        detail: str | None,
        at: datetime | None,
        label: str,
        order: tuple[Any, ...],
        target: AttentionTargetRead | None = None,
    ) -> _Item:
        return _Item(
            AttentionItemRead(
                kind=kind,  # type: ignore[arg-type]
                priority=priority,
                project=snapshot.project_ref(project.id),
                account=snapshot.account_ref(account),
                post=_post_ref(publication, content, display_state),
                title=title,
                detail=detail,
                at=at,
                action=AttentionActionRead(
                    label=label, target=target or _post_target(publication)
                ),
            ),
            order,
        )

    if publication.status == Status.FAILED:
        attempt = snapshot.latest.get(publication.id)
        detail = attempt.error_message if attempt is not None else None
        at = (attempt.finished_at if attempt is not None else None) or (
            publication.updated_at
        )
        order = (_descending(publication.updated_at),)
        if attempt is not None and needs_manual_review(attempt):
            return item(
                "manual_review",
                1,
                f"Check {platform} before retrying",
                MAY_HAVE_PUBLISHED,
                at,
                "Review",
                order,
            )
        return item("failed", 2, "Publishing failed", detail, at, "Retry", order)
    if publication.status == Status.AWAITING_USER_ACTION:
        return item(
            "needs_action",
            4,
            f"Finish the post on {platform}",
            None,
            publication.updated_at,
            "Check status",
            (_ascending(publication.updated_at),),
        )
    if not project.is_active or publication.status != Status.SCHEDULED:
        return None
    scheduled_at = publication.scheduled_at
    order = (_ascending(scheduled_at),)
    if display_state == "missed":
        detail = (
            "Its automatic publishing window passed without publishing."
            if publication.auto_publish_enabled
            else "It was set to be published manually at this time."
        )
        return item(
            "missed", 3, "Missed its time", detail, scheduled_at, "Publish now", order
        )
    if (
        publication.auto_publish_enabled
        and snapshot.paused
        and scheduled_at is not None
        and scheduled_at <= now
    ):
        return item(
            "missed",
            3,
            "Missed its time",
            "Automation is paused, so it won't publish automatically.",
            scheduled_at,
            "Resume automation",
            order,
            AttentionTargetRead(type="settings"),
        )
    return None


def _incomplete_item(
    snapshot: _Snapshot,
    publication: Publication,
    content: Content | None,
    account: Account,
    ctx: PublishContext,
    publishers: Mapping[Platform, Publisher],
    reconnect_items: dict[int, _Item],
) -> _Item | None:
    """Rule 6: an upcoming scheduled post whose requirements are incomplete or
    cannot be verified. Never reconciles; `local_check` uses no network."""
    now = snapshot.now
    scheduled_at = publication.scheduled_at
    if (
        publication.status != Status.SCHEDULED
        or scheduled_at is None
        or not now < scheduled_at <= now + HORIZON
    ):
        return None
    detail: str | None = None
    if publication.auto_publish_error_code is not None:
        detail = publication.auto_publish_error_message or COULD_NOT_VERIFY
    else:
        try:
            problems = local_check(
                snapshot.session, publication, ctx, publishers
            ).problems
        except Exception as exc:  # Never "ready", never hidden.
            logger.info(
                "Requirements of publication %s could not be verified (%s).",
                publication.id,
                type(exc).__name__,
            )
            detail = COULD_NOT_VERIFY
        else:
            if not problems:
                return None
            reconnect = reconnect_items.get(account.id)
            if reconnect is not None and all(
                _is_connection_problem(problem.code) for problem in problems
            ):
                reconnect.read.affected_posts += 1
                return None
            detail = problems[0].message
    return _Item(
        AttentionItemRead(
            kind="incomplete",
            priority=6,
            project=snapshot.project_ref(publication.project_id),
            account=snapshot.account_ref(account),
            post=_post_ref(publication, content, snapshot.display_state(publication)),
            title="Needs details before publishing",
            detail=detail,
            at=scheduled_at,
            action=AttentionActionRead(
                label="Complete", target=_post_target(publication)
            ),
        ),
        (_ascending(scheduled_at),),
    )


def _upcoming(snapshot: _Snapshot) -> list[UpcomingPostRead]:
    """The next scheduled posts of active projects (at most five)."""
    active = [p.id for p in snapshot.projects if p.is_active]
    rows = snapshot.session.execute(
        select(Publication, Content)
        .outerjoin(Content, Content.id == Publication.content_id)
        .where(
            Publication.project_id.in_(active),
            Publication.status == Status.SCHEDULED,
            Publication.scheduled_at > snapshot.now,
        )
        .order_by(Publication.scheduled_at, Publication.id)
        .limit(UPCOMING_LIMIT)
    ).all()
    upcoming = []
    for publication, content in rows:
        media_title, excerpt = _titles(publication, content)
        assert publication.scheduled_at is not None
        upcoming.append(
            UpcomingPostRead(
                post_id=publication.id,
                project=snapshot.project_ref(publication.project_id),
                account=snapshot.account_ref(
                    snapshot.accounts_by_id[publication.account_id]
                ),
                scheduled_at=publication.scheduled_at,
                display_state=snapshot.display_state(publication),
                media_title=media_title,
                excerpt=excerpt,
            )
        )
    return upcoming


def _next_posts(snapshot: _Snapshot) -> dict[int, NextPostRead]:
    """The next scheduled post of each active project, in one query."""
    active = [p.id for p in snapshot.projects if p.is_active]
    first = (
        select(
            Publication.project_id.label("project_id"),
            func.min(Publication.scheduled_at).label("scheduled_at"),
        )
        .where(
            Publication.project_id.in_(active),
            Publication.status == Status.SCHEDULED,
            Publication.scheduled_at > snapshot.now,
        )
        .group_by(Publication.project_id)
        .subquery()
    )
    rows = snapshot.session.scalars(
        select(Publication)
        .join(
            first,
            (Publication.project_id == first.c.project_id)
            & (Publication.scheduled_at == first.c.scheduled_at),
        )
        .where(Publication.status == Status.SCHEDULED)
        .order_by(Publication.id)
    )
    result: dict[int, NextPostRead] = {}
    for publication in rows:
        if publication.project_id in result or publication.scheduled_at is None:
            continue
        result[publication.project_id] = NextPostRead(
            post_id=publication.id,
            scheduled_at=publication.scheduled_at,
            display_state=snapshot.display_state(publication),
        )
    return result


def _projects_with(session: Session, column: Any, project_ids: list[int]) -> set[int]:
    """Projects having at least one row (one grouped query)."""
    return set(
        session.scalars(select(column).where(column.in_(project_ids)).group_by(column))
    )


def _paused_automatic_posts(snapshot: _Snapshot) -> int:
    """Armed future posts of active projects that won't publish while paused."""
    if not snapshot.paused:
        return 0
    active = [p.id for p in snapshot.projects if p.is_active]
    count = snapshot.session.scalar(
        select(func.count(Publication.id)).where(
            Publication.project_id.in_(active),
            Publication.status == Status.SCHEDULED,
            Publication.auto_publish_enabled.is_(True),
            Publication.scheduled_at > snapshot.now,
        )
    )
    return int(count or 0)


def _project_summaries(
    snapshot: _Snapshot, attention: list[AttentionItemRead]
) -> list[ProjectSummaryRead]:
    next_posts = _next_posts(snapshot)
    with_media = _projects_with(
        snapshot.session, Content.project_id, snapshot.project_ids
    )
    with_posts = _projects_with(
        snapshot.session, Publication.project_id, snapshot.project_ids
    )
    summaries = []
    for project in snapshot.projects:
        active_accounts = [
            a for a in snapshot.accounts if a.project_id == project.id and a.is_active
        ]
        ready = sum(
            1 for a in active_accounts if snapshot.health[a.id].state == "ready"
        )
        onboarding = OnboardingRead(
            account_ready=ready > 0,
            media_imported=project.id in with_media,
            post_created=project.id in with_posts,
            complete=False,
        )
        onboarding.complete = (
            onboarding.account_ready
            and onboarding.media_imported
            and onboarding.post_created
        )
        summaries.append(
            ProjectSummaryRead(
                id=project.id,
                name=project.name,
                is_active=project.is_active,
                accounts_active=len(active_accounts),
                accounts_ready=ready,
                attention_count=sum(
                    1 for item in attention if item.project.id == project.id
                ),
                next_post=next_posts.get(project.id),
                onboarding=onboarding,
            )
        )
    return summaries


@contextmanager
def _read_only(session: Session) -> Iterator[None]:
    """Discard anything a local check might have staged: the overview never writes."""
    try:
        yield
    finally:
        session.rollback()


def get_publish_context(request: Request) -> PublishContext:
    ctx: PublishContext = request.app.state.publish_context
    return ctx


@router.get("/overview", response_model=OverviewRead)
def get_overview(
    request: Request,
    session: SessionDep,
    clock: ClockDep,
    publishers: PublishersDep,
    ctx: Annotated[PublishContext, Depends(get_publish_context)],
    project_id: int | None = None,
) -> OverviewRead:
    """Home, project strip and checklist in one read-only call: no writes, no
    platform calls, no reconciliation."""
    if project_id is not None:
        get_project_or_404(session, project_id)
    now = clock()
    with _read_only(session):
        snapshot = _Snapshot(session, project_id, now, publishers)
        attention = derive_attention(snapshot, ctx, publishers)
        return OverviewRead(
            generated_at=now,
            automation=OverviewAutomationRead(
                paused=snapshot.paused,
                running=request.app.state.scheduler.running,
                paused_automatic_posts=_paused_automatic_posts(snapshot),
            ),
            attention=attention,
            upcoming=_upcoming(snapshot),
            projects=_project_summaries(snapshot, attention),
        )
