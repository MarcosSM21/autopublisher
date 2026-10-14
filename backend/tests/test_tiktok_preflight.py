"""TikTok preflight (spec US4, contracts §5): `check()` never uses the network and
reports every local problem; `prepare()` reads Creator Info once, right before the
upload, and verifies the real file digest. A failing preflight never initializes a
Direct Post, never creates an attempt and never changes the options."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TT_OPTIONS,
    attempt_rows,
    create_publications,
    get_publication,
    import_one,
    make_image,
    run_sql,
    stored_file,
    tiktok_probe_streams,
    tiktok_publication,
    tiktok_ready,
    tiktok_ready_publication,
)
from tests.fakes import FakeTikTok, tiktok_creator_info


@pytest.fixture
def client(tiktok_publishing_client: TestClient) -> TestClient:
    return tiktok_publishing_client


def _check(client: TestClient, publication_id: int) -> dict[str, Any]:
    response = client.get(f"/api/publications/{publication_id}/publish-check")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _codes(client: TestClient, publication_id: int) -> list[str]:
    return [problem["code"] for problem in _check(client, publication_id)["problems"]]


# --- check(): local, no network ------------------------------------------------------


def test_ready_publication_is_eligible_without_network(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)

    body = _check(client, created["publication"]["id"])

    assert body["eligible"] is True
    labels = [item["label"] for item in body["summary"]]
    assert labels == [
        "TikTok account",
        "File",
        "Caption",
        "Privacy",
        "Interactions",
        "Commercial content",
        "AI-generated",
        "Declaration accepted",
    ]
    summary = {item["label"]: item["value"] for item in body["summary"]}
    assert summary["Privacy"] == "Only me"
    assert summary["AI-generated"] == "No"
    assert summary["Commercial content"] == "Off"
    assert fake_tiktok.requests == []


@pytest.mark.parametrize(
    ("statement", "code"),
    [
        ("DELETE FROM tiktok_connections", "tiktok_not_connected"),
        (
            "UPDATE tiktok_connections SET status = 'reconnect_required'",
            "tiktok_reconnect_required",
        ),
    ],
)
def test_connection_problems(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    statement: str,
    code: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    run_sql(db_path, statement)

    assert code in _codes(client, created["publication"]["id"])
    assert fake_tiktok.requests == []


def test_photos_are_not_supported(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    image = import_one(
        client, created["account"]["project_id"], "photo.png", make_image()
    )["content"]
    publication = create_publications(client, image["id"], [created["account"]["id"]])[
        0
    ]

    assert "tiktok_video_required" in _codes(client, publication["id"])
    assert fake_tiktok.requests == []


def test_missing_file(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    stored_file(media_dir, db_path, created["content"]["id"]).unlink()

    assert "media_unavailable" in _codes(client, created["publication"]["id"])


@pytest.mark.parametrize(
    ("streams", "code"),
    [
        (None, "tiktok_video_uninspectable"),
        (
            tiktok_probe_streams(video={"codec_name": "av1"}),
            "tiktok_video_incompatible",
        ),
        (tiktok_probe_streams(duration_seconds=601.0), "tiktok_video_incompatible"),
    ],
)
def test_video_problems(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    streams: Any,
    code: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    from app import media

    monkeypatch.setattr(media, "probe_video_streams", lambda path: streams)

    assert code in _codes(client, created["publication"]["id"])
    assert fake_tiktok.requests == []


def test_caption_too_long(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    client.patch(
        f"/api/publications/{created['publication']['id']}",
        json={"description_override": "😀" * 1100 + "a", "hashtags_override": []},
    )

    assert "tiktok_caption_invalid" in _codes(client, created["publication"]["id"])


@pytest.mark.parametrize(
    ("values", "code"),
    [
        ({"privacy_level": None}, "tiktok_privacy_required"),
        ({"privacy_level": "FOLLOWER_OF_CREATOR"}, "tiktok_privacy_not_allowed"),
        ({"is_aigc": None}, "tiktok_aigc_required"),
        ({"commercial_disclosure_enabled": True}, "tiktok_disclosure_incomplete"),
    ],
)
def test_option_problems(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, Any],
    code: str,
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    client.put(
        f"/api/publications/{created['publication']['id']}/tiktok-options",
        json={**TT_OPTIONS, **values},
    )

    assert code in _codes(client, created["publication"]["id"])
    assert fake_tiktok.requests == []


def test_consent_is_required(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    client.put(
        f"/api/publications/{created['publication']['id']}/tiktok-options",
        json=TT_OPTIONS,
    )

    assert _codes(client, created["publication"]["id"]) == ["tiktok_consent_required"]


def test_stale_consent_is_required_again(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    client.patch(
        f"/api/publications/{created['publication']['id']}",
        json={"description_override": "Changed after consenting"},
    )

    assert _codes(client, created["publication"]["id"]) == ["tiktok_consent_required"]


# --- prepare(): Creator Info and the real file ---------------------------------------


def _assert_not_started(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    db_path: Path,
    publication_id: int,
    options_before: dict[str, Any],
) -> None:
    assert get_publication(client, publication_id)["status"] == "unscheduled"
    assert attempt_rows(db_path) == []
    assert fake_tiktok.requests_to("init") == []
    assert fake_tiktok.requests_to("upload") == []
    after = client.get(f"/api/publications/{publication_id}/tiktok-options").json()
    for name in TT_OPTIONS:
        assert after[name] == options_before[name]
    assert after["consent"]["state"] == "valid"


def _publish(client: TestClient, publication_id: int) -> Any:
    return client.post(f"/api/publications/{publication_id}/publish", json={})


def test_creator_info_is_read_again_right_before_init(
    client: TestClient, fake_tiktok: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    # The review read Creator Info first; publishing never reuses it.
    client.get(f"/api/publications/{publication_id}/tiktok-creator-info")

    response = _publish(client, publication_id)
    from tests.conftest import wait_idle

    wait_idle(client)

    assert response.status_code == 202, response.text
    calls = fake_tiktok.calls()
    assert calls[:3] == ["creator_info", "creator_info", "init"]
    assert calls.count("creator_info") == 2


PREPARE_FAILURES = [
    (
        tiktok_creator_info(privacy_level_options=["FOLLOWER_OF_CREATOR"]),
        {},
        409,
        "tiktok_privacy_unavailable",
    ),
    (
        tiktok_creator_info(comment_disabled=True),
        {"allow_comment": True},
        409,
        "tiktok_interaction_unavailable",
    ),
    (
        tiktok_creator_info(max_video_post_duration_sec=10),
        {},
        409,
        "tiktok_video_too_long",
    ),
]


@pytest.mark.parametrize(("info", "options", "status", "code"), PREPARE_FAILURES)
def test_creator_info_changed_since_the_review(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    info: dict[str, Any],
    options: dict[str, Any],
    status: int,
    code: str,
) -> None:
    created = tiktok_ready_publication(
        client, fake_tiktok, monkeypatch, options=options
    )
    publication_id = created["publication"]["id"]
    fake_tiktok.creator_info_data = info

    response = _publish(client, publication_id)

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    _assert_not_started(
        client, fake_tiktok, db_path, publication_id, created["options"]
    )


@pytest.mark.parametrize(
    "code",
    [
        "spam_risk_too_many_posts",
        "spam_risk_user_banned_from_posting",
        "reached_active_user_cap",
    ],
)
def test_creator_cannot_post(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    code: str,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    fake_tiktok.faults["creator_info"] = f"api200_{code}"

    response = _publish(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_creator_cannot_post"
    _assert_not_started(
        client, fake_tiktok, db_path, publication_id, created["options"]
    )


def test_malformed_creator_info(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    fake_tiktok.creator_info_data = tiktok_creator_info(stitch_disabled=None)

    response = _publish(client, publication_id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tiktok_unexpected_response"
    _assert_not_started(
        client, fake_tiktok, db_path, publication_id, created["options"]
    )


def test_creator_info_server_error_is_retried_once(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    recorded_sleeps: list[float],
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    fake_tiktok.fault_queue["creator_info"] = ["server_error"]

    response = _publish(client, created["publication"]["id"])
    from tests.conftest import wait_idle

    wait_idle(client)

    assert response.status_code == 202, response.text
    assert fake_tiktok.calls()[:3] == ["creator_info", "creator_info", "init"]
    # The only wait before the upload is the Creator Info retry.
    assert recorded_sleeps[0] == 2.0


def test_creator_info_unavailable_twice(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    fake_tiktok.faults["creator_info"] = "transport"

    response = _publish(client, publication_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tiktok_unavailable"
    assert fake_tiktok.calls() == ["creator_info", "creator_info"]
    _assert_not_started(
        client, fake_tiktok, db_path, publication_id, created["options"]
    )


def test_creator_info_rate_limit_is_not_retried(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    fake_tiktok.faults["creator_info"] = "rate_limited"

    response = _publish(client, publication_id)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "tiktok_rate_limited"
    assert fake_tiktok.calls() == ["creator_info"]
    _assert_not_started(
        client, fake_tiktok, db_path, publication_id, created["options"]
    )


def test_changed_file_bytes_are_detected(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    media_dir: Path,
    db_path: Path,
) -> None:
    created = tiktok_ready_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    path = stored_file(media_dir, db_path, created["content"]["id"])
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    # Same size: only the streaming digest can notice it.
    assert _check(client, publication_id)["eligible"] is True

    response = _publish(client, publication_id)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "tiktok_video_changed"
    assert "TikTok" in error["message"] and "rejected" not in error["message"]
    _assert_not_started(
        client, fake_tiktok, db_path, publication_id, created["options"]
    )


def test_local_problems_never_reach_tiktok_when_publishing(
    client: TestClient,
    fake_tiktok: FakeTikTok,
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    created = tiktok_publication(client, fake_tiktok, monkeypatch)
    publication_id = created["publication"]["id"]
    tiktok_ready(client, publication_id)
    client.patch(
        f"/api/publications/{publication_id}",
        json={"description_override": "Edited after the consent"},
    )
    fake_tiktok.requests.clear()

    response = _publish(client, publication_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "tiktok_consent_required"
    assert fake_tiktok.requests == []
    assert attempt_rows(db_path) == []
