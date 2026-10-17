"""Discard a provisional account (contracts/api.md §5).

Only for an abandoned "Add account": an account whose identity was never known,
with no connection and no posts. It is not a general account deletion: any other
account can only be deactivated. Kept apart from `app.accounts` because it needs
the Telegram session lock, and `app.telegram_connections` already depends on
`app.accounts`.
"""

from contextlib import ExitStack
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError, NotFoundError
from app.models import (
    Account,
    InstagramConnection,
    Publication,
    TelegramConnection,
    ThreadsConnection,
    TikTokConnection,
    YouTubeConnection,
)
from app.telegram_connections import account_session

router = APIRouter(prefix="/api", tags=["accounts"])

SessionDep = Annotated[Session, Depends(get_session)]

CONNECTION_MODELS = (
    YouTubeConnection,
    InstagramConnection,
    ThreadsConnection,
    TikTokConnection,
    TelegramConnection,
)
NOT_DISCARDABLE_MESSAGE = (
    "This account is in use and can't be removed. Deactivate it instead."
)
BUSY_MESSAGE = "A connection step is in progress. Try again in a moment."


def is_discardable(session: Session, account: Account) -> bool:
    """Provisional: no identity ever adopted, no connection row (connected or
    needing reconnection) and no publication in any status."""
    if account.handle is not None:
        return False
    used = [
        exists().where(model.account_id == account.id) for model in CONNECTION_MODELS
    ]
    used.append(exists().where(Publication.account_id == account.id))
    return not any(session.scalar(select(condition)) for condition in used)


def _not_discardable() -> AppError:
    return AppError(409, "account_not_discardable", NOT_DISCARDABLE_MESSAGE)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_account(account_id: int, request: Request, session: SessionDep) -> Response:
    """Never contacts a platform nor the secure storage: before a connection
    completes nothing exists outside memory."""
    if session.get(Account, account_id) is None:
        raise NotFoundError("Account not found.")
    with ExitStack() as stack:
        # Held until the row is gone: no Telegram login step can run meanwhile.
        try:
            stack.enter_context(account_session(account_id, wait=False))
        except AppError as error:
            if error.code != "telegram_busy":
                raise
            raise AppError(409, "account_busy", BUSY_MESSAGE) from None

        account = session.get(Account, account_id)
        if account is None:
            raise NotFoundError("Account not found.")
        if not is_discardable(session, account):
            raise _not_discardable()

        # In-memory attempts: a later provider redirect is "Authorization not valid".
        state = request.app.state
        for registry in (
            state.oauth_attempts,
            state.instagram_attempts,
            state.threads_attempts,
            state.tiktok_attempts,
        ):
            registry.expire_for_account(account_id)
        state.telegram_logins.discard(account_id)

        # A callback may have created a connection meanwhile: check again, and the
        # RESTRICT foreign keys reject the delete if it commits in between.
        session.expire_all()
        account = session.get(Account, account_id)
        if account is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        if not is_discardable(session, account):
            raise _not_discardable()
        session.delete(account)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise _not_discardable() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
