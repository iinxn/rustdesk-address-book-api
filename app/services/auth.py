"""AuthService: users + opaque sessions."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, new_token, verify_password
from app.models.models import AddressBook, Session as SessionModel, User


def create_user(db: Session, username: str, password: str, is_admin: bool = False) -> User:
    user = User(username=username, password_hash=hash_password(password), is_admin=is_admin)
    db.add(user)
    db.flush()
    # every user gets a personal address book (guid = book id)
    db.add(AddressBook(name="My address book", type="personal", owner_user_id=user.id))
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or user.is_disabled:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_session(db: Session, user: User) -> SessionModel:
    expires = None
    if settings.session_days > 0:
        expires = datetime.utcnow() + timedelta(days=settings.session_days)
    s = SessionModel(user_id=user.id, token=new_token(), expires_at=expires)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


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
