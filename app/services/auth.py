"""AuthService: users + opaque sessions."""
import asyncio
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, new_token, password_error, verify_password
from app.models.models import AddressBook, Session as SessionModel, User

DISPLAY_NAME_MAX = 128


def clean_display_name(raw: str | None) -> str:
    """Trim and collapse whitespace in a user-visible name.

    The RustDesk client sends this value to the peer as `my_name`, so it must
    stay a single bounded line (see DECISIONS.md DEC-015). Callers validate
    `len(clean_display_name(x)) <= DISPLAY_NAME_MAX`; the DB column is
    String(128) and SQLite does not enforce it.
    """
    return " ".join((raw or "").split())


def create_user(
    db: Session,
    username: str,
    password: str,
    is_admin: bool = False,
    display_name: str = "",
    commit: bool = True,
) -> User:
    # Defence in depth: every caller validates first and answers 400; this
    # guard keeps a passwordless account from ever reaching the database.
    if (problem := password_error(password)) is not None:
        raise ValueError(problem)
    user = User(
        username=username,
        password_hash=hash_password(password),
        is_admin=is_admin,
        display_name=clean_display_name(display_name),
    )
    db.add(user)
    db.flush()
    # every user gets a personal address book (guid = book id)
    db.add(AddressBook(name="My address book", type="personal", owner_user_id=user.id))
    if commit:
        db.commit()
        db.refresh(user)
    else:
        db.flush()
    return user


class AuthBusy(Exception):
    """Too many password checks in flight; the caller should answer 429."""


# bcrypt costs ~0.4 s of CPU. It must never run on the event loop (one burst of
# failed logins would freeze every request, heartbeats included), and it must
# not occupy the shared request threadpool either. A small dedicated pool plus
# a hard in-flight cap sheds a guessing burst instead of queueing it.
_hash_pool = ThreadPoolExecutor(
    max_workers=max(1, settings.password_hash_workers), thread_name_prefix="pwhash"
)
_inflight = 0
_inflight_lock = threading.Lock()


def _release(_future=None) -> None:
    global _inflight
    with _inflight_lock:
        _inflight -= 1


def _verify_future(password: str, hashed: str) -> Future:
    global _inflight
    with _inflight_lock:
        if _inflight >= max(1, settings.password_hash_queue):
            raise AuthBusy()
        _inflight += 1
    try:
        future = _hash_pool.submit(verify_password, password, hashed)
    except BaseException:
        _release()
        raise
    future.add_done_callback(_release)
    return future


def _candidate(db: Session, username: str, password: str) -> User | None:
    if not password:
        return None
    user = db.scalar(select(User).where(User.username == username))
    if user is None or user.is_disabled:
        return None
    return user


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Blocking variant for sync handlers (they already run in a worker thread).

    Raises AuthBusy when the password-check pool is saturated."""
    user = _candidate(db, username, password)
    if user is None:
        return None
    return user if _verify_future(password, user.password_hash).result() else None


async def authenticate_async(db: Session, username: str, password: str) -> User | None:
    """Event-loop friendly variant: the bcrypt check is awaited, not run inline.

    Raises AuthBusy when the password-check pool is saturated."""
    user = _candidate(db, username, password)
    if user is None:
        return None
    ok = await asyncio.wrap_future(_verify_future(password, user.password_hash))
    return user if ok else None


def create_session(db: Session, user: User, device_id: str = "") -> SessionModel:
    purge_expired_sessions(db)  # keep the table from growing (SEC-007/019)
    expires = None
    if settings.session_days > 0:
        expires = datetime.utcnow() + timedelta(days=settings.session_days)
    s = SessionModel(
        user_id=user.id,
        token=new_token(),
        expires_at=expires,
        device_id=(device_id or "").strip()[:64],
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def destroy_user_sessions(db: Session, user_id: str) -> int:
    """Revoke every live token of a user (disable or password rotation).

    SEC-007: a password change / account disable must invalidate existing
    Bearer sessions, not only the one that made the request."""
    res = db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))
    db.commit()
    return res.rowcount or 0


def purge_expired_sessions(db: Session) -> int:
    """Delete tokens whose expiry has passed. Returns the number removed."""
    res = db.execute(
        delete(SessionModel).where(
            SessionModel.expires_at.is_not(None),
            SessionModel.expires_at < datetime.utcnow(),
        )
    )
    db.commit()
    return res.rowcount or 0


def user_by_token(db: Session, token: str) -> User | None:
    s = db.scalar(select(SessionModel).where(SessionModel.token == token))
    if s is None:
        return None
    if s.expires_at is not None and s.expires_at < datetime.utcnow():
        db.delete(s)
        db.commit()
        return None
    user = db.get(User, s.user_id)
    if user is None or user.is_disabled:
        return None
    return user


def destroy_session(db: Session, token: str) -> None:
    s = db.scalar(select(SessionModel).where(SessionModel.token == token))
    if s is not None:
        db.delete(s)
        db.commit()
