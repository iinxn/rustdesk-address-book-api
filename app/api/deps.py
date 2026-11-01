"""Shared FastAPI dependencies."""
from typing import Any

from fastapi import Depends, Header, HTTPException, Request
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


class BadJson:
    """Marker returned by `json_body` instead of raising (route keeps its error order)."""


BAD_JSON = BadJson()


async def json_body(request: Request) -> Any:
    """Raw JSON body for routes with free-form client payloads.

    Async so the body is read on the event loop while the route itself stays a
    plain `def` running in the threadpool (SQLite work never blocks the loop).
    """
    try:
        return await request.json()
    except ValueError:
        return BAD_JSON
