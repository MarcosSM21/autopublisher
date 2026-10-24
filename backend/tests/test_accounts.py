from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import create_account, create_project


def field_errors(response_json: dict[str, Any]) -> dict[str, str]:
    return {item["field"]: item["message"] for item in response_json["error"]["fields"]}


def list_accounts(client: TestClient, project_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/api/projects/{project_id}/accounts")
    assert response.status_code == 200
    accounts: list[dict[str, Any]] = response.json()
    return accounts


def test_create_account_returns_active_account(client: TestClient) -> None:
    project = create_project(client, "L4i4")

    response = client.post(
        f"/api/projects/{project['id']}/accounts",
        json={"platform": "instagram", "handle": " @l4i4 ", "display_name": "  "},
    )

    assert response.status_code == 201
    account = response.json()
    assert account["project_id"] == project["id"]
    assert account["platform"] == "instagram"
    assert account["handle"] == "l4i4"
    assert account["display_name"] is None
    assert account["is_active"] is True
    assert account["created_at"] == account["updated_at"]


def test_project_can_have_accounts_on_several_platforms(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    for platform in ["instagram", "tiktok", "x"]:
        create_account(client, project["id"], platform, "l4i4", "L4i4 Official")

    accounts = list_accounts(client, project["id"])

    assert [account["platform"] for account in accounts] == ["instagram", "tiktok", "x"]
    assert all(account["display_name"] == "L4i4 Official" for account in accounts)


def test_project_can_have_several_accounts_on_the_same_platform(
    client: TestClient,
) -> None:
    project = create_project(client, "Cybersecurity")
    create_account(client, project["id"], "youtube", "cyber")
    create_account(client, project["id"], "youtube", "cyber_shorts")

    assert len(list_accounts(client, project["id"])) == 2


@pytest.mark.parametrize("duplicate", ["@L4I4", "l4i4", " L4i4 "])
def test_duplicate_handle_in_same_project_is_rejected(
    client: TestClient, duplicate: str
) -> None:
    project = create_project(client, "L4i4")
    create_account(client, project["id"], "instagram", "l4i4")

    response = client.post(
        f"/api/projects/{project['id']}/accounts",
        json={"platform": "instagram", "handle": duplicate},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert "handle" in field_errors(response.json())
    assert len(list_accounts(client, project["id"])) == 1


def test_same_handle_is_allowed_in_another_project(client: TestClient) -> None:
    first = create_project(client, "L4i4")
    second = create_project(client, "Cybersecurity")
    create_account(client, first["id"], "instagram", "shared")

    create_account(client, second["id"], "instagram", "shared")


def test_same_handle_is_allowed_on_another_platform(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    create_account(client, project["id"], "instagram", "l4i4")

    create_account(client, project["id"], "tiktok", "l4i4")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"handle": "l4i4"}, "platform"),
        ({"platform": "myspace", "handle": "l4i4"}, "platform"),
        ({"platform": "instagram", "handle": "   "}, "handle"),
        ({"platform": "instagram", "handle": "@"}, "handle"),
        ({"platform": "instagram", "handle": "l4i4", "project_id": 2}, "project_id"),
    ],
)
def test_invalid_account_is_rejected(
    client: TestClient, body: dict[str, Any], field: str
) -> None:
    project = create_project(client, "L4i4")

    response = client.post(f"/api/projects/{project['id']}/accounts", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert field in field_errors(response.json())
    assert list_accounts(client, project["id"]) == []


@pytest.mark.parametrize("field", ["handle", "display_name"])
def test_too_long_values_are_rejected_with_maximum_in_message(
    client: TestClient, field: str
) -> None:
    project = create_project(client, "L4i4")
    body = {"platform": "instagram", "handle": "l4i4", field: "a" * 101}

    response = client.post(f"/api/projects/{project['id']}/accounts", json=body)

    assert response.status_code == 422
    assert "100" in field_errors(response.json())[field]


def test_account_for_unknown_project_is_rejected(client: TestClient) -> None:
    project = create_project(client, "L4i4")

    response = client.post(
        "/api/projects/9999/accounts", json={"platform": "instagram", "handle": "x"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert list_accounts(client, project["id"]) == []


def test_listing_accounts_of_unknown_project_returns_not_found(
    client: TestClient,
) -> None:
    response = client.get("/api/projects/9999/accounts")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_accounts_are_listed_only_in_their_project_and_ordered(
    client: TestClient,
) -> None:
    l4i4 = create_project(client, "L4i4")
    cyber = create_project(client, "Cybersecurity")
    create_account(client, l4i4["id"], "x", "l4i4")
    create_account(client, l4i4["id"], "instagram", "zeta")
    create_account(client, l4i4["id"], "instagram", "Alpha")
    create_account(client, cyber["id"], "youtube", "cyber")

    l4i4_accounts = list_accounts(client, l4i4["id"])
    cyber_accounts = list_accounts(client, cyber["id"])

    assert [(a["platform"], a["handle"]) for a in l4i4_accounts] == [
        ("instagram", "Alpha"),
        ("instagram", "zeta"),
        ("x", "l4i4"),
    ]
    assert [a["handle"] for a in cyber_accounts] == ["cyber"]
    assert all(a["project_id"] == l4i4["id"] for a in l4i4_accounts)


def test_deactivating_a_project_keeps_its_accounts_unchanged(
    client: TestClient,
) -> None:
    project = create_project(client, "Cybersecurity")
    create_account(client, project["id"], "youtube", "cyber")
    create_account(client, project["id"], "instagram", "cyber")
    before = list_accounts(client, project["id"])

    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    after_deactivation = list_accounts(client, project["id"])
    client.patch(f"/api/projects/{project['id']}", json={"is_active": True})
    after_reactivation = list_accounts(client, project["id"])

    assert after_deactivation == before
    assert after_reactivation == before
    assert len(before) == 2


def test_accounts_cannot_be_added_to_inactive_project(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    response = client.post(
        f"/api/projects/{project['id']}/accounts",
        json={"platform": "instagram", "handle": "l4i4"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_inactive"
    assert list_accounts(client, project["id"]) == []

    client.patch(f"/api/projects/{project['id']}", json={"is_active": True})
    create_account(client, project["id"], "instagram", "l4i4")


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def patch_account(client: TestClient, account_id: int, body: object) -> Any:
    return client.patch(f"/api/accounts/{account_id}", json=body)


def test_edit_account_updates_values_and_updated_at(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(
        client, account["id"], {"handle": "@l4i4_art", "display_name": "L4i4 Art"}
    )

    assert response.status_code == 200
    edited = response.json()
    assert edited["handle"] == "l4i4_art"
    assert edited["display_name"] == "L4i4 Art"
    assert edited["platform"] == "instagram"
    assert edited["project_id"] == project["id"]
    assert edited["created_at"] == account["created_at"]
    assert ts(edited["updated_at"]) > ts(account["updated_at"])
    assert list_accounts(client, project["id"]) == [edited]


def test_equivalent_handle_is_not_a_change(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], {"handle": " @l4i4 "})

    assert response.status_code == 200
    assert response.json() == account


def test_changing_only_the_case_of_own_handle_is_allowed(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], {"handle": "L4i4"})

    assert response.status_code == 200
    assert response.json()["handle"] == "L4i4"
    assert ts(response.json()["updated_at"]) > ts(account["updated_at"])


@pytest.mark.parametrize("other_active", [True, False])
def test_handle_of_another_account_is_rejected(
    client: TestClient, other_active: bool
) -> None:
    project = create_project(client, "L4i4")
    other = create_account(client, project["id"], "instagram", "taken")
    patch_account(client, other["id"], {"is_active": other_active})
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], {"handle": "@TAKEN"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate"
    assert "handle" in field_errors(response.json())


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"platform": "x"}, "platform"),
        ({"project_id": 2}, "project_id"),
        ({"handle": ""}, "handle"),
        ({"handle": None}, "handle"),
        ({"is_active": None}, "is_active"),
        ({}, None),
    ],
)
def test_invalid_account_edits_are_rejected(
    client: TestClient, body: dict[str, Any], field: str | None
) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4")

    response = patch_account(client, account["id"], body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    if field:
        assert field in field_errors(response.json())
    assert list_accounts(client, project["id"]) == [account]


def test_display_name_can_be_cleared(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "instagram", "l4i4", "L4i4")

    response = patch_account(client, account["id"], {"display_name": None})

    assert response.json()["display_name"] is None


def test_account_can_be_deactivated_and_reactivated(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4", "L4i4")

    deactivated = patch_account(client, account["id"], {"is_active": False}).json()
    listed = list_accounts(client, project["id"])
    reactivated = patch_account(client, account["id"], {"is_active": True}).json()

    assert deactivated["is_active"] is False
    assert listed == [deactivated]
    assert ts(deactivated["updated_at"]) > ts(account["updated_at"])
    assert reactivated["is_active"] is True
    assert {k: v for k, v in reactivated.items() if k != "updated_at"} == {
        k: v for k, v in account.items() if k != "updated_at"
    }


@pytest.mark.parametrize("state", [True, False])
def test_repeating_the_current_account_state_keeps_updated_at(
    client: TestClient, state: bool
) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4")
    current = patch_account(client, account["id"], {"is_active": state}).json()

    response = patch_account(client, account["id"], {"is_active": state})

    assert response.status_code == 200
    assert response.json() == current


def test_accounts_of_inactive_project_can_be_edited(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4")
    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})

    edited = patch_account(client, account["id"], {"handle": "l4i4_new"})
    toggled = patch_account(client, account["id"], {"is_active": False})

    assert edited.status_code == 200
    assert toggled.json()["is_active"] is False


def test_deactivating_a_project_keeps_individual_account_states(
    client: TestClient,
) -> None:
    project = create_project(client, "Cybersecurity")
    create_account(client, project["id"], "youtube", "cyber")
    inactive = create_account(client, project["id"], "instagram", "cyber")
    patch_account(client, inactive["id"], {"is_active": False})
    before = list_accounts(client, project["id"])

    client.patch(f"/api/projects/{project['id']}", json={"is_active": False})
    client.patch(f"/api/projects/{project['id']}", json={"is_active": True})

    assert list_accounts(client, project["id"]) == before
    assert [a["is_active"] for a in before] == [False, True]


def test_editing_unknown_account_returns_not_found(client: TestClient) -> None:
    response = patch_account(client, 9999, {"handle": "ghost"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_deleting_an_account_requires_its_confirmation(client: TestClient) -> None:
    """Any account can be deleted (Feature 021), only with the preview's token."""
    project = create_project(client, "L4i4")
    account = create_account(client, project["id"], "x", "l4i4")

    response = client.delete(f"/api/accounts/{account['id']}")

    assert response.status_code == 422
    assert list_accounts(client, project["id"]) == [account]
    assert discard(client, account["id"]).status_code == 204
    assert list_accounts(client, project["id"]) == []


ACCOUNT_FIELDS = {
    "id",
    "project_id",
    "platform",
    "handle",
    "display_name",
    "is_active",
    "created_at",
    "updated_at",
}


def test_account_responses_have_no_platform_connection_fields(
    client: TestClient,
) -> None:
    project = create_project(client, "Cyber")
    youtube = create_account(client, project["id"], "youtube", "cyber")
    instagram = create_account(client, project["id"], "instagram", "cyber")

    assert set(youtube) == ACCOUNT_FIELDS
    assert set(instagram) == ACCOUNT_FIELDS
    for account in list_accounts(client, project["id"]):
        assert set(account) == ACCOUNT_FIELDS


def test_accounts_core_does_not_depend_on_platforms() -> None:
    """Constitution III: platform-specific code never leaks into the accounts core."""
    import ast
    import inspect

    from app import accounts, models

    source = inspect.getsource(accounts)
    assert "threads_" not in source.lower()
    assert "tiktok" not in source.lower()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any("youtube" in name for name in imported)
    assert not any("instagram" in name for name in imported)
    assert not any("threads" in name for name in imported)
    assert not any("tiktok" in name for name in imported)
    assert not hasattr(models.Account, "youtube_connection")
    assert not hasattr(models.Account, "instagram_connection")
    assert not hasattr(models.Account, "instagram_connections")
    assert not hasattr(models.Account, "threads_connection")
    assert not hasattr(models.Account, "threads_connections")
    assert not hasattr(models.Account, "tiktok_connection")
    assert not hasattr(models.Account, "tiktok_connections")


# --- Provisional accounts (Feature 018) ---------------------------------------------


def create_provisional(
    client: TestClient, project_id: int, platform: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/projects/{project_id}/accounts", json={"platform": platform}
    )
    assert response.status_code == 201, response.text
    account: dict[str, Any] = response.json()
    return account


def health_of(client: TestClient, account: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"/api/projects/{account['project_id']}/account-health")
    assert response.status_code == 200, response.text
    matches: list[dict[str, Any]] = [
        h for h in response.json() if h["account_id"] == account["id"]
    ]
    [health] = matches
    return health


def test_create_without_handle_is_provisional(client: TestClient) -> None:
    project = create_project(client, "L4i4")

    first = create_provisional(client, project["id"], "instagram")
    second = create_provisional(client, project["id"], "instagram")
    legacy = create_account(client, project["id"], "instagram", "@l4i4")
    duplicate = client.post(
        f"/api/projects/{project['id']}/accounts",
        json={"platform": "instagram", "handle": "L4I4"},
    )

    assert first["handle"] is None and second["handle"] is None  # real NULL
    assert legacy["handle"] == "l4i4"
    assert duplicate.status_code == 409
    health = health_of(client, first)
    assert (health["state"], health["label"], health["can_discard"]) == (
        "not_connected",
        "Instagram account",
        True,
    )
    assert health_of(client, legacy)["can_discard"] is False


def test_account_label_never_shows_a_missing_handle() -> None:
    from app.models import Account
    from app.publications import account_label, account_reference

    provisional = Account(platform="instagram", handle=None, display_name=None)
    named = Account(platform="instagram", handle=None, display_name="Studio")
    legacy = Account(platform="instagram", handle="l4i4", display_name="Studio")

    assert account_label(provisional) == "Instagram account"
    assert account_label(named) == "Instagram account · Studio"
    assert account_label(legacy) == "Instagram @l4i4"
    assert account_reference(provisional) == "Instagram account"
    assert account_reference(legacy) == "@l4i4"


@pytest.mark.parametrize(
    ("handle", "taken", "channel_handle", "title", "expected"),
    [
        (None, None, "@cyberchannel", "Cyber Channel", "cyberchannel"),
        (None, None, None, "Cyber Channel", "Cyber Channel"),
        ("legacy", None, "@cyberchannel", "Cyber Channel", "legacy"),  # kept
        (None, "cyberchannel", "@cyberchannel", "Cyber", None),  # collision
        (None, None, None, "x" * 101, None),  # not a valid handle
    ],
)
def test_connection_adopts_the_identity_of_a_provisional_account(
    youtube_client: TestClient,
    fake_google: Any,
    handle: str | None,
    taken: str | None,
    channel_handle: str | None,
    title: str,
    expected: str | None,
) -> None:
    from tests.conftest import connect_youtube

    project = create_project(youtube_client, "Cyber")
    if taken is not None:
        create_account(youtube_client, project["id"], "youtube", taken)
    account = (
        create_account(youtube_client, project["id"], "youtube", handle)
        if handle is not None
        else create_provisional(youtube_client, project["id"], "youtube")
    )

    connection = connect_youtube(
        youtube_client, fake_google, account["id"], title=title, handle=channel_handle
    )

    assert connection["status"] == "connected"  # never fails because of the name
    [stored] = [
        a
        for a in list_accounts(youtube_client, project["id"])
        if a["id"] == account["id"]
    ]
    assert stored["handle"] == expected
    health = health_of(youtube_client, account)
    assert (health["state"], health["can_discard"]) == ("ready", False)
    assert health["identity"]["name"] == title


def test_telegram_login_adopts_the_username(telegram_client: TestClient) -> None:
    from tests.test_telegram_connections import connect

    project = create_project(telegram_client, "Tg")
    account = create_provisional(telegram_client, project["id"], "telegram")

    assert connect(telegram_client, account["id"])["status"] == "connected"

    [stored] = list_accounts(telegram_client, project["id"])
    assert stored["handle"] == "tester"
    assert health_of(telegram_client, account)["state"] == "setup_required"


# --- Discard (DELETE /api/accounts/{id}, Feature 021 delete) -----------------------


def discard(client: TestClient, account_id: int) -> Any:
    """Discard = the general account delete, confirmed with its preview's token."""
    preview = client.get(f"/api/accounts/{account_id}/deletion-preview")
    assert preview.status_code == 200, preview.text
    return client.delete(
        f"/api/accounts/{account_id}",
        params={"confirmation": preview.json()["confirmation"]},
    )


def test_discard_removes_a_provisional_account(client: TestClient) -> None:
    project = create_project(client, "L4i4")
    account = create_provisional(client, project["id"], "instagram")
    kept = create_account(client, project["id"], "x", "l4i4")
    preset = client.post(
        f"/api/projects/{project['id']}/distribution-presets",
        json={"name": "All", "account_ids": [account["id"], kept["id"]]},
    )
    assert preset.status_code == 201, preset.text

    response = discard(client, account["id"])

    assert response.status_code == 204
    assert [a["id"] for a in list_accounts(client, project["id"])] == [kept["id"]]
    [stored_preset] = client.get(
        f"/api/projects/{project['id']}/distribution-presets"
    ).json()
    assert stored_preset["account_ids"] == [kept["id"]]
    again = client.get(f"/api/accounts/{account['id']}/deletion-preview")
    assert again.status_code == 404


@pytest.mark.parametrize("reason", ["identity", "connection", "post"])
def test_an_account_in_use_is_not_offered_as_discard_but_can_be_deleted(
    client: TestClient, db_path: Any, reason: str
) -> None:
    from app.db import utc_now
    from tests.readmodels import connect, post

    project = create_project(client, "L4i4")
    if reason == "identity":
        account = create_account(client, project["id"], "instagram", "l4i4")
    else:
        account = create_provisional(client, project["id"], "instagram")
    if reason == "connection":
        connect(db_path, account, utc_now(), status="reconnect_required")
    if reason == "post":
        post(db_path, account, utc_now(), status="unscheduled")

    assert health_of(client, account)["can_discard"] is False
    assert discard(client, account["id"]).status_code == 204
    assert list_accounts(client, project["id"]) == []


def test_discard_never_waits_for_a_connection_step_holding_the_account(
    client: TestClient,
) -> None:
    """A connection step in progress never blocks a delete (no `account_busy`)."""
    from app.telegram_connections import account_session

    project = create_project(client, "Tg")
    account = create_provisional(client, project["id"], "telegram")

    with account_session(account["id"], wait=False):
        response = discard(client, account["id"])

    assert response.status_code == 204
    assert list_accounts(client, project["id"]) == []


def test_discard_invalidates_pending_youtube_connection_attempts(
    youtube_client: TestClient,
) -> None:
    from tests.conftest import authorize, complete_callback, get_attempt

    project = create_project(youtube_client, "Cyber")
    account = create_provisional(youtube_client, project["id"], "youtube")
    body, state = authorize(youtube_client, account["id"])

    assert discard(youtube_client, account["id"]).status_code == 204
    assert get_attempt(youtube_client, body["attempt_id"])["status"] == "expired"
    late = complete_callback(youtube_client, state)
    assert late.status_code == 400
    assert "Authorization not valid" in late.text


def test_discard_invalidates_pending_telegram_logins(
    telegram_client: TestClient,
) -> None:
    from tests.fakes_telegram import FAKE_PHONE
    from tests.test_telegram_connections import base

    tg_project = create_project(telegram_client, "Tg")
    tg_account = create_provisional(telegram_client, tg_project["id"], "telegram")
    started = telegram_client.post(
        f"{base(tg_account['id'])}/login/start", json={"phone": FAKE_PHONE}
    )
    assert started.status_code == 200, started.text
    app: Any = telegram_client.app
    assert app.state.telegram_logins.get(tg_account["id"]) is not None

    assert discard(telegram_client, tg_account["id"]).status_code == 204
    assert app.state.telegram_logins.get(tg_account["id"]) is None


def test_discard_during_youtube_completion_leaves_no_secret_nor_connection(
    youtube_client: TestClient, credential_store: Any, db_path: Any
) -> None:
    """Representative race: the callback already consumed its state, the account
    is discarded, then the completion tries to link the channel."""
    import sqlite3
    from datetime import UTC, datetime, timedelta

    from app.errors import AppError
    from app.models import Account
    from app.youtube_connections import complete_connection
    from app.youtube_gateway import TokenSet
    from app.youtube_oauth import ChannelInfo
    from tests.conftest import authorize

    project = create_project(youtube_client, "Cyber")
    account = create_provisional(youtube_client, project["id"], "youtube")
    _, state = authorize(youtube_client, account["id"])
    app: Any = youtube_client.app
    # (1) The callback consumed its state and loaded the account.
    assert app.state.oauth_attempts.consume_state(state) is not None
    with app.state.session_factory() as session:
        loaded = session.get(Account, account["id"])
        assert loaded is not None
        # (2) The account is discarded meanwhile.
        assert discard(youtube_client, account["id"]).status_code == 204
        # (3) The completion fails: the account no longer exists.
        tokens = TokenSet(
            access_token="access-SECRET",
            refresh_token="refresh-SECRET",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=frozenset({"scope"}),
        )
        with pytest.raises(AppError) as failure:
            complete_connection(
                app.state.session_factory,
                credential_store,
                loaded.id,
                ChannelInfo("UC_TEST_1", "Cyber Channel", "@cyber"),
                tokens,
            )

    # (4) rolled back, (5) no secret left, (6) no connection, (7) a clear message.
    assert failure.value.code == "oauth_state_invalid"
    assert "no longer valid" in failure.value.message
    assert "already connected" not in failure.value.message
    assert credential_store.secrets == {}
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM youtube_connections"
        ).fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone() == (0,)
