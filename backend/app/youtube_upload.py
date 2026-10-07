"""YouTube resumable upload protocol (research.md §3–§5).

The session URI identifies the upload and lets anyone holding it continue it: it only
ever lives in local variables of the upload thread, never in logs, the database or
API responses.
"""

import random
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, BinaryIO

import httpx2 as httpx

from app.publishing import ProgressReporter, PublishFailure

MIB = 1024 * 1024
KIB = 1024


@dataclass(frozen=True)
class YouTubeUploadSettings:
    """Upload tuning that only makes sense for YouTube; injected by `main.py`."""

    # Chunks must be multiples of 256 KiB except the last one.
    chunk_size: int = 8 * MIB
    # Bytes read from disk at a time while streaming a chunk.
    slice_size: int = 256 * KIB
    max_consecutive_failures: int = 6
    max_backoff: float = 32.0
    # A longer Retry-After stops the attempt instead of waiting (research.md §4).
    max_retry_wait: float = 60.0
    sleep: Callable[[float], None] = time.sleep


UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
SESSION_PREFIX = UPLOAD_ENDPOINT + "?"
VIDEO_URL = "https://www.youtube.com/watch?v={}"
UPLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_RANGE = re.compile(r"^bytes=0-(\d+)$")

# Receives `force_refresh` and returns a valid access token, or raises TokenError.
TokenProvider = Callable[[bool], str]

RECOVERABLE_STATUSES = {429, 500, 502, 503, 504}
RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
# Error reasons of videos.insert mapped to safe codes (research.md §6).
REASON_CODES = {
    "invalidTitle": "invalid_metadata",
    "invalidDescription": "invalid_metadata",
    "invalidVideoMetadata": "invalid_metadata",
    "invalidCategoryId": "invalid_metadata",
    "invalidFilename": "invalid_metadata",
    "mediaBodyRequired": "invalid_metadata",
    "uploadLimitExceeded": "upload_limit_exceeded",
    "quotaExceeded": "quota_exceeded",
    "dailyLimitExceeded": "quota_exceeded",
    "forbidden": "permission_denied",
    "insufficientPermissions": "permission_denied",
    "forbiddenPrivacySetting": "permission_denied",
    "forbiddenLicenseSetting": "permission_denied",
    "youtubeSignupRequired": "permission_denied",
}

# Fixed messages: the text of Google's responses is never shown or stored.
MESSAGES = {
    "reconnect_required": (
        "YouTube no longer accepts the stored credentials. Reconnect the channel and "
        "publish again."
    ),
    "media_unavailable": "The media file changed or disappeared during the upload.",
    "invalid_metadata": "YouTube rejected the title, description or settings.",
    "permission_denied": (
        "YouTube did not allow this upload. Check the channel's permissions and "
        "settings."
    ),
    "quota_exceeded": (
        "The YouTube API quota of AutoPublisher's Google project is used up. Try "
        "again after it resets."
    ),
    "upload_limit_exceeded": (
        "The channel reached its YouTube upload limit. Try again later."
    ),
    "youtube_rejected": "YouTube rejected the upload.",
    "youtube_unavailable": (
        "YouTube is temporarily unavailable. Try publishing again later."
    ),
    "network_error": (
        "The connection to YouTube was lost. Try publishing again when the network "
        "is back."
    ),
    "upload_session_expired": (
        "The YouTube upload session expired before the video was complete."
    ),
    "unexpected_response": "YouTube answered in an unexpected way.",
    "credential_store_unavailable": (
        "The system's secure credential storage is not available."
    ),
    "oauth_not_configured": "YouTube integration is not configured.",
    "internal_error": (
        "AutoPublisher could not save the upload progress, so the last part was not "
        "sent and nothing was published."
    ),
    "interrupted": (
        "The upload was interrupted because AutoPublisher stopped. Nothing is "
        "retried automatically."
    ),
}
# Added when the last part may have reached YouTube (research.md §5).
REVIEW_SUFFIX = (
    " The last part of the video may have reached YouTube: check YouTube Studio "
    "(channel, title and time of the attempt) before publishing again."
)


def open_media(path: Path) -> BinaryIO:
    """Open the stored file read-only; it is never modified or copied."""
    return path.open("rb")


def video_url(video_id: str) -> str:
    return VIDEO_URL.format(video_id)


@dataclass(frozen=True)
class UploadRequest:
    file_path: Path
    total_bytes: int
    mime_type: str
    # The `video` resource (snippet + status) sent when the session starts.
    resource: dict[str, Any]
    notify_subscribers: bool


