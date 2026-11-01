"""`/api/v1`: address books, entries, tags and bulk entry operations."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.errors import PanelError
from app.api.v1.common import (
    PREFIX,
    book_or_404,
    entry_for_write,
    entry_out,
    infos_for,
    is_uuid,
    one_entry_out,
    page_window,
    record,
    require_admin,
    writable_or_403,
)
from app.core.crypto import encrypt_password
from app.core.timeutil import utcnow
from app.db.session import get_db
from app.models.models import AddressBook, AddressBookEntry, DeviceInfo, DiscoveredDevice, EntryTag, Tag, User
from app.schemas.panel import BulkIdsIn, BulkTagsIn, EntryIn, TagIn
from app.services import ab as ab_svc
from app.services import audit as audit_svc
from app.services.ab import BookAccess
from app.services.presence import status_of

router = APIRouter(prefix=PREFIX)

MAX_BULK_IDS = 500
MAX_BULK_TAGS = 20
_STATUS_RANK = {"online": 0, "unknown": 1, "offline": 2}


def _entry_error(exc: ab_svc.EntryError) -> PanelError:
    if exc.code == "invalid_id":
        return PanelError(422, exc.message)
    if exc.code == "duplicate":
        return PanelError(409, "duplicate")
    return PanelError(403, "exceed_max_devices")


# --- books --------------------------------------------------------------------

@router.get("/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    total = {"devices": 0, "online": 0, "offline": 0, "unknown": 0}
    counts = ab_svc.book_counts(db, [a.book.id for a in ab_svc.visible_books(db, user)])
    for c in counts.values():
        for key in total:
            total[key] += c[key]
    # Discovery is server-wide (shim evidence), independent of the book model.
    online = func.sum(case((DiscoveredDevice.online.is_(True), 1), else_=0))
    discovered, discovered_online = db.execute(
        select(func.count(), online).select_from(DiscoveredDevice)).one()
    return {**total, "discovered": discovered or 0, "discovered_online": int(discovered_online or 0)}


@router.get("/address-books")
def list_books(user: User = Depends(current_user), db: Session = Depends(get_db)):
    books = ab_svc.visible_books(db, user)
    counts = ab_svc.book_counts(db, [a.book.id for a in books])
    return [{"id": a.book.id, "name": a.book.name, "type": a.book.type, "rule": a.rule,
             **counts[a.book.id]} for a in books]


def _book_name(body: dict) -> str:
    name = str(body.get("name", "")).strip()
    if not name:
        raise PanelError(400, "missing name")
    return name


def _managed_shared(db: Session, user: User, bid: str, personal_message: str) -> AddressBook:
    access = book_or_404(db, user, bid)
    if access.book.type != "shared":
        raise PanelError(400, personal_message)
    if not access.full_control:
        raise PanelError(403, "full control required")
    return access.book


@router.post("/address-books")
def create_book(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    book = AddressBook(name=_book_name(body), type="shared", owner_user_id=user.id)
    db.add(book)
    db.flush()
    record(db, user, "data", "book.create", target_type="book", target_id=book.id,
           details={"name": book.name, "type": book.type})
    db.commit()
    return {"id": book.id, "name": book.name, "type": book.type}


@router.put("/address-books/{bid}")
def rename_book(bid: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = _managed_shared(db, user, bid, "only shared books can be renamed")
    name = _book_name(body)
    old_name, book.name = book.name, name
    record(db, user, "data", "book.update", target_type="book", target_id=book.id,
           details={"fields": audit_svc.diff_fields({"name": old_name}, {"name": name})})
    db.commit()
    return {"id": book.id, "name": book.name, "type": book.type}


@router.delete("/address-books/{bid}")
def delete_book(bid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = _managed_shared(db, user, bid, "personal address book cannot be deleted")
    record(db, user, "data", "book.delete", target_type="book", target_id=book.id,
           details={"name": book.name})
    db.delete(book)  # entries, tags and permissions cascade via ORM relationships
    db.commit()
    return {"ok": True}


# --- entries ----------------------------------------------------------------------

def _sort_key(sort: str):
    def label(e: AddressBookEntry) -> str:
        return (e.alias or e.rustdesk_id).lower()

    if sort == "rustdesk_id":
        return lambda row: row[0].rustdesk_id
    if sort == "last_seen":
        return lambda row: (row[0].last_seen is None, row[0].last_seen)
    if sort == "status":
        return lambda row: (_STATUS_RANK[row[2]], label(row[0]))
    return lambda row: label(row[0])  # "alias" (default)


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
    """Filtered, sorted page of a book.

    Text search runs in SQL; tag/presence filters and sorting run over the
    book in memory (presence is derived from `last_seen`, sort-by-status needs
    it too). Tags are fetched once for all candidate rows, sysinfo only for
    the returned page — a constant number of queries per request.
    """
    book_or_404(db, user, bid)
    q = select(AddressBookEntry).where(AddressBookEntry.address_book_id == bid)
    if search:
        like = f"%{search}%"
        info_rids = select(DeviceInfo.rustdesk_id).where(or_(
            DeviceInfo.hostname.like(like), DeviceInfo.username.like(like), DeviceInfo.os.like(like)))
        q = q.where(or_(
            AddressBookEntry.rustdesk_id.like(like), AddressBookEntry.alias.like(like),
            AddressBookEntry.note.like(like), AddressBookEntry.hostname.like(like),
            AddressBookEntry.username.like(like), AddressBookEntry.rustdesk_id.in_(info_rids)))
    entries = list(db.scalars(q))
    tags = (ab_svc.tags_by_entry(db, entry_ids=[e.id for e in entries]) if search
            else ab_svc.tags_by_entry(db, book_id=bid))
    now = utcnow()
    rows = [(e, tags.get(e.id, []), status_of(e.last_seen, now)) for e in entries]
    if tag:
        wanted = set(tag)
        if mode == "and":
            rows = [r for r in rows if wanted <= {t.name for t in r[1]}]
        else:
            rows = [r for r in rows if wanted & {t.name for t in r[1]}]
    if untagged:
        rows = [r for r in rows if not r[1]]
    if presence in _STATUS_RANK:
        rows = [r for r in rows if r[2] == presence]
    rows.sort(key=_sort_key(sort), reverse=order == "desc")
    offset, limit = page_window(page, page_size)
    page_rows = rows[offset:offset + limit]
    infos = infos_for(db, [e.rustdesk_id for e, _, _ in page_rows])
    return {
        "total": len(rows),
        "data": [entry_out(e, t, infos.get(e.rustdesk_id)) for e, t, _ in page_rows],
    }


@router.post("/address-books/{bid}/entries")
def create_entry(bid: str, body: EntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    access = writable_or_403(book_or_404(db, user, bid))
    try:
        entry = ab_svc.add_entry(db, access.book, body.rustdesk_id, alias=body.alias,
                                 note=body.note, password=body.password, tags=body.tags)
    except ab_svc.EntryError as exc:
        raise _entry_error(exc) from None
    record(db, user, "data", "entry.create", target_type="device", target_id=entry.rustdesk_id,
           details={"entry_id": entry.id, "book_id": bid, "alias": entry.alias,
                    "tags": body.tags, "password_set": bool(body.password)})
    db.commit()
    return one_entry_out(db, entry)


@router.get("/entries/{eid}")
def get_entry(eid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(AddressBookEntry, eid)
    if e is None or ab_svc.book_access(db, user, e.address_book_id) is None:
        raise PanelError(404, "not found")
    return one_entry_out(db, e, db.get(DeviceInfo, e.rustdesk_id))


@router.put("/entries/{eid}")
def update_entry(eid: str, body: EntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e, _ = entry_for_write(db, user, eid)
    before_tags = ab_svc.entry_tag_names(db, e.id)
    before = {"alias": e.alias, "rustdesk_id": e.rustdesk_id}
    note_changed = e.note != body.note
    e.alias, e.note = body.alias, body.note
    if body.password:
        e.password_encrypted = encrypt_password(body.password)
    try:
        ab_svc.rename_entry(db, e, body.rustdesk_id)
    except ab_svc.EntryError as exc:
        raise _entry_error(exc) from None
    ab_svc.set_entry_tags(db, e, body.tags)
    fields = audit_svc.diff_fields(before, {"alias": e.alias, "rustdesk_id": e.rustdesk_id})
    if note_changed:
        fields["note"] = "changed"
    if before_tags != sorted(body.tags):
        fields["tags"] = {"from": before_tags, "to": sorted(body.tags)}
    if body.password:
        fields["password_changed"] = True
    record(db, user, "data", "entry.update", target_type="device", target_id=e.rustdesk_id,
           details={"entry_id": e.id, "book_id": e.address_book_id, "fields": fields})
    db.commit()
    return one_entry_out(db, e)


@router.delete("/entries/{eid}")
def delete_entry(eid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e, _ = entry_for_write(db, user, eid)
    record(db, user, "data", "entry.delete", target_type="device", target_id=e.rustdesk_id,
           details={"entry_id": e.id, "book_id": e.address_book_id, "alias": e.alias})
    db.delete(e)
    db.commit()
    return {"ok": True}


# --- bulk operations (server-side authorization per entry) ---

def _dedupe_ids(raw: list[str]) -> list[str]:
    """Order-preserving dedupe; more than MAX_BULK_IDS distinct ids is a 400."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) > MAX_BULK_IDS:
            raise PanelError(400, f"too many ids (max {MAX_BULK_IDS})")
    return out


