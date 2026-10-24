"""Consequence summary and confirmation token (Feature 021 T014, research §3).

Pure logic over `DeletionScope`, plus `collect_post` on real rows to show that the
token follows the persisted state and never the clock.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import deletion
from app.deletion import DeletionScope, PostEntry, build_preview, confirmation_token
from app.models import Platform
from tests import readmodels
from tests.conftest import create_account, create_project, run_sql
from tests.fakes import FakeClock


def _post(
    post_id: int = 1,
    status: str = "unscheduled",
    *,
    needs_review: bool = False,
    in_progress: bool = False,
    platform: Platform = Platform.YOUTUBE,
) -> PostEntry:
    return PostEntry(post_id, status, needs_review, in_progress, platform)


def _scope(
    *posts: PostEntry,
    content_ids: tuple[int, ...] = (),
    account_ids: tuple[int, ...] = (),
    folder_ids: tuple[int, ...] = (),
) -> DeletionScope:
    return DeletionScope(
        "post",
        1,
        "Teaser",
        posts,
        content_ids=content_ids,
        account_ids=account_ids,
        folder_ids=folder_ids,
    )


def test_token_is_versioned_and_deterministic() -> None:
    token = confirmation_token(_scope(_post()))
    assert token.startswith("v1:")
    assert token == confirmation_token(_scope(_post()))


def test_token_ignores_query_order() -> None:
    first = _scope(
        _post(1), _post(2, "published"), content_ids=(3, 1), account_ids=(9, 4)
    )
    second = _scope(
        _post(2, "published"), _post(1), content_ids=(1, 3), account_ids=(4, 9)
    )
    assert confirmation_token(first) == confirmation_token(second)


@pytest.mark.parametrize(
    "changed",
    [
        _scope(_post(1, "scheduled")),  # draft → scheduled
        _scope(_post(1, "failed", needs_review=True)),  # needs review appears
        _scope(_post(1), _post(2)),  # a post added
        _scope(),  # the post removed
        _scope(_post(1), content_ids=(5,)),
        _scope(_post(1), account_ids=(5,)),
        _scope(_post(1), folder_ids=(5,)),
    ],
    ids=["status", "needs-review", "added", "removed", "content", "account", "folder"],
)
def test_token_changes_with_the_consequences(changed: DeletionScope) -> None:
    assert confirmation_token(changed) != confirmation_token(_scope(_post(1)))


def test_failed_to_needs_review_changes_the_token() -> None:
    failed = _scope(_post(1, "failed"))
    review = _scope(_post(1, "failed", needs_review=True))
    assert confirmation_token(failed) != confirmation_token(review)


def test_blocker_name_and_platform_are_not_part_of_the_token() -> None:
    base = confirmation_token(_scope(_post(1)))
    blocked = DeletionScope("post", 1, "Other name", (_post(1, in_progress=True),))
    assert confirmation_token(blocked) == base
    elsewhere = _scope(_post(1, platform=Platform.TIKTOK))
    assert confirmation_token(elsewhere) == base


@pytest.mark.parametrize(
    ("status", "needs_review", "bucket", "summary"),
    [
        ("unscheduled", False, "unpublished_posts", []),
        ("scheduled", False, "unpublished_posts", ["This post will not be published."]),
        ("cancelled", False, "unpublished_posts", []),
        ("failed", False, "unpublished_posts", []),
        (
            "published",
            False,
            "remote_posts",
            [
                "It will only be removed from AutoPublisher. The content published "
                "on YouTube is not affected."
            ],
        ),
        (
            "awaiting_user_action",
            False,
            "remote_posts",
            [
                "It will only be removed from AutoPublisher. The content published "
                "on YouTube is not affected."
            ],
        ),
        (
            "failed",
            True,
            "needs_review_posts",
            [
                "This post may have been published. Check YouTube before publishing "
                "this media again."
            ],
        ),
    ],
)
def test_post_preview_per_state(
    status: str, needs_review: bool, bucket: str, summary: list[str]
) -> None:
    preview = build_preview(_scope(_post(1, status, needs_review=needs_review)))

    assert preview.summary == summary
    counts = preview.counts.model_dump()
    assert counts.pop("posts") == 1
    assert counts.pop(bucket) == 1
    assert set(counts.values()) == {0}
    assert preview.blocker is None
    assert preview.kind == "post" and preview.id == 1 and preview.name == "Teaser"


def test_publishing_post_is_a_blocker_not_a_bucket() -> None:
    preview = build_preview(_scope(_post(1, "publishing", in_progress=True)))

    assert preview.blocker is not None
    assert preview.blocker.code == "post_in_progress"
    assert preview.blocker.message == (
        "This post is being published right now. Try again when it finishes."
    )
    assert preview.counts.posts == 1
    assert preview.counts.unpublished_posts == preview.counts.remote_posts == 0
    assert preview.confirmation == confirmation_token(_scope(_post(1, "publishing")))


# --- collect_post on real rows -------------------------------------------------------


def _session_scope(client: TestClient, post_id: int) -> DeletionScope:
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        return deletion.collect_post(session, post_id)


def test_clock_alone_never_changes_the_token(
    client: TestClient, db_path: Path, fake_clock: FakeClock
) -> None:
    """A scheduled post that becomes Missed keeps its token: only persisted values
    count, and `collect_post` reads no clock."""
    project = create_project(client, "Cyber")
    account = create_account(client, project["id"], "telegram", "cyber")
    now = fake_clock.now()
    post_id = readmodels.post(
        db_path, account, now, scheduled_at=now + timedelta(minutes=5), armed=True
    )
    before = confirmation_token(_session_scope(client, post_id))

    # The scheduled time is now in the past: the UI would call it Missed.
    run_sql(
        db_path,
        "UPDATE publications SET scheduled_at = '2000-01-01 10:00:00' WHERE id = ?",
        post_id,
    )
    assert confirmation_token(_session_scope(client, post_id)) == before

    run_sql(
        db_path,
        "UPDATE publications SET status = 'unscheduled', scheduled_at = NULL, "
        "auto_publish_enabled = 0 WHERE id = ?",
        post_id,
    )
    assert confirmation_token(_session_scope(client, post_id)) != before


def test_needs_review_follows_the_latest_attempt(
    client: TestClient, db_path: Path, fake_clock: FakeClock
) -> None:
    project = create_project(client, "Cyber")
    account = create_account(client, project["id"], "telegram", "cyber")
    now = fake_clock.now()
    post_id = readmodels.post(db_path, account, now, status="failed")
    readmodels.failed_attempt(db_path, post_id, now)
    (entry,) = _session_scope(client, post_id).posts
    assert (entry.bucket, entry.platform) == ("unpublished", Platform.TELEGRAM)

    readmodels.failed_attempt(
        db_path, post_id, now + timedelta(minutes=1), uncertain=True
    )
    (entry,) = _session_scope(client, post_id).posts
    assert entry.bucket == "needs_review"
