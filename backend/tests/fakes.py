"""In-memory stand-ins for Google, the system keyring, the clock and publishers, so
tests never go online nor really wait."""

import hashlib
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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content_files import effective_checksum_sql
from app.credential_store import CredentialStoreUnavailable
from app.instagram_gateway import InstagramToken
from app.instagram_oauth import InstagramIdentity
from app.media_delivery import MediaDeliveryFailed, SecretUrl
from app.models import Content, Publication, PublicationAttempt
from app.publishing import (
    PreparedPublication,
    ProgressReporter,
    PublishCheck,
    PublishContext,
    PublishFailure,
    PublishOutcome,
    PublishProblem,
    ReconciledFailure,
    Reconciliation,
    UserActionCompleted,
    UserActionFailed,
)
from app.threads_gateway import ThreadsToken, ThreadsTokenInfo
from app.threads_oauth import ThreadsIdentity

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
    # Analytics `videos.list?part=statistics` (Feature 027): the statistics of each
    # video id, and a queue of outcomes (then "ok"): ok | server_error | timeout |
    # unauthorized | quota | rate_limit | forbidden | not_found | paged.
    statistics: dict[str, dict[str, Any]] = field(default_factory=dict)
    statistics_outcomes: list[str] = field(default_factory=list)
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

    @property
    def statistics_requests(self) -> list[RecordedRequest]:
        return [r for r in self.videos_list_requests if "part=statistics" in r.url]

    def _statistics(self, request: httpx.Request) -> httpx.Response:
        outcome = self.statistics_outcomes.pop(0) if self.statistics_outcomes else "ok"
        errors = {
            "server_error": (503, "backendError"),
            "unauthorized": (401, "authError"),
            "quota": (403, "quotaExceeded"),
            "rate_limit": (403, "rateLimitExceeded"),
            "forbidden": (403, "insufficientPermissions"),
            "not_found": (404, "videoNotFound"),
        }
        if outcome == "timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        if outcome in errors:
            status, reason = errors[outcome]
            return self._google_error(status, reason, request, None)
        ids = (request.url.params.get("id") or "").split(",")
        items = [
            {"id": video_id, "statistics": self.statistics[video_id]}
            for video_id in ids
            if video_id in self.statistics
        ]
        body: dict[str, Any] = {"items": items}
        if outcome == "paged":
            body["nextPageToken"] = "NEXT"
        return httpx.Response(200, json=body, request=request)

    def _videos_list(self, request: httpx.Request) -> httpx.Response:
        if request.url.params.get("part") == "statistics":
            return self._statistics(request)
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
      per publication id);
    - `outcomes`: the `PublishOutcome` `upload` returns per publication id (a
      published outcome with a fake identity otherwise);
    - `release_warnings` / `release_error`: what `release` returns or raises;
    - `reconciliations`: what `reconcile` returns per publication id (None otherwise):
      a confirmed publication or a confirmed failure;
    - `reconcile_errors`: an exception `reconcile` raises per publication id;
    - `reconcile_hook`: called inside `reconcile` with the publication id;
    - `follow_ups` / `follow_up_errors`: what `follow_up` returns or raises per
      publication id (None, still waiting, otherwise); `follow_up_hook` runs
      inside `follow_up` with the publication id;
    - `accepts_text_only`: whether publications without media are accepted;
    - `arming`: problems `arming_problems` reports per account id (none otherwise).
    """

    def __init__(self, *, accepts_text_only: bool = False) -> None:
        self.accepts_text_only = accepts_text_only
        self.problems: dict[int, list[PublishProblem]] = {}
        self.prepare_error: dict[int | None, Exception] = {}
        self.prepare_hook: Callable[[int], None] | None = None
        self.upload_gate: threading.Event | None = None
        self.upload_gates: dict[int, threading.Event] = {}
        self.upload_failure: PublishFailure | None = None
        self.upload_failures: dict[int, PublishFailure] = {}
        self.outcomes: dict[int, PublishOutcome] = {}
        self.check_calls: list[int] = []
        self.prepare_calls: list[int] = []
        self.upload_calls: list[int] = []
        self.release_warnings: list[dict[str, str]] = []
        self.release_error: Exception | None = None
        # (attempt_id, succeeded, publication status seen when release ran)
        self.release_calls: list[tuple[int, bool, str]] = []
        self.reconciliations: dict[int, Reconciliation | ReconciledFailure] = {}
        self.reconcile_errors: dict[int, Exception] = {}
        self.reconcile_hook: Callable[[int], None] | None = None
        self.reconcile_calls: list[int] = []
        self.follow_ups: dict[int, UserActionCompleted | UserActionFailed] = {}
        self.follow_up_errors: dict[int, Exception] = {}
        self.follow_up_calls: list[int] = []
        self.follow_up_hook: Callable[[int], None] | None = None
        self.arming: dict[int, list[PublishProblem]] = {}
        self.arming_calls: list[int | None] = []
        self._lock = threading.Lock()

    def arming_problems(
        self, session: Session, publication: Publication
    ) -> list[PublishProblem]:
        with self._lock:
            self.arming_calls.append(publication.id)
        return list(self.arming.get(publication.account_id, []))

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
        # Resolved first, as a real publisher does before any network step, so a
        # hook can simulate a change of the file after the preparation.
        file_checksum = None
        if publication.content_id is not None:
            file_checksum = session.scalar(
                select(effective_checksum_sql()).where(
                    Content.id == publication.content_id
                )
            )
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
            file_checksum=file_checksum,
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
        outcome = self.outcomes.get(prepared.publication_id)
        if outcome is not None:
            return outcome
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

    def release(
        self,
        prepared: PreparedPublication,
        ctx: PublishContext,
        *,
        attempt_id: int,
        succeeded: bool,
    ) -> list[dict[str, str]]:
        with ctx.session_factory() as session:
            publication = session.get_one(Publication, prepared.publication_id)
            status = publication.status
        with self._lock:
            self.release_calls.append((attempt_id, succeeded, status))
        if self.release_error is not None:
            raise self.release_error
        return list(self.release_warnings)

    def reconcile(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> Reconciliation | ReconciledFailure | None:
        with self._lock:
            self.reconcile_calls.append(publication.id)
        if self.reconcile_hook is not None:
            self.reconcile_hook(publication.id)
        error = self.reconcile_errors.get(publication.id)
        if error is not None:
            raise error
        return self.reconciliations.get(publication.id)

    def follow_up(
        self,
        session: Session,
        publication: Publication,
        attempt: PublicationAttempt,
        ctx: PublishContext,
    ) -> UserActionCompleted | UserActionFailed | None:
        with self._lock:
            self.follow_up_calls.append(publication.id)
        if self.follow_up_hook is not None:
            self.follow_up_hook(publication.id)
        error = self.follow_up_errors.get(publication.id)
        if error is not None:
            raise error
        return self.follow_ups.get(publication.id)


# --- Instagram Login (Feature 008) ---------------------------------------------------

IG_CODE_URL = "https://api.instagram.com/oauth/access_token"
IG_LONG_LIVED_URL = "https://graph.instagram.com/access_token"
IG_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
IG_ME_URL = "https://graph.instagram.com/v26.0/me"
IG_GRAPH_ROOT = "https://graph.instagram.com/v26.0"
IG_USER_ID = "17841400000000001"

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
    graph_<n>_<subcode> | oauth_exception | bad_json | missing_fields.

    Content Publishing endpoints ("create", "status", "publish", "permalink",
    "limit") accept the same faults; "publish" also accepts `<fault>_after_publish`,
    which publishes the container and then fails the response (an uncertain
    result). `status_script` is the sequence of `status_code` values a new container
    reports (the last one repeats); `container_statuses` can be changed per container.
    Requests to the media list endpoint are recorded in `media_list_requests` and
    rejected: publishers must never use them.
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
    # Content Publishing (Feature 009).
    status_script: list[str] = field(default_factory=lambda: ["FINISHED"])
    container_statuses: dict[str, list[str]] = field(default_factory=dict)
    containers: dict[str, dict[str, str]] = field(default_factory=dict)
    published: list[str] = field(default_factory=list)
    quota: tuple[int, int] | None = (0, 50)
    permalinks: bool = True
    publish_hook: Callable[[], None] | None = None
    create_hook: Callable[[], None] | None = None
    media_list_requests: int = 0
    _next_id: int = 100
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
        if base.startswith(IG_GRAPH_ROOT + "/"):
            return self._publishing(request, base, form, params)
        raise AssertionError(f"Unexpected request to Meta: {request.method} {base}")

    def _graph_error(
        self, code: int, request: httpx.Request, subcode: int | None = None
    ) -> httpx.Response:
        message = FAKE_META_ERROR_TEXT
        if self.error_permission:
            message += f" ({self.error_permission})"
        error: dict[str, Any] = {
            "message": message,
            "type": "OAuthException",
            "code": code,
            "fbtrace_id": "AbCdEf",
        }
        if subcode is not None:
            error["error_subcode"] = subcode
        return httpx.Response(400, json={"error": error}, request=request)

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
            numbers = fault.removeprefix("graph_").rsplit("_", 1)
            if len(numbers) == 2 and numbers[0]:
                return self._graph_error(int(numbers[0]), request, int(numbers[1]))
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

    # --- Content Publishing ------------------------------------------------------

    def requests_for(self, endpoint: str) -> list[RecordedRequest]:
        """Recorded Content Publishing requests: create, status, publish, permalink,
        limit."""
        result = []
        for recorded in self.requests:
            base = recorded.url.split("?")[0]
            if not base.startswith(IG_GRAPH_ROOT + "/"):
                continue
            if self._endpoint_of(recorded.method, base, recorded.url) == endpoint:
                result.append(recorded)
        return result

    def _endpoint_of(self, method: str, base: str, url: str) -> str:
        path = base.removeprefix(IG_GRAPH_ROOT + "/")
        if method == "POST" and path.endswith("/media_publish"):
            return "publish"
        if method == "POST" and path.endswith("/media"):
            return "create"
        if method == "GET" and path.endswith("/content_publishing_limit"):
            return "limit"
        if method == "GET" and path.endswith("/media"):
            return "media_list"
        if method == "GET" and "status_code" in url:
            return "status"
        if method == "GET" and "permalink" in url:
            return "permalink"
        return "unknown"

    def _token_ok(self, token: str | None) -> bool:
        return token in {FAKE_IG_LONG_TOKEN, FAKE_IG_REFRESHED_TOKEN}

    def _publishing(
        self,
        request: httpx.Request,
        base: str,
        form: dict[str, str],
        params: dict[str, str],
    ) -> httpx.Response:
        endpoint = self._endpoint_of(request.method, base, str(request.url))
        token = form.get("access_token") or params.get("access_token")
        assert self._token_ok(token), "unexpected access token"
        path = base.removeprefix(IG_GRAPH_ROOT + "/")
        if endpoint == "media_list":
            with self._lock:
                self.media_list_requests += 1
            return self._graph_error(100, request)
        if endpoint == "create":
            if self.create_hook is not None:
                self.create_hook()
            return self._respond("create", request, lambda: self._create(form))
        if endpoint == "status":
            return self._respond("status", request, lambda: self._status(path))
        if endpoint == "publish":
            return self._publish(request, form)
        if endpoint == "permalink":
            return self._respond("permalink", request, lambda: self._permalink(path))
        if endpoint == "limit":
            return self._respond("limit", request, self._limit)
        raise AssertionError(f"Unexpected request to Meta: {request.method} {base}")

    def _create(self, form: dict[str, str]) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            container_id = f"1790000000000{self._next_id}"
            self.containers[container_id] = dict(form)
            self.container_statuses[container_id] = list(self.status_script)
        return {"id": container_id}

    def _status(self, container_id: str) -> dict[str, Any] | httpx.Response:
        with self._lock:
            script = self.container_statuses.get(container_id)
            if not script:
                return httpx.Response(400, json={"error": {"code": 100}}, request=None)
            status = script.pop(0) if len(script) > 1 else script[0]
        return {"status_code": status, "id": container_id}

    def _publish(self, request: httpx.Request, form: dict[str, str]) -> httpx.Response:
        if self.publish_hook is not None:
            self.publish_hook()
        container_id = form.get("creation_id", "")
        fault = self._fault("publish")
        if fault is not None and fault.endswith("_after_publish"):
            self._mark_published(container_id)
            fault = fault.removesuffix("_after_publish")
            with self._lock:
                self.fault_queue.setdefault("publish", []).insert(0, fault)
            return self._respond("publish", request, lambda: {})
        if fault is not None:
            with self._lock:
                self.fault_queue.setdefault("publish", []).insert(0, fault)
            return self._respond("publish", request, lambda: {})
        media_id = self._mark_published(container_id)
        return httpx.Response(200, json={"id": media_id}, request=request)

    def _mark_published(self, container_id: str) -> str:
        with self._lock:
            assert container_id in self.containers, "unknown container"
            self.published.append(container_id)
            self.container_statuses[container_id] = ["PUBLISHED"]
            return f"1800000000000{len(self.published)}"

    def _permalink(self, media_id: str) -> dict[str, Any]:
        if not self.permalinks:
            return {"id": media_id}
        return {"id": media_id, "permalink": f"https://www.instagram.com/p/{media_id}/"}

    def _limit(self) -> dict[str, Any]:
        if self.quota is None:
            return {"data": [{"unexpected": True}]}
        usage, total = self.quota
        return {
            "data": [
                {
                    "quota_usage": usage,
                    "config": {"quota_total": total, "quota_duration": 86400},
                }
            ]
        }


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


# --- Temporary media delivery (Feature 009) -----------------------------------------

FAKE_DELIVERY_SECRET = "fake-delivery-secret-9b31e0"
FAKE_DELIVERY_ACCESS_KEY = "FAKEACCESSKEY7d22"
FAKE_SIGNATURE = "fakesignature5c8a1f"


def media_delivery_config_json(**overrides: Any) -> str:
    values: dict[str, Any] = {
        "provider": "s3_compatible",
        "endpoint_url": "https://fake-account.r2.cloudflarestorage.com",
        "bucket": "autopublisher-temp",
        "region": "auto",
        "access_key_id": FAKE_DELIVERY_ACCESS_KEY,
        "secret_access_key": FAKE_DELIVERY_SECRET,
        "key_prefix": "autopublisher-tmp/",
        "url_ttl_seconds": 3600,
    }
    values.update(overrides)
    return json.dumps(values)


@dataclass
class FakeMediaDeliveryProvider:
    """In-memory, private object store with signed URLs that look like R2's.

    - `put_failures` / `delete_failures`: how many next calls fail;
    - `put_hook`: called with the key before each upload (e.g. to inspect SQLite).
    """

    name: str = "s3_compatible"
    objects: dict[str, bytes] = field(default_factory=dict)
    content_types: dict[str, str] = field(default_factory=dict)
    put_calls: list[str] = field(default_factory=list)
    delete_calls: list[str] = field(default_factory=list)
    signed: list[str] = field(default_factory=list)
    put_failures: int = 0
    delete_failures: int = 0
    put_hook: Callable[[str], None] | None = None
    delete_hook: Callable[[str], None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def put(
        self,
        key: str,
        source: bytes | Path,
        content_type: str,
        size: int,
        on_progress: Callable[[int], None],
    ) -> None:
        if self.put_hook is not None:
            self.put_hook(key)
        with self._lock:
            self.put_calls.append(key)
            if self.put_failures:
                self.put_failures -= 1
                raise MediaDeliveryFailed()
        data = source if isinstance(source, bytes) else source.read_bytes()
        half = len(data) // 2
        on_progress(half)
        on_progress(len(data))
        with self._lock:
            self.objects[key] = data
            self.content_types[key] = content_type

    def signed_get_url(self, key: str, ttl_seconds: int) -> SecretUrl:
        url = (
            f"https://fake-account.r2.cloudflarestorage.com/autopublisher-temp/{key}"
            f"?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential="
            f"{FAKE_DELIVERY_ACCESS_KEY}%2F20261009%2Fauto%2Fs3%2Faws4_request"
            f"&X-Amz-Expires={ttl_seconds}&X-Amz-Signature={FAKE_SIGNATURE}"
        )
        with self._lock:
            self.signed.append(url)
        return SecretUrl(url)

    def delete(self, key: str) -> None:
        if self.delete_hook is not None:
            self.delete_hook(key)
        with self._lock:
            self.delete_calls.append(key)
            if self.delete_failures:
                self.delete_failures -= 1
                raise MediaDeliveryFailed()
            self.objects.pop(key, None)


# --- Threads API (Feature 010) -------------------------------------------------------

TH_CODE_URL = "https://graph.threads.net/oauth/access_token"
TH_LONG_LIVED_URL = "https://graph.threads.net/access_token"
TH_REFRESH_URL = "https://graph.threads.net/refresh_access_token"
TH_DEBUG_URL = "https://graph.threads.net/v1.0/debug_token"
TH_ME_URL = "https://graph.threads.net/v1.0/me"
TH_GRAPH_ROOT = "https://graph.threads.net/v1.0"
TH_USER_ID = "25841234567890123"

# Distinctive values so leak tests can search for them anywhere.
FAKE_TH_CODE = "fake-th-code-3c9d71"
FAKE_TH_SHORT_TOKEN = "fake-th-short-token-8e14ab"
FAKE_TH_LONG_TOKEN = "fake-th-long-token-52f0c6"
FAKE_TH_REFRESHED_TOKEN = "fake-th-refreshed-token-a7d3e9"
FAKE_TH_APP_SECRET = "fake-th-app-secret-1b6f28"
FAKE_TH_APP_ID = "9876543210"
FAKE_TH_REDIRECT_URI = "https://localhost/autopublisher/threads/callback"

TH_BASIC = "threads_basic"
TH_PUBLISH = "threads_content_publish"
TH_ALL_SCOPES = [TH_BASIC, TH_PUBLISH]
# Unix time of the data access expiry reported by the fake `debug_token`.
TH_DATA_ACCESS_EXPIRES_AT = int(datetime(2027, 1, 10, 18, tzinfo=UTC).timestamp())


def threads_app_config_json(
    *,
    app_id: str = FAKE_TH_APP_ID,
    app_secret: str = FAKE_TH_APP_SECRET,
    redirect_uri: str = FAKE_TH_REDIRECT_URI,
) -> str:
    return json.dumps(
        {"app_id": app_id, "app_secret": app_secret, "redirect_uri": redirect_uri}
    )


@dataclass
class FakeThreadsIdentity:
    id: str = TH_USER_ID
    username: str = "cyber.studio"
    name: str | None = "Cyber Studio"
    threads_profile_picture_url: str | None = "https://scontent.example/th-pic.jpg"


@dataclass
class FakeThreads:
    """Programmable Threads API endpoints served via httpx MockTransport.

    `faults` maps an endpoint ("code", "long_lived", "refresh", "debug", "me") to a
    fault; `fault_queue` holds one-shot faults per endpoint, used before `faults`.
    Faults: transport | timeout | server_error | rate_limited | graph_<n> (Graph error
    code n) | bad_json | missing_fields. `exchange_user_id` and `debug` override what
    the code exchange and `debug_token` report, to simulate incoherent or partial
    answers.

    Publishing endpoints (Feature 011) accept the same faults: "create" (also
    `link_limit`, Meta's THREADS_API__LINK_LIMIT_EXCEEDED rejection), "status",
    "publish", "post" and "limit". "publish" also accepts `<fault>_after_publish`,
    which really publishes the container and then fails the response (an uncertain
    result). `status_script` is the sequence of statuses a new container reports
    (the last one repeats); an entry `ERROR:<code>` reports `ERROR` with that
    `error_message`. `container_statuses` can be changed per container. Every POST
    must carry its parameters in the form body only: a query string fails the test.
    Requests to the post list endpoint are counted in `post_list_requests` and
    rejected: publishers must never use them.
    """

    identity: FakeThreadsIdentity = field(default_factory=FakeThreadsIdentity)
    # None reports the identity's id.
    exchange_user_id: str | None = None
    expires_in: int = LONG_LIVED_SECONDS
    refreshed_expires_in: int = LONG_LIVED_SECONDS
    # `debug_token` answer; keys set to None are omitted from the response.
    debug_is_valid: bool | None = True
    debug_user_id: str | None = None
    debug_scopes: list[str] | None = field(default_factory=lambda: list(TH_ALL_SCOPES))
    debug_data_access_expires_at: int | None = TH_DATA_ACCESS_EXPIRES_AT
    faults: dict[str, str] = field(default_factory=dict)
    fault_queue: dict[str, list[str]] = field(default_factory=dict)
    # Scope named in simulated permission errors (graph_10 / graph_2xx).
    error_permission: str | None = None
    requests: list[RecordedRequest] = field(default_factory=list)
    refresh_hook: Callable[[], None] | None = None
    # Publishing (Feature 011).
    status_script: list[str] = field(default_factory=lambda: ["FINISHED"])
    container_statuses: dict[str, list[str]] = field(default_factory=dict)
    # Form body received for each created container.
    containers: dict[str, dict[str, str]] = field(default_factory=dict)
    # Containers published, in order (one entry per real publication).
    published: list[str] = field(default_factory=list)
    # Post id → container id.
    posts: dict[str, str] = field(default_factory=dict)
    # (quota_usage, quota_total); None answers a shape AutoPublisher cannot read.
    quota: tuple[int, int] | None = (0, 250)
    quota_wrap_data: bool = True
    # False omits `permalink` from the post (as Meta does for flagged media).
    permalinks: bool = True
    create_hook: Callable[[], None] | None = None
    publish_hook: Callable[[], None] | None = None
    post_list_requests: int = 0
    _next_id: int = 100
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_identity(self, **values: Any) -> None:
        self.identity = FakeThreadsIdentity(**values)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def requests_to(self, endpoint: str) -> list[RecordedRequest]:
        url = {
            "code": TH_CODE_URL,
            "long_lived": TH_LONG_LIVED_URL,
            "refresh": TH_REFRESH_URL,
            "debug": TH_DEBUG_URL,
            "me": TH_ME_URL,
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
        if base == TH_CODE_URL and request.method == "POST":
            return self._respond("code", request, lambda: self._code(form))
        if base == TH_LONG_LIVED_URL and request.method == "GET":
            return self._respond("long_lived", request, lambda: self._long(params))
        if base == TH_REFRESH_URL and request.method == "GET":
            if self.refresh_hook is not None:
                self.refresh_hook()
            return self._respond("refresh", request, lambda: self._refresh(params))
        if base == TH_DEBUG_URL and request.method == "GET":
            return self._respond("debug", request, lambda: self._debug(params))
        if base == TH_ME_URL and request.method == "GET":
            return self._respond("me", request, lambda: self._me(params))
        if base.startswith(TH_GRAPH_ROOT + "/"):
            return self._publishing(request, base, form, params)
        raise AssertionError(f"Unexpected request to Threads: {request.method} {base}")

    def _respond(
        self,
        endpoint: str,
        request: httpx.Request,
        success: Callable[[], dict[str, Any] | httpx.Response],
    ) -> httpx.Response:
        fault = self._fault(endpoint)
        if fault is not None:
            return self._fault_response(fault, request)
        result = success()
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result, request=request)

    def _fault_response(self, fault: str, request: httpx.Request) -> httpx.Response:
        if fault == "transport":
            raise httpx.ConnectTimeout("timed out", request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if fault == "server_error":
            return httpx.Response(503, text=FAKE_META_ERROR_TEXT, request=request)
        if fault == "rate_limited":
            return httpx.Response(429, text=FAKE_META_ERROR_TEXT, request=request)
        if fault.startswith("graph_"):
            message = FAKE_META_ERROR_TEXT
            if self.error_permission:
                message += f" ({self.error_permission})"
            return self._graph_error(
                int(fault.removeprefix("graph_")), request, message
            )
        if fault == "link_limit":
            # Meta's documented error name for more than 5 links (2025-12-22).
            return self._graph_error(
                100,
                request,
                f"THREADS_API__LINK_LIMIT_EXCEEDED {FAKE_META_ERROR_TEXT}",
            )
        if fault == "bad_json":
            return httpx.Response(200, text="<html>not json", request=request)
        if fault == "missing_fields":
            return httpx.Response(
                200, json={"unexpected": FAKE_META_ERROR_TEXT}, request=request
            )
        raise AssertionError(f"Unknown fault {fault}")

    @staticmethod
    def _graph_error(code: int, request: httpx.Request, message: str) -> httpx.Response:
        error = {
            "message": message,
            "type": "OAuthException",
            "code": code,
            "fbtrace_id": "AbCdEf",
        }
        return httpx.Response(400, json={"error": error}, request=request)

    def _code(self, form: dict[str, str]) -> dict[str, Any]:
        assert form.get("code") == FAKE_TH_CODE, "unexpected authorization code"
        return {
            "access_token": FAKE_TH_SHORT_TOKEN,
            "token_type": "bearer",
            "user_id": self.exchange_user_id or self.identity.id,
        }

    def _long(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("access_token") == FAKE_TH_SHORT_TOKEN
        return {
            "access_token": FAKE_TH_LONG_TOKEN,
            "token_type": "bearer",
            "expires_in": self.expires_in,
        }

    def _refresh(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("access_token") in {
            FAKE_TH_LONG_TOKEN,
            FAKE_TH_REFRESHED_TOKEN,
        }
        return {
            "access_token": FAKE_TH_REFRESHED_TOKEN,
            "token_type": "bearer",
            "expires_in": self.refreshed_expires_in,
        }

    def _debug(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("input_token") in {
            FAKE_TH_LONG_TOKEN,
            FAKE_TH_REFRESHED_TOKEN,
        }
        assert params.get("access_token") == params.get("input_token")
        data: dict[str, Any] = {"type": "USER", "application": "AutoPublisher"}
        if self.debug_is_valid is not None:
            data["is_valid"] = self.debug_is_valid
        data["user_id"] = self.debug_user_id or self.identity.id
        if self.debug_scopes is not None:
            data["scopes"] = self.debug_scopes
        if self.debug_data_access_expires_at is not None:
            data["data_access_expires_at"] = self.debug_data_access_expires_at
        return {"data": data}

    def _me(self, params: dict[str, str]) -> dict[str, Any]:
        assert params.get("access_token") in {
            FAKE_TH_LONG_TOKEN,
            FAKE_TH_REFRESHED_TOKEN,
        }
        identity = self.identity
        payload: dict[str, Any] = {"id": identity.id, "username": identity.username}
        if identity.name is not None:
            payload["name"] = identity.name
        if identity.threads_profile_picture_url is not None:
            payload["threads_profile_picture_url"] = (
                identity.threads_profile_picture_url
            )
        return payload

    # --- Publishing (Feature 011) ------------------------------------------------

    def requests_for(self, endpoint: str) -> list[RecordedRequest]:
        """Recorded publishing requests: create, status, publish, post, limit."""
        return [
            recorded
            for recorded in self.requests
            if recorded.url.split("?")[0].startswith(TH_GRAPH_ROOT + "/")
            and self._endpoint_of(recorded.method, recorded.url) == endpoint
        ]

    def publish_count(self, container_id: str) -> int:
        """`threads_publish` requests received for one container."""
        return sum(
            1
            for recorded in self.requests_for("publish")
            if recorded.form.get("creation_id") == container_id
        )

    def _endpoint_of(self, method: str, url: str) -> str:
        path = url.split("?")[0].removeprefix(TH_GRAPH_ROOT + "/")
        query = parse_qs(urlsplit(url).query)
        fields = query.get("fields", [""])[0]
        if method == "POST" and path.endswith("/threads_publish"):
            return "publish"
        if method == "POST" and path.endswith("/threads"):
            return "create"
        if method == "GET" and path.endswith("/threads_publishing_limit"):
            return "limit"
        if method == "GET" and path.endswith("/threads"):
            return "post_list"
        if method == "GET" and "status" in fields:
            return "status"
        if method == "GET" and "permalink" in fields:
            return "post"
        return "unknown"

    def _token_ok(self, token: str | None) -> bool:
        return token in {FAKE_TH_LONG_TOKEN, FAKE_TH_REFRESHED_TOKEN}

    def _publishing(
        self,
        request: httpx.Request,
        base: str,
        form: dict[str, str],
        params: dict[str, str],
    ) -> httpx.Response:
        endpoint = self._endpoint_of(request.method, str(request.url))
        path = base.removeprefix(TH_GRAPH_ROOT + "/")
        if request.method == "POST":
            # Parameters (token, text, signed media URL) only travel in the body.
            assert not request.url.query, "POST parameters must not be in the URL"
            assert request.headers.get("content-type", "").startswith(
                "application/x-www-form-urlencoded"
            ), "POST bodies must be form-encoded"
            token = form.get("access_token")
        else:
            token = params.get("access_token")
        assert self._token_ok(token), "unexpected access token"
        if endpoint == "post_list":
            with self._lock:
                self.post_list_requests += 1
            return self._graph_error(100, request, FAKE_META_ERROR_TEXT)
        if endpoint in ("create", "publish", "limit"):
            user_id = path.split("/")[0]
            assert user_id == self.identity.id, "publishing for another user"
        if endpoint == "create":
            if self.create_hook is not None:
                self.create_hook()
            return self._respond("create", request, lambda: self._create(form))
        if endpoint == "status":
            return self._respond("status", request, lambda: self._status(path))
        if endpoint == "publish":
            return self._publish(request, form)
        if endpoint == "post":
            return self._respond("post", request, lambda: self._post(path))
        if endpoint == "limit":
            return self._respond("limit", request, self._limit)
        raise AssertionError(f"Unexpected request to Threads: {request.method} {base}")

    def _create(self, form: dict[str, str]) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            container_id = f"1790000000000{self._next_id}"
            self.containers[container_id] = {
                key: value for key, value in form.items() if key != "access_token"
            }
            self.container_statuses[container_id] = list(self.status_script)
        return {"id": container_id}

    def _status(self, container_id: str) -> dict[str, Any] | httpx.Response:
        with self._lock:
            script = self.container_statuses.get(container_id)
            if not script:
                return httpx.Response(400, json={"error": {"code": 100}}, request=None)
            entry = script.pop(0) if len(script) > 1 else script[0]
        status, _, error_message = entry.partition(":")
        payload: dict[str, Any] = {"id": container_id, "status": status}
        if error_message:
            payload["error_message"] = error_message
        return payload

    def _publish(self, request: httpx.Request, form: dict[str, str]) -> httpx.Response:
        if self.publish_hook is not None:
            self.publish_hook()
        container_id = form.get("creation_id", "")
        fault = self._fault("publish")
        if fault is not None and fault.endswith("_after_publish"):
            self._mark_published(container_id)
            return self._fault_response(fault.removesuffix("_after_publish"), request)
        if fault is not None:
            return self._fault_response(fault, request)
        post_id = self._mark_published(container_id)
        return httpx.Response(200, json={"id": post_id}, request=request)

    def _mark_published(self, container_id: str) -> str:
        with self._lock:
            assert container_id in self.containers, "unknown container"
            self.published.append(container_id)
            self.container_statuses[container_id] = ["PUBLISHED"]
            post_id = f"1800000000000{len(self.published)}"
            self.posts[post_id] = container_id
            return post_id

    def _post(self, post_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": post_id,
            "timestamp": "2026-10-13T10:00:00+0000",
        }
        if self.permalinks:
            payload["permalink"] = (
                f"https://www.threads.com/@cyber.studio/post/{post_id}"
            )
        return payload

    def _limit(self) -> dict[str, Any]:
        if self.quota is None:
            return {"data": []}
        usage, total = self.quota
        item = {
            "quota_usage": usage,
            "config": {"quota_total": total, "quota_duration": 86400},
        }
        return {"data": [item]} if self.quota_wrap_data else item


class StubThreadsGateway:
    """Gateway double that speaks only the semantic classification
    (ThreadsUnavailable, ThreadsTokenInvalid, ...), for service tests that must not
    depend on Meta's error numbers. Every call is counted so tests can assert that
    Meta was not contacted."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock.now
        self.refresh_error: Exception | None = None
        self.debug_error: Exception | None = None
        self.me_error: Exception | None = None
        self.refresh_delay = 0.0
        self.refreshed_expires_in = LONG_LIVED_SECONDS
        self.calls: list[str] = []
        self.debug_info = ThreadsTokenInfo(
            is_valid=True,
            user_id=TH_USER_ID,
            scopes=frozenset(TH_ALL_SCOPES),
            data_access_expires_at=datetime.fromtimestamp(
                TH_DATA_ACCESS_EXPIRES_AT, UTC
            ),
        )
        self.identity = ThreadsIdentity(
            threads_user_id=TH_USER_ID,
            username="cyber.studio",
            display_name="Cyber Studio",
            profile_picture_url="https://scontent.example/th-pic.jpg",
        )

    def refresh(self, token: ThreadsToken) -> ThreadsToken:
        self.calls.append("refresh")
        if self.refresh_delay:
            time.sleep(self.refresh_delay)
        if self.refresh_error is not None:
            raise self.refresh_error
        now = self.clock()
        return ThreadsToken(
            FAKE_TH_REFRESHED_TOKEN,
            now,
            now + timedelta(seconds=self.refreshed_expires_in),
            token.scopes,
        )

    def debug_token(self, access_token: str) -> ThreadsTokenInfo:
        self.calls.append("debug")
        if self.debug_error is not None:
            raise self.debug_error
        return self.debug_info

    def fetch_me(self, access_token: str) -> ThreadsIdentity:
        self.calls.append("me")
        if self.me_error is not None:
            raise self.me_error
        return self.identity


# --- TikTok Login Kit (Feature 012) --------------------------------------------------

TT_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TT_REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
TT_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
TT_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
TT_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TT_INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TT_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
# The upload host is fake on purpose: a real upload URL is never written anywhere.
TT_UPLOAD_BASE = "https://open-upload.tiktokapis.example/upload/"

# Distinctive values so leak tests can search for them anywhere.
FAKE_TT_CODE = "fake-tt-code-6b2e90"
FAKE_TT_ACCESS_TOKEN = "act.fake-tt-access-token-c41d7a"
FAKE_TT_REFRESHED_ACCESS_TOKEN = "act.fake-tt-refreshed-access-token-2f8b64"
FAKE_TT_REFRESH_TOKEN = "rft.fake-tt-refresh-token-93f0b1"
FAKE_TT_ROTATED_REFRESH_TOKEN = "rft.fake-tt-rotated-refresh-token-5a7c12"
FAKE_TT_CLIENT_SECRET = "fake-tt-client-secret-d81e4f"
FAKE_TT_CLIENT_KEY = "sbawfakettclientkey"
FAKE_TT_OPEN_ID = "-000fake-tt-open-id-7d1c3e"
FAKE_TT_LOG_ID = "202610140000000000FAKELOGID"
# Text placed in every simulated TikTok error; it must never reach the user.
FAKE_TT_ERROR_TEXT = "raw-tiktok-error-text-5e2a"
FAKE_TT_REDIRECT_URI = "http://127.0.0.1:8000/api/tiktok/oauth/callback"

# Recognisable parts of the fake upload URL, searched for by the leak tests.
FAKE_TT_UPLOAD_ID = "fake-tt-upload-id-0c7e55"
FAKE_TT_UPLOAD_TOKEN = "SECRET-fake-tt-upload-token-91ad3f"
FAKE_TT_PUBLISH_ID_PREFIX = "v_pub_file~v2-fake."

TT_BASIC = "user.info.basic"
TT_PUBLISH = "video.publish"
TT_UPLOAD = "video.upload"
# Scopes requested by Connect / Reconnect since Feature 014.
TT_ALL_SCOPES = f"{TT_BASIC},{TT_PUBLISH},{TT_UPLOAD}"
TT_ACCESS_SECONDS = 86400
TT_REFRESH_SECONDS = 31536000


def tiktok_app_config_json(redirect_uri: str | None = None, **overrides: Any) -> str:
    data: dict[str, Any] = {
        "client_key": FAKE_TT_CLIENT_KEY,
        "client_secret": FAKE_TT_CLIENT_SECRET,
    }
    if redirect_uri is not None:
        data["redirect_uri"] = redirect_uri
    data.update(overrides)
    return json.dumps(data)


def tiktok_creator_info(**overrides: Any) -> dict[str, Any]:
    """The `data` of a valid Creator Info answer for a private account."""
    data: dict[str, Any] = {
        "creator_avatar_url": "https://p16-sign.tiktokcdn.example/creator.jpeg",
        "creator_username": "cyber.studio",
        "creator_nickname": "Cyber Studio",
        "privacy_level_options": [
            "FOLLOWER_OF_CREATOR",
            "MUTUAL_FOLLOW_FRIENDS",
            "SELF_ONLY",
        ],
        "comment_disabled": False,
        "duet_disabled": True,
        "stitch_disabled": True,
        "max_video_post_duration_sec": 600,
    }
    data.update(overrides)
    return data


@dataclass
class UploadAction:
    """How the fake answers one `PUT` of the upload URL.

    `status`: HTTP status to answer (None: the default 206/201); `content_range`:
    "auto" adds `bytes 0-{received}/{total}` like the real TikTok (V2: the second
    number is the count of accepted bytes, not the last byte), None omits it, any
    other string is sent as is; `store`: whether the bytes are kept (TikTok
    received them).
    `raise_`: "transport" (connection error), "timeout" (no answer) or "lost" (the
    bytes are kept, then the answer is lost).
    """

    status: int | None = None
    content_range: str | None = "auto"
    store: bool = True
    raise_: str | None = None


@dataclass
class FakeTikTok:
    """Programmable TikTok OAuth, user info and Content Posting endpoints served via
    httpx MockTransport.

    Endpoints: "exchange" (token, `authorization_code`), "refresh" (token,
    `refresh_token`), "revoke", "user_info", "creator_info", "init" (Direct Post),
    "inbox_init" (Upload to Inbox), "upload" (`PUT` to the fake upload host) and
    "status". `faults` maps an endpoint to a fault;
    `fault_queue` holds one-shot faults per endpoint, used before `faults`. Faults:
    transport | timeout | server_error | rate_limited | oauth_<code> (OAuth error
    body, HTTP 400) | oauth200_<code> (OAuth error body with HTTP 200) | api_<code> (v2
    API error object) | api200_<code> (v2 API error object with HTTP 200) | bad_json |
    missing_fields | bad_token_type | empty_object (answers `{}`) | empty_body
    (answers 200 without a body).

    The exchange checks the hex SHA-256 of `code_verifier` against the challenges
    registered with `register_challenge` and answers `invalid_grant` on a mismatch.
    `user_open_id` makes user/info report another `open_id` ("" omits it). Every POST
    must carry its parameters in the form body only: a query string fails the test.
    `scope` / `refresh_scope` are the scopes granted by the exchange / refresh (the
    three requested scopes by default; `refresh_scope` None repeats `scope`).

    Publishing: `creator_info_data` is the `data` of Creator Info (`creator_info_queue`
    gives one-shot payloads first); `init` and `inbox_init` answer a new `publish_id`
    and the fake upload URL (`init_data` replaces its `data`; their bodies are kept in
    `requests`, see `init_bodies` / `inbox_init_bodies`); each `PUT` follows
    `upload_actions` (one-shot, in order), else 206/201 depending on whether all bytes
    were received; a `PUT` whose first byte is not the next expected one answers 416.
    `statuses` are the `data` of successive status reads (the last one repeats; a
    string entry is a fault), e.g. `{"status": "SEND_TO_USER_INBOX"}`. Upload to Inbox
    errors use the generic faults (`api_spam_risk_too_many_pending_share` answers 403,
    `api_scope_not_authorized` 401). `hooks[endpoint]` runs inside the request (e.g. to
    read the database).
    Any other request is recorded in `unexpected` and fails the request.
    """

    open_id: str = FAKE_TT_OPEN_ID
    user_open_id: str | None = None
    display_name: str | None = "Cyber Studio"
    avatar_url: str | None = "https://p16-sign.tiktokcdn.example/avatar.jpeg"
    scope: str = TT_ALL_SCOPES
    refresh_scope: str | None = None
    refresh_open_id: str | None = None
    expires_in: int = TT_ACCESS_SECONDS
    refresh_expires_in: int = TT_REFRESH_SECONDS
    rotate_refresh_token: bool = True
    faults: dict[str, str] = field(default_factory=dict)
    fault_queue: dict[str, list[str]] = field(default_factory=dict)
    challenges: set[str] = field(default_factory=set)
    requests: list[RecordedRequest] = field(default_factory=list)
    refresh_hook: Callable[[], None] | None = None
    # Refresh token TikTok currently accepts.
    valid_refresh_token: str = FAKE_TT_REFRESH_TOKEN
    # --- Content Posting API ---
    creator_info_data: dict[str, Any] = field(default_factory=tiktok_creator_info)
    creator_info_queue: list[dict[str, Any]] = field(default_factory=list)
    init_data: dict[str, Any] | None = None
    upload_actions: list[UploadAction] = field(default_factory=list)
    statuses: list[dict[str, Any] | str] = field(
        default_factory=lambda: [
            {"status": "PROCESSING_UPLOAD"},
            {"status": "PUBLISH_COMPLETE"},
        ]
    )
    hooks: dict[str, Callable[[httpx.Request], None]] = field(default_factory=dict)
    unexpected: list[str] = field(default_factory=list)
    # Upload state of the current publish_id.
    published_ids: list[str] = field(default_factory=list)
    received: int = 0
    upload_total: int | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def register_challenge(self, challenge: str) -> None:
        self.challenges.add(challenge)

    def _endpoint(self, request: RecordedRequest) -> str:
        base = request.url.split("?")[0]
        if base.startswith(TT_USER_INFO_URL):
            return "user_info"
        if base == TT_REVOKE_URL:
            return "revoke"
        if base == TT_CREATOR_INFO_URL:
            return "creator_info"
        if base == TT_VIDEO_INIT_URL:
            return "init"
        if base == TT_INBOX_INIT_URL:
            return "inbox_init"
        if base == TT_STATUS_URL:
            return "status"
        if base == TT_UPLOAD_BASE:
            return "upload"
        if base == TT_TOKEN_URL:
            if request.form.get("grant_type") == "authorization_code":
                return "exchange"
            return "refresh"
        return "unknown"

    def requests_to(self, endpoint: str) -> list[RecordedRequest]:
        return [r for r in self.requests if self._endpoint(r) == endpoint]

    def calls(self) -> list[str]:
        """Endpoints called, in order."""
        return [self._endpoint(r) for r in self.requests]

    def _fault(self, endpoint: str) -> str | None:
        with self._lock:
            queue = self.fault_queue.get(endpoint)
            if queue:
                return queue.pop(0)
        return self.faults.get(endpoint)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        base = url.split("?")[0]
        body = request.content.decode(errors="replace") if request.content else ""
        is_form = "x-www-form-urlencoded" in request.headers.get("content-type", "")
        form = (
            {key: values[0] for key, values in parse_qs(body).items()}
            if is_form
            else {}
        )
        with self._lock:
            self.requests.append(
                RecordedRequest(
                    request.method, url, form, dict(request.headers), request.content
                )
            )
        if request.method == "POST":
            assert "?" not in url, "TikTok POSTs must not carry a query string"
        if base == TT_TOKEN_URL and request.method == "POST":
            grant = form.get("grant_type")
            if grant == "authorization_code":
                return self._respond("exchange", request, lambda: self._exchange(form))
            if grant == "refresh_token":
                if self.refresh_hook is not None:
                    self.refresh_hook()
                return self._respond("refresh", request, lambda: self._refresh(form))
            raise AssertionError(f"Unexpected grant_type {grant}")
        if base == TT_REVOKE_URL and request.method == "POST":
            return self._respond("revoke", request, lambda: self._revoke(form))
        if base == TT_USER_INFO_URL and request.method == "GET":
            return self._respond("user_info", request, lambda: self._user_info(request))
        if base == TT_CREATOR_INFO_URL and request.method == "POST":
            return self._respond(
                "creator_info", request, lambda: self._creator_info(request)
            )
        if base == TT_VIDEO_INIT_URL and request.method == "POST":
            return self._respond("init", request, lambda: self._init(request))
        if base == TT_INBOX_INIT_URL and request.method == "POST":
            return self._respond("inbox_init", request, lambda: self._init(request))
        if base == TT_STATUS_URL and request.method == "POST":
            return self._respond("status", request, lambda: self._status(request))
        if base == TT_UPLOAD_BASE and request.method == "PUT":
            self._run_hook("upload", request)
            return self._upload(request)
        with self._lock:
            self.unexpected.append(f"{request.method} {base}")
        raise AssertionError(f"Unexpected request to TikTok: {request.method} {base}")

    def _run_hook(self, endpoint: str, request: httpx.Request) -> None:
        hook = self.hooks.get(endpoint)
        if hook is not None:
            hook(request)

    def _respond(
        self,
        endpoint: str,
        request: httpx.Request,
        success: Callable[[], dict[str, Any] | httpx.Response],
    ) -> httpx.Response:
        self._run_hook(endpoint, request)
        fault = self._fault(endpoint)
        if fault is not None:
            return self._fault_response(fault, request)
        result = success()
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result, request=request)

    @staticmethod
    def _oauth_error(code: str, request: httpx.Request, status: int) -> httpx.Response:
        body = {
            "error": code,
            "error_description": FAKE_TT_ERROR_TEXT,
            "log_id": FAKE_TT_LOG_ID,
        }
        return httpx.Response(status, json=body, request=request)

    @staticmethod
    def _api_error(
        code: str, request: httpx.Request, status: int | None = None
    ) -> httpx.Response:
        if status is None:
            status = (
                401 if code in ("access_token_invalid", "scope_not_authorized") else 400
            )
            if code == "rate_limit_exceeded":
                status = 429
            if code in (
                "spam_risk_too_many_posts",
                "spam_risk_too_many_pending_share",
                "spam_risk_user_banned_from_posting",
                "reached_active_user_cap",
                "unaudited_client_can_only_post_to_private_accounts",
                "url_ownership_unverified",
                "privacy_level_option_mismatch",
            ):
                status = 403
            if code == "internal_error":
                status = 500
        body = {
            "data": {},
            "error": {
                "code": code,
                "message": FAKE_TT_ERROR_TEXT,
                "log_id": FAKE_TT_LOG_ID,
            },
        }
        return httpx.Response(status, json=body, request=request)

    def _fault_response(self, fault: str, request: httpx.Request) -> httpx.Response:
        if fault == "transport":
            raise httpx.ConnectTimeout("timed out", request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if fault == "server_error":
            return httpx.Response(503, text=FAKE_TT_ERROR_TEXT, request=request)
        if fault == "rate_limited":
            return httpx.Response(429, text=FAKE_TT_ERROR_TEXT, request=request)
        if fault.startswith("oauth200_"):
            return self._oauth_error(fault.removeprefix("oauth200_"), request, 200)
        if fault.startswith("oauth_"):
            return self._oauth_error(fault.removeprefix("oauth_"), request, 400)
        if fault.startswith("api200_"):
            return self._api_error(fault.removeprefix("api200_"), request, 200)
        if fault.startswith("api_"):
            return self._api_error(fault.removeprefix("api_"), request)
        if fault == "bad_json":
            return httpx.Response(200, text="<html>not json", request=request)
        if fault == "missing_fields":
            return httpx.Response(
                200, json={"unexpected": FAKE_TT_ERROR_TEXT}, request=request
            )
        if fault == "bad_token_type":
            payload = self._token_payload(FAKE_TT_ACCESS_TOKEN, FAKE_TT_REFRESH_TOKEN)
            payload["token_type"] = "mac"
            return httpx.Response(200, json=payload, request=request)
        if fault == "empty_object":
            return httpx.Response(200, json={}, request=request)
        if fault == "empty_body":
            return httpx.Response(200, request=request)
        raise AssertionError(f"Unknown fault {fault}")

    def _token_payload(
        self,
        access_token: str,
        refresh_token: str,
        scope: str | None = None,
        open_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "access_token": access_token,
            "expires_in": self.expires_in,
            "open_id": open_id or self.open_id,
            "refresh_expires_in": self.refresh_expires_in,
            "refresh_token": refresh_token,
            "scope": scope if scope is not None else self.scope,
            "token_type": "Bearer",
        }

    def _exchange(self, form: dict[str, str]) -> dict[str, Any] | httpx.Response:
        verifier = form.get("code_verifier", "")
        challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
        if form.get("code") != FAKE_TT_CODE or challenge not in self.challenges:
            return self._oauth_error("invalid_grant", httpx.Request("POST", ""), 400)
        return self._token_payload(FAKE_TT_ACCESS_TOKEN, FAKE_TT_REFRESH_TOKEN)

    def _refresh(self, form: dict[str, str]) -> dict[str, Any] | httpx.Response:
        if form.get("refresh_token") != self.valid_refresh_token:
            return self._oauth_error("invalid_grant", httpx.Request("POST", ""), 400)
        if self.rotate_refresh_token:
            self.valid_refresh_token = FAKE_TT_ROTATED_REFRESH_TOKEN
        return self._token_payload(
            FAKE_TT_REFRESHED_ACCESS_TOKEN,
            self.valid_refresh_token,
            scope=self.refresh_scope,
            open_id=self.refresh_open_id,
        )

    def _revoke(self, form: dict[str, str]) -> httpx.Response:
        assert form.get("token") in {
            FAKE_TT_ACCESS_TOKEN,
            FAKE_TT_REFRESHED_ACCESS_TOKEN,
        }
        # The real Sandbox answers a successful revocation with `200 {}` (V-5).
        return httpx.Response(
            200, json={}, request=httpx.Request("POST", TT_REVOKE_URL)
        )

    def _user_info(self, request: httpx.Request) -> dict[str, Any] | httpx.Response:
        authorization = request.headers.get("authorization", "")
        if authorization not in {
            f"Bearer {FAKE_TT_ACCESS_TOKEN}",
            f"Bearer {FAKE_TT_REFRESHED_ACCESS_TOKEN}",
        }:
            return self._api_error("access_token_invalid", request)
        user: dict[str, Any] = {
            "display_name": self.display_name or "",
            "avatar_url": self.avatar_url or "",
        }
        open_id = self.open_id if self.user_open_id is None else self.user_open_id
        if open_id:
            user["open_id"] = open_id
        return {
            "data": {"user": user},
            "error": {"code": "ok", "message": "", "log_id": FAKE_TT_LOG_ID},
        }

    # --- Content Posting API ------------------------------------------------------

    def _authorized(self, request: httpx.Request) -> bool:
        return request.headers.get("authorization", "") in {
            f"Bearer {FAKE_TT_ACCESS_TOKEN}",
            f"Bearer {FAKE_TT_REFRESHED_ACCESS_TOKEN}",
        }

    @staticmethod
    def _ok(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "data": data,
            "error": {"code": "ok", "message": "", "log_id": FAKE_TT_LOG_ID},
        }

    def _creator_info(self, request: httpx.Request) -> dict[str, Any] | httpx.Response:
        if not self._authorized(request):
            return self._api_error("access_token_invalid", request)
        with self._lock:
            data = (
                self.creator_info_queue.pop(0)
                if self.creator_info_queue
                else self.creator_info_data
            )
        return self._ok(data)

    def _init(self, request: httpx.Request) -> dict[str, Any] | httpx.Response:
        if not self._authorized(request):
            return self._api_error("access_token_invalid", request)
        body = json.loads(request.content)
        with self._lock:
            publish_id = f"{FAKE_TT_PUBLISH_ID_PREFIX}{len(self.published_ids) + 1}"
            self.published_ids.append(publish_id)
            self.received = 0
            self.upload_total = body.get("source_info", {}).get("video_size")
        data = self.init_data
        if data is None:
            data = {
                "publish_id": publish_id,
                "upload_url": (
                    f"{TT_UPLOAD_BASE}?upload_id={FAKE_TT_UPLOAD_ID}"
                    f"&upload_token={FAKE_TT_UPLOAD_TOKEN}"
                ),
            }
        return self._ok(data)

    def init_bodies(self) -> list[dict[str, Any]]:
        """JSON bodies of every `video/init/` request."""
        return [json.loads(r.content) for r in self.requests_to("init")]

    def inbox_init_bodies(self) -> list[dict[str, Any]]:
        """JSON bodies of every `inbox/video/init/` request."""
        return [json.loads(r.content) for r in self.requests_to("inbox_init")]

    def _upload(self, request: httpx.Request) -> httpx.Response:
        content_range = request.headers.get("content-range", "")
        first, last, total = _parse_content_range(content_range)
        with self._lock:
            action = self.upload_actions.pop(0) if self.upload_actions else None
        action = action or UploadAction()
        if action.raise_ == "transport":
            raise httpx.ConnectError("connection failed", request=request)
        if action.raise_ == "timeout":
            raise httpx.WriteTimeout("timed out", request=request)
        expected = first == self.received and last - first + 1 == len(request.content)
        if action.store and expected:
            with self._lock:
                self.received = last + 1
        if action.raise_ == "lost":
            raise httpx.ReadTimeout("timed out", request=request)
        status = action.status
        if status is None:
            if not expected:
                status = 416
            else:
                status = 201 if self.received == total else 206
        headers: dict[str, str] = {}
        if action.content_range == "auto":
            if self.received:
                headers["Content-Range"] = f"bytes 0-{self.received}/{total}"
        elif action.content_range is not None:
            headers["Content-Range"] = action.content_range
        return httpx.Response(
            status, headers=headers, text=FAKE_TT_ERROR_TEXT, request=request
        )

    def _status(self, request: httpx.Request) -> dict[str, Any] | httpx.Response:
        if not self._authorized(request):
            return self._api_error("access_token_invalid", request)
        body = json.loads(request.content)
        if body.get("publish_id") not in self.published_ids:
            return self._api_error("invalid_publish_id", request)
        with self._lock:
            entry = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if isinstance(entry, str):
            return self._fault_response(entry, request)
        # V1: the real PUBLISH_COMPLETE answer carried no `uploaded_bytes`.
        data = dict(entry)
        if entry.get("status") != "PUBLISH_COMPLETE":
            data = {"uploaded_bytes": self.received, **entry}
        return self._ok(data)


def _parse_content_range(value: str) -> tuple[int, int, int]:
    """`bytes first-last/total` of an upload request (fails the test otherwise)."""
    assert value.startswith("bytes "), value
    span, _, total = value.removeprefix("bytes ").partition("/")
    first, _, last = span.partition("-")
    return int(first), int(last), int(total)
