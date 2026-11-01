"""`/api/v1`: discovered devices (shim evidence) and merged device cards."""
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.errors import PanelError
from app.api.v1.common import (
    PREFIX,
    book_or_404,
    discovered_out,
    entry_out,
    infos_for,
    page_window,
    record,
    require_admin,
    valid_rid,
    writable_or_403,
)
from app.db.session import get_db
from app.models.models import AddressBookEntry, DeviceInfo, DiscoveredDevice, User
from app.schemas.panel import DiscoveredAddIn
from app.services import ab as ab_svc
from app.services import device_info as info_svc

router = APIRouter(prefix=PREFIX)


def _discovered(db: Session, rid: str) -> DiscoveredDevice | None:
    return db.scalar(select(DiscoveredDevice).where(DiscoveredDevice.rustdesk_id == rid))


def _books_for_rids(books: dict, db: Session, rids: list[str]) -> dict[str, list[dict]]:
    """rustdesk_id -> visible books containing it (one query for a page)."""
    if not rids or not books:
        return {}
    rows = db.execute(
        select(AddressBookEntry.rustdesk_id, AddressBookEntry.address_book_id).where(
            AddressBookEntry.address_book_id.in_(list(books)),
            AddressBookEntry.rustdesk_id.in_(rids),
        )
    ).all()
    out: dict[str, list[dict]] = defaultdict(list)
    for rid, bid in rows:
        out[rid].append({"id": bid, "name": books[bid].name})
    for value in out.values():
        value.sort(key=lambda x: x["name"].lower())
    return dict(out)


def _visible_books(db: Session, user: User) -> dict:
    return {a.book.id: a.book for a in ab_svc.visible_books(db, user)}


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
    books = _visible_books(db, user)
    q = select(DiscoveredDevice).outerjoin(
        DeviceInfo, DeviceInfo.rustdesk_id == DiscoveredDevice.rustdesk_id)
    if only_unlinked and books:
        linked = select(AddressBookEntry.rustdesk_id).where(
            AddressBookEntry.address_book_id.in_(list(books)))
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
    offset, limit = page_window(page, page_size)
    rows = list(db.scalars(q.order_by(DiscoveredDevice.last_seen.desc()).offset(offset).limit(limit)))
    rids = [r.rustdesk_id for r in rows]
    infos = infos_for(db, rids)
    in_books = _books_for_rids(books, db, rids)
    return {
        "total": total,
        "data": [discovered_out(r, infos.get(r.rustdesk_id), in_books.get(r.rustdesk_id, []))
                 for r in rows],
    }


@router.post("/discovered/{rid}/add")
def add_discovered(rid: str, body: DiscoveredAddIn,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Add a discovered ID to a book the caller may write, prefilled from sysinfo."""
    rid = valid_rid(rid)
    access = writable_or_403(book_or_404(db, user, body.book_id))
    info = db.get(DeviceInfo, rid)
    hostname = info.hostname if info else ""
    alias = body.alias.strip() or hostname or rid
    try:
        entry = ab_svc.add_entry(
            db, access.book, rid, alias=alias[:128], note=body.note[:4000],
            hostname=hostname[:128], username=(info.username if info else "")[:128],
            tags=body.tags,
        )
    except ab_svc.EntryError as exc:
        if exc.code == "duplicate":
            raise PanelError(409, "already in this book") from None
        raise PanelError(403, "exceed_max_devices") from None
    record(db, user, "data", "entry.create", target_type="device", target_id=entry.rustdesk_id,
           details={"entry_id": entry.id, "book_id": access.book.id, "alias": entry.alias,
                    "tags": body.tags, "source": "discovered"})
    db.commit()
    tags = ab_svc.tags_by_entry(db, entry_ids=[entry.id]).get(entry.id, [])
    return entry_out(entry, tags, info)


def _may_inspect(user: User, disc: DiscoveredDevice | None, in_my_books: bool) -> bool:
    """Non-admins may only inspect discovered IDs or devices in their books."""
    return user.is_admin or disc is not None or in_my_books


@router.get("/device-info/{rid}")
def get_device_info(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Merged card: address-book rows + discovery evidence + client sysinfo."""
    rid = valid_rid(rid)
    info = db.get(DeviceInfo, rid)
    disc = _discovered(db, rid)
    books = _visible_books(db, user)
    entries: list[AddressBookEntry] = []
    if books:
        entries = list(db.scalars(select(AddressBookEntry).where(
            AddressBookEntry.rustdesk_id == rid,
            AddressBookEntry.address_book_id.in_(list(books)),
        )))
    if not _may_inspect(user, disc, bool(entries)) or (info is None and disc is None and not entries):
        raise PanelError(404, "not found")

    tags = ab_svc.tags_by_entry(db, entry_ids=[e.id for e in entries])
    entry_data = []
    for e in entries:
        item = entry_out(e, tags.get(e.id, []), info)
        item["book_id"] = e.address_book_id
        item["book_name"] = books[e.address_book_id].name
        entry_data.append(item)
    stamps = [s for s in (
        disc.last_seen if disc else None,
        info.last_heartbeat_at if info else None,
        info.collected_at if info else None,
        *(e.last_seen for e in entries),
    ) if s is not None]
    sources = []
    if disc is not None:
        sources.append("discovery")
    if info is not None and info.collected_at is not None:
        sources.append("sysinfo")
    if entries:
        sources.append("address_book")
    in_books = _books_for_rids(books, db, [rid]).get(rid, [])
    return {
        "rustdesk_id": rid,
        "online": bool(disc and disc.online) or any(x["presence"] == "online" for x in entry_data),
        "last_seen": max(stamps).isoformat() if stamps else None,
        "last_ip": (disc.last_ip if disc else "") or (info.ip if info else ""),
        "discovered": discovered_out(disc, info, in_books) if disc else None,
        "info": info_svc.info_out(info),
        "entries": entry_data,
        "sources": sources,
    }


@router.post("/device-info/{rid}/refresh")
def refresh_device_info(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ask the client to re-upload sysinfo on its next heartbeat.

    The flag is consumed once and expires after 30 minutes; it only works for
    devices that have a custom api-server configured (the stock client's
    heartbeat loop delivers it).
    """
    rid = valid_rid(rid)
    books = _visible_books(db, user)
    in_my_books = bool(books) and db.scalar(select(AddressBookEntry.id).where(
        AddressBookEntry.rustdesk_id == rid,
        AddressBookEntry.address_book_id.in_(list(books)),
    ).limit(1)) is not None
    if not _may_inspect(user, _discovered(db, rid), in_my_books):
        raise PanelError(404, "not found")
    info_svc.request_refresh(rid)
    record(db, user, "device", "device.refresh_request", target_type="device", target_id=rid,
           details={"expires_in": info_svc.REFRESH_TTL_SEC})
    db.commit()
    return {"ok": True, "expires_in": info_svc.REFRESH_TTL_SEC}


@router.delete("/discovered/{rid}")
def forget_discovered(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Admin cleanup for polluted discovery rows (never touches books/info)."""
    require_admin(user)
    rid = valid_rid(rid)
    row = _discovered(db, rid)
    if row is None:
        raise PanelError(404, "not found")
    record(db, user, "device", "device.forget", target_type="device", target_id=rid,
           details={"last_ip": row.last_ip, "source": row.source})
    db.delete(row)
    db.commit()
    return {"ok": True}
