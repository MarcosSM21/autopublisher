"""In-memory stand-ins for Google, the system keyring, the clock and publishers, so
tests never go online nor really wait."""

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
from sqlalchemy.orm import Session

from app.credential_store import CredentialStoreUnavailable
from app.instagram_gateway import InstagramToken
from app.instagram_oauth import InstagramIdentity
from app.models import Publication
from app.publishing import (
    PreparedPublication,
    ProgressReporter,
    PublishCheck,
    PublishContext,
    PublishFailure,
    PublishOutcome,
    PublishProblem,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# Distinctive values so leak tests can search for them anywhere.
FAKE_ACCESS_TOKEN = "fake-access-token-7f3a2c"
FAKE_REFRESHED_ACCESS_TOKEN = "fake-refreshed-access-token-41bd9e"
FAKE_REFRESH_TOKEN = "fake-refresh-token-9c2e51"
FAKE_ROTATED_REFRESH_TOKEN = "fake-rotated-refresh-token-a81f07"
FAKE_AUTH_CODE = "fake-auth-code-58d1b4"
FAKE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
FAKE_CLIENT_SECRET = "fake-client-secret-for-tests-3e6c"
# The resumable session URI carries this id; it must never leave the upload thread.
FAKE_UPLOAD_ID = "fake-upload-id-5d8e2a"
# A syntactically valid YouTube video ID (11 chars of [A-Za-z0-9_-]).
FAKE_VIDEO_ID = "FakeVid_001"
# Text placed in every simulated Google error body; it must never reach the user.
FAKE_GOOGLE_ERROR_TEXT = "raw-google-error-text-9b14"

SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"
SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
ALL_SCOPES = f"{SCOPE_READONLY} {SCOPE_UPLOAD}"


class InMemoryCredentialStore:
    """CredentialStore double; `fail_on` makes the named operations unavailable."""

    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}
        self.fail_on: set[str] = set()

    @property
    def unavailable(self) -> bool:
        return self.fail_on == {"get", "set", "delete"}

    @unavailable.setter
    def unavailable(self, value: bool) -> None:
        self.fail_on = {"get", "set", "delete"} if value else set()

    def _check(self, operation: str) -> None:
        if operation in self.fail_on:
            raise CredentialStoreUnavailable()

    def get(self, ref: str) -> str | None:
        self._check("get")
        return self.secrets.get(ref)

    def set(self, ref: str, value: str) -> None:
        self._check("set")
        self.secrets[ref] = value

    def delete(self, ref: str) -> None:
        self._check("delete")
        self.secrets.pop(ref, None)


@dataclass
class FakeChannel:
    id: str
    title: str
    handle: str | None = None
    thumbnail_url: str | None = None


@dataclass
class RecordedRequest:
    method: str
    url: str
    form: dict[str, str]
    headers: dict[str, str]
    content: bytes = b""


@dataclass
class UploadFault:
    """One programmed failure of the resumable upload simulator.

    `on` selects the request it applies to: "start" (session start), "chunk" (any
    data PUT), "last_chunk" (the PUT carrying the last byte), "status" (empty status
    query) or "put" (any PUT). `status=None` raises a transport error instead of
    answering; with `store=True` a data PUT keeps its bytes before failing.
    `truncate_to` answers a data PUT with 308 after keeping only that many bytes.
    `video_id` overrides the id of the final resource ("" omits it).
    """

    on: str
    status: int | None = None
    reason: str | None = None
    retry_after: str | None = None
    store: bool = False
    truncate_to: int | None = None
    video_id: str | None = None
    timeout: bool = False


@dataclass
class FakeSession:
    upload_id: str
    total: int
    metadata: dict[str, Any]
    params: dict[str, str]
    headers: dict[str, str]
    data: bytearray = field(default_factory=bytearray)
    video_id: str | None = None


