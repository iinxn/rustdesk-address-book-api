from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import User
from app.services.auth import user_by_token


def bearer_token(authorization: str = Header(default="")) -> str:
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def current_user(token: str = Depends(bearer_token), db: Session = Depends(get_db)) -> User:
    user = user_by_token(db, token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def optional_user(token: str = Depends(bearer_token), db: Session = Depends(get_db)) -> User | None:
    return user_by_token(db, token) if token else None
