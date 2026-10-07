"""YouTube publisher: options, metadata, preflight and upload (see contracts/api.md).

Everything YouTube-specific about running a publication lives here; the generic core
in `app.publishing` only talks to `YouTubePublisher` through the `Publisher`
protocol. Its own dependencies (Google gateway, credential store and upload settings)
are given by `main.py`.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.contents import file_available
from app.credential_store import CredentialStore
from app.db import get_session, utc_now
from app.errors import AppError, ConflictError
from app.models import (
    Account,
    Content,
    MediaType,
    Platform,
    Publication,
    PublicationStatus,
    YouTubeConnectionStatus,
    YouTubePrivacy,
    YouTubePublicationOptions,
)
from app.publications import ensure_editable, get_publication_or_404
from app.publishing import (
    PreparedPublication,
    ProgressReporter,
    PublishCheck,
    PublishContext,
    PublishFailure,
    PublishOutcome,
    PublishProblem,
)
from app.schemas import YouTubePublicationOptionsRead, YouTubePublicationOptionsWrite
from app.youtube_connections import (
    NOT_CONFIGURED_MESSAGE,
    get_connection,
    get_valid_credentials,
    list_channels,
    mark_reconnect_required,
    oauth_configured,
)
from app.youtube_gateway import GoogleGateway
from app.youtube_upload import (
    ResumableUpload,
    TokenError,
    UploadRequest,
    YouTubeUploadSettings,
    video_url,
)

router = APIRouter(prefix="/api", tags=["youtube"])

SessionDep = Annotated[Session, Depends(get_session)]

TITLE_MAX_CHARACTERS = 100
DESCRIPTION_MAX_BYTES = 5000
# YouTube rejects these characters in titles and descriptions.
FORBIDDEN_CHARACTERS = ("<", ">")
MIME_TYPES = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm"}
# Non-sensitive values copied from the uploaded video resource.
RESOURCE_STATUS_KEYS = (
    ("privacy_status", "privacyStatus"),
    ("upload_status", "uploadStatus"),
)
EDITABLE_STATUSES = (
    PublicationStatus.UNSCHEDULED,
    PublicationStatus.SCHEDULED,
    PublicationStatus.FAILED,
)


# --- Metadata ----------------------------------------------------------------------


def build_description(description: str | None, hashtags: list[str]) -> str:
    """Effective description, then a blank line and the hashtags as `#a #b`."""
    tags = " ".join(f"#{tag}" for tag in hashtags)
    parts = [part for part in (description or "", tags) if part]
    return "\n\n".join(parts)


def validate_metadata(title: str | None, description: str) -> list[PublishProblem]:
    """Problems YouTube would reject, found before any upload session exists."""
    problems: list[PublishProblem] = []

    def problem(field: str, message: str) -> None:
        problems.append(PublishProblem("invalid_metadata", message, field))

    clean_title = (title or "").strip()
    if not clean_title:
        problem("title", "Add a title: YouTube requires one.")
    elif len(clean_title) > TITLE_MAX_CHARACTERS:
        problem(
            "title",
            f"The title must be at most {TITLE_MAX_CHARACTERS} characters for YouTube.",
        )
    elif any(char in clean_title for char in FORBIDDEN_CHARACTERS):
        problem("title", "YouTube does not accept < or > in the title.")
    if len(description.encode("utf-8")) > DESCRIPTION_MAX_BYTES:
        problem(
            "description",
            f"The description and hashtags must be at most {DESCRIPTION_MAX_BYTES} "
            "bytes for YouTube.",
        )
    elif any(char in description for char in FORBIDDEN_CHARACTERS):
        problem("description", "YouTube does not accept < or > in the description.")
    return problems


def build_resource(
    *,
    title: str,
    description: str,
    privacy_status: str,
    made_for_kids: bool,
    contains_synthetic_media: bool,
) -> dict[str, Any]:
    """The `video` resource sent when the upload session starts. No tags, category
    or publishAt (research.md §12)."""
    return {
        "snippet": {"title": title, "description": description},
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
            "containsSyntheticMedia": contains_synthetic_media,
        },
    }


def _effective_metadata(
    publication: Publication, content: Content
) -> tuple[str | None, str | None, list[str]]:
    title = (
        publication.title_override
        if publication.title_override is not None
        else content.title
    )
    description = (
        publication.description_override
        if publication.description_override is not None
        else content.description
    )
    hashtags = (
        publication.hashtags_override
        if publication.hashtags_override is not None
        else content.hashtags
    )
    return title, description, list(hashtags or [])


# --- Options -----------------------------------------------------------------------


def get_options(session: Session, publication_id: int) -> YouTubePublicationOptions:
    """Stored options, or the safe defaults (not added to the session)."""
    stored = session.get(YouTubePublicationOptions, publication_id)
    if stored is not None:
        return stored
    return YouTubePublicationOptions(
        publication_id=publication_id,
        privacy_status=YouTubePrivacy.PRIVATE,
        made_for_kids=None,
        contains_synthetic_media=None,
        notify_subscribers=False,
    )


def options_complete(options: YouTubePublicationOptions) -> bool:
    return (
        options.made_for_kids is not None
        and options.contains_synthetic_media is not None
    )


def options_to_read(
    publication: Publication, options: YouTubePublicationOptions
) -> YouTubePublicationOptionsRead:
    return YouTubePublicationOptionsRead(
        privacy_status=YouTubePrivacy(options.privacy_status),
        made_for_kids=options.made_for_kids,
        contains_synthetic_media=options.contains_synthetic_media,
        notify_subscribers=options.notify_subscribers,
        complete=options_complete(options),
        editable=publication.status in EDITABLE_STATUSES,
    )


def _youtube_publication(session: Session, publication_id: int) -> Publication:
    publication = get_publication_or_404(session, publication_id)
    account = session.get_one(Account, publication.account_id)
    if account.platform != Platform.YOUTUBE:
        raise ConflictError(
            "platform_not_supported",
            "YouTube options only apply to publications of YouTube accounts.",
        )
    return publication


@router.get(
    "/publications/{publication_id}/youtube-options",
    response_model=YouTubePublicationOptionsRead,
)
def get_youtube_options(
    publication_id: int, session: SessionDep
) -> YouTubePublicationOptionsRead:
    publication = _youtube_publication(session, publication_id)
    return options_to_read(publication, get_options(session, publication_id))


@router.put(
    "/publications/{publication_id}/youtube-options",
    response_model=YouTubePublicationOptionsRead,
)
def save_youtube_options(
    publication_id: int, body: YouTubePublicationOptionsWrite, session: SessionDep
) -> YouTubePublicationOptionsRead:
    publication = _youtube_publication(session, publication_id)
    if publication.status == PublicationStatus.CANCELLED:
        raise ConflictError(
            "publication_not_editable",
            "Reactivate the publication before changing its YouTube options.",
        )
    ensure_editable(publication)
    options = session.get(YouTubePublicationOptions, publication_id)
    values = {
        "privacy_status": body.privacy_status.value,
        "made_for_kids": body.made_for_kids,
        "contains_synthetic_media": body.contains_synthetic_media,
        "notify_subscribers": body.notify_subscribers,
    }
    if options is None:
        options = YouTubePublicationOptions(
            publication_id=publication_id, updated_at=utc_now(), **values
        )
        session.add(options)
        session.commit()
    elif any(getattr(options, key) != value for key, value in values.items()):
        for key, value in values.items():
            setattr(options, key, value)
        options.updated_at = utc_now()
        session.commit()
    return options_to_read(publication, options)


# --- Publisher ---------------------------------------------------------------------


@dataclass(frozen=True)
class YouTubePayload:
    """What the core treats as an opaque payload."""

    account_id: int
    requested_privacy: str
    upload: UploadRequest


def privacy_warnings(requested: str, actual: str | None) -> list[dict[str, str]]:
    if actual is None or actual == requested:
        return []
    return [
        {
            "code": "privacy_differs",
            "message": (
                f"YouTube set the privacy to {YouTubePrivacy(actual).value} instead "
                f"of the requested {YouTubePrivacy(requested).value}. Unverified API "
                "projects can only upload private videos."
            ),
        }
    ]


def _yes_no(value: bool | None) -> str:
    return "Not declared" if value is None else ("Yes" if value else "No")


def _file_label(content: Content) -> str:
    return f"{content.original_filename} ({content.size_bytes / 1_000_000:.1f} MB)"


class YouTubePublisher:
    def __init__(
        self,
        gateway: GoogleGateway,
        credential_store: CredentialStore,
        upload_settings: YouTubeUploadSettings,
    ) -> None:
        self.gateway = gateway
        self.credential_store = credential_store
        self.upload_settings = upload_settings

    # Local checks (no network), in the order of contracts/api.md.
    def check(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PublishCheck:
        content = session.get_one(Content, publication.content_id)
        options = get_options(session, publication.id)
        connection = get_connection(session, publication.account_id)
        problems: list[PublishProblem] = []
        if content.media_type != MediaType.VIDEO:
            problems.append(
                PublishProblem(
                    "content_not_video", "YouTube only accepts video content."
                )
            )
        elif not self._file_ready(ctx, content):
            problems.append(
                PublishProblem(
                    "media_unavailable",
                    "The media file of this content is not available or has changed.",
                )
            )
        title, description, hashtags = _effective_metadata(publication, content)
        problems.extend(
            validate_metadata(title, build_description(description, hashtags))
        )
        if options.made_for_kids is None:
            problems.append(
                PublishProblem(
                    "youtube_options_incomplete",
                    "Declare whether the video is made for kids.",
                    "made_for_kids",
                )
            )
        if options.contains_synthetic_media is None:
            problems.append(
                PublishProblem(
                    "youtube_options_incomplete",
                    "Declare whether the video contains realistic altered or "
                    "synthetic content.",
                    "contains_synthetic_media",
                )
            )
        if not oauth_configured():
            problems.append(
                PublishProblem(
                    "oauth_not_configured", NOT_CONFIGURED_MESSAGE, status_code=503
                )
            )
        if connection is None:
            problems.append(
                PublishProblem(
                    "not_connected",
                    "Connect this YouTube account before publishing.",
                )
            )
        elif connection.status != YouTubeConnectionStatus.CONNECTED:
            problems.append(
                PublishProblem(
                    "reconnect_required",
                    "Reconnect this YouTube account before publishing.",
                )
            )
        channel = (
            f"{connection.channel_title} ({connection.channel_id})"
            if connection is not None
            else "Not connected"
        )
        summary = [
            ("Title", title or ""),
            ("Channel", channel),
            ("Privacy", YouTubePrivacy(options.privacy_status).value),
            ("Notify subscribers", "Yes" if options.notify_subscribers else "No"),
            ("Made for kids", _yes_no(options.made_for_kids)),
            ("Altered or synthetic content", _yes_no(options.contains_synthetic_media)),
            ("File", _file_label(content)),
        ]
        return PublishCheck(problems, summary)

    @staticmethod
    def _file_ready(ctx: PublishContext, content: Content) -> bool:
        if not file_available(ctx.storage, content):
            return False
        path = ctx.storage.resolve(content.storage_path)
        return path.stat().st_size == content.size_bytes

    def prepare(
        self, session: Session, publication: Publication, ctx: PublishContext
    ) -> PreparedPublication:
        """Make sure the credentials still act on the linked channel, then build the
        upload. Never uploads to another channel (FR-017)."""
        connection = get_connection(session, publication.account_id)
        if connection is None:
            raise ConflictError(
                "not_connected", "Connect this YouTube account before publishing."
            )
        channels = list_channels(
            session, self.credential_store, self.gateway, connection
        )
        if len(channels) != 1 or channels[0].id != connection.channel_id:
            mark_reconnect_required(session, connection)
            raise ConflictError(
                "reconnect_required",
                "The authorized YouTube channel no longer matches the linked channel. "
                "Reconnect the channel; nothing was uploaded.",
            )
        content = session.get_one(Content, publication.content_id)
        options = get_options(session, publication.id)
        title, description, hashtags = _effective_metadata(publication, content)
        final_title = (title or "").strip()
        final_description = build_description(description, hashtags)
        assert options.made_for_kids is not None
        assert options.contains_synthetic_media is not None
        privacy = YouTubePrivacy(options.privacy_status).value
        path = ctx.storage.resolve(content.storage_path)
        upload = UploadRequest(
            file_path=path,
            total_bytes=content.size_bytes,
            mime_type=MIME_TYPES[content.media_format],
            resource=build_resource(
                title=final_title,
                description=final_description,
                privacy_status=privacy,
                made_for_kids=options.made_for_kids,
                contains_synthetic_media=options.contains_synthetic_media,
            ),
            notify_subscribers=options.notify_subscribers,
        )
        submitted: dict[str, Any] = {
            "title": final_title,
            "description": final_description,
            "privacy_status": privacy,
            "made_for_kids": options.made_for_kids,
            "contains_synthetic_media": options.contains_synthetic_media,
            "notify_subscribers": options.notify_subscribers,
            "channel_id": connection.channel_id,
            "channel_title": connection.channel_title,
            "file_name": content.original_filename,
            "file_size": content.size_bytes,
        }
        return PreparedPublication(
            publication_id=publication.id,
            file_path=path,
            total_bytes=content.size_bytes,
            submitted=submitted,
            payload=YouTubePayload(publication.account_id, privacy, upload),
        )

    def _token(self, ctx: PublishContext, account_id: int, force: bool) -> str:
        """A valid access token; credential problems become upload failures."""
        try:
            with ctx.session_factory() as session:
                tokens = get_valid_credentials(
                    session,
                    self.credential_store,
                    self.gateway,
                    account_id,
                    force_refresh=force,
                )
        except ConflictError:
            # not_connected / reconnect_required: the connection is already marked.
            raise TokenError("reconnect_required") from None
        except AppError as error:
            if error.code == "youtube_unavailable":
                raise TokenError("network_error", recoverable=True) from None
            raise TokenError(error.code) from None
        return tokens.access_token

    def _mark_reconnect_required(self, ctx: PublishContext, account_id: int) -> None:
        with ctx.session_factory() as session:
            connection = get_connection(session, account_id)
            if connection is not None:
                mark_reconnect_required(session, connection)

    def upload(
        self,
        prepared: PreparedPublication,
        reporter: ProgressReporter,
        ctx: PublishContext,
    ) -> PublishOutcome:
        payload = prepared.payload
        assert isinstance(payload, YouTubePayload)
        uploader = ResumableUpload(self.gateway.client, self.upload_settings)
        try:
            resource = uploader.run(
                payload.upload,
                reporter,
                lambda force: self._token(ctx, payload.account_id, force),
            )
        except PublishFailure as failure:
            if failure.code == "reconnect_required":
                # YouTube kept rejecting fresh credentials (research.md §6).
                self._mark_reconnect_required(ctx, payload.account_id)
            raise
        video_id: str = resource["id"]
        status = resource.get("status") or {}
        details: dict[str, Any] = {}
        for key, name in RESOURCE_STATUS_KEYS:
            value = status.get(name)
            if isinstance(value, str):
                details[key] = value
        return PublishOutcome(
            external_id=video_id,
            external_url=video_url(video_id),
            details=details,
            warnings=privacy_warnings(
                payload.requested_privacy, details.get("privacy_status")
            ),
        )

    def refresh_details(
        self,
        prepared: PreparedPublication,
        outcome: PublishOutcome,
        ctx: PublishContext,
    ) -> PublishOutcome:
        payload = prepared.payload
        assert isinstance(payload, YouTubePayload)
        token = self._token(ctx, payload.account_id, False)
        status = self.gateway.get_video_status(token, outcome.external_id)
        details = {**outcome.details, **status}
        return PublishOutcome(
            external_id=outcome.external_id,
            external_url=outcome.external_url,
            details=details,
            warnings=privacy_warnings(
                payload.requested_privacy, details.get("privacy_status")
            ),
        )
