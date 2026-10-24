"""Installation password, browser sessions and the `/api/auth` routes (Feature 020).

- Password (research §10): `hashlib.scrypt`, stored as the self-describing
  `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`; never reversible, never logged.
- Sessions (research §11): opaque random tokens kept only in an HttpOnly cookie; the
  database stores their SHA-256. Valid while `now < min(last_seen_at + 7 d,
  expires_at)`, with `expires_at = created_at + 30 d` never extended.
- Login rate limit (research §12): in memory, per client IP and global.

Races (M2): login verifies the password outside any transaction (scrypt is slow), so
the session is inserted by one statement that only succeeds while the stored hash is
still the verified one; a password change updates the hash only where it still
equals the verified one. A reset or change between verification and persistence
therefore never leaves a session of the old password.

Initial setup and forgotten-password reset are local only (`set-password` in
`app.cli`): there is no HTTP endpoint for them.
"""

import base64
import binascii
import hashlib
import hmac
import logging
import secrets
import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, exists, insert, literal, select, update
from sqlalchemy.orm import Session

from app.db import UTCDateTime, get_session
from app.errors import AppError, field_errors
from app.models import AuthSession, InstallationAuth

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]

# --- Password hashing (research §10) -------------------------------------------------

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16
KEY_BYTES = 32
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024
_ALGORITHM = "scrypt"


@dataclass(frozen=True)
class _ScryptHash:
    n: int
    r: int
    p: int
    salt: bytes
    key: bytes


