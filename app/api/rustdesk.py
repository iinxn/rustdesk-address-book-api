"""RustDesk Client compatibility API. Mirrors Server Pro shapes from
docs/en.md §5. Error shape is always {"error": msg}."""
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import bearer_token, current_user
from app.core.config import settings
from app.core.middleware import client_ip
from app.db.session import SessionLocal, get_db
from app.models.models import AddressBook, AddressBookEntry, EntryTag, Tag, User
from app.schemas.rustdesk import LoginIn
from app.core.validators import validate_rustdesk_id
from app.services import ab as ab_svc
from app.services import audit as audit_svc
from app.services import device_info as info_svc
from app.services import presence as presence_svc
from app.services.auth import authenticate, create_session, destroy_session, user_by_token

router = APIRouter()


def err(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": msg})


def ok_empty() -> Response:
    return Response(status_code=200)


# --- auth ---

@router.post("/api/login")
async def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = authenticate(db, body.username, body.password)
    if user is None:
        audit_svc.write_event(
            category="auth",
            event_type="auth.login_failed",
            outcome="denied",
            actor_type="anonymous",
            source_ip=client_ip(request),
            destination="api",
            http_method="POST",
            route="/api/login",
            status_code=401,
            details={"username": body.username},
        )
        return err("Invalid username or password", 401)
    valid_device_id = (body.id or "").strip() if validate_rustdesk_id(body.id) is None else ""
    s = create_session(db, user, device_id=valid_device_id)
    login_details = {"type": body.type}
    if valid_device_id:
        # Same id the client later registers on rendezvous; safe, not a secret.
        login_details["device_id"] = valid_device_id
    audit_svc.write_event(
        category="auth",
        event_type="auth.login",
        outcome="success",
        actor=user,
        source_ip=client_ip(request),
        destination="api",
        http_method="POST",
        route="/api/login",
        status_code=200,
        details=login_details,
    )
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
async def logout(request: Request, db: Session = Depends(get_db), token: str = Depends(bearer_token)):
    user = user_by_token(db, token) if token else None
    if token:
        destroy_session(db, token)
    if user is not None:
        audit_svc.write_event(
            category="auth",
            event_type="auth.logout",
            outcome="success",
            actor=user,
            source_ip=client_ip(request),
            destination="api",
            http_method="POST",
            route="/api/logout",
            status_code=200,
        )
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
        db.flush()
        audit_svc.record(
            db,
            category="data",
            event_type="book.create",
            actor=user,
            destination="api",
            target_type="book",
            target_id=book.id,
            details={"name": book.name, "type": book.type, "source": "rustdesk_client"},
        )
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
    if (rid_err := validate_rustdesk_id(rid)) is not None:
        return err(rid_err, 422 if rid_err != "missing id" else 400)
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
    audit_svc.record(
        db,
        category="data",
        event_type="entry.create",
        actor=user,
        destination="api",
        target_type="device",
        target_id=e.rustdesk_id,
        details={
            "entry_id": e.id,
            "book_id": book.id,
            "alias": e.alias,
            "tags": [str(t) for t in tags] if isinstance(tags, list) else [],
            "source": "rustdesk_client",
            "password_set": bool(e.password_encrypted),
        },
    )
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
    before = {
        "alias": e.alias,
        "note": e.note,
        "username": e.username,
        "hostname": e.hostname,
        "platform": e.platform,
        "hash": e.hash_value,
        "password": "set" if e.password_encrypted else "",
    }
    before_tags = ab_svc.entry_tag_names(db, e.id)
    ab_svc.apply_peer_update(db, e, data, book)
    after_tags = ab_svc.entry_tag_names(db, e.id)
    fields = audit_svc.diff_fields(
        {k: before[k] for k in ("alias", "note", "username", "hostname", "platform")},
        {k: getattr(e, k) for k in ("alias", "note", "username", "hostname", "platform")},
    )
    if before["hash"] != e.hash_value:
        fields["hash"] = "changed"
    if before["password"] != ("set" if e.password_encrypted else ""):
        fields["password_changed"] = True
    if before_tags != after_tags:
        fields["tags"] = {"from": before_tags, "to": after_tags}
    audit_svc.record(
        db,
        category="data",
        event_type="entry.update",
        actor=user,
        destination="api",
        target_type="device",
        target_id=e.rustdesk_id,
        details={
            "entry_id": e.id,
            "book_id": book.id,
            "fields": fields,
            "source": "rustdesk_client",
        },
    )
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
    deleted: list[str] = []
    for rid in ids:
        e = db.scalar(
            select(AddressBookEntry).where(
                AddressBookEntry.address_book_id == book.id, AddressBookEntry.rustdesk_id == str(rid)
            )
        )
        if e is not None:
            db.delete(e)
            deleted.append(e.rustdesk_id)
    audit_svc.record(
        db,
        category="data",
        event_type="entry.bulk_delete",
        outcome="success" if deleted else "unknown",
        actor=user,
        destination="api",
        target_type="device",
        details={
            "book_id": book.id,
            "deleted_count": len(deleted),
            "sample_deleted": deleted[:10],
            "source": "rustdesk_client",
        },
    )
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
        t = Tag(address_book_id=book.id, name=name, color=color)
        db.add(t)
        db.flush()
        event_type = "tag.create"
        details = {"book_id": book.id, "name": t.name, "color": t.color}
    else:
        old_color = t.color
        t.color = color
        event_type = "tag.update"
        details = {
            "book_id": book.id,
            "fields": audit_svc.diff_fields(
                {"color": str(old_color)}, {"color": str(t.color)}
            ),
        }
    audit_svc.record(
        db,
        category="data",
        event_type=event_type,
        actor=user,
        destination="api",
        target_type="tag",
        target_id=t.id,
        details={**details, "source": "rustdesk_client"},
    )
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
    audit_svc.record(
        db,
        category="data",
        event_type="tag.update",
        actor=user,
        destination="api",
        target_type="tag",
        target_id=t.id,
        details={
            "book_id": book.id,
            "fields": audit_svc.diff_fields({"name": old}, {"name": new}),
            "source": "rustdesk_client",
        },
    )
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
    old_color = t.color
    t.color = int(data.get("color", 0) or 0)
    audit_svc.record(
        db,
        category="data",
        event_type="tag.update",
        actor=user,
        destination="api",
        target_type="tag",
        target_id=t.id,
        details={
            "book_id": book.id,
            "fields": audit_svc.diff_fields(
                {"color": str(old_color)}, {"color": str(t.color)}
            ),
            "source": "rustdesk_client",
        },
    )
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
    deleted: list[dict] = []
    for name in names:
        t = db.scalar(select(Tag).where(Tag.address_book_id == book.id, Tag.name == str(name)))
        if t is not None:
            deleted.append({"id": t.id, "name": t.name})
            db.delete(t)  # entry_tags cascade
    audit_svc.record(
        db,
        category="data",
        event_type="tag.bulk_delete",
        outcome="success" if deleted else "unknown",
        actor=user,
        destination="api",
        target_type="tag",
        details={
            "book_id": book.id,
            "deleted_count": len(deleted),
            "sample_deleted": deleted[:10],
            "source": "rustdesk_client",
        },
    )
    db.commit()
    return ok_empty()


# --- device heartbeat + sysinfo (presence/inventory sources, see services) ---

def _record_heartbeat(rid: str, version: str, ip: str) -> bool:
    """Own session in a worker thread: never block the event loop on SQLite."""
    with SessionLocal() as db:
        presence_svc.record_heartbeat(db, rid)
        info_svc.record_heartbeat(db, rid, version, ip)
        return info_svc.take_refresh(rid)


@router.post("/api/heartbeat")
async def heartbeat(request: Request):
    """Unauthenticated by design: controlled devices post {"id","uuid","ver",...}
    every 15s when a custom api-server is configured. We stamp last_seen on
    matching entries, refresh liveness of an existing info row, and optionally
    ask for a sysinfo re-upload ({"sysinfo": true}).

    DB work runs in Starlette's threadpool: a burst of 800 devices must not
    serialise on the event loop or exhaust the SQLite connection pool.
    """
    try:
        data = await request.json()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    rid = str(data.get("id", "")).strip()
    if rid and validate_rustdesk_id(rid) is None:
        refresh = await run_in_threadpool(
            _record_heartbeat, rid, str(data.get("ver", "")), client_ip(request)
        )
        if refresh:
            return {"sysinfo": True}
    return {}


@router.post("/api/sysinfo_ver")
async def sysinfo_ver():
    """Version probe used by the stock client for public API servers."""
    return PlainTextResponse(info_svc.SYSINFO_VER,
                             headers={"Cache-Control": "no-store"})


def _persist_sysinfo(rid: str, data: dict, ip: str) -> None:
    """Own session in a worker thread: a first-boot burst must not block users."""
    approved = info_svc.take_approval(rid)
    with SessionLocal() as db:
        info_svc.save_sysinfo(db, rid, data, ip, force=approved)


@router.post("/api/sysinfo")
async def sysinfo(request: Request):
    """Stock-client inventory upload (no auth by design).

    Only a small whitelist is stored; `uuid` and all preset/option keys (some
    carry address-book passwords) are discarded. The exact response string is
    part of the client contract.

    The client also re-sends this on its own (startup, Windows user login) and
    retries every ~2 minutes unless it sees `SYSINFO_UPDATED`. So duplicates
    are acknowledged but not written: a card is only refreshed via the panel
    button, which arms a one-shot approval on the next heartbeat.
    """
    raw = await request.body()
    if len(raw) > 32 * 1024:
        return PlainTextResponse("ID_NOT_FOUND", status_code=413)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return PlainTextResponse("ID_NOT_FOUND", status_code=400)
    if not isinstance(data, dict):
        return PlainTextResponse("ID_NOT_FOUND", status_code=400)
    rid = str(data.get("id", "")).strip()
    if validate_rustdesk_id(rid) is not None:
        # Pro returns ID_NOT_FOUND for unknown/invalid devices; the client then
        # retries after its normal timeout. Never echo the supplied value.
        return PlainTextResponse("ID_NOT_FOUND",
                                 headers={"Cache-Control": "no-store"})
    await run_in_threadpool(_persist_sysinfo, rid, data, client_ip(request))
    return PlainTextResponse("SYSINFO_UPDATED",
                             headers={"Cache-Control": "no-store"})


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
