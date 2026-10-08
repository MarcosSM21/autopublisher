"""Connecting an Instagram account: success, errors and uniqueness (US1, US2, US6)."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import instagram_connections
from tests.conftest import (
    complete_instagram,
    connect_instagram,
    create_account,
    create_instagram_account,
    create_project,
    get_instagram_connection,
    instagram_rows,
    make_instagram_app,
    redirect_url_for,
    run_sql,
    start_instagram_authorization,
)
from tests.fakes import (
    FAKE_IG_CODE,
    FAKE_IG_LONG_TOKEN,
    FAKE_IG_REDIRECT_URI,
    FAKE_IG_SHORT_TOKEN,
    FAKE_META_ERROR_TEXT,
    IG_BASIC,
    IG_PUBLISH,
    LONG_LIVED_SECONDS,
    FakeClock,
    FakeMeta,
    InMemoryCredentialStore,
    instagram_app_config_json,
)
from tests.test_accounts import ACCOUNT_FIELDS

ROUTES = (
    ("get", "/api/accounts/{id}/instagram-connection"),
    ("post", "/api/accounts/{id}/instagram-connection/authorize"),
    ("post", "/api/accounts/{id}/instagram-connection/verify"),
    ("post", "/api/accounts/{id}/instagram-connection/disconnect"),
)


def _error(response: Any) -> dict[str, Any]:
    error: dict[str, Any] = response.json()["error"]
    return error


# --- US1: connect --------------------------------------------------------------------


def test_new_account_is_not_connected(instagram_client: TestClient) -> None:
    _, account = create_instagram_account(instagram_client)

    assert get_instagram_connection(instagram_client, account["id"]) == {
        "status": "not_connected",
        "identity": None,
        "connected_at": None,
        "last_verified_at": None,
        "access_expires_at": None,
        "oauth_configured": True,
    }


def test_authorize_returns_attempt_and_url(instagram_client: TestClient) -> None:
    _, account = create_instagram_account(instagram_client)

    response = instagram_client.post(
        f"/api/accounts/{account['id']}/instagram-connection/authorize"
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"attempt_id", "authorization_url", "expires_at"}
    assert body["authorization_url"].startswith(
        "https://www.instagram.com/oauth/authorize?client_id=1234567890&redirect_uri="
    )
    assert "force_reauth=true" in body["authorization_url"]
    assert "code_challenge" not in body["authorization_url"]


@pytest.mark.parametrize(
    ("meta_type", "stored_type"),
    [("Business", "BUSINESS"), ("Media_Creator", "MEDIA_CREATOR")],
)
def test_connect_professional_account(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    db_path: Path,
    meta_type: str,
    stored_type: str,
) -> None:
    fake_meta.set_identity(account_type=meta_type)
    _, account = create_instagram_account(instagram_client)
    attempt_id, state = start_instagram_authorization(instagram_client, account["id"])

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 200, response.text
    attempt = response.json()
    assert attempt["status"] == "completed"
    assert attempt["attempt_id"] == attempt_id
    assert attempt["error"] is None
    connection = attempt["connection"]
    assert connection["status"] == "connected"
    assert connection["identity"] == {
        "instagram_user_id": "17841400000000001",
        "username": "cyber.studio",
        "account_type": stored_type,
        "profile_picture_url": "https://scontent.example.com/cyber.jpg",
    }
    expected_expiry = fake_clock.now() + timedelta(seconds=LONG_LIVED_SECONDS)
    assert connection["access_expires_at"] == expected_expiry.isoformat().replace(
        "+00:00", "Z"
    )
    assert connection["connected_at"] is not None
    assert connection["last_verified_at"] == connection["connected_at"]
    assert get_instagram_connection(instagram_client, account["id"]) == connection

    # Only the long-lived token is stored, only in the secure store.
    (row,) = instagram_rows(db_path)
    assert row["account_type"] == stored_type
    assert row["app_scoped_id"] == "9000000000000001"
    secret = json.loads(instagram_credential_store.secrets[row["credential_ref"]])
    assert set(secret) == {"access_token", "issued_at", "expires_at", "permissions"}
    assert secret["access_token"] == FAKE_IG_LONG_TOKEN
    assert secret["permissions"] == [IG_BASIC, IG_PUBLISH]
    assert len(instagram_credential_store.secrets) == 1
    assert FAKE_IG_SHORT_TOKEN not in json.dumps(instagram_credential_store.secrets)

    # Requests to Meta in the documented order.
    urls = [request.url.split("?")[0] for request in fake_meta.requests]
    assert urls == [
        "https://api.instagram.com/oauth/access_token",
        "https://graph.instagram.com/access_token",
        "https://graph.instagram.com/v26.0/me",
    ]


def test_account_fields_unchanged_after_connecting(
    instagram_client: TestClient,
) -> None:
    project_id, account = create_instagram_account(instagram_client)
    connect_instagram(instagram_client, account["id"])

    response = instagram_client.get(f"/api/projects/{project_id}/accounts")
    (read,) = response.json()
    assert set(read) == ACCOUNT_FIELDS
    assert read["handle"] == account["handle"]
    assert read["display_name"] == account["display_name"]


def test_connection_survives_restart(
    instagram_client: TestClient,
    db_path: Path,
    media_dir: Path,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connection = connect_instagram(instagram_client, account["id"])

    app = make_instagram_app(
        db_path, media_dir, instagram_credential_store, fake_meta, fake_clock
    )
    with TestClient(app) as restarted:
        assert get_instagram_connection(restarted, account["id"]) == connection


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_other_platforms_are_rejected(
    instagram_client: TestClient, method: str, path: str
) -> None:
    project = create_project(instagram_client, "Cyber")
    youtube = create_account(instagram_client, project["id"], "youtube", "cyber")

    response = getattr(instagram_client, method)(path.format(id=youtube["id"]))

    assert response.status_code == 409
    assert _error(response)["code"] == "platform_not_supported"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_unknown_account(instagram_client: TestClient, method: str, path: str) -> None:
    response = getattr(instagram_client, method)(path.format(id=999))

    assert response.status_code == 404
    assert _error(response)["code"] == "not_found"


@pytest.mark.parametrize(
    "content", [None, "not json", instagram_app_config_json(app_secret="")]
)
def test_not_configured(
    instagram_client: TestClient, instagram_app_file: Path, content: str | None
) -> None:
    if content is None:
        instagram_app_file.unlink()
    else:
        instagram_app_file.write_text(content)
    _, account = create_instagram_account(instagram_client)

    assert (
        get_instagram_connection(instagram_client, account["id"])["oauth_configured"]
        is False
    )
    response = instagram_client.post(
        f"/api/accounts/{account['id']}/instagram-connection/authorize"
    )

    assert response.status_code == 503
    error = _error(response)
    assert error["code"] == "instagram_oauth_not_configured"
    assert str(instagram_app_file) not in error["message"]
    app = instagram_client.app
    assert not app.state.instagram_attempts._attempts  # type: ignore[attr-defined]


def test_configuration_changes_without_restart(
    instagram_client: TestClient, instagram_app_file: Path
) -> None:
    _, account = create_instagram_account(instagram_client)
    content = instagram_app_file.read_text()
    instagram_app_file.unlink()
    assert not get_instagram_connection(instagram_client, account["id"])[
        "oauth_configured"
    ]

    instagram_app_file.write_text(content)

    assert get_instagram_connection(instagram_client, account["id"])["oauth_configured"]


# --- US2: errors ---------------------------------------------------------------------


def _assert_nothing_stored(
    store: InMemoryCredentialStore, db_path: Path, account_id: int
) -> None:
    assert store.secrets == {}
    assert all(row["account_id"] != account_id for row in instagram_rows(db_path))


def _assert_safe(error: dict[str, Any], state: str) -> None:
    text = json.dumps(error)
    for secret in (
        FAKE_IG_CODE,
        state,
        FAKE_IG_REDIRECT_URI,
        FAKE_META_ERROR_TEXT,
        FAKE_IG_SHORT_TOKEN,
        FAKE_IG_LONG_TOKEN,
    ):
        assert secret not in text


@pytest.fixture
def started(instagram_client: TestClient) -> tuple[dict[str, Any], str, str]:
    _, account = create_instagram_account(instagram_client)
    attempt_id, state = start_instagram_authorization(instagram_client, account["id"])
    return account, attempt_id, state


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("access_denied", "instagram_oauth_denied"),
        ("server_error", "instagram_oauth_provider_error"),
        ("unauthorized_client", "instagram_oauth_provider_error"),
    ],
)
def test_provider_errors(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    error: str,
    code: str,
) -> None:
    account, attempt_id, state = started
    redirect = (
        f"{FAKE_IG_REDIRECT_URI}?error={error}&error_reason=user_denied"
        f"&error_description={FAKE_META_ERROR_TEXT}&state={state}"
    )

    response = complete_instagram(instagram_client, attempt_id, redirect)

    assert response.status_code == 400
    assert _error(response)["code"] == code
    _assert_safe(_error(response), state)
    _assert_nothing_stored(instagram_credential_store, db_path, account["id"])
    assert fake_meta.requests == []
    # The attempt is finished: the same redirect cannot be used again.
    again = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))
    assert _error(again)["code"] == "instagram_oauth_state_invalid"


def test_wrong_state_keeps_attempt_pending(
    instagram_client: TestClient,
    fake_meta: FakeMeta,
    started: tuple[dict[str, Any], str, str],
) -> None:
    _, attempt_id, state = started

    for wrong in (redirect_url_for("not-the-state"), f"{FAKE_IG_REDIRECT_URI}?code=c"):
        response = complete_instagram(instagram_client, attempt_id, wrong)
        assert response.status_code == 400
        assert _error(response)["code"] == "instagram_oauth_state_invalid"
    assert fake_meta.requests == []

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_redirect_reused_after_completion(
    instagram_client: TestClient, started: tuple[dict[str, Any], str, str]
) -> None:
    _, attempt_id, state = started
    assert (
        complete_instagram(
            instagram_client, attempt_id, redirect_url_for(state)
        ).status_code
        == 200
    )

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 400
    assert _error(response)["code"] == "instagram_oauth_state_invalid"


def test_state_of_another_account(instagram_client: TestClient) -> None:
    project_id, first = create_instagram_account(instagram_client)
    _, second = create_instagram_account(
        instagram_client, handle="other", project_id=project_id
    )
    first_attempt, _ = start_instagram_authorization(instagram_client, first["id"])
    _, second_state = start_instagram_authorization(instagram_client, second["id"])

    response = complete_instagram(
        instagram_client, first_attempt, redirect_url_for(second_state)
    )

    assert response.status_code == 400
    assert _error(response)["code"] == "instagram_oauth_state_invalid"


def test_superseded_attempt_expires(
    instagram_client: TestClient, started: tuple[dict[str, Any], str, str]
) -> None:
    account, attempt_id, state = started
    start_instagram_authorization(instagram_client, account["id"])

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 410
    assert _error(response)["code"] == "instagram_oauth_attempt_expired"


def test_attempt_expires_after_ten_minutes(
    instagram_client: TestClient,
    fake_clock: FakeClock,
    started: tuple[dict[str, Any], str, str],
) -> None:
    _, attempt_id, state = started
    fake_clock.advance(timedelta(minutes=10).total_seconds())

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 410
    assert _error(response)["code"] == "instagram_oauth_attempt_expired"


def test_attempt_lost_after_restart(
    instagram_client: TestClient,
    db_path: Path,
    media_dir: Path,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    fake_clock: FakeClock,
    started: tuple[dict[str, Any], str, str],
) -> None:
    _, attempt_id, state = started
    app = make_instagram_app(
        db_path, media_dir, instagram_credential_store, fake_meta, fake_clock
    )
    with TestClient(app) as restarted:
        response = complete_instagram(restarted, attempt_id, redirect_url_for(state))

    assert response.status_code == 410
    assert _error(response)["code"] == "instagram_oauth_attempt_expired"


@pytest.mark.parametrize(
    "pasted",
    [
        "https://evil.example.com/autopublisher/instagram/callback?code=c&state=s",
        "https://localhost/somewhere/else?code=c&state=s",
        f"{FAKE_IG_REDIRECT_URI}?state=only",
        "hello",
    ],
)
def test_invalid_redirect_url_keeps_attempt_pending(
    instagram_client: TestClient,
    started: tuple[dict[str, Any], str, str],
    pasted: str,
) -> None:
    _, attempt_id, state = started

    response = complete_instagram(instagram_client, attempt_id, pasted)

    assert response.status_code == 400
    assert _error(response)["code"] == "instagram_oauth_redirect_url_invalid"
    assert (
        complete_instagram(
            instagram_client, attempt_id, redirect_url_for(state)
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "body", [{}, {"redirect_url": ""}, {"redirect_url": "x" * 4097}, {"other": 1}]
)
def test_invalid_body(
    instagram_client: TestClient,
    started: tuple[dict[str, Any], str, str],
    body: dict[str, Any],
) -> None:
    _, attempt_id, state = started

    response = instagram_client.post(
        f"/api/instagram/oauth/attempts/{attempt_id}/complete", json=body
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "validation_error"
    assert (
        complete_instagram(
            instagram_client, attempt_id, redirect_url_for(state)
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("endpoint", "fault", "status", "code"),
    [
        ("code", "oauth_exception", 502, "instagram_token_exchange_failed"),
        ("code", "graph_100", 502, "instagram_token_exchange_failed"),
        ("long_lived", "graph_190", 502, "instagram_token_exchange_failed"),
        ("long_lived", "graph_100", 502, "instagram_token_exchange_failed"),
        ("code", "server_error", 503, "instagram_unavailable"),
        ("code", "transport", 503, "instagram_unavailable"),
        ("long_lived", "rate_limited", 503, "instagram_unavailable"),
        ("me", "graph_4", 503, "instagram_unavailable"),
        ("code", "bad_json", 502, "instagram_unexpected_response"),
        ("long_lived", "missing_fields", 502, "instagram_unexpected_response"),
        ("me", "missing_fields", 502, "instagram_unexpected_response"),
    ],
)
def test_meta_failures(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    endpoint: str,
    fault: str,
    status: int,
    code: str,
) -> None:
    account, attempt_id, state = started
    fake_meta.faults[endpoint] = fault

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == status
    assert _error(response)["code"] == code
    _assert_safe(_error(response), state)
    _assert_nothing_stored(instagram_credential_store, db_path, account["id"])
    # The attempt failed: it cannot be completed again.
    fake_meta.faults.clear()
    again = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))
    assert _error(again)["code"] == "instagram_oauth_state_invalid"


@pytest.mark.parametrize(
    ("permissions", "missing"),
    [(IG_BASIC, IG_PUBLISH), (IG_PUBLISH, IG_BASIC), ("", IG_BASIC)],
)
def test_missing_permission(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    permissions: str,
    missing: str,
) -> None:
    account, attempt_id, state = started
    fake_meta.permissions = permissions

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "instagram_permission_missing"
    assert missing in error["message"]
    _assert_nothing_stored(instagram_credential_store, db_path, account["id"])
    assert fake_meta.requests_to("long_lived") == []


def test_permissions_field_absent(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
) -> None:
    account, attempt_id, state = started
    fake_meta.permissions = None

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 502
    assert _error(response)["code"] == "instagram_unexpected_response"
    _assert_nothing_stored(instagram_credential_store, db_path, account["id"])


@pytest.mark.parametrize("account_type", ["Personal", "PERSONAL", "Unknown", None])
def test_not_professional(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
    account_type: str | None,
) -> None:
    account, attempt_id, state = started
    fake_meta.set_identity(account_type=account_type)

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "instagram_account_not_professional"
    assert "Business or Creator" in error["message"]
    assert "Convert" in error["message"]
    _assert_nothing_stored(instagram_credential_store, db_path, account["id"])


def test_store_unavailable(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    db_path: Path,
    started: tuple[dict[str, Any], str, str],
) -> None:
    account, attempt_id, state = started
    instagram_credential_store.unavailable = True

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 503
    assert _error(response)["code"] == "credential_store_unavailable"
    assert instagram_rows(db_path) == []


def test_failure_keeps_previous_connection(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    fake_meta: FakeMeta,
    db_path: Path,
) -> None:
    _, account = create_instagram_account(instagram_client)
    connection = connect_instagram(instagram_client, account["id"])
    secrets_before = dict(instagram_credential_store.secrets)
    rows_before = instagram_rows(db_path)
    attempt_id, state = start_instagram_authorization(instagram_client, account["id"])
    fake_meta.faults["long_lived"] = "graph_190"

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 502
    assert instagram_credential_store.secrets == secrets_before
    assert instagram_rows(db_path) == rows_before
    assert get_instagram_connection(instagram_client, account["id"]) == connection


# --- US6: one Instagram account per project -------------------------------------------


@pytest.mark.parametrize("holder_active", [True, False])
def test_same_instagram_account_twice_in_a_project(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    db_path: Path,
    holder_active: bool,
) -> None:
    project_id, holder = create_instagram_account(instagram_client, handle="holder")
    connect_instagram(instagram_client, holder["id"])
    if not holder_active:
        run_sql(db_path, "UPDATE accounts SET is_active = 0 WHERE id = ?", holder["id"])
    _, second = create_instagram_account(
        instagram_client, handle="second", project_id=project_id
    )
    attempt_id, state = start_instagram_authorization(instagram_client, second["id"])

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 409
    error = _error(response)
    assert error["code"] == "instagram_account_already_connected"
    assert "@holder" in error["message"]
    assert len(instagram_credential_store.secrets) == 1
    assert len(instagram_rows(db_path)) == 1


def test_same_instagram_account_in_another_project(
    instagram_client: TestClient,
) -> None:
    _, first = create_instagram_account(instagram_client, "Cyber")
    _, second = create_instagram_account(instagram_client, "Other")
    connect_instagram(instagram_client, first["id"])

    connection = connect_instagram(instagram_client, second["id"])

    assert connection["status"] == "connected"


def test_allowed_after_disconnecting_the_holder(instagram_client: TestClient) -> None:
    project_id, holder = create_instagram_account(instagram_client, handle="holder")
    connect_instagram(instagram_client, holder["id"])
    instagram_client.post(
        f"/api/accounts/{holder['id']}/instagram-connection/disconnect"
    )
    _, second = create_instagram_account(
        instagram_client, handle="second", project_id=project_id
    )

    assert connect_instagram(instagram_client, second["id"])["status"] == "connected"


def test_same_username_different_id_is_allowed(
    instagram_client: TestClient, fake_meta: FakeMeta
) -> None:
    project_id, first = create_instagram_account(instagram_client, handle="first")
    connect_instagram(instagram_client, first["id"])
    _, second = create_instagram_account(
        instagram_client, handle="second", project_id=project_id
    )

    connection = connect_instagram(
        instagram_client, second["id"], fake_meta, user_id="17841400000000999"
    )

    assert connection["identity"]["username"] == "cyber.studio"


def test_race_is_caught_by_the_constraint(
    instagram_client: TestClient,
    instagram_credential_store: InMemoryCredentialStore,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, holder = create_instagram_account(instagram_client, handle="holder")
    connect_instagram(instagram_client, holder["id"])
    _, second = create_instagram_account(
        instagram_client, handle="second", project_id=project_id
    )
    # Simulate a concurrent request that passed the rule check first.
    monkeypatch.setattr(
        instagram_connections, "ensure_identity_available", lambda *args: None
    )
    attempt_id, state = start_instagram_authorization(instagram_client, second["id"])

    response = complete_instagram(instagram_client, attempt_id, redirect_url_for(state))

    assert response.status_code == 409
    assert _error(response)["code"] == "instagram_account_already_connected"
    assert len(instagram_credential_store.secrets) == 1
    assert len(instagram_rows(db_path)) == 1