def _derive(password: str, salt: bytes, n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=SCRYPT_MAXMEM,
        dklen=length,
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, KEY_BYTES)
    return f"{_ALGORITHM}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def _parse(encoded: str) -> _ScryptHash | None:
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != _ALGORITHM:
        return None
    try:
        n, r, p = (int(part) for part in parts[1:4])
        salt = base64.b64decode(parts[4], validate=True)
        key = base64.b64decode(parts[5], validate=True)
    except (ValueError, binascii.Error):
        return None
    if n < 2 or n & (n - 1) or r < 1 or p < 1 or not salt or len(key) < 16:
        return None
    return _ScryptHash(n, r, p, salt, key)


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check; a malformed or unusable hash never matches."""
    parsed = _parse(encoded)
    if parsed is None:
        return False
    try:
        candidate = _derive(
            password, parsed.salt, parsed.n, parsed.r, parsed.p, len(parsed.key)
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(candidate, parsed.key)


def needs_rehash(encoded: str) -> bool:
    """Whether the hash was made with other parameters than the current ones."""
    parsed = _parse(encoded)
    return parsed is None or (parsed.n, parsed.r, parsed.p, len(parsed.key)) != (
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        KEY_BYTES,
    )


def password_length_error(password: str) -> str | None:
    if MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        return None
    return f"Use {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters."


def current_password_hash(db: Session) -> str | None:
    return db.scalar(
        select(InstallationAuth.password_hash).where(InstallationAuth.id == 1)
    )


def set_password(db: Session, password: str, now: datetime) -> None:
    """Local setup or reset: store the new hash and delete every session, in one
    transaction (the hash is computed before it starts)."""
    encoded = hash_password(password)
    row = db.get(InstallationAuth, 1)
    if row is None:
        db.add(InstallationAuth(id=1, password_hash=encoded, password_changed_at=now))
    else:
        row.password_hash = encoded
        row.password_changed_at = now
    db.flush()
    db.execute(delete(AuthSession))
    db.commit()


# --- Sessions (research §11) ---------------------------------------------------------

SESSION_COOKIE = "autopublisher_session"
SESSION_IDLE = timedelta(days=7)
SESSION_LIFETIME = timedelta(days=30)
SESSION_TOUCH_INTERVAL = timedelta(minutes=10)
MAX_SESSIONS = 20


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _session_row(token: str, now: datetime) -> dict[str, Any]:
    return {
        "token_hash": hash_token(token),
        "created_at": now,
        "last_seen_at": now,
        "expires_at": now + SESSION_LIFETIME,
    }


def purge_expired_sessions(db: Session, now: datetime) -> None:
    db.execute(
        delete(AuthSession).where(
            (AuthSession.expires_at <= now)
            | (AuthSession.last_seen_at <= now - SESSION_IDLE)
        )
    )
    db.commit()


def _enforce_session_cap(db: Session) -> None:
    """Keep at most MAX_SESSIONS, deleting the least recently used ones."""
    newest = (
        select(AuthSession.token_hash)
        .order_by(AuthSession.last_seen_at.desc(), AuthSession.created_at.desc())
        .offset(MAX_SESSIONS)
    )
    db.execute(delete(AuthSession).where(AuthSession.token_hash.in_(newest)))


def create_session(db: Session, verified_hash: str, now: datetime) -> str | None:
    """Insert a new session only if the stored hash is still `verified_hash`.

    A single `INSERT … SELECT … WHERE EXISTS` statement: SQLite runs it atomically,
    so a reset or change committed after the verification makes it insert nothing.
    """
    purge_expired_sessions(db, now)
    token = _new_token()
    row = _session_row(token, now)
    columns = list(row)
    values = select(
        *(
            literal(value, UTCDateTime())
            if isinstance(value, datetime)
            # Plain text binds for the hash.
            else literal(value)
            for value in row.values()
        )
    ).where(
        exists().where(
            InstallationAuth.id == 1, InstallationAuth.password_hash == verified_hash
        )
    )
    result = db.execute(
        insert(AuthSession).from_select(
            [getattr(AuthSession, name) for name in columns], values
        )
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        db.rollback()
        return None
    _enforce_session_cap(db)
    db.commit()
    return token


def replace_password(
    db: Session, verified_hash: str, new_hash: str, now: datetime
) -> str | None:
    """Change the password only where the stored hash is still the verified one,
    delete every session and open one for the caller, in one transaction."""
    result = db.execute(
        update(InstallationAuth)
        .where(
            InstallationAuth.id == 1, InstallationAuth.password_hash == verified_hash
        )
        .values(password_hash=new_hash, password_changed_at=now)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        db.rollback()
        return None
    db.execute(delete(AuthSession))
    token = _new_token()
    db.execute(insert(AuthSession).values(**_session_row(token, now)))
    db.commit()
    return token


def session_deadline(last_seen_at: datetime, expires_at: datetime) -> datetime:
    return min(last_seen_at + SESSION_IDLE, expires_at)


def authenticate(db: Session, token: str, now: datetime) -> bool:
    """Whether `token` is a valid session; renews its idle deadline at most every
    10 minutes (never past `expires_at`) and deletes it once invalid."""
    token_hash = hash_token(token)
    row = db.execute(
        select(AuthSession.last_seen_at, AuthSession.expires_at).where(
            AuthSession.token_hash == token_hash
        )
    ).one_or_none()
    if row is None:
        return False
    last_seen_at, expires_at = row
    if now >= session_deadline(last_seen_at, expires_at):
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
        db.commit()
        return False
    if now - last_seen_at >= SESSION_TOUCH_INTERVAL:
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == token_hash)
            .values(last_seen_at=now)
        )
        db.commit()
    return True


def delete_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    db.commit()


def set_session_cookie(
    response: Response, token: str, expires_at: datetime, now: datetime
) -> None:
    """Host-only (no Domain) and without `Secure`: LAN access is plain HTTP (D14)."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max(0, int((expires_at - now).total_seconds())),
        path="/",
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")


# --- Login rate limit (research §12) -------------------------------------------------

RATE_WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_IP = 5
MAX_FAILURES_GLOBAL = 20
MAX_TRACKED_IPS = 256


