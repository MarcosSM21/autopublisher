"""Send to phone: a media's publish file to the user's phone via Tailscale Taildrop
(Feature 029).

One synchronous action, no state: the file is whatever `resolve_publish_file`
returns, and the whole send runs under the content file guard so `Clean metadata`
or a deletion never replaces or removes it mid-transfer. `tailscale` output may
contain paths and device names: it is never logged nor shown, only the exit code.
"""

import logging
import os
import shutil
import subprocess

from fastapi import APIRouter, Response

from app.asset_library import GuardDep
from app.content_files import ContentFileUnavailable, resolve_publish_file
from app.contents import SessionDep, StorageDep, get_content_or_404
from app.errors import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["send-to-phone"])

TARGET_ENV = "TAILSCALE_PHONE_TARGET"
SEND_TIMEOUT_SECONDS = 300

NOT_CONFIGURED_MESSAGE = (
    "Sending to your phone is not set up. Set TAILSCALE_PHONE_TARGET and restart "
    "AutoPublisher."
)
TAILSCALE_UNAVAILABLE_MESSAGE = "Tailscale is not available on this computer."
SEND_FAILED_MESSAGE = (
    "Could not send the file to your phone. Check that it is online in Tailscale "
    "and try again."
)
SEND_TIMEOUT_MESSAGE = "Sending to your phone took too long and was stopped. Try again."


@router.post("/contents/{content_id}/send-to-phone", status_code=204)
def send_to_phone(
    content_id: int, session: SessionDep, storage: StorageDep, guard: GuardDep
) -> Response:
    """Send the publish file to `TAILSCALE_PHONE_TARGET` with its original name."""
    content = get_content_or_404(session, content_id)
    target = os.environ.get(TARGET_ENV, "").strip()
    if not target:
        raise AppError(503, "phone_target_not_configured", NOT_CONFIGURED_MESSAGE)
    tailscale = shutil.which("tailscale")
    if tailscale is None:
        raise AppError(503, "tailscale_unavailable", TAILSCALE_UNAVAILABLE_MESSAGE)

    with guard.sanitizing(content.id, lambda: None):
        try:
            effective = resolve_publish_file(storage, content, verify=True)
        except ContentFileUnavailable as error:
            raise AppError(409, error.code, error.message) from None
        command = [
            tailscale,
            "file",
            "cp",
            "--name",
            content.original_filename,
            str(effective.path),
            f"{target}:",
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=SEND_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "tailscale file cp timed out after %s s", SEND_TIMEOUT_SECONDS
            )
            raise AppError(504, "phone_send_timeout", SEND_TIMEOUT_MESSAGE) from None
        except OSError as error:
            logger.warning("tailscale file cp could not run: %s", type(error).__name__)
            raise AppError(
                503, "tailscale_unavailable", TAILSCALE_UNAVAILABLE_MESSAGE
            ) from None
        if completed.returncode != 0:
            # stdout/stderr may contain paths and device names: never logged.
            logger.warning(
                "tailscale file cp failed with exit code %s", completed.returncode
            )
            raise AppError(502, "phone_send_failed", SEND_FAILED_MESSAGE)
    return Response(status_code=204)
