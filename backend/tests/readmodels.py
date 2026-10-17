"""Rows for the read-model tests (Feature 018), written straight to SQLite so each
test states exactly the situation it checks, without OAuth or publishing flows."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def ts(value: datetime) -> str:
    """The naive UTC text SQLite stores for `UTCDateTime` columns."""
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def insert(db_path: Path, table: str, **values: object) -> int:
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({marks})",
            [ts(v) if isinstance(v, datetime) else v for v in values.values()],
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid


def connect(
    db_path: Path,
    account: dict[str, object],
    now: datetime,
    *,
    status: str = "connected",
    expires_at: datetime | None = None,
    channel: bool = True,
    flood_wait_until: datetime | None = None,
) -> None:
    """A connection row for the account's platform; tokens never live in SQLite."""
    account_id, project_id = account["id"], account["project_id"]
    common = {
        "account_id": account_id,
        "project_id": project_id,
        "status": status,
        "credential_ref": f"secret-ref-{account_id}",
        "connected_at": now,
        "updated_at": now,
    }
    platform = account["platform"]
    if platform == "youtube":
        insert(
            db_path,
            "youtube_connections",
            channel_id=f"UC-SENTINEL-{account_id}",
            channel_title="Cyber Channel",
            channel_handle="@cyber",
            **common,
        )
    elif platform == "instagram":
        insert(
            db_path,
            "instagram_connections",
            instagram_user_id=f"IG-SENTINEL-{account_id}",
            username="cyber.studio",
            account_type="BUSINESS",
            credential_expires_at=expires_at or datetime(2999, 1, 1, tzinfo=UTC),
            **common,
        )
    elif platform == "threads":
        insert(
            db_path,
            "threads_connections",
            threads_user_id=f"TH-SENTINEL-{account_id}",
            username="cyber.studio",
            display_name="Cyber Studio",
            token_obtained_at=now,
            credential_expires_at=expires_at or datetime(2999, 1, 1, tzinfo=UTC),
            **common,
        )
    elif platform == "tiktok":
        insert(
            db_path,
            "tiktok_connections",
            open_id=f"TT-SENTINEL-{account_id}",
            display_name="Cyber Studio",
            access_expires_at=now,
            refresh_expires_at=expires_at or datetime(2999, 1, 1, tzinfo=UTC),
            **common,
        )
    elif platform == "telegram":
        channel_values: dict[str, object] = (
            {
                "channel_id": "1987654321",
                "channel_access_hash": "HASH-SENTINEL",
                "channel_title": "Cyber channel",
            }
            if channel
            else {}
        )
        insert(
            db_path,
            "telegram_connections",
            telegram_user_id=f"TG-SENTINEL-{account_id}",
            display_name="Cyber Studio",
            username="cyber",
            flood_wait_until=flood_wait_until,
            **channel_values,
            **common,
        )
    else:
        raise AssertionError(f"no connection table for {platform}")


def post(
    db_path: Path,
    account: dict[str, object],
    now: datetime,
    *,
    status: str = "scheduled",
    scheduled_at: datetime | None = None,
    armed: bool = False,
    text: str = "Hello",
    updated_at: datetime | None = None,
    auto_error: str | None = None,
) -> int:
    """A text post (no content: several can share an account)."""
    error: dict[str, object] = (
        {
            "auto_publish_error_code": "auto_publish_failed",
            "auto_publish_error_message": auto_error,
            "auto_publish_failed_at": now,
        }
        if auto_error is not None
        else {}
    )
    return insert(
        db_path,
        "publications",
        project_id=account["project_id"],
        account_id=account["id"],
        status=status,
        scheduled_at=scheduled_at,
        description_override=text,
        auto_publish_enabled=armed,
        published_at=now if status == "published" else None,
        created_at=now,
        updated_at=updated_at or now,
        **error,
    )


def failed_attempt(
    db_path: Path,
    publication_id: int,
    now: datetime,
    *,
    uncertain: bool = False,
    message: str = "The platform rejected the post.",
) -> None:
    insert(
        db_path,
        "publication_attempts",
        publication_id=publication_id,
        platform="telegram",
        status="failed",
        stage="done",
        started_at=now,
        finished_at=now,
        bytes_sent=0,
        total_bytes=0,
        error_code="upload_failed",
        error_message=message,
        outcome_determined=not uncertain,
        submitted="{}",
        details="{}",
        warnings="[]",
    )
