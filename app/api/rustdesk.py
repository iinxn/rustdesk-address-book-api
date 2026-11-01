"""RustDesk client compatibility API (`/api/*`).

Mirrors the Server Pro shapes from docs/en.md §5; the stock client is not
patched, so keys, status codes, messages and empty 200 bodies are a contract
(AGENTS.md §1). Errors are always `{"error": msg}`.

Routes that touch SQLite are plain `def` (FastAPI runs them in the
threadpool); only the unauthenticated high-rate device routes are `async` and
hand their DB work to the threadpool explicitly.
"""
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import BAD_JSON, bearer_token, current_user, json_body
from app.api.errors import ClientError
from app.core.config import settings
from app.core.middleware import client_ip
from app.core.validators import validate_rustdesk_id
from app.db.session import SessionLocal, get_db
from app.models.models import AddressBook, Tag, User
from app.schemas.rustdesk import LoginIn
from app.services import ab as ab_svc
from app.services import audit as audit_svc
from app.services import device_info as info_svc
from app.services import presence as presence_svc
from app.services.auth import (
    AuthBusy,
    authenticate_async,
    create_session,
    destroy_session,
    user_by_token,
)

router = APIRouter()

SOURCE = "rustdesk_client"
SYSINFO_MAX_BYTES = 32 * 1024


def ok_empty() -> Response:
    return Response(status_code=200)


def _user_payload(user: User) -> dict:
    return {
        "name": user.username,
        "display_name": user.display_name or "",
        "avatar": "",
        "email": "",
        "note": "",
        "status": 1,
        "is_admin": user.is_admin,
    }


def _book(db: Session, user: User, guid: str, *, write: bool = False) -> AddressBook:
    access = ab_svc.book_access(db, user, guid)
    if access is None:
        raise ClientError(404, "no such address book")
    if write and not access.writable:
        raise ClientError(403, "read-only")
    return access.book


def _object(data: Any) -> dict:
    """Client payload that must be a JSON object."""
    if data is BAD_JSON or not isinstance(data, dict):
        raise ClientError(400, "bad json")
    return data


def _list(data: Any, what: str) -> list:
    if data is BAD_JSON:
        raise ClientError(400, "bad json")
    if not isinstance(data, list):
        raise ClientError(400, f"expected {what} list")
    return data


def _color(value: Any) -> int:
    color = ab_svc.parse_color(value)
    if color is None:
        raise ClientError(400, "invalid color")
    return color


def _record(db: Session, user: User, event_type: str, *, target_type: str,
            target_id: str = "", outcome: str = "success", **details: Any) -> None:
    audit_svc.record(db, category="data", event_type=event_type, outcome=outcome, actor=user,
                     target_type=target_type, target_id=target_id,
                     details={**details, "source": SOURCE})


# --- auth ---

@router.post("/api/login")
async def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    # bcrypt is awaited in its own small pool and SQLite work goes to the
    # threadpool: a burst of failed logins must not freeze the event loop
    # (heartbeats of every device are served by the same loop).
    ip = client_ip(request)
    try:
        user = await authenticate_async(db, body.username, body.password)
    except AuthBusy:
        await run_in_threadpool(audit_svc.note_rate_limited, "/api/login", ip, 5, True)
        return JSONResponse(status_code=429, content={"error": "too many login attempts"},
                            headers={"Retry-After": "5"})
    event = dict(category="auth", source_ip=ip, destination="api", http_method="POST",
                 route="/api/login")
    if user is None:
        await run_in_threadpool(
            audit_svc.write_event, **event, event_type="auth.login_failed", outcome="denied",
            actor_type="anonymous", status_code=401, details={"username": body.username},
        )
        raise ClientError(401, "Invalid username or password")
    device_id = (body.id or "").strip() if validate_rustdesk_id(body.id) is None else ""
    session = await run_in_threadpool(create_session, db, user, device_id)
    details = {"type": body.type}
    if device_id:
        # Same id the client later registers on rendezvous; safe, not a secret.
        details["device_id"] = device_id
    await run_in_threadpool(
        audit_svc.write_event, **event, event_type="auth.login", outcome="success",
        actor=user, status_code=200, details=details,
    )
    return {"access_token": session.token, "type": "access_token", "user": _user_payload(user)}


