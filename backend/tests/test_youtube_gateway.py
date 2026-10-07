import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
import pytest

from app.youtube_gateway import (
    GoogleForbidden,
    GoogleGateway,
    GoogleRejected,
    GoogleUnauthorized,
    GoogleUnavailable,
    InvalidGrant,
    TokenSet,
)
from app.youtube_oauth import OAuthClientConfig
from tests.fakes import (
    ALL_SCOPES,
    FAKE_ACCESS_TOKEN,
    FAKE_AUTH_CODE,
    FAKE_CLIENT_ID,
    FAKE_CLIENT_SECRET,
    FAKE_REFRESH_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_ROTATED_REFRESH_TOKEN,
    FakeChannel,
    FakeGoogle,
)

CLIENT = OAuthClientConfig(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET)
REDIRECT = "http://127.0.0.1:8000/api/youtube/oauth/callback"
SECRETS = [
    FAKE_ACCESS_TOKEN,
    FAKE_REFRESH_TOKEN,
    FAKE_REFRESHED_ACCESS_TOKEN,
    FAKE_AUTH_CODE,
    FAKE_CLIENT_SECRET,
    "the-verifier",
]


@pytest.fixture
def fake() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def gateway(fake: FakeGoogle) -> Iterator[GoogleGateway]:
    with httpx.Client(transport=fake.transport()) as client:
        yield GoogleGateway(client)


def _tokens() -> TokenSet:
    return TokenSet(
        access_token=FAKE_ACCESS_TOKEN,
        refresh_token=FAKE_REFRESH_TOKEN,
        expires_at=datetime(2000, 1, 1, tzinfo=UTC),
        scopes=frozenset(ALL_SCOPES.split()),
    )


def test_exchange_code_posts_the_verifier(
    gateway: GoogleGateway, fake: FakeGoogle
) -> None:
    before = datetime.now(UTC)
    tokens = gateway.exchange_code(FAKE_AUTH_CODE, "the-verifier", REDIRECT, CLIENT)

    request = fake.token_requests[0]
    assert request.form == {
        "grant_type": "authorization_code",
        "code": FAKE_AUTH_CODE,
        "code_verifier": "the-verifier",
        "client_id": FAKE_CLIENT_ID,
        "client_secret": FAKE_CLIENT_SECRET,
        "redirect_uri": REDIRECT,
    }
    assert FAKE_AUTH_CODE not in request.url
    assert tokens.access_token == FAKE_ACCESS_TOKEN
    assert tokens.refresh_token == FAKE_REFRESH_TOKEN
    assert tokens.scopes == frozenset(ALL_SCOPES.split())
    assert tokens.expires_at.tzinfo is not None
    assert tokens.expires_at >= before + timedelta(seconds=3500)


def test_exchange_without_refresh_token(
    gateway: GoogleGateway, fake: FakeGoogle
) -> None:
    fake.exchange_outcome = "no_refresh"
    tokens = gateway.exchange_code(FAKE_AUTH_CODE, "the-verifier", REDIRECT, CLIENT)
    assert tokens.refresh_token is None


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        ("rejected", GoogleRejected),
        ("server_error", GoogleUnavailable),
        ("rate_limited", GoogleUnavailable),
        ("timeout", GoogleUnavailable),
    ],
)
def test_exchange_errors(
    gateway: GoogleGateway, fake: FakeGoogle, outcome: str, error: type[Exception]
) -> None:
    fake.exchange_outcome = outcome
    with pytest.raises(error) as raised:
        gateway.exchange_code(FAKE_AUTH_CODE, "the-verifier", REDIRECT, CLIENT)
    assert not any(secret in str(raised.value) for secret in SECRETS)


def test_refresh_keeps_the_refresh_token(
    gateway: GoogleGateway, fake: FakeGoogle
) -> None:
    tokens = gateway.refresh(_tokens(), CLIENT)
    assert fake.token_requests[0].form == {
        "grant_type": "refresh_token",
        "refresh_token": FAKE_REFRESH_TOKEN,
        "client_id": FAKE_CLIENT_ID,
        "client_secret": FAKE_CLIENT_SECRET,
    }
    assert tokens.access_token == FAKE_REFRESHED_ACCESS_TOKEN
    assert tokens.refresh_token == FAKE_REFRESH_TOKEN
    assert tokens.expires_at > datetime.now(UTC)