class TokenError(Exception):
    """Credentials could not be obtained; `recoverable` for transient causes."""

    def __init__(self, code: str, *, recoverable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.recoverable = recoverable


class _ShortRead(Exception):
    pass


class _Stopped(Exception):
    pass


class _Retry(Exception):
    """A recoverable failure; the caller waits and tries again."""

    def __init__(self, code: str, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def _reason(response: httpx.Response) -> str | None:
    """Only the error reason is read from Google's answer, never its message."""
    try:
        errors = response.json()["error"]["errors"]
        reason = errors[0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return reason if isinstance(reason, str) else None


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Seconds requested by a `Retry-After` header; None if absent or unusable."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        seconds = float(value)
    else:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if moment.tzinfo is None:
            return None
        seconds = (moment - now).total_seconds()
    return seconds if seconds > 0 else None


class ResumableUpload:
    """One upload session; every resume stays in the same publication attempt."""

    def __init__(self, client: httpx.Client, settings: YouTubeUploadSettings) -> None:
        self.client = client
        self.settings = settings

    def run(
        self,
        request: UploadRequest,
        reporter: ProgressReporter,
        token_provider: TokenProvider,
    ) -> dict[str, Any]:
        """Upload the file and return YouTube's `video` resource with a valid id."""
        self.request = request
        self.reporter = reporter
        self.token_provider = token_provider
        # True from the commit of `final_chunk` until YouTube says it is incomplete.
        self.final = False
        self.failures = 0
        self.confirmed = 0
        session_uri = self._retrying(self._start_session)
        reporter.report_bytes(0, confirmed=True)
        offset = 0
        with open_media(request.file_path) as media:
            while True:
                if reporter.should_stop():
                    raise self._failure("interrupted")
                end = min(offset + self.settings.chunk_size, request.total_bytes)
                if end == request.total_bytes and not self.final:
                    # Write-ahead: the last byte is only sent once this is committed.
                    if not reporter.enter_final_chunk():
                        raise self._failure("internal_error")
                    self.final = True
                try:
                    response = self._send_chunk(session_uri, media, offset, end)
                    resource = self._handle_upload_response(response)
                except _Retry as retry:
                    self._wait(retry)
                    resource = self._retrying(
                        lambda: self._handle_upload_response(
                            self._query_status(session_uri)
                        )
                    )
                if isinstance(resource, dict):
                    return resource
                offset = resource

    # --- Retrying ------------------------------------------------------------------

    def _retrying[T](self, operation: Callable[[], T]) -> T:
        while True:
            try:
                return operation()
            except _Retry as retry:
                self._wait(retry)

    def _wait(self, retry: _Retry) -> None:
        """Count a recoverable failure and wait before trying again (research §4)."""
        self.failures += 1
        if self.failures >= self.settings.max_consecutive_failures:
            raise self._failure(retry.code)
        if retry.retry_after is not None and retry.retry_after > (
            self.settings.max_retry_wait
        ):
            raise self._failure(retry.code)
        base = min(self.settings.max_backoff, 2.0 ** (self.failures - 1))
        backoff = min(self.settings.max_backoff, base * (1 + random.uniform(0, 0.2)))
        self.settings.sleep(max(backoff, retry.retry_after or 0))

    def _progress(self, offset: int) -> None:
        if offset > self.confirmed:
            self.confirmed = offset
            self.failures = 0

    # --- Requests ------------------------------------------------------------------

    def _token(self, force_refresh: bool) -> str:
        try:
            return self.token_provider(force_refresh)
        except TokenError as error:
            if error.recoverable:
                raise _Retry("network_error") from None
            raise self._failure(error.code) from None

    def _call(self, send: Callable[[str], httpx.Response]) -> httpx.Response:
        """Send with a valid token; a 401 refreshes it once and repeats."""
        try:
            response = send(self._token(False))
            if response.status_code == 401:
                response = send(self._token(True))
                if response.status_code == 401:
                    raise self._failure("reconnect_required")
        except httpx.TransportError:
            raise _Retry("network_error") from None
        return response

    def _start_session(self) -> str:
        request = self.request

        def send(token: str) -> httpx.Response:
            return self.client.post(
                UPLOAD_ENDPOINT,
                params={
                    "uploadType": "resumable",
                    "part": "snippet,status",
                    "notifySubscribers": (
                        "true" if request.notify_subscribers else "false"
                    ),
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Upload-Content-Length": str(request.total_bytes),
                    "X-Upload-Content-Type": request.mime_type,
                },
                json=request.resource,
                timeout=UPLOAD_TIMEOUT,
            )

        response = self._call(send)
        if response.status_code != 200:
            raise self._error(response, session=False)
        location = response.headers.get("Location", "")
        # The token is only ever sent to YouTube's own upload endpoint.
        if not location.startswith(SESSION_PREFIX):
            raise self._failure("unexpected_response")
        return location

    def _send_chunk(
        self, session_uri: str, media: BinaryIO, start: int, end: int
    ) -> httpx.Response:
        def send(token: str) -> httpx.Response:
            media.seek(start)
            return self.client.put(
                session_uri,
                content=self._read(media, start, end),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Length": str(end - start),
                    "Content-Type": self.request.mime_type,
                    "Content-Range": (
                        f"bytes {start}-{end - 1}/{self.request.total_bytes}"
                    ),
                },
                timeout=UPLOAD_TIMEOUT,
            )

        try:
            return self._call(send)
        except _ShortRead:
            raise self._failure("media_unavailable") from None
        except _Stopped:
            raise self._failure("interrupted") from None

    def _query_status(self, session_uri: str) -> httpx.Response:
        """Ask YouTube how much of the file it has (empty PUT, `bytes */TOTAL`)."""

        def send(token: str) -> httpx.Response:
            return self.client.put(
                session_uri,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Length": "0",
                    "Content-Range": f"bytes */{self.request.total_bytes}",
                },
                timeout=UPLOAD_TIMEOUT,
            )

        return self._call(send)

    def _read(self, media: BinaryIO, start: int, end: int) -> Iterator[bytes]:
        """Stream the chunk from disk, one slice at a time."""
        position = start
        while position < end:
            if self.reporter.should_stop():
                raise _Stopped
            piece = media.read(min(self.settings.slice_size, end - position))
            if not piece:
                raise _ShortRead
            position += len(piece)
            self.reporter.report_bytes(position)
            yield piece

    # --- Responses -----------------------------------------------------------------

    def _handle_upload_response(self, response: httpx.Response) -> dict[str, Any] | int:
        """The final resource, or the next byte to send."""
        if response.status_code in (200, 201):
            return self._finish(response)
        if response.status_code == 308:
            return self._confirmed(response)
        raise self._error(response, session=True)

    def _error(self, response: httpx.Response, *, session: bool) -> Exception:
        status = response.status_code
        reason = _reason(response)
        if status in RECOVERABLE_STATUSES or (
            status == 403 and reason in RATE_LIMIT_REASONS
        ):
            now = datetime.now(UTC)
            retry_after = parse_retry_after(response.headers.get("Retry-After"), now)
            return _Retry("youtube_unavailable", retry_after)
        if session and status in (404, 410):
            return self._failure("upload_session_expired")
        if reason in REASON_CODES:
            return self._failure(REASON_CODES[reason])
        if 400 <= status < 500:
            return self._failure("youtube_rejected")
        return self._failure("unexpected_response")

    def _confirmed(self, response: httpx.Response) -> int:
        """Next byte to send according to YouTube (`Range: bytes=0-N`)."""
        header = response.headers.get("Range")
        if header is None:
            offset = 0
        else:
            match = _RANGE.match(header)
            if match is None:
                raise self._failure("unexpected_response")
            offset = int(match.group(1)) + 1
        if offset > self.request.total_bytes:
            raise self._failure("unexpected_response")
        if self.final and offset < self.request.total_bytes:
            # YouTube confirms it does not have the whole file: not ambiguous.
            self.reporter.leave_final_chunk()
            self.final = False
        self._progress(offset)
        self.reporter.report_bytes(offset, confirmed=True)
        return offset

    def _finish(self, response: httpx.Response) -> dict[str, Any]:
        try:
            resource = response.json()
        except ValueError:
            resource = None
        if not isinstance(resource, dict):
            raise self._failure("unexpected_response")
        video_id = resource.get("id")
        if not isinstance(video_id, str) or not _VIDEO_ID.match(video_id):
            raise self._failure("unexpected_response")
        return resource

    def _failure(self, code: str) -> PublishFailure:
        """A failure is ambiguous only once the last part may have reached YouTube."""
        determined = not self.final
        message = MESSAGES[code] + ("" if determined else REVIEW_SUFFIX)
        return PublishFailure(code, message, determined=determined)