def _bulk_targets(db: Session, user: User, ids: list[str]) -> tuple[list[AddressBookEntry], list[dict]]:
    """Entries the caller may write, in request order, plus per-id failures.

    Every id is checked independently (UUID format, existence, write access to
    its book). Entries are loaded in one query and the rule is resolved once
    per book.
    """
    valid = [i for i in ids if is_uuid(i)]
    found = {e.id: e for e in db.scalars(
        select(AddressBookEntry).where(AddressBookEntry.id.in_(valid)))} if valid else {}
    access: dict[str, BookAccess | None] = {}
    targets: list[AddressBookEntry] = []
    failed: list[dict] = []
    for eid in ids:
        if not is_uuid(eid):
            failed.append({"id": eid, "error": "invalid id"})
            continue
        e = found.get(eid)
        if e is None:
            failed.append({"id": eid, "error": "not found"})
            continue
        if e.address_book_id not in access:
            access[e.address_book_id] = ab_svc.writable_book(db, user, e.address_book_id)
        if access[e.address_book_id] is None:
            failed.append({"id": eid, "error": "forbidden"})
            continue
        targets.append(e)
    return targets, failed


def _outcome(done: list, failed: list) -> str:
    if not failed:
        return "success"
    return "partial" if done else "error"


@router.post("/entries/bulk-delete")
def bulk_delete(body: BulkIdsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Delete up to 500 entries in one request.

    Partial success is reported explicitly; duplicate IDs are collapsed, so a
    retried request cannot delete anything twice. Deleting an entry cascades
    only its entry_tags rows — tags and other entries survive.
    """
    targets, failed = _bulk_targets(db, user, _dedupe_ids(body.ids))
    deleted = [e.id for e in targets]
    for e in targets:
        db.delete(e)
    record(db, user, "data", "entry.bulk_delete", target_type="device",
           outcome=_outcome(deleted, failed),
           details={"deleted_count": len(deleted), "failed_count": len(failed),
                    "sample_deleted": deleted[:10], "sample_failed": failed[:10]})
    db.commit()
    return {"deleted": deleted, "failed": failed}


@router.post("/entries/bulk-tags")
def bulk_tags(body: BulkTagsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Add and/or remove tags on many entries without touching other tags.

    A name present in both lists ends up attached ("add" wins).
    """
    ids = _dedupe_ids(body.ids)
    add = ab_svc.clean_tag_names(body.add, limit=MAX_BULK_TAGS)
    remove = ab_svc.clean_tag_names(body.remove, limit=MAX_BULK_TAGS)
    if not add and not remove:
        raise PanelError(400, "no valid tag names")
    targets, failed = _bulk_targets(db, user, ids)
    ab_svc.change_tags(db, targets, add=add, remove=remove)
    updated = [e.id for e in targets]
    record(db, user, "data", "entry.bulk_tags", target_type="device",
           outcome=_outcome(updated, failed),
           details={"updated_count": len(updated), "failed_count": len(failed),
                    "added": add, "removed": remove,
                    "sample_updated": updated[:10], "sample_failed": failed[:10]})
    db.commit()
    return {"updated": updated, "failed": failed, "added": add, "removed": remove}


# --- tags -------------------------------------------------------------------------

def _tag_for_write(db: Session, user: User, tid: str) -> Tag:
    t = db.get(Tag, tid)
    if t is None:
        raise PanelError(404, "not found")
    writable_or_403(ab_svc.book_access(db, user, t.address_book_id))
    return t


def _tag_name_taken(db: Session, book_id: str, name: str) -> bool:
    return db.scalar(select(Tag.id).where(Tag.address_book_id == book_id, Tag.name == name)) is not None


@router.get("/address-books/{bid}/tags")
def list_tags(bid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book_or_404(db, user, bid)
    usage = ab_svc.tag_usage(db, bid)
    tags = db.scalars(select(Tag).where(Tag.address_book_id == bid).order_by(Tag.name))
    return [{"id": t.id, "name": t.name, "color": t.color, "devices": usage.get(t.id, 0)} for t in tags]


@router.post("/address-books/{bid}/tags")
def create_tag(bid: str, body: TagIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    writable_or_403(book_or_404(db, user, bid))
    if _tag_name_taken(db, bid, body.name):
        raise PanelError(409, "duplicate")
    t = Tag(address_book_id=bid, name=body.name, color=body.color)
    db.add(t)
    db.flush()
    record(db, user, "data", "tag.create", target_type="tag", target_id=t.id,
           details={"book_id": bid, "name": t.name, "color": t.color})
    db.commit()
    return {"id": t.id, "name": t.name, "color": t.color, "devices": 0}


@router.put("/tags/{tid}")
def update_tag(tid: str, body: TagIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = _tag_for_write(db, user, tid)
    if body.name != t.name and _tag_name_taken(db, t.address_book_id, body.name):
        raise PanelError(409, "duplicate")
    fields = audit_svc.diff_fields({"name": t.name, "color": str(t.color)},
                                   {"name": body.name, "color": str(body.color)})
    t.name, t.color = body.name, body.color
    record(db, user, "data", "tag.update", target_type="tag", target_id=t.id,
           details={"book_id": t.address_book_id, "fields": fields})
    db.commit()
    return {"id": t.id, "name": t.name, "color": t.color}


@router.delete("/tags/{tid}")
def delete_tag(tid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = _tag_for_write(db, user, tid)
    record(db, user, "data", "tag.delete", target_type="tag", target_id=t.id,
           details={"book_id": t.address_book_id, "name": t.name})
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.put("/entries/{eid}/tags/{tid}")
def attach_tag(eid: str, tid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e, t = db.get(AddressBookEntry, eid), db.get(Tag, tid)
    if e is None or t is None or e.address_book_id != t.address_book_id:
        raise PanelError(404, "not found")
    writable_or_403(ab_svc.book_access(db, user, e.address_book_id))
    if db.get(EntryTag, (eid, tid)) is None:
        db.add(EntryTag(entry_id=eid, tag_id=tid))
        record(db, user, "data", "entry.tag_attach", target_type="device", target_id=e.rustdesk_id,
               details={"entry_id": e.id, "tag_id": t.id, "tag": t.name})
        db.commit()
    return {"ok": True}


@router.delete("/entries/{eid}/tags/{tid}")
def detach_tag(eid: str, tid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e, _ = entry_for_write(db, user, eid)
    link = db.get(EntryTag, (eid, tid))
    if link is not None:
        t = db.get(Tag, tid)
        db.delete(link)
        record(db, user, "data", "entry.tag_detach", target_type="device", target_id=e.rustdesk_id,
               details={"entry_id": e.id, "tag_id": tid, "tag": t.name if t else ""})
        db.commit()
    return {"ok": True}