def test_refresh_accepts_a_rotated_refresh_token(
    gateway: GoogleGateway, fake: FakeGoogle
) -> None:
    fake.refresh_outcome = "rotate"
    assert gateway.refresh(_tokens(), CLIENT).refresh_token == (
        FAKE_ROTATED_REFRESH_TOKEN
    )


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        ("invalid_grant", InvalidGrant),
        ("rejected", GoogleRejected),
        ("server_error", GoogleUnavailable),
        ("timeout", GoogleUnavailable),
    ],
)
def test_refresh_errors(
    gateway: GoogleGateway, fake: FakeGoogle, outcome: str, error: type[Exception]
) -> None:
    fake.refresh_outcome = outcome
    with pytest.raises(error) as raised:
        gateway.refresh(_tokens(), CLIENT)
    assert not any(secret in str(raised.value) for secret in SECRETS)


def test_invalid_grant_is_not_a_generic_rejection() -> None:
    assert not issubclass(InvalidGrant, GoogleUnavailable)


def test_list_my_channels(gateway: GoogleGateway, fake: FakeGoogle) -> None:
    fake.channels = [
        FakeChannel("UC1", "One", "@one", "https://yt3.example.com/1.jpg"),
        FakeChannel("UC2", "Two"),
    ]
    channels = gateway.list_my_channels(FAKE_ACCESS_TOKEN)

    request = fake.channel_requests[0]
    assert request.url == (
        "https://www.googleapis.com/youtube/v3/channels"
        "?part=snippet&mine=true&maxResults=50"
    )
    assert request.headers["authorization"] == f"Bearer {FAKE_ACCESS_TOKEN}"
    assert [(c.id, c.title, c.handle, c.thumbnail_url) for c in channels] == [
        ("UC1", "One", "@one", "https://yt3.example.com/1.jpg"),
        ("UC2", "Two", None, None),
    ]


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        ("unauthorized", GoogleUnauthorized),
        ("forbidden", GoogleForbidden),
        ("server_error", GoogleUnavailable),
        ("rate_limited", GoogleUnavailable),
        ("timeout", GoogleUnavailable),
    ],
)
def test_list_my_channels_errors(
    gateway: GoogleGateway, fake: FakeGoogle, outcome: str, error: type[Exception]
) -> None:
    fake.channels_outcome = outcome
    with pytest.raises(error):
        gateway.list_my_channels(FAKE_ACCESS_TOKEN)


def test_gateway_never_revokes() -> None:
    assert not hasattr(GoogleGateway, "revoke")


def test_token_set_repr_and_round_trip_hide_secrets() -> None:
    tokens = _tokens()
    assert FAKE_ACCESS_TOKEN not in repr(tokens)
    assert FAKE_REFRESH_TOKEN not in repr(tokens)
    assert TokenSet.from_json(tokens.to_json()) == tokens


def test_no_secret_is_logged(
    gateway: GoogleGateway, fake: FakeGoogle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    gateway.exchange_code(FAKE_AUTH_CODE, "the-verifier", REDIRECT, CLIENT)
    gateway.refresh(_tokens(), CLIENT)
    gateway.list_my_channels(FAKE_ACCESS_TOKEN)
    fake.refresh_outcome = "invalid_grant"
    with pytest.raises(InvalidGrant):
        gateway.refresh(_tokens(), CLIENT)

    assert not any(secret in caplog.text for secret in SECRETS)


def _created_video(fake: FakeGoogle, video_id: str, privacy: str) -> None:
    fake.videos_created.append(
        {"id": video_id, "snippet": {}, "status": {}, "privacy": privacy, "data": b""}
    )


def test_get_video_status(gateway: GoogleGateway, fake: FakeGoogle) -> None:
    _created_video(fake, "FakeVid_001", "private")

    status = gateway.get_video_status(FAKE_ACCESS_TOKEN, "FakeVid_001")

    assert status == {
        "privacy_status": "private",
        "upload_status": "uploaded",
        "processing_status": "processing",
    }
    request = fake.videos_list_requests[0]
    assert request.headers["authorization"] == f"Bearer {FAKE_ACCESS_TOKEN}"
    assert FAKE_ACCESS_TOKEN not in request.url
    assert "part=status%2CprocessingDetails" in request.url or (
        "part=status,processingDetails" in request.url
    )


def test_get_video_status_unknown_video_is_rejected(gateway: GoogleGateway) -> None:
    with pytest.raises(GoogleRejected):
        gateway.get_video_status(FAKE_ACCESS_TOKEN, "Missing_001")


@pytest.mark.parametrize("outcome", ["server_error", "timeout"])
def test_get_video_status_unavailable(
    gateway: GoogleGateway, fake: FakeGoogle, outcome: str
) -> None:
    _created_video(fake, "FakeVid_001", "private")
    fake.videos_list_outcome = outcome

    with pytest.raises(GoogleUnavailable):
        gateway.get_video_status(FAKE_ACCESS_TOKEN, "FakeVid_001")