class LoginRateLimiter:
    """Sliding-window failure counts, bounded in memory, never a permanent block."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._by_ip: OrderedDict[str, deque[datetime]] = OrderedDict()
        self._global: deque[datetime] = deque()

    def _prune(self, now: datetime) -> None:
        cutoff = now - RATE_WINDOW
        while self._global and self._global[0] <= cutoff:
            self._global.popleft()
        for ip in list(self._by_ip):
            failures = self._by_ip[ip]
            while failures and failures[0] <= cutoff:
                failures.popleft()
            if not failures:
                del self._by_ip[ip]

    def blocked(self, ip: str) -> bool:
        with self._lock:
            self._prune(self._clock())
            failures = self._by_ip.get(ip)
            return (
                len(self._global) >= MAX_FAILURES_GLOBAL
                or failures is not None
                and len(failures) >= MAX_FAILURES_PER_IP
            )

    def record_failure(self, ip: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._global.append(now)
            failures = self._by_ip.pop(ip, None) or deque()
            failures.append(now)
            self._by_ip[ip] = failures  # most recently failing last
            while len(self._by_ip) > MAX_TRACKED_IPS:
                self._by_ip.popitem(last=False)

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._by_ip.pop(ip, None)

    @property
    def tracked_ips(self) -> int:
        with self._lock:
            return len(self._by_ip)


# --- API (contracts/api.md §3) -------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_session)]

_Password = Annotated[str, Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: _Password


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: _Password
    # Its length is checked by the endpoint, with the contract's message.
    new_password: str


def _auth_not_enabled() -> AppError:
    return AppError(
        409,
        "auth_not_enabled",
        "Sign-in is only used by the installed application.",
    )


def _too_many_attempts() -> AppError:
    return AppError(
        429,
        "too_many_attempts",
        "Too many attempts. Try again in a few minutes.",
    )


def _invalid_credentials(message: str) -> AppError:
    return AppError(401, "invalid_credentials", message)


def _requires_auth(request: Request) -> bool:
    deployment = request.app.state.deployment
    return deployment is not None and deployment.is_installation


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "-"


def _now(request: Request) -> datetime:
    clock: Clock = request.app.state.clock
    return clock()


@router.get("/session")
def session_state(request: Request, db: SessionDep, response: Response) -> Any:
    if not _requires_auth(request):
        return {"mode": "development", "auth_required": False, "authenticated": True}
    token = request.cookies.get(SESSION_COOKIE)
    authenticated = bool(token) and authenticate(db, token or "", _now(request))
    if token and not authenticated:
        clear_session_cookie(response)
    return {
        "mode": "installation",
        "auth_required": True,
        "authenticated": authenticated,
    }


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(body: LoginRequest, request: Request, db: SessionDep) -> Response:
    if not _requires_auth(request):
        raise _auth_not_enabled()
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = _client_ip(request)
    if limiter.blocked(ip):
        logger.warning("Sign-in blocked for %s: too many attempts.", ip)
        raise _too_many_attempts()
    stored = current_password_hash(db)
    if stored is None or not verify_password(body.password, stored):
        limiter.record_failure(ip)
        logger.warning("Sign-in failed from %s.", ip)
        raise _invalid_credentials("Incorrect password.")
    now = _now(request)
    token = create_session(db, stored, now)
    if token is None:
        # The password changed after it was verified: same answer as a wrong one.
        logger.warning("Sign-in from %s refused: the password changed.", ip)
        raise _invalid_credentials("Incorrect password.")
    limiter.record_success(ip)
    if needs_rehash(stored):
        db.execute(
            update(InstallationAuth)
            .where(InstallationAuth.id == 1, InstallationAuth.password_hash == stored)
            .values(password_hash=hash_password(body.password))
        )
        db.commit()
    logger.info("Signed in from %s.", ip)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(response, token, now + SESSION_LIFETIME, now)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: SessionDep) -> Response:
    """Idempotent: deletes this browser's session (if any) and its cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(db, token)
        logger.info("Signed out from %s.", _client_ip(request))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeRequest, request: Request, db: SessionDep
) -> Response:
    """Every other session is signed out; this browser gets a new session."""
    if not _requires_auth(request):
        raise _auth_not_enabled()
    error = password_length_error(body.new_password)
    if error is not None:
        raise field_errors([("new_password", error)])
    limiter: LoginRateLimiter = request.app.state.login_limiter
    ip = _client_ip(request)
    if limiter.blocked(ip):
        logger.warning("Password change blocked for %s: too many attempts.", ip)
        raise _too_many_attempts()
    stored = current_password_hash(db)
    if stored is None or not verify_password(body.current_password, stored):
        limiter.record_failure(ip)
        logger.warning("Password change from %s: wrong current password.", ip)
        raise _invalid_credentials("Current password is incorrect.")
    now = _now(request)
    token = replace_password(db, stored, hash_password(body.new_password), now)
    if token is None:
        logger.warning("Password change from %s refused: it changed meanwhile.", ip)
        raise _invalid_credentials("Current password is incorrect.")
    limiter.record_success(ip)
    logger.info("Password changed from %s; other sessions were signed out.", ip)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(response, token, now + SESSION_LIFETIME, now)
    return response
