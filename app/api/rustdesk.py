"""RustDesk Client compatibility API. Mirrors Server Pro shapes from
docs/rustdesk-api-analysis.md. Error shape is always {"error": msg}."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import bearer_token, current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import AddressBook, AddressBookEntry, EntryTag, Tag, User
from app.schemas.rustdesk import LoginIn
from app.services import ab as ab_svc
from app.services import presence as presence_svc
from app.services.auth import authenticate, create_session, destroy_session, user_by_token

router = APIRouter()


def err(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": msg})


def ok_empty() -> Response:
    return Response(status_code=200)


# --- auth ---

@router.post("/api/login")
async def login(body: LoginIn, db: Session = Depends(get_db)):
    user = authenticate(db, body.username, body.password)
    if user is None:
        return err("Invalid username or password", 401)
    s = create_session(db, user)
    return {
        "access_token": s.token,
        "type": "access_token",
        "user": {
            "name": user.username,
            "display_name": user.display_name or "",
            "avatar": "",
            "email": "",
            "note": "",
            "status": 1,
            "is_admin": user.is_admin,
        },
    }


@router.post("/api/currentUser")
async def current_user_info(request: Request, db: Session = Depends(get_db), token: str = Depends(bearer_token)):
    user = user_by_token(db, token) if token else None
    if user is None:
        return err("unauthorized", 401)
    return {
        "name": user.username,
        "display_name": user.display_name or "",
        "avatar": "",
        "email": "",
        "note": "",
        "status": 0 if user.is_disabled else 1,
        "is_admin": user.is_admin,
    }


@router.post("/api/logout")
async def logout(db: Session = Depends(get_db), token: str = Depends(bearer_token)):
    if token:
        destroy_session(db, token)
    return ok_empty()


@router.get("/api/login-options")
async def login_options():
    return []


# --- discovery ---

@router.post("/api/ab/settings")
async def ab_settings(user: User = Depends(current_user)):
    return {"max_peer_one_ab": settings.max_peer_one_ab}


@router.post("/api/ab/personal")
async def ab_personal(user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.personal_book(db, user)
    if book is None:  # defensive: user created before auto-book logic
        book = AddressBook(name="My address book", type="personal", owner_user_id=user.id)
        db.add(book)
        db.commit()
        db.refresh(book)
    return {"guid": book.id}


@router.post("/api/ab/shared/profiles")
async def ab_shared_profiles(
    current: int = 1, pageSize: int = 100,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    profiles = ab_svc.shared_profiles(db, user)
    total = len(profiles)
    start = (max(current, 1) - 1) * pageSize
    chunk = profiles[start:start + pageSize]
    return {
        "total": total,
        "data": [
            {"guid": b.id, "name": b.name, "owner": b.owner_user_id, "note": "", "info": None, "rule": rule}
            for b, rule in chunk
        ],
    }


# --- peers ---

@router.post("/api/ab/peers")
async def ab_peers(
    current: int = 1, pageSize: int = 100, ab: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    book = ab_svc.get_book_for_user(db, user, ab)
    if book is None:
        return err("no such address book", 404)
    total = db.scalar(select(func.count()).select_from(AddressBookEntry).where(AddressBookEntry.address_book_id == book.id)) or 0
    start = (max(current, 1) - 1) * pageSize
    rows = db.scalars(
        select(AddressBookEntry)
        .where(AddressBookEntry.address_book_id == book.id)
        .order_by(AddressBookEntry.rustdesk_id)
        .offset(start)
        .limit(pageSize)
    ).all()
    return {"total": total, "data": [ab_svc.peer_out(db, e, book) for e in rows]}


@router.post("/api/ab/peer/add/{guid}")
async def ab_peer_add(guid: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    try:
        data = await request.json()
    except Exception:
        return err("bad json", 400)
    rid = str(data.get("id", "")).strip()
    if not rid:
        return err("missing id", 400)
    exists = db.scalar(
        select(AddressBookEntry).where(
            AddressBookEntry.address_book_id == book.id, AddressBookEntry.rustdesk_id == rid
        )
    )
    if exists is not None:
        return err(f"{rid} already exists", 409)
    if settings.max_peer_one_ab > 0:
        n = db.scalar(select(func.count()).select_from(AddressBookEntry).where(AddressBookEntry.address_book_id == book.id)) or 0
        if n >= settings.max_peer_one_ab:
            return err("exceed_max_devices", 403)
    e = AddressBookEntry(
        address_book_id=book.id,
        rustdesk_id=rid,
        alias=str(data.get("alias", "")),
        note=str(data.get("note", "")),
        username=str(data.get("username", "")),
        hostname=str(data.get("hostname", "")),
        platform=str(data.get("platform", "")),
    )
    if book.type == "personal":
        e.hash_value = str(data.get("hash", ""))
    else:
        pw = str(data.get("password", ""))
        if pw:
            from app.core.crypto import encrypt_password
            e.password_encrypted = encrypt_password(pw)
    db.add(e)
    db.flush()
    tags = data.get("tags", [])
    if isinstance(tags, list) and tags:
        ab_svc.sync_entry_tags(db, e, [str(t) for t in tags])
    db.commit()
    return ok_empty()


@router.put("/api/ab/peer/update/{guid}")
async def ab_peer_update(guid: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    try:
        data = await request.json()
    except Exception:
        return err("bad json", 400)
    rid = str(data.get("id", "")).strip()
    if not rid:
        return err("missing id", 400)
    e = db.scalar(
        select(AddressBookEntry).where(
            AddressBookEntry.address_book_id == book.id, AddressBookEntry.rustdesk_id == rid
        )
    )
    if e is None:
        return err("not found", 404)
    ab_svc.apply_peer_update(db, e, data, book)
    db.commit()
    return ok_empty()


@router.delete("/api/ab/peer/{guid}")
async def ab_peer_delete(guid: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    try:
        ids = await request.json()
    except Exception:
        return err("bad json", 400)
    if not isinstance(ids, list):
        return err("expected id list", 400)
    for rid in ids:
        e = db.scalar(
            select(AddressBookEntry).where(
                AddressBookEntry.address_book_id == book.id, AddressBookEntry.rustdesk_id == str(rid)
            )
        )
        if e is not None:
            db.delete(e)
    db.commit()
    return ok_empty()


# --- tags ---

@router.post("/api/ab/tags/{guid}")
async def ab_tags(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    tags = db.scalars(select(Tag).where(Tag.address_book_id == book.id).order_by(Tag.name)).all()
    return [{"name": t.name, "color": t.color} for t in tags]


@router.post("/api/ab/tag/add/{guid}")
async def ab_tag_add(guid: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    try:
        data = await request.json()
    except Exception:
        return err("bad json", 400)
    name = str(data.get("name", "")).strip()
    if not name:
        return err("missing name", 400)
    color = int(data.get("color", 0) or 0)
    t = db.scalar(select(Tag).where(Tag.address_book_id == book.id, Tag.name == name))
    if t is None:
        db.add(Tag(address_book_id=book.id, name=name, color=color))
    else:
        t.color = color
    db.commit()
    return ok_empty()


@router.put("/api/ab/tag/rename/{guid}")
async def ab_tag_rename(guid: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    try:
        data = await request.json()
    except Exception:
        return err("bad json", 400)
    old, new = str(data.get("old", "")), str(data.get("new", "")).strip()
    if not old or not new:
        return err("missing names", 400)
    if db.scalar(select(Tag).where(Tag.address_book_id == book.id, Tag.name == new)) is not None:
        return err(f"Tag {new} already exists", 409)
    t = db.scalar(select(Tag).where(Tag.address_book_id == book.id, Tag.name == old))
    if t is None:
        return err("not found", 404)
    t.name = new
    db.commit()
    return ok_empty()


@router.put("/api/ab/tag/update/{guid}")
async def ab_tag_update(guid: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    try:
        data = await request.json()
    except Exception:
        return err("bad json", 400)
    name = str(data.get("name", ""))
    t = db.scalar(select(Tag).where(Tag.address_book_id == book.id, Tag.name == name))
    if t is None:
        return err("not found", 404)
    t.color = int(data.get("color", 0) or 0)
    db.commit()
    return ok_empty()


@router.delete("/api/ab/tag/{guid}")
async def ab_tag_delete(guid: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, guid)
    if book is None:
        return err("no such address book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    try:
        names = await request.json()
    except Exception:
        return err("bad json", 400)
    if not isinstance(names, list):
        return err("expected tag list", 400)
    for name in names:
        t = db.scalar(select(Tag).where(Tag.address_book_id == book.id, Tag.name == str(name)))
        if t is not None:
            db.delete(t)  # entry_tags cascade
    db.commit()
    return ok_empty()


# --- device heartbeat (presence source, see PresenceService) ---

@router.post("/api/heartbeat")
async def heartbeat(request: Request, db: Session = Depends(get_db)):
    """Unauthenticated by design: controlled devices post {"id","uuid","ver",...}
    every 15s when a custom api-server is configured. We stamp last_seen on
    matching entries and return {} (client only looks for sysinfo/disconnect keys)."""
    try:
        data = await request.json()
    except Exception:
        return {}
    rid = str(data.get("id", "")) if isinstance(data, dict) else ""
    if rid:
        presence_svc.record_heartbeat(db, rid)
    return {}


# --- legacy stubs ---

@router.get("/api/ab")
async def legacy_get(user: User = Depends(current_user)):
    return Response(content="null", media_type="application/json")


@router.post("/api/ab")
async def legacy_post(user: User = Depends(current_user)):
    return ok_empty()


# --- group panel stubs (outside MVP, silence client errors) ---

@router.get("/api/device-group/accessible")
async def group_device_groups(user: User = Depends(current_user)):
    return {"total": 0, "data": []}


@router.get("/api/users")
async def group_users(user: User = Depends(current_user)):
    return {"total": 0, "data": []}


@router.get("/api/peers")
async def group_peers(user: User = Depends(current_user)):
    return {"total": 0, "data": []}
