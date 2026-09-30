"""Internal Web Panel JSON API (/api/v1/*). Bearer auth, same tokens.

Extended shapes (customer/tag objects, presence, counts) live ONLY here;
RustDesk-compatible /api/ab/* is untouched.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.crypto import encrypt_password
from app.models.models import (
    AddressBook,
    AddressBookEntry,
    Customer,
    EntryTag,
    Tag,
    User,
)
from app.schemas.panel import CustomerIn, EntryIn, TagIn, UserIn
from app.services import ab as ab_svc
from app.services import presence as presence_svc
from app.db.session import get_db

router = APIRouter(prefix="/api/v1")


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


def entry_out(db: Session, e: AddressBookEntry) -> dict:
    state, last_seen = presence_svc.status_of(e)
    tags = db.scalars(select(Tag).join(EntryTag, EntryTag.tag_id == Tag.id).where(EntryTag.entry_id == e.id).order_by(Tag.name)).all()
    cust = db.get(Customer, e.customer_id) if e.customer_id else None
    return {
        "id": e.id,
        "rustdesk_id": e.rustdesk_id,
        "alias": e.alias,
        "note": e.note,
        "customer_id": e.customer_id,
        "customer": {"id": cust.id, "name": cust.name} if cust else None,
        "tags": [t.name for t in tags],
        "tag_objs": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
        "presence": state,
        "last_seen": last_seen,
        "password_configured": bool(e.password_encrypted),
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
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
    return total


@router.get("/address-books")
def list_books(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for b in books_visible(db, user):
        d = {"id": b.id, "name": b.name, "type": b.type}
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


@router.get("/address-books/{bid}/entries")
def list_entries(
    bid: str,
    search: str = "",
    tag: list[str] = Query(default=[]),
    mode: str = "or",
    untagged: bool = False,
    customer_id: str = "",
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
        q = q.where(or_(AddressBookEntry.rustdesk_id.like(like), AddressBookEntry.alias.like(like),
                        AddressBookEntry.note.like(like)))
    if customer_id:
        q = q.where(AddressBookEntry.customer_id == customer_id)
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
    return {"total": total, "data": [entry_out(db, e) for e, _, _ in enriched[start:start + page_size]]}


@router.post("/address-books/{bid}/entries")
def create_entry(bid: str, body: EntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    book = ab_svc.get_book_for_user(db, user, bid)
    if book is None:
        return err("no such book", 404)
    if not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    if db.scalar(select(AddressBookEntry).where(AddressBookEntry.address_book_id == bid, AddressBookEntry.rustdesk_id == body.rustdesk_id)):
        return err("duplicate", 409)
    e = AddressBookEntry(
        address_book_id=bid, rustdesk_id=body.rustdesk_id, alias=body.alias,
        note=body.note, customer_id=body.customer_id,
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
    return entry_out(db, e)


@router.put("/entries/{eid}")
def update_entry(eid: str, body: EntryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(AddressBookEntry, eid)
    if e is None:
        return err("not found", 404)
    book = ab_svc.get_book_for_user(db, user, e.address_book_id)
    if book is None or not ab_svc.can_write(ab_svc.rule_for(db, user, book)):
        return err("read-only", 403)
    e.alias, e.note, e.customer_id = body.alias, body.note, body.customer_id
    if body.password:
        e.password_encrypted = encrypt_password(body.password)
    if body.rustdesk_id != e.rustdesk_id:
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


@router.get("/customers")
def list_customers(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for c in db.scalars(select(Customer).order_by(Customer.name)):
        n = db.scalar(select(func.count()).select_from(AddressBookEntry).where(AddressBookEntry.customer_id == c.id)) or 0
        out.append({"id": c.id, "name": c.name, "note": c.note, "devices": n})
    return out


@router.post("/customers")
def create_customer(body: CustomerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = Customer(name=body.name, note=body.note)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "note": c.note, "devices": 0}


@router.put("/customers/{cid}")
def update_customer(cid: str, body: CustomerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if c is None:
        return err("not found", 404)
    c.name, c.note = body.name, body.note
    db.commit()
    return {"id": c.id, "name": c.name, "note": c.note}


@router.delete("/customers/{cid}")
def delete_customer(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if c is None:
        return err("not found", 404)
    db.delete(c)
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
    """Edit user: {is_admin?, is_disabled?, password?}. Admin only."""
    if not user.is_admin:
        return err("admin required", 403)
    u = db.get(User, uid)
    if u is None:
        return err("not found", 404)
    if "is_admin" in body:
        if u.id == user.id and not body["is_admin"]:
            return err("cannot demote self", 400)
        u.is_admin = bool(body["is_admin"])
    if "is_disabled" in body:
        if u.id == user.id and body["is_disabled"]:
            return err("cannot disable self", 400)
        u.is_disabled = bool(body["is_disabled"])
    if body.get("password"):
        from app.core.security import hash_password
        u.password_hash = hash_password(str(body["password"]))
    db.commit()
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