@dataclass
class FakeGoogle:
    """Programmable Google OAuth + YouTube endpoints served via httpx MockTransport.

    Outcomes:
    - exchange: ok | no_refresh | partial_scope | rejected | server_error |
      rate_limited | timeout
    - refresh: ok | rotate | invalid_grant | rejected | server_error | timeout
    - channels (queue, then default): ok | unauthorized | forbidden | server_error |
      timeout
    """

    exchange_outcome: str = "ok"
    refresh_outcome: str = "ok"
    channels_outcome: str = "ok"
    channels_outcomes: list[str] = field(default_factory=list)
    channels: list[FakeChannel] = field(
        default_factory=lambda: [
            FakeChannel(
                "UC_TEST_1",
                "Cyber Channel",
                "@cyberchannel",
                "https://yt3.example.com/cyber.jpg",
            )
        ]
    )
    expires_in: int = 3600
    requests: list[RecordedRequest] = field(default_factory=list)
    # Resumable upload simulator.
    upload_faults: list[UploadFault] = field(default_factory=list)
    returned_privacy: str | None = None
    videos_list_outcome: str = "ok"
    sessions: dict[str, FakeSession] = field(default_factory=dict)
    videos_created: list[dict[str, Any]] = field(default_factory=list)
    upload_hook: Callable[[str, httpx.Request], None] | None = None
    channels_barrier: threading.Barrier | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _block_at: str | None = None
    _blocked: threading.Event = field(default_factory=threading.Event)
    _release: threading.Event = field(default_factory=threading.Event)

    def set_channel(
        self, channel_id: str, title: str = "Cyber Channel", handle: str | None = None
    ) -> None:
        self.channels = [FakeChannel(channel_id, title, handle)]

    @property
    def token_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.url.startswith(TOKEN_URL)]

    @property
    def channel_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.url.startswith(CHANNELS_URL)]

    @property
    def upload_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.url.startswith(UPLOAD_URL)]

    @property
    def session_starts(self) -> list[RecordedRequest]:
        return [r for r in self.upload_requests if r.method == "POST"]

    @property
    def videos_list_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.url.startswith(VIDEOS_URL + "?")]

    def block_uploads(self, at: str = "chunk") -> None:
        """Hold the next matching upload request until `release()` is called."""
        self._block_at = at
        self._blocked.clear()
        self._release.clear()

    def wait_until_blocked(self, timeout: float = 5) -> bool:
        return self._blocked.wait(timeout)

    def release(self) -> None:
        self._block_at = None
        self._release.set()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(UPLOAD_URL):
            return self._upload(request)
        if url.startswith(VIDEOS_URL + "?") and request.method == "GET":
            self._record(request, {})
            return self._videos_list(request)
        body = request.content.decode() if request.content else ""
        form = {key: values[0] for key, values in parse_qs(body).items()}
        self.requests.append(
            RecordedRequest(
                request.method, str(request.url), form, dict(request.headers)
            )
        )
        url = str(request.url)
        if url == TOKEN_URL and request.method == "POST":
            if form.get("grant_type") == "authorization_code":
                return self._exchange(request)
            if form.get("grant_type") == "refresh_token":
                return self._refresh(request)
        if url.startswith(CHANNELS_URL) and request.method == "GET":
            return self._channels(request)
        raise AssertionError(f"Unexpected request to Google: {request.method} {url}")

    @staticmethod
    def _error(status: int, error: str, request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": error}, request=request)

    def _common_failure(
        self, outcome: str, request: httpx.Request
    ) -> httpx.Response | None:
        if outcome == "server_error":
            return self._error(503, "backend_error", request)
        if outcome == "rate_limited":
            return self._error(429, "rate_limit_exceeded", request)
        if outcome == "timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        return None

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        outcome = self.exchange_outcome
        failure = self._common_failure(outcome, request)
        if failure is not None:
            return failure
        if outcome == "rejected":
            return self._error(400, "invalid_grant", request)
        payload: dict[str, Any] = {
            "access_token": FAKE_ACCESS_TOKEN,
            "expires_in": self.expires_in,
            "token_type": "Bearer",
            "scope": SCOPE_READONLY if outcome == "partial_scope" else ALL_SCOPES,
        }
        if outcome != "no_refresh":
            payload["refresh_token"] = FAKE_REFRESH_TOKEN
        return httpx.Response(200, json=payload, request=request)

    def _refresh(self, request: httpx.Request) -> httpx.Response:
        outcome = self.refresh_outcome
        failure = self._common_failure(outcome, request)
        if failure is not None:
            return failure
        if outcome == "invalid_grant":
            return self._error(400, "invalid_grant", request)
        if outcome == "rejected":
            return self._error(401, "invalid_client", request)
        payload: dict[str, Any] = {
            "access_token": FAKE_REFRESHED_ACCESS_TOKEN,
            "expires_in": self.expires_in,
            "token_type": "Bearer",
            "scope": ALL_SCOPES,
        }
        if outcome == "rotate":
            payload["refresh_token"] = FAKE_ROTATED_REFRESH_TOKEN
        return httpx.Response(200, json=payload, request=request)

    def _channels(self, request: httpx.Request) -> httpx.Response:
        if self.channels_barrier is not None:
            self.channels_barrier.wait()
        outcome = (
            self.channels_outcomes.pop(0)
            if self.channels_outcomes
            else self.channels_outcome
        )
        failure = self._common_failure(outcome, request)
        if failure is not None:
            return failure
        if outcome == "unauthorized":
            return httpx.Response(401, json={"error": {"code": 401}}, request=request)
        if outcome == "forbidden":
            return httpx.Response(
                403,
                json={
                    "error": {
                        "code": 403,
                        "errors": [{"reason": "insufficientPermissions"}],
                    }
                },
                request=request,
            )
        items = []
        for channel in self.channels:
            snippet: dict[str, Any] = {"title": channel.title}
            if channel.handle:
                snippet["customUrl"] = channel.handle
            if channel.thumbnail_url:
                snippet["thumbnails"] = {"default": {"url": channel.thumbnail_url}}
            items.append({"id": channel.id, "snippet": snippet})
        return httpx.Response(200, json={"items": items}, request=request)

    # --- Resumable upload simulator ---------------------------------------------------

    def _record(self, request: httpx.Request, form: dict[str, str]) -> None:
        with self._lock:
            self.requests.append(
                RecordedRequest(
                    request.method,
                    str(request.url),
                    form,
                    dict(request.headers),
                    request.content,
                )
            )

    def _take_fault(self, kinds: set[str]) -> UploadFault | None:
        with self._lock:
            for index, fault in enumerate(self.upload_faults):
                if fault.on in kinds:
                    return self.upload_faults.pop(index)
        return None

    def _maybe_block(self, kind: str) -> None:
        at = self._block_at
        if at is not None and (at == kind or (at == "chunk" and kind == "last_chunk")):
            self._block_at = None
            self._blocked.set()
            self._release.wait(10)

    @staticmethod
    def _google_error(
        status: int, reason: str | None, request: httpx.Request, retry_after: str | None
    ) -> httpx.Response:
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        return httpx.Response(
            status,
            json={
                "error": {
                    "code": status,
                    "message": FAKE_GOOGLE_ERROR_TEXT,
                    "errors": [{"reason": reason or "backendError"}],
                }
            },
            headers=headers,
            request=request,
        )

    def _fault_response(
        self, fault: UploadFault, request: httpx.Request
    ) -> httpx.Response:
        if fault.status is None:
            if fault.timeout:
                raise httpx.ReadTimeout("timed out", request=request)
            raise httpx.ConnectError("connection lost", request=request)
        return self._google_error(
            fault.status, fault.reason, request, fault.retry_after
        )

    def _upload(self, request: httpx.Request) -> httpx.Response:
        self._record(request, {})
        url = urlsplit(str(request.url))
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        if request.method == "POST":
            return self._start_session(request, params)
        if request.method != "PUT":
            raise AssertionError(f"Unexpected upload request {request.method}")
        session = self.sessions.get(params.get("upload_id", ""))
        content_range = request.headers.get("Content-Range", "")
        if not content_range.startswith("bytes "):
            raise AssertionError("Upload PUT without Content-Range")
        spec = content_range[len("bytes ") :]
        if spec.startswith("*/"):
            kind = "status"
        else:
            span, total = spec.split("/")
            end = int(span.split("-")[1])
            kind = "last_chunk" if end == int(total) - 1 else "chunk"
        if self.upload_hook is not None:
            self.upload_hook(kind, request)
        self._maybe_block(kind)
        kinds = {kind, "put"} | ({"chunk"} if kind == "last_chunk" else set())
        fault = self._take_fault(kinds)
        if session is None:
            return self._google_error(404, "notFound", request, None)
        if kind == "status":
            if fault is not None:
                return self._fault_response(fault, request)
            return self._session_state(session, request)
        start = int(spec.split("-")[0])
        if start > len(session.data):
            raise AssertionError("Upload chunk leaves a gap")
        stores = fault is None or fault.store or fault.video_id is not None
        if fault is not None and fault.truncate_to is None and not stores:
            return self._fault_response(fault, request)
        del session.data[start:]
        session.data.extend(request.content)
        if fault is not None and fault.truncate_to is not None:
            del session.data[fault.truncate_to :]
            return self._session_state(session, request)
        if len(session.data) >= session.total and session.video_id is None:
            self._create_video(session, fault)
        if fault is not None and fault.video_id is None:
            return self._fault_response(fault, request)
        return self._session_state(session, request)

    def _start_session(
        self, request: httpx.Request, params: dict[str, str]
    ) -> httpx.Response:
        if self.upload_hook is not None:
            self.upload_hook("start", request)
        self._maybe_block("start")
        fault = self._take_fault({"start"})
        if fault is not None:
            return self._fault_response(fault, request)
        with self._lock:
            number = len(self.sessions)
        upload_id = FAKE_UPLOAD_ID if number == 0 else f"{FAKE_UPLOAD_ID}-{number}"
        self.sessions[upload_id] = FakeSession(
            upload_id=upload_id,
            total=int(request.headers["X-Upload-Content-Length"]),
            metadata=json.loads(request.content),
            params=params,
            headers=dict(request.headers),
        )
        location = f"{UPLOAD_URL}?uploadType=resumable&upload_id={upload_id}"
        return httpx.Response(200, headers={"Location": location}, request=request)

    def _create_video(self, session: FakeSession, fault: UploadFault | None) -> None:
        with self._lock:
            number = len(self.videos_created)
            video_id = FAKE_VIDEO_ID if number == 0 else f"FakeVid_{number + 1:03d}"
            if fault is not None and fault.video_id is not None:
                video_id = fault.video_id
            requested = session.metadata.get("status", {}).get("privacyStatus")
            session.video_id = video_id
            self.videos_created.append(
                {
                    "id": video_id,
                    "snippet": session.metadata.get("snippet", {}),
                    "status": dict(session.metadata.get("status", {})),
                    "privacy": self.returned_privacy or requested,
                    "data": bytes(session.data),
                }
            )

    def _video_resource(self, video_id: str) -> dict[str, Any]:
        video = next(v for v in self.videos_created if v["id"] == video_id)
        resource: dict[str, Any] = {
            "kind": "youtube#video",
            "snippet": video["snippet"],
            "status": {"privacyStatus": video["privacy"], "uploadStatus": "uploaded"},
        }
        if video_id:
            resource["id"] = video_id
        return resource

    def _session_state(
        self, session: FakeSession, request: httpx.Request
    ) -> httpx.Response:
        if session.video_id is not None:
            return httpx.Response(
                200, json=self._video_resource(session.video_id), request=request
            )
        headers = {"Range": f"bytes=0-{len(session.data) - 1}"} if session.data else {}
        return httpx.Response(308, headers=headers, request=request)

    def _videos_list(self, request: httpx.Request) -> httpx.Response:
        outcome = self.videos_list_outcome
        if outcome == "server_error":
            return self._google_error(503, "backendError", request, None)
        if outcome == "timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        video_id = request.url.params.get("id")
        items = [
            {
                "id": video["id"],
                "status": {
                    "privacyStatus": video["privacy"],
                    "uploadStatus": "uploaded",
                },
                "processingDetails": {"processingStatus": "processing"},
            }
            for video in self.videos_created
            if video["id"] == video_id
        ]
        return httpx.Response(200, json={"items": items}, request=request)


def client_config_json() -> str:
    return json.dumps(
        {
            "installed": {
                "client_id": FAKE_CLIENT_ID,
                "client_secret": FAKE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    )


# --- Scheduler (Feature 007) --------------------------------------------------------


class FakeClock:
    """A mutable UTC clock shared by the scheduler and the API in tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = value

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += timedelta(seconds=seconds)


class FakePublisher:
    """Programmable `Publisher` that never touches the network.

    - `problems`: local problems returned by `check` (per publication id);
    - `prepare_error`: exception raised by `prepare` (per publication id or for all
      with the key `None`);
    - `prepare_hook`: called inside `prepare` with the publication id, e.g. to wait on
      a barrier, advance the clock or pause the automation;
    - `upload_gate`: when set, `upload` waits until the event is set;
    - `upload_gates`: the same, per publication id;
    - `upload_failure`: a `PublishFailure` raised by `upload` (`upload_failures`
      per publication id).
    """

    def __init__(self) -> None:
        self.problems: dict[int, list[PublishProblem]] = {}
        self.prepare_error: dict[int | None, Exception] = {}
        self.prepare_hook: Callable[[int], None] | None = None
        self.upload_gate: threading.Event | None = None
        self.upload_gates: dict[int, threading.Event] = {}
        self.upload_failure: PublishFailure | None = None
        self.upload_failures: dict[int, PublishFailure] = {}
        self.check_calls: list[int] = []
        self.prepare_calls: list[int] = []
        self.upload_calls: list[int] = []
        self._lock = threading.Lock()

    def check(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PublishCheck:
        with self._lock:
            self.check_calls.append(publication.id)
        return PublishCheck(list(self.problems.get(publication.id, [])), [])

    def prepare(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PreparedPublication:
        with self._lock:
            self.prepare_calls.append(publication.id)
        if self.prepare_hook is not None:
            self.prepare_hook(publication.id)
        error = self.prepare_error.get(publication.id) or self.prepare_error.get(None)
        if error is not None:
            raise error
        return PreparedPublication(
            publication_id=publication.id,
            file_path=Path("unused"),
            total_bytes=10,
            submitted={"title": "fake"},
            payload=None,
        )

    def upload(
        self,
        prepared: PreparedPublication,
        reporter: ProgressReporter,
        ctx: PublishContext,
    ) -> PublishOutcome:
        with self._lock:
            self.upload_calls.append(prepared.publication_id)
        gate = self.upload_gates.get(prepared.publication_id, self.upload_gate)
        if gate is not None:
            assert gate.wait(timeout=10), "upload gate never opened"
        failure = self.upload_failures.get(prepared.publication_id, self.upload_failure)
        if failure is not None:
            raise failure
        reporter.report_bytes(prepared.total_bytes, confirmed=True)
        return PublishOutcome(
            external_id=f"fake-{prepared.publication_id}",
            external_url=f"https://example.invalid/{prepared.publication_id}",
        )

    def refresh_details(
        self,
        prepared: PreparedPublication,
        outcome: PublishOutcome,
        ctx: PublishContext,
    ) -> PublishOutcome:
        return outcome


# --- Instagram Login (Feature 008) ---------------------------------------------------

IG_CODE_URL = "https://api.instagram.com/oauth/access_token"
IG_LONG_LIVED_URL = "https://graph.instagram.com/access_token"
IG_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
IG_ME_URL = "https://graph.instagram.com/v26.0/me"

# Distinctive values so leak tests can search for them anywhere.
FAKE_IG_CODE = "fake-ig-code-6a1e93"
FAKE_IG_SHORT_TOKEN = "fake-ig-short-token-2b7c40"
FAKE_IG_LONG_TOKEN = "fake-ig-long-token-c58f12"
FAKE_IG_REFRESHED_TOKEN = "fake-ig-refreshed-token-0d94e7"
FAKE_IG_APP_SECRET = "fake-ig-app-secret-71ac3d"
FAKE_IG_APP_ID = "1234567890"
FAKE_IG_REDIRECT_URI = "https://localhost/autopublisher/instagram/callback"
# Text placed in every simulated Meta error body; it must never reach the user.
FAKE_META_ERROR_TEXT = "raw-meta-error-text-4e2a"

IG_BASIC = "instagram_business_basic"
IG_PUBLISH = "instagram_business_content_publish"
IG_ALL_PERMISSIONS = f"{IG_BASIC},{IG_PUBLISH}"
LONG_LIVED_SECONDS = 60 * 24 * 3600


def instagram_app_config_json(
    *,
    app_id: str = FAKE_IG_APP_ID,
    app_secret: str = FAKE_IG_APP_SECRET,
    redirect_uri: str = FAKE_IG_REDIRECT_URI,
) -> str:
    return json.dumps(
        {"app_id": app_id, "app_secret": app_secret, "redirect_uri": redirect_uri}
    )


@dataclass
class FakeInstagramIdentity:
    user_id: str = "17841400000000001"
    id: str = "9000000000000001"
    username: str = "cyber.studio"
    account_type: str | None = "Business"
    profile_picture_url: str | None = "https://scontent.example.com/cyber.jpg"


@dataclass
class FakeMeta:
    """Programmable Instagram Login endpoints served via httpx MockTransport.

    `faults` maps an endpoint ("code", "long_lived", "refresh", "me") to a fault;
    `fault_queue` holds one-shot faults per endpoint, used before `faults`. Faults:
    transport | server_error | rate_limited | graph_<n> (Graph error code n) |
    oauth_exception | bad_json | missing_fields.
    """

    identity: FakeInstagramIdentity = field(default_factory=FakeInstagramIdentity)
    # None omits the field from the code exchange response.
    permissions: str | None = IG_ALL_PERMISSIONS
    wrap_data: bool = True
    expires_in: int = LONG_LIVED_SECONDS
    faults: dict[str, str] = field(default_factory=dict)
    fault_queue: dict[str, list[str]] = field(default_factory=dict)
    # Permission named in simulated permission errors (graph_10 / graph_2xx).
    error_permission: str | None = None
    requests: list[RecordedRequest] = field(default_factory=list)
    refresh_hook: Callable[[], None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_identity(self, **values: Any) -> None:
        self.identity = FakeInstagramIdentity(**values)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def requests_to(self, endpoint: str) -> list[RecordedRequest]:
        url = {
            "code": IG_CODE_URL,
            "long_lived": IG_LONG_LIVED_URL,
            "refresh": IG_REFRESH_URL,
            "me": IG_ME_URL,
        }[endpoint]
        return [r for r in self.requests if r.url.split("?")[0] == url]

    def _fault(self, endpoint: str) -> str | None:
        with self._lock:
            queue = self.fault_queue.get(endpoint)
            if queue:
                return queue.pop(0)
        return self.faults.get(endpoint)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        base = url.split("?")[0]
        body = request.content.decode() if request.content else ""
        form = {key: values[0] for key, values in parse_qs(body).items()}
        with self._lock:
            self.requests.append(
                RecordedRequest(request.method, url, form, dict(request.headers))
            )
        params = dict(request.url.params)
        if base == IG_CODE_URL and request.method == "POST":
            return self._respond("code", request, lambda: self._code(form))
        if base == IG_LONG_LIVED_URL and request.method == "GET":
            return self._respond("long_lived", request, lambda: self._long(params))
        if base == IG_REFRESH_URL and request.method == "GET":
            if self.refresh_hook is not None:
                self.refresh_hook()
            return self._respond("refresh", request, lambda: self._refresh(params))
        if base == IG_ME_URL and request.method == "GET":
            return self._respond("me", request, lambda: self._me(params))
        raise AssertionError(f"Unexpected request to Meta: {request.method} {base}")

    def _graph_error(self, code: int, request: httpx.Request) -> httpx.Response:
        message = FAKE_META_ERROR_TEXT
        if self.error_permission:
            message += f" ({self.error_permission})"
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": message,
                    "type": "OAuthException",
                    "code": code,
                    "fbtrace_id": "AbCdEf",
                }
            },
            request=request,
        )

    def _respond(
        self,
        endpoint: str,
        request: httpx.Request,
        success: Callable[[], dict[str, Any] | httpx.Response],
    ) -> httpx.Response:
        fault = self._fault(endpoint)
        if fault == "transport":
            raise httpx.ConnectTimeout("timed out", request=request)
        if fault == "server_error":
            return httpx.Response(503, text=FAKE_META_ERROR_TEXT, request=request)
        if fault == "rate_limited":
            return httpx.Response(429, text=FAKE_META_ERROR_TEXT, request=request)
        if fault is not None and fault.startswith("graph_"):
            return self._graph_error(int(fault.removeprefix("graph_")), request)
        if fault == "oauth_exception":
            return httpx.Response(
                400,
                json={
                    "error_type": "OAuthException",
                    "code": 400,
                    "error_message": FAKE_META_ERROR_TEXT,
                },
                request=request,
            )
        if fault == "bad_json":
            return httpx.Response(200, text="<html>not json", request=request)
        if fault == "missing_fields":
            return httpx.Response(
                200,
                json={"data": []}
                if endpoint == "code"
                else {"unexpected": FAKE_META_ERROR_TEXT},
                request=request,
            )
        result = success()
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result, request=request)

    def _code(self, form: dict[str, str]) -> dict[str, Any] | httpx.Response:
        assert form.get("code") == FAKE_IG_CODE, "unexpected authorization code"
        item: dict[str, Any] = {
            "access_token": FAKE_IG_SHORT_TOKEN,
            "user_id": self.identity.id,
        }
        if self.permissions is not None:
            item["permissions"] = self.permissions
        return {"data": [item]} if self.wrap_data else item

    def _long(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("access_token") == FAKE_IG_SHORT_TOKEN
        return {
            "access_token": FAKE_IG_LONG_TOKEN,
            "token_type": "bearer",
            "expires_in": self.expires_in,
        }

    def _refresh(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("access_token") in {
            FAKE_IG_LONG_TOKEN,
            FAKE_IG_REFRESHED_TOKEN,
        }
        return {
            "access_token": FAKE_IG_REFRESHED_TOKEN,
            "token_type": "bearer",
            "expires_in": self.expires_in,
        }

    def _me(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("access_token") in {
            FAKE_IG_LONG_TOKEN,
            FAKE_IG_REFRESHED_TOKEN,
        }
        identity = self.identity
        payload: dict[str, Any] = {
            "user_id": identity.user_id,
            "id": identity.id,
            "username": identity.username,
        }
        if identity.account_type is not None:
            payload["account_type"] = identity.account_type
        if identity.profile_picture_url is not None:
            payload["profile_picture_url"] = identity.profile_picture_url
        return payload


class StubInstagramGateway:
    """Gateway double that speaks only the semantic classification (MetaUnavailable,
    MetaTokenInvalid, ...), for service tests that must not depend on Meta's error
    numbers. Every call is counted so tests can assert that Meta was not contacted."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock.now
        self.refresh_error: Exception | None = None
        self.me_error: Exception | None = None
        self.refresh_delay = 0.0
        self.calls: list[str] = []
        self.identity: dict[str, Any] = {
            "instagram_user_id": "17841400000000001",
            "username": "cyber.studio",
            "account_type": "BUSINESS",
            "profile_picture_url": "https://scontent.example.com/cyber.jpg",
            "app_scoped_id": "9000000000000001",
        }

    def refresh(self, token: InstagramToken) -> InstagramToken:
        self.calls.append("refresh")
        if self.refresh_delay:
            time.sleep(self.refresh_delay)
        if self.refresh_error is not None:
            raise self.refresh_error
        now = self.clock()
        return InstagramToken(
            FAKE_IG_REFRESHED_TOKEN,
            now,
            now + timedelta(seconds=LONG_LIVED_SECONDS),
            token.permissions,
        )

    def fetch_me(self, access_token: str) -> InstagramIdentity:
        self.calls.append("me")
        if self.me_error is not None:
            raise self.me_error
        return InstagramIdentity(**self.identity)