@router.post("/api/currentUser")
def current_user_info(user: User = Depends(current_user)):
    return _user_payload(user)


@router.post("/api/logout")
def logout(request: Request, db: Session = Depends(get_db), token: str = Depends(bearer_token)):
    user = user_by_token(db, token) if token else None
    if token:
        destroy_session(db, token)
    if user is not None:
        audit_svc.write_event(
            category="auth", event_type="auth.logout", outcome="success", actor=user,
            source_ip=client_ip(request), destination="api", http_method="POST",
            route="/api/logout", status_code=200,
        )
    return ok_empty()


@router.get("/api/login-options")
async def login_options():
    return []


# --- discovery ---

@router.post("/api/ab/settings")
def ab_settings(user: User = Depends(current_user)):
    return {"max_peer_one_ab": settings.max_peer_one_ab}


@router.post("/api/ab/personal")
def ab_personal(user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.personal_book(db, user)
    if book is None:  # defensive: user created before auto-book logic
        book = AddressBook(name="My address book", type="personal", owner_user_id=user.id)
        db.add(book)
        db.flush()
        _record(db, user, "book.create", target_type="book", target_id=book.id,
                name=book.name, type=book.type)
        db.commit()
    return {"guid": book.id}


@router.post("/api/ab/shared/profiles")
def ab_shared_profiles(
    current: int = 1, pageSize: int = 100,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    profiles = ab_svc.shared_profiles(db, user)
    start = (max(current, 1) - 1) * pageSize
    return {
        "total": len(profiles),
        "data": [
            {"guid": a.book.id, "name": a.book.name, "owner": a.book.owner_user_id,
             "note": "", "info": None, "rule": a.rule}
            for a in profiles[start:start + pageSize]
        ],
    }


# --- peers ---

@router.post("/api/ab/peers")
def ab_peers(
    current: int = 1, pageSize: int = 100, ab: str = "",
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    book = _book(db, user, ab)
    total, data = ab_svc.peers_page(db, book, (max(current, 1) - 1) * pageSize, pageSize)
    return {"total": total, "data": data}


@router.post("/api/ab/peer/add/{guid}")
def ab_peer_add(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                payload: Any = Depends(json_body)):
    book = _book(db, user, guid, write=True)
    data = _object(payload)
    rid = str(data.get("id", "")).strip()
    tags = data.get("tags")
    tag_names = [str(t) for t in tags] if isinstance(tags, list) else []
    personal = book.type == "personal"
    try:
        entry = ab_svc.add_entry(
            db, book, rid,
            alias=str(data.get("alias", "")),
            note=str(data.get("note", "")),
            username=str(data.get("username", "")),
            hostname=str(data.get("hostname", "")),
            platform=str(data.get("platform", "")),
            hash_value=str(data.get("hash", "")) if personal else "",
            password="" if personal else str(data.get("password", "")),
            tags=tag_names,
        )
    except ab_svc.EntryError as exc:
        if exc.code == "invalid_id":
            raise ClientError(400 if exc.message == "missing id" else 422, exc.message) from None
        if exc.code == "duplicate":
            raise ClientError(409, f"{rid} already exists") from None
        raise ClientError(403, "exceed_max_devices") from None
    _record(db, user, "entry.create", target_type="device", target_id=entry.rustdesk_id,
            entry_id=entry.id, book_id=book.id, alias=entry.alias, tags=tag_names,
            password_set=bool(entry.password_encrypted))
    db.commit()
    return ok_empty()


@router.put("/api/ab/peer/update/{guid}")
def ab_peer_update(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                   payload: Any = Depends(json_body)):
    book = _book(db, user, guid, write=True)
    data = _object(payload)
    rid = str(data.get("id", "")).strip()
    if not rid:
        raise ClientError(400, "missing id")
    entry = ab_svc.find_entry(db, book.id, rid)
    if entry is None:
        raise ClientError(404, "not found")
    text_fields = ("alias", "note", "username", "hostname", "platform")
    before = {k: getattr(entry, k) for k in text_fields}
    before_hash, before_password = entry.hash_value, bool(entry.password_encrypted)
    before_tags = ab_svc.entry_tag_names(db, entry.id)
    ab_svc.apply_peer_update(db, entry, data, book)
    after_tags = ab_svc.entry_tag_names(db, entry.id)
    fields = audit_svc.diff_fields(before, {k: getattr(entry, k) for k in text_fields})
    if before_hash != entry.hash_value:
        fields["hash"] = "changed"
    if before_password != bool(entry.password_encrypted):
        fields["password_changed"] = True
    if before_tags != after_tags:
        fields["tags"] = {"from": before_tags, "to": after_tags}
    _record(db, user, "entry.update", target_type="device", target_id=entry.rustdesk_id,
            entry_id=entry.id, book_id=book.id, fields=fields)
    db.commit()
    return ok_empty()


@router.delete("/api/ab/peer/{guid}")
def ab_peer_delete(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                   payload: Any = Depends(json_body)):
    book = _book(db, user, guid, write=True)
    ids = _list(payload, "id")
    deleted: list[str] = []
    for rid in ids:
        entry = ab_svc.find_entry(db, book.id, str(rid))
        if entry is not None:
            db.delete(entry)
            deleted.append(entry.rustdesk_id)
    _record(db, user, "entry.bulk_delete", target_type="device",
            outcome="success" if deleted else "unknown", book_id=book.id,
            deleted_count=len(deleted), sample_deleted=deleted[:10])
    db.commit()
    return ok_empty()


# --- tags ---

def _tag(db: Session, book: AddressBook, name: str) -> Tag | None:
    return db.scalar(select(Tag).where(Tag.address_book_id == book.id, Tag.name == name))


@router.post("/api/ab/tags/{guid}")
def ab_tags(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = _book(db, user, guid)
    tags = db.scalars(select(Tag).where(Tag.address_book_id == book.id).order_by(Tag.name))
    return [{"name": t.name, "color": t.color} for t in tags]


@router.post("/api/ab/tag/add/{guid}")
def ab_tag_add(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
               payload: Any = Depends(json_body)):
    book = _book(db, user, guid, write=True)
    data = _object(payload)
    name = str(data.get("name", "")).strip()
    if not name:
        raise ClientError(400, "missing name")
    color = _color(data.get("color", 0))
    tag = _tag(db, book, name)
    if tag is None:
        tag = Tag(address_book_id=book.id, name=name, color=color)
        db.add(tag)
        db.flush()
        _record(db, user, "tag.create", target_type="tag", target_id=tag.id,
                book_id=book.id, name=tag.name, color=tag.color)
    else:
        old_color, tag.color = tag.color, color
        _record(db, user, "tag.update", target_type="tag", target_id=tag.id, book_id=book.id,
                fields=audit_svc.diff_fields({"color": str(old_color)}, {"color": str(color)}))
    db.commit()
    return ok_empty()


@router.put("/api/ab/tag/rename/{guid}")
def ab_tag_rename(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                  payload: Any = Depends(json_body)):
    book = _book(db, user, guid, write=True)
    data = _object(payload)
    old, new = str(data.get("old", "")), str(data.get("new", "")).strip()
    if not old or not new:
        raise ClientError(400, "missing names")
    if _tag(db, book, new) is not None:
        raise ClientError(409, f"Tag {new} already exists")
    tag = _tag(db, book, old)
    if tag is None:
        raise ClientError(404, "not found")
    tag.name = new
    _record(db, user, "tag.update", target_type="tag", target_id=tag.id, book_id=book.id,
            fields=audit_svc.diff_fields({"name": old}, {"name": new}))
    db.commit()
    return ok_empty()


@router.put("/api/ab/tag/update/{guid}")
def ab_tag_update(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                  payload: Any = Depends(json_body)):
    book = _book(db, user, guid, write=True)
    data = _object(payload)
    tag = _tag(db, book, str(data.get("name", "")))
    if tag is None:
        raise ClientError(404, "not found")
    color = _color(data.get("color", 0))
    old_color, tag.color = tag.color, color
    _record(db, user, "tag.update", target_type="tag", target_id=tag.id, book_id=book.id,
            fields=audit_svc.diff_fields({"color": str(old_color)}, {"color": str(color)}))
    db.commit()
    return ok_empty()


@router.delete("/api/ab/tag/{guid}")
def ab_tag_delete(guid: str, user: User = Depends(current_user), db: Session = Depends(get_db),
                  payload: Any = Depends(json_body)):
    book = _book(db, user, guid, write=True)
    names = _list(payload, "tag")
    deleted: list[dict] = []
    for name in names:
        tag = _tag(db, book, str(name))
        if tag is not None:
            deleted.append({"id": tag.id, "name": tag.name})
            db.delete(tag)  # entry_tags cascade
    _record(db, user, "tag.bulk_delete", target_type="tag",
            outcome="success" if deleted else "unknown", book_id=book.id,
            deleted_count=len(deleted), sample_deleted=deleted[:10])
    db.commit()
    return ok_empty()


# --- device heartbeat + sysinfo (presence/inventory sources, see services) ---

_heartbeats = presence_svc.HeartbeatWriter(SessionLocal)


def _record_heartbeat(rid: str, version: str, ip: str) -> bool:
    _heartbeats.record(rid, version, ip)
    return info_svc.take_refresh(rid)


@router.post("/api/heartbeat")
async def heartbeat(request: Request):
    """Unauthenticated by design: controlled devices post {"id","uuid","ver",...}
    every 15s when a custom api-server is configured. We stamp last_seen on
    matching entries, refresh liveness of an existing info row, and optionally
    ask for a sysinfo re-upload ({"sysinfo": true}).

    DB work runs in Starlette's threadpool: a burst of 800 devices must not
    serialise on the event loop.
    """
    try:
        data = await request.json()
    except ValueError:
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


def _sysinfo_reply(text: str, status: int = 200) -> PlainTextResponse:
    return PlainTextResponse(text, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/api/sysinfo_ver")
async def sysinfo_ver():
    """Version probe used by the stock client for public API servers."""
    return _sysinfo_reply(info_svc.SYSINFO_VER)


def _persist_sysinfo(rid: str, data: dict, ip: str) -> None:
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
    if len(raw) > SYSINFO_MAX_BYTES:
        return PlainTextResponse("ID_NOT_FOUND", status_code=413)
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return PlainTextResponse("ID_NOT_FOUND", status_code=400)
    if not isinstance(data, dict):
        return PlainTextResponse("ID_NOT_FOUND", status_code=400)
    rid = str(data.get("id", "")).strip()
    if validate_rustdesk_id(rid) is not None:
        # Pro returns ID_NOT_FOUND for unknown/invalid devices; the client then
        # retries after its normal timeout. Never echo the supplied value.
        return _sysinfo_reply("ID_NOT_FOUND")
    await run_in_threadpool(_persist_sysinfo, rid, data, client_ip(request))
    return _sysinfo_reply("SYSINFO_UPDATED")


# --- legacy stubs ---

@router.get("/api/ab")
async def legacy_get(user: User = Depends(current_user)):
    return Response(content="null", media_type="application/json")


@router.post("/api/ab")
async def legacy_post(user: User = Depends(current_user)):
    return ok_empty()


# --- group panel stubs (outside MVP, silence client errors) ---

@router.get("/api/device-group/accessible")
@router.get("/api/users")
@router.get("/api/peers")
async def group_stub(user: User = Depends(current_user)):
    return {"total": 0, "data": []}
