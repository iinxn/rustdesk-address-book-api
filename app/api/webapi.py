"""Internal Web Panel JSON API (/api/v1/*). Bearer auth, same tokens.

Extended shapes (tag objects, presence, counts) live ONLY here;
RustDesk-compatible /api/ab/* is untouched.
"""
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import settings
from app.core.crypto import encrypt_password
from app.core.validators import validate_rustdesk_id
from app.models.models import (
    AddressBook,
    AddressBookEntry,
    DeviceInfo,
    DiscoveredDevice,
    EntryTag,
    Tag,
    User,
)
from app.schemas.panel import (
    BulkIdsIn,
    BulkTagsIn,
    DiscoveredAddIn,
    EntryIn,
    TagIn,
    UserIn,
)
from app.services import ab as ab_svc
from app.services import device_info as info_svc
from app.services import presence as presence_svc
from app.db.session import get_db

router = APIRouter(prefix="/api/v1")

MAX_BULK_IDS = 500
MAX_BULK_TAGS = 20


def err(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": msg})


def books_visible(db: Session, user: User) -> list[AddressBook]:
    if user.is_admin:
        return list(db.scalars(select(AddressBook).order_by(AddressBook.name)))
    ids = {b.id for b, _ in ab_svc.shared_profiles(db, user)}
    own = list(db.scalars(select(AddressBook).where(AddressBook.owner_user_id == user.id)))
    ids.update(b.id for b in own)
    if not ids:
        return []
    return list(db.scalars(select(AddressBook).where(AddressBook.id.in_(ids)).order_by(AddressBook.name)))


def entry_out(db: Session, e: AddressBookEntry, info: DeviceInfo | None = None) -> dict:
    state, last_seen = presence_svc.status_of(e)
    tags = db.scalars(select(Tag).join(EntryTag, EntryTag.tag_id == Tag.id).where(EntryTag.entry_id == e.id).order_by(Tag.name)).all()
    return {
        "id": e.id,
        "rustdesk_id": e.rustdesk_id,
        "alias": e.alias,
        "note": e.note,
        "tags": [t.name for t in tags],
        "tag_objs": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
        "presence": state,
        "last_seen": last_seen,
        "password_configured": bool(e.password_encrypted),
        # Address-book metadata augmented by a client-uploaded report when one
        # exists. Fields stay empty/null when the source did not provide them.
        "hostname": e.hostname or (info.hostname if info else ""),
        "username": e.username or (info.username if info else ""),
        "platform": e.platform,
        "ip": (info.ip or None) if info else None,
        "os": (info.os_name or info.os or None) if info else None,
        "has_info": bool(info and info.collected_at),
        "info_updated_at": info.collected_at.isoformat() if info and info.collected_at else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _dedupe_ids(raw: list[str]) -> list[str] | None:
    """Deduplicate preserving order; None means "over the server-side cap"."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) > MAX_BULK_IDS:
            return None
    return out


def _clean_tag_names(raw: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip()
        if not name or len(name) > 64 or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= MAX_BULK_TAGS:
            break
    return out


def _books_for_rids(db: Session, user: User, rids: list[str]) -> dict[str, list[dict]]:
    """Map rustdesk_id -> visible books containing it (one query for a page)."""
    if not rids:
        return {}
    books = books_visible(db, user)
    if not books:
        return {}
    by_id = {b.id: b for b in books}
    rows = db.execute(
        select(AddressBookEntry.rustdesk_id, AddressBookEntry.address_book_id).where(
            AddressBookEntry.address_book_id.in_(list(by_id)),
            AddressBookEntry.rustdesk_id.in_(rids),
        )
    ).all()
    out: dict[str, list[dict]] = defaultdict(list)
    for rid, bid in rows:
        book = by_id.get(bid)
        if book is not None:
            out[rid].append({"id": book.id, "name": book.name})
    for value in out.values():
        value.sort(key=lambda x: x["name"].lower())
    return dict(out)


def _discovered_out(row: DiscoveredDevice, info: DeviceInfo | None,
                    in_books: list[dict]) -> dict:
    return {
        "rustdesk_id": row.rustdesk_id,
        "first_seen": row.first_seen.isoformat() if row.first_seen else None,
        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        "last_connected": row.last_connected.isoformat() if row.last_connected else None,
        "last_disconnected": row.last_disconnected.isoformat() if row.last_disconnected else None,
        "last_ip": row.last_ip,
        "source": row.source,
        "online": bool(row.online),
        "seen_count": row.seen_count,
        "in_books": in_books,
        "info": info_svc.info_out(info),
    }


def _book_counts(db: Session, bid: str) -> dict:
    entries = list(db.scalars(select(AddressBookEntry).where(AddressBookEntry.address_book_id == bid)))
    c = {"devices": len(entries), "online": 0, "offline": 0, "unknown": 0}
    for e in entries:
        c[presence_svc.status_of(e)[0]] += 1
    return c


@router.get("/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    total = {"devices": 0, "online": 0, "offline": 0, "unknown": 0}
    for b in books_visible(db, user):
        for k, v in _book_counts(db, b.id).items():
            total[k] += v
    # Discovery is server-wide (shim evidence), independent of the book model.
    total["discovered"] = db.scalar(select(func.count()).select_from(DiscoveredDevice)) or 0
    total["discovered_online"] = db.scalar(
        select(func.count()).select_from(DiscoveredDevice).where(DiscoveredDevice.online.is_(True))
    ) or 0
    return total


@router.get("/address-books")
def list_books(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for b in books_visible(db, user):
        d = {"id": b.id, "name": b.name, "type": b.type,
             "rule": ab_svc.rule_for(db, user, b)}
        d.update(_book_counts(db, b.id))
        out.append(d)
    return out


@router.post("/address-books")
def create_book(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        return err("admin required", 403)
    name = str(body.get("name", "")).strip()
    if not name:
        return err("missing name", 400)
    b = AddressBook(name=name, type="shared", owner_user_id=user.id)
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"id": b.id, "name": b.name, "type": b.type}


@router.put("/address-books/{bid}")
def rename_book(bid: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, bid)
    if book is None:
        return err("no such book", 404)
    if book.type != "shared":
        return err("only shared books can be renamed", 400)
    if ab_svc.rule_for(db, user, book) < 3:
        return err("full control required", 403)
    name = str(body.get("name", "")).strip()
    if not name:
        return err("missing name", 400)
    book.name = name
    db.commit()
    return {"id": book.id, "name": book.name, "type": book.type}


@router.delete("/address-books/{bid}")
def delete_book(bid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, bid)
    if book is None:
        return err("no such book", 404)
    if book.type != "shared":
        return err("personal address book cannot be deleted", 400)
    if ab_svc.rule_for(db, user, book) < 3:
        return err("full control required", 403)
    db.delete(book)  # entries, tags and permissions cascade via ORM relationships
    db.commit()
    return {"ok": True}


@router.get("/address-books/{bid}/entries")
def list_entries(
    bid: str,
    search: str = "",
    tag: list[str] = Query(default=[]),
    mode: str = "or",
    untagged: bool = False,
    presence: str = "all",
    sort: str = "alias",
    order: str = "asc",
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    book = ab_svc.get_book_for_user(db, user, bid)
    if book is None:
        return err("no such book", 404)
    q = select(AddressBookEntry).where(AddressBookEntry.address_book_id == bid)
    if search:
        like = f"%{search}%"
        info_rids = select(DeviceInfo.rustdesk_id).where(or_(
            DeviceInfo.hostname.like(like),
            DeviceInfo.username.like(like),
            DeviceInfo.os.like(like),
        ))
        q = q.where(or_(AddressBookEntry.rustdesk_id.like(like), AddressBookEntry.alias.like(like),
                        AddressBookEntry.note.like(like), AddressBookEntry.hostname.like(like),
                        AddressBookEntry.username.like(like),
                        AddressBookEntry.rustdesk_id.in_(info_rids)))
    entries = list(db.scalars(q))
    enriched = [(e, ab_svc.entry_tag_names(db, e.id), presence_svc.status_of(e)[0]) for e in entries]
    if tag:
        wanted = set(tag)
        if mode == "and":
            enriched = [(e, n, s) for e, n, s in enriched if wanted <= set(n)]
        else:
            enriched = [(e, n, s) for e, n, s in enriched if wanted & set(n)]
    if untagged:
        enriched = [(e, n, s) for e, n, s in enriched if not n]
    if presence in ("online", "offline", "unknown"):
        enriched = [(e, n, s) for e, n, s in enriched if s == presence]
    reverse = order == "desc"
    if sort == "rustdesk_id":
        enriched.sort(key=lambda t: t[0].rustdesk_id, reverse=reverse)
    elif sort == "last_seen":
        enriched.sort(key=lambda t: (t[0].last_seen is None, t[0].last_seen), reverse=reverse)
    elif sort == "status":
        rank = {"online": 0, "unknown": 1, "offline": 2}
        enriched.sort(key=lambda t: (rank[t[2]], (t[0].alias or t[0].rustdesk_id).lower()), reverse=reverse)
    else:  # alias default
        enriched.sort(key=lambda t: (t[0].alias or t[0].rustdesk_id).lower(), reverse=reverse)
    total = len(enriched)
    page_size = min(max(page_size, 1), 200)
    start = (max(page, 1) - 1) * page_size
    page_rows = enriched[start:start + page_size]
    rids = [e.rustdesk_id for e, _, _ in page_rows]
    infos: dict[str, DeviceInfo] = {}
    if rids:
        infos = {
            i.rustdesk_id: i
            for i in db.scalars(select(DeviceInfo).where(DeviceInfo.rustdesk_id.in_(rids)))
        }
    return {
        "total": total,
        "data": [entry_out(db, e, infos.get(e.rustdesk_id)) for e, _, _ in page_rows],
    }


@router.post("/address-books/{bid}/entries")
def create_entry(bid: str, body: EntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, bid)
    if book is None:
        return err("no such book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    if (rid_err := validate_rustdesk_id(body.rustdesk_id)) is not None:
        return err(rid_err, 422)
    if db.scalar(select(AddressBookEntry).where(AddressBookEntry.address_book_id == bid, AddressBookEntry.rustdesk_id == body.rustdesk_id)):
        return err("duplicate", 409)
    e = AddressBookEntry(
        address_book_id=bid, rustdesk_id=body.rustdesk_id, alias=body.alias,
        note=body.note,
        password_encrypted=encrypt_password(body.password) if body.password else None,
    )
    db.add(e)
    db.flush()
    ab_svc.sync_entry_tags(db, e, body.tags)
    db.commit()
    db.refresh(e)
    return entry_out(db, e)


@router.get("/entries/{eid}")
def get_entry(eid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(AddressBookEntry, eid)
    if e is None:
        return err("not found", 404)
    if ab_svc.get_book_for_user(db, user, e.address_book_id) is None:
        return err("not found", 404)
    return entry_out(db, e, db.get(DeviceInfo, e.rustdesk_id))


@router.put("/entries/{eid}")
def update_entry(eid: str, body: EntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(AddressBookEntry, eid)
    if e is None:
        return err("not found", 404)
    book = ab_svc.get_book_for_user(db, user, e.address_book_id)
    if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    e.alias, e.note = body.alias, body.note
    if body.password:
        e.password_encrypted = encrypt_password(body.password)
    if body.rustdesk_id != e.rustdesk_id:
        if (rid_err := validate_rustdesk_id(body.rustdesk_id)) is not None:
            return err(rid_err, 422)
        dup = db.scalar(select(AddressBookEntry).where(AddressBookEntry.address_book_id == e.address_book_id, AddressBookEntry.rustdesk_id == body.rustdesk_id))
        if dup is not None:
            return err("duplicate", 409)
        e.rustdesk_id = body.rustdesk_id
    ab_svc.sync_entry_tags(db, e, body.tags)
    db.commit()
    return entry_out(db, e)


@router.delete("/entries/{eid}")
def delete_entry(eid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(AddressBookEntry, eid)
    if e is None:
        return err("not found", 404)
    book = ab_svc.get_book_for_user(db, user, e.address_book_id)
    if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    db.delete(e)
    db.commit()
    return {"ok": True}


# --- bulk operations (server-side authorization per entry) ---

@router.post("/entries/bulk-delete")
def bulk_delete(body: BulkIdsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Delete up to 500 entries in one request.

    Every ID is checked independently: UUID format, existence and write access
    to its book. Partial success is reported explicitly; duplicate IDs are
    collapsed, so a retried request cannot delete anything twice. Deleting an
    entry cascades only its entry_tags rows — tags and other entries survive.
    """
    ids = _dedupe_ids(body.ids)
    if ids is None:
        return err(f"too many ids (max {MAX_BULK_IDS})", 400)
    deleted: list[str] = []
    failed: list[dict] = []
    for eid in ids:
        if not _valid_uuid(eid):
            failed.append({"id": eid, "error": "invalid id"})
            continue
        e = db.get(AddressBookEntry, eid)
        if e is None:
            failed.append({"id": eid, "error": "not found"})
            continue
        book = ab_svc.get_book_for_user(db, user, e.address_book_id)
        if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
            failed.append({"id": eid, "error": "forbidden"})
            continue
        db.delete(e)
        deleted.append(eid)
    try:
        db.commit()
    except Exception:
        db.rollback()
        return err("bulk delete failed", 500)
    return {"deleted": deleted, "failed": failed}


@router.post("/entries/bulk-tags")
def bulk_tags(body: BulkTagsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Add and/or remove tags on many entries without touching other tags."""
    ids = _dedupe_ids(body.ids)
    if ids is None:
        return err(f"too many ids (max {MAX_BULK_IDS})", 400)
    add = _clean_tag_names(body.add)
    remove = _clean_tag_names(body.remove)
    if not add and not remove:
        return err("no valid tag names", 400)
    updated: list[str] = []
    failed: list[dict] = []
    for eid in ids:
        if not _valid_uuid(eid):
            failed.append({"id": eid, "error": "invalid id"})
            continue
        e = db.get(AddressBookEntry, eid)
        if e is None:
            failed.append({"id": eid, "error": "not found"})
            continue
        book = ab_svc.get_book_for_user(db, user, e.address_book_id)
        if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
            failed.append({"id": eid, "error": "forbidden"})
            continue
        # Remove first, then add: if a name is in both lists, "add" wins.
        if remove:
            ab_svc.remove_entry_tags(db, e, remove)
        if add:
            ab_svc.add_entry_tags(db, e, add)
        updated.append(eid)
    try:
        db.commit()
    except Exception:
        db.rollback()
        return err("bulk tag update failed", 500)
    return {"updated": updated, "failed": failed, "added": add, "removed": remove}


@router.get("/address-books/{bid}/tags")
def list_tags(bid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, bid)
    if book is None:
        return err("no such book", 404)
    usage = ab_svc.tag_usage(db, bid)
    tags = db.scalars(select(Tag).where(Tag.address_book_id == bid).order_by(Tag.name)).all()
    return [{"id": t.id, "name": t.name, "color": t.color, "devices": usage.get(t.id, 0)} for t in tags]


@router.post("/address-books/{bid}/tags")
def create_tag(bid: str, body: TagIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, bid)
    if book is None:
        return err("no such book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    if db.scalar(select(Tag).where(Tag.address_book_id == bid, Tag.name == body.name)):
        return err("duplicate", 409)
    t = Tag(address_book_id=bid, name=body.name, color=body.color)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "color": t.color, "devices": 0}


@router.put("/tags/{tid}")
def update_tag(tid: str, body: TagIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(Tag, tid)
    if t is None:
        return err("not found", 404)
    book = ab_svc.get_book_for_user(db, user, t.address_book_id)
    if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    if body.name != t.name and db.scalar(select(Tag).where(Tag.address_book_id == t.address_book_id, Tag.name == body.name)):
        return err("duplicate", 409)
    t.name, t.color = body.name, body.color
    db.commit()
    return {"id": t.id, "name": t.name, "color": t.color}


@router.delete("/tags/{tid}")
def delete_tag(tid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(Tag, tid)
    if t is None:
        return err("not found", 404)
    book = ab_svc.get_book_for_user(db, user, t.address_book_id)
    if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.put("/entries/{eid}/tags/{tid}")
def attach_tag(eid: str, tid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e, t = db.get(AddressBookEntry, eid), db.get(Tag, tid)
    if e is None or t is None or e.address_book_id != t.address_book_id:
        return err("not found", 404)
    book = ab_svc.get_book_for_user(db, user, e.address_book_id)
    if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    if db.get(EntryTag, (eid, tid)) is None:
        db.add(EntryTag(entry_id=eid, tag_id=tid))
        db.commit()
    return {"ok": True}


@router.delete("/entries/{eid}/tags/{tid}")
def detach_tag(eid: str, tid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(AddressBookEntry, eid)
    if e is None:
        return err("not found", 404)
    book = ab_svc.get_book_for_user(db, user, e.address_book_id)
    if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    r = db.get(EntryTag, (eid, tid))
    if r is not None:
        db.delete(r)
        db.commit()
    return {"ok": True}


# --- discovered devices (shim evidence) + device info (client uploads) ---

@router.get("/discovered")
def list_discovered(
    search: str = "",
    status: str = "all",
    page: int = 1,
    page_size: int = 50,
    only_unlinked: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    q = select(DiscoveredDevice).outerjoin(
        DeviceInfo, DeviceInfo.rustdesk_id == DiscoveredDevice.rustdesk_id
    )
    if only_unlinked:
        visible = [b.id for b in books_visible(db, user)]
        if visible:
            linked = select(AddressBookEntry.rustdesk_id).where(
                AddressBookEntry.address_book_id.in_(visible)
            )
            q = q.where(~DiscoveredDevice.rustdesk_id.in_(linked))
    if search:
        like = f"%{search}%"
        q = q.where(or_(
            DiscoveredDevice.rustdesk_id.like(like),
            DiscoveredDevice.last_ip.like(like),
            DeviceInfo.hostname.like(like),
            DeviceInfo.username.like(like),
            DeviceInfo.os.like(like),
        ))
    if status == "online":
        q = q.where(DiscoveredDevice.online.is_(True))
    elif status == "offline":
        q = q.where(DiscoveredDevice.online.is_(False))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    page_size = min(max(page_size, 1), 200)
    start = (max(page, 1) - 1) * page_size
    rows = list(db.scalars(
        q.order_by(DiscoveredDevice.last_seen.desc()).offset(start).limit(page_size)
    ))
    rids = [r.rustdesk_id for r in rows]
    infos: dict[str, DeviceInfo] = {}
    if rids:
        infos = {
            i.rustdesk_id: i
            for i in db.scalars(select(DeviceInfo).where(DeviceInfo.rustdesk_id.in_(rids)))
        }
    books = _books_for_rids(db, user, rids)
    return {
        "total": total,
        "data": [
            _discovered_out(r, infos.get(r.rustdesk_id), books.get(r.rustdesk_id, []))
            for r in rows
        ],
    }


@router.post("/discovered/{rid}/add")
def add_discovered(rid: str, body: DiscoveredAddIn,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Add a discovered ID to a book the caller may write, prefilled from sysinfo."""
    rid = rid.strip()
    if validate_rustdesk_id(rid) is not None:
        return err("invalid id", 422)
    book = ab_svc.get_book_for_user(db, user, body.book_id)
    if book is None:
        return err("no such book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    duplicate = db.scalar(select(AddressBookEntry).where(
        AddressBookEntry.address_book_id == book.id,
        AddressBookEntry.rustdesk_id == rid,
    ))
    if duplicate is not None:
        return err("already in this book", 409)
    if settings.max_peer_one_ab > 0:
        count = db.scalar(select(func.count()).select_from(AddressBookEntry).where(
            AddressBookEntry.address_book_id == book.id
        )) or 0
        if count >= settings.max_peer_one_ab:
            return err("exceed_max_devices", 403)
    info = db.get(DeviceInfo, rid)
    alias = body.alias.strip() or (info.hostname if info else "") or rid
    e = AddressBookEntry(
        address_book_id=book.id,
        rustdesk_id=rid,
        alias=alias[:128],
        note=body.note[:4000],
        hostname=(info.hostname if info else "")[:128],
        username=(info.username if info else "")[:128],
        platform="",
    )
    db.add(e)
    db.flush()
    ab_svc.sync_entry_tags(db, e, body.tags)
    db.commit()
    db.refresh(e)
    return entry_out(db, e, info)


@router.get("/device-info/{rid}")
def get_device_info(rid: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Merged card: address-book rows + discovery evidence + client sysinfo."""
    rid = rid.strip()
    if validate_rustdesk_id(rid) is not None:
        return err("invalid id", 422)
    info = db.get(DeviceInfo, rid)
    disc = db.scalar(select(DiscoveredDevice).where(DiscoveredDevice.rustdesk_id == rid))
    books = {b.id: b for b in books_visible(db, user)}
    entries: list[AddressBookEntry] = []
    if books:
        entries = list(db.scalars(select(AddressBookEntry).where(
            AddressBookEntry.rustdesk_id == rid,
            AddressBookEntry.address_book_id.in_(list(books)),
        )))
    # Non-admins may only inspect discovered IDs or devices in their books.
    if not user.is_admin and disc is None and not entries:
        return err("not found", 404)
    if info is None and disc is None and not entries:
        return err("not found", 404)

    in_books = _books_for_rids(db, user, [rid]).get(rid, [])
    entry_data = []
    for e in entries:
        item = entry_out(db, e, info)
        item["book_id"] = e.address_book_id
        item["book_name"] = books[e.address_book_id].name
        entry_data.append(item)
    online = bool(disc and disc.online) or any(x["presence"] == "online" for x in entry_data)
    stamps = []
    if disc and disc.last_seen:
        stamps.append(disc.last_seen)
    if info and info.last_heartbeat_at:
        stamps.append(info.last_heartbeat_at)
    if info and info.collected_at:
        stamps.append(info.collected_at)
    for e in entries:
        if e.last_seen:
            stamps.append(e.last_seen)
    sources = []
    if disc is not None:
        sources.append("discovery")
    if info is not None and info.collected_at is not None:
        sources.append("sysinfo")
    if entries:
        sources.append("address_book")
    return {
        "rustdesk_id": rid,
        "online": online,
        "last_seen": max(stamps).isoformat() if stamps else None,
        "last_ip": (disc.last_ip if disc else "") or (info.ip if info else ""),
        "discovered": _discovered_out(disc, info, in_books) if disc else None,
        "info": info_svc.info_out(info),
        "entries": entry_data,
        "sources": sources,
    }


@router.post("/device-info/{rid}/refresh")
def refresh_device_info(rid: str, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Ask the client to re-upload sysinfo on its next heartbeat.

    The flag is consumed once and expires after 30 minutes; it only works for
    devices that have a custom api-server configured (the stock client's
    heartbeat loop delivers it).
    """
    rid = rid.strip()
    if validate_rustdesk_id(rid) is not None:
        return err("invalid id", 422)
    disc = db.scalar(select(DiscoveredDevice).where(DiscoveredDevice.rustdesk_id == rid))
    books = {b.id for b in books_visible(db, user)}
    has_entry = False
    if books:
        has_entry = db.scalar(select(AddressBookEntry.id).where(
            AddressBookEntry.rustdesk_id == rid,
            AddressBookEntry.address_book_id.in_(list(books)),
        ).limit(1)) is not None
    if not user.is_admin and disc is None and not has_entry:
        return err("not found", 404)
    info_svc.request_refresh(rid)
    return {"ok": True, "expires_in": info_svc.REFRESH_TTL_SEC}


@router.delete("/discovered/{rid}")
def forget_discovered(rid: str, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Admin cleanup for polluted discovery rows (never touches books/info)."""
    if not user.is_admin:
        return err("admin required", 403)
    rid = rid.strip()
    if validate_rustdesk_id(rid) is not None:
        return err("invalid id", 422)
    row = db.scalar(select(DiscoveredDevice).where(DiscoveredDevice.rustdesk_id == rid))
    if row is None:
        return err("not found", 404)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        return err("admin required", 403)
    return [{"id": u.id, "username": u.username, "is_admin": u.is_admin, "is_disabled": u.is_disabled} for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users")
def create_panel_user(body: UserIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        return err("admin required", 403)
    if db.scalar(select(User).where(User.username == body.username)):
        return err("duplicate", 409)
    from app.services.auth import create_user
    u = create_user(db, body.username, body.password, body.is_admin)
    return {"id": u.id, "username": u.username, "is_admin": u.is_admin, "is_disabled": u.is_disabled}


@router.put("/users/{uid}")
def update_panel_user(uid: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Edit user: {username?, is_admin?, is_disabled?, password?}. Admin only."""
    if not user.is_admin:
        return err("admin required", 403)
    u = db.get(User, uid)
    if u is None:
        return err("not found", 404)
    if "username" in body:
        new_name = str(body["username"]).strip()
        if not new_name:
            return err("missing username", 400)
        if new_name != u.username and db.scalar(select(User).where(User.username == new_name)):
            return err("duplicate", 409)
        u.username = new_name
    if "is_admin" in body:
        if u.id == user.id and not body["is_admin"]:
            return err("cannot demote self", 400)
        u.is_admin = bool(body["is_admin"])
    revoke_sessions = False
    if "is_disabled" in body:
        if u.id == user.id and body["is_disabled"]:
            return err("cannot disable self", 400)
        u.is_disabled = bool(body["is_disabled"])
        revoke_sessions = revoke_sessions or u.is_disabled
    if body.get("password"):
        from app.core.security import hash_password
        u.password_hash = hash_password(str(body["password"]))
        revoke_sessions = True
    db.commit()
    if revoke_sessions:
        # SEC-007: disable and password rotation must kill every live Bearer
        # session of that user, not just the caller's. Panel cookies are
        # already invalidated by the is_disabled check in panel_user (SEC-001).
        from app.services.auth import destroy_user_sessions
        destroy_user_sessions(db, u.id)
    return {"id": u.id, "username": u.username, "is_admin": u.is_admin, "is_disabled": u.is_disabled}


@router.delete("/users/{uid}")
def delete_panel_user(uid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        return err("admin required", 403)
    u = db.get(User, uid)
    if u is None:
        return err("not found", 404)
    if u.id == user.id:
        return err("cannot delete self", 400)
    db.delete(u)
    db.commit()
    return {"ok": True}
