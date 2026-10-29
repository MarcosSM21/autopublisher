"""GET /api/analytics/catalog and GET /api/projects/{id}/analytics/accounts
(Feature 027 T017, contracts/analytics-api.md)."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests import readmodels
from tests.conftest import create_account, create_project
from tests.fakes import FakeClock
from tests.test_delete_post import (
    PASSWORD,
    installation,  # noqa: F401 - fixture
)


def get_json(client: TestClient, url: str) -> Any:
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_shape(client: TestClient) -> None:
    body = get_json(client, "/api/analytics/catalog")

    assert set(body) == {"concepts", "platforms"}
    assert body["concepts"][0].keys() == {"key", "label", "definition", "alignable"}
    assert {c["key"]: c["alignable"] for c in body["concepts"]} == {
        "views": False,
        "likes": True,
        "comments": True,
        "shares": False,
    }
    platforms = {p["platform"]: p for p in body["platforms"]}
    assert set(platforms) == {"youtube", "instagram", "threads"}
    youtube = platforms["youtube"]
    assert youtube.keys() == {"platform", "metrics", "excluded", "engagement"}
    assert youtube["metrics"][0].keys() == {
        "name",
        "label",
        "definition",
        "origin",
        "concept",
        "group",
    }
    assert youtube["engagement"] == {
        "numerator": ["likeCount", "commentCount"],
        "denominator": "viewCount",
    }
    assert youtube["excluded"] == [
        {"name": "favoriteCount", "reason": "deprecated by YouTube in 2015, always 0"}
    ]
    assert "favoriteCount" not in {m["name"] for m in youtube["metrics"]}
    assert platforms["instagram"]["engagement"] is None
    assert platforms["threads"]["engagement"] is None


def test_accounts_lists_every_account_with_its_capability(
    client: TestClient, db_path: Path
) -> None:
    project = create_project(client, "Cyber")
    other = create_project(client, "Other")
    accounts = {
        platform: create_account(client, project["id"], platform, "cyber")
        for platform in ("youtube", "instagram", "threads", "tiktok", "telegram", "x")
    }
    create_account(client, other["id"], "youtube", "elsewhere")
    now = FakeClock().now()
    readmodels.connect(db_path, accounts["youtube"], now)
    readmodels.connect(db_path, accounts["instagram"], now)
    readmodels.connect(db_path, accounts["threads"], now, status="reconnect_required")

    body = get_json(client, f"/api/projects/{project['id']}/analytics/accounts")

    assert [row["account_id"] for row in body] == [a["id"] for a in accounts.values()]
    rows = {row["platform"]: row for row in body}
    assert rows["youtube"] == {
        "account_id": accounts["youtube"]["id"],
        "platform": "youtube",
        "label": "YouTube @cyber",
        "capability": {
            "state": "supported",
            "groups": [
                {"group": "basic", "state": "supported", "missing_permission": None}
            ],
            "reason": None,
        },
    }
    assert rows["instagram"]["capability"]["groups"] == [
        {"group": "basic", "state": "supported", "missing_permission": None},
        {
            "group": "insights",
            "state": "permission_required",
            "missing_permission": "instagram_business_manage_insights",
        },
    ]
    states = {p: row["capability"]["state"] for p, row in rows.items()}
    assert states == {
        "youtube": "supported",
        "instagram": "supported",
        "threads": "reconnect_required",
        "tiktok": "not_supported",
        "telegram": "not_supported",
        "x": "not_applicable",
    }


def test_accounts_of_an_unknown_project_is_404(client: TestClient) -> None:
    response = client.get("/api/projects/999/analytics/accounts")

    assert response.status_code == 404


def test_analytics_routes_require_a_session(installation: TestClient) -> None:  # noqa: F811
    client = installation
    urls = ["/api/analytics/catalog", "/api/projects/1/analytics/accounts"]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 401, url
        assert response.json()["error"]["code"] == "auth_required"

    assert (
        client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    )
    project = create_project(client, "Cyber")
    assert client.get(urls[0]).status_code == 200
    assert (
        client.get(f"/api/projects/{project['id']}/analytics/accounts").status_code
        == 200
    )
