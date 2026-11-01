"""`/api/v1`: panel users (admin only) and the caller's own profile."""
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.errors import PanelError
from app.api.v1.common import PREFIX, check_display_name, record, require_admin, user_out
from app.core.security import password_error
from app.db.session import get_db
from app.models.models import User
from app.schemas.panel import MeIn, UserIn
from app.services import audit as audit_svc
from app.services.auth import create_user, destroy_user_sessions, set_password

router = APIRouter(prefix=PREFIX)


def _username_taken(db: Session, username: str) -> bool:
    return db.scalar(select(User.id).where(User.username == username)) is not None


def _snapshot(u: User) -> dict:
    return {"username": u.username, "display_name": u.display_name,
            "is_admin": str(u.is_admin), "is_disabled": str(u.is_disabled)}


@router.get("/users")
def list_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users")
def create_panel_user(body: UserIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    if not body.username.strip():
        raise PanelError(400, "missing username")
    if (problem := password_error(body.password)) is not None:
        raise PanelError(400, problem)
    if _username_taken(db, body.username):
        raise PanelError(409, "duplicate")
    check_display_name(body.display_name)
    u = create_user(db, body.username, body.password, body.is_admin, body.display_name, commit=False)
    record(db, user, "security", "user.create", target_type="user", target_id=u.id,
           details={"username": u.username, "display_name": u.display_name, "is_admin": u.is_admin})
    db.commit()
    return user_out(u)


@router.put("/users/{uid}")
def update_panel_user(uid: str, body: dict[str, Any], user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Edit user: {username?, display_name?, is_admin?, is_disabled?, password?}. Admin only.

    Every field is validated before anything changes. An empty/absent
    password means "keep the current one" (panel form contract). A password
    change or disable revokes all sessions of that user (SEC-007): Bearer
    tokens and panel cookies alike.
    """
    require_admin(user)
    u = db.get(User, uid)
    if u is None:
        raise PanelError(404, "not found")
    new_password = body.get("password")
    change_password = new_password not in (None, "")
    if change_password and (problem := password_error(new_password)) is not None:
        raise PanelError(400, problem)
    before = _snapshot(u)

    if "username" in body:
        new_name = str(body["username"]).strip()
        if not new_name:
            raise PanelError(400, "missing username")
        if new_name != u.username and _username_taken(db, new_name):
            raise PanelError(409, "duplicate")
        u.username = new_name
    if "display_name" in body:
        if not isinstance(body["display_name"], str):
            raise PanelError(400, "display_name must be a string")
        u.display_name = check_display_name(body["display_name"])
    if "is_admin" in body:
        if u.id == user.id and not body["is_admin"]:
            raise PanelError(400, "cannot demote self")
        u.is_admin = bool(body["is_admin"])
    if "is_disabled" in body:
        if u.id == user.id and body["is_disabled"]:
            raise PanelError(400, "cannot disable self")
        u.is_disabled = bool(body["is_disabled"])
    if change_password:
        set_password(db, u, str(new_password))
    revoke = change_password or ("is_disabled" in body and u.is_disabled)

    fields = audit_svc.diff_fields(before, _snapshot(u))
    if change_password:
        fields["password_changed"] = True
    record(db, user, "security", "user.update", target_type="user", target_id=u.id,
           details={"fields": fields, "sessions_revoked": revoke})
    if revoke:
        destroy_user_sessions(db, u.id)  # commits the update and the audit row too
    else:
        db.commit()
    return user_out(u)


@router.delete("/users/{uid}")
def delete_panel_user(uid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    u = db.get(User, uid)
    if u is None:
        raise PanelError(404, "not found")
    if u.id == user.id:
        raise PanelError(400, "cannot delete self")
    record(db, user, "security", "user.delete", target_type="user", target_id=u.id,
           details={"username": u.username, "display_name": u.display_name})
    db.delete(u)
    db.commit()
    return {"ok": True}


@router.get("/me")
def get_me(user: User = Depends(current_user)):
    return user_out(user)


@router.put("/me")
def update_me(body: MeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Self-service: the signed-in user edits their own display name."""
    new_name = check_display_name(body.display_name)
    old_name, user.display_name = user.display_name, new_name
    record(db, user, "security", "user.self_update", target_type="user", target_id=user.id,
           details={"fields": audit_svc.diff_fields({"display_name": old_name},
                                                    {"display_name": new_name})})
    db.commit()
    return user_out(user)
