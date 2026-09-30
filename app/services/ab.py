"""AddressBookService + PeerService + TagService (one module, MVP-small)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_password, encrypt_password
from app.models.models import (
    AddressBook,
    AddressBookEntry,
    AddressBookPermission,
    EntryTag,
    Tag,
    User,
)


def personal_book(db: Session, user: User) -> AddressBook | None:
    return db.scalar(
        select(AddressBook).where(
            AddressBook.owner_user_id == user.id, AddressBook.type == "personal"
        )
    )


def get_book_for_user(db: Session, user: User, guid: str) -> AddressBook | None:
    """Personal book owned by user, or shared book with a permission row."""
    book = db.get(AddressBook, guid)
    if book is None:
        return None
    if book.type == "personal" and book.owner_user_id == user.id:
        return book
    perm = db.scalar(
        select(AddressBookPermission).where(
            AddressBookPermission.address_book_id == guid,
            AddressBookPermission.user_id == user.id,
        )
    )
    if perm is not None:
        return book
    if user.is_admin and book.type == "shared":
        return book
    return None


def rule_for(db: Session, user: User, book: AddressBook) -> int:
    if book.type == "personal" and book.owner_user_id == user.id:
        return 3
    perm = db.scalar(
        select(AddressBookPermission).where(
            AddressBookPermission.address_book_id == book.id,
            AddressBookPermission.user_id == user.id,
        )
    )
    if perm is not None:
        return perm.rule
    if user.is_admin and book.type == "shared":
        return 3
    return 0


def can_write(rule: int) -> bool:
    return rule >= 2


def shared_profiles(db: Session, user: User) -> list[tuple[AddressBook, int]]:
    out: list[tuple[AddressBook, int]] = []
    if user.is_admin:
        for b in db.scalars(select(AddressBook).where(AddressBook.type == "shared")):
            out.append((b, 3))
        return out
    for p in db.scalars(select(AddressBookPermission).where(AddressBookPermission.user_id == user.id)):
        b = db.get(AddressBook, p.address_book_id)
        if b is not None:
            out.append((b, p.rule))
    return out


def entry_tag_names(db: Session, entry_id: str) -> list[str]:
    rows = db.scalars(
        select(Tag.name).join(EntryTag, EntryTag.tag_id == Tag.id).where(EntryTag.entry_id == entry_id)
    ).all()
    return sorted(rows)


def peer_out(db: Session, e: AddressBookEntry, book: AddressBook) -> dict:
    tags = entry_tag_names(db, e.id)
    d = {
        "id": e.rustdesk_id,
        "username": e.username,
        "hostname": e.hostname,
        "platform": e.platform,
        "alias": e.alias,
        "tags": tags,
        "note": e.note,
    }
    if book.type == "personal":
        d["hash"] = e.hash_value or ""
    else:
        d["password"] = decrypt_password(e.password_encrypted) if e.password_encrypted else ""
    return d


def sync_entry_tags(db: Session, entry: AddressBookEntry, tag_names: list[str]) -> None:
    """Replace entry_tags with exactly tag_names (auto-create missing tags, color 0)."""
    clean = sorted({t.strip() for t in tag_names if t and t.strip()})
    existing = {t.name: t for t in db.scalars(select(Tag).where(Tag.address_book_id == entry.address_book_id))}
    wanted_ids: set[str] = set()
    for name in clean:
        t = existing.get(name)
        if t is None:
            t = Tag(address_book_id=entry.address_book_id, name=name, color=0)
            db.add(t)
            db.flush()
        wanted_ids.add(t.id)
    current = {r.tag_id for r in db.scalars(select(EntryTag).where(EntryTag.entry_id == entry.id))}
    for tid in wanted_ids - current:
        db.add(EntryTag(entry_id=entry.id, tag_id=tid))
    for tid in current - wanted_ids:
        r = db.get(EntryTag, (entry.id, tid))
        if r is not None:
            db.delete(r)


def apply_peer_update(db: Session, entry: AddressBookEntry, data: dict, book: AddressBook) -> None:
    if "alias" in data and isinstance(data["alias"], str):
        entry.alias = data["alias"]
    if "note" in data and isinstance(data["note"], str):
        entry.note = data["note"]
    if "username" in data and isinstance(data["username"], str):
        entry.username = data["username"]
    if "hostname" in data and isinstance(data["hostname"], str):
        entry.hostname = data["hostname"]
    if "platform" in data and isinstance(data["platform"], str):
        entry.platform = data["platform"]
    if "hash" in data and isinstance(data["hash"], str) and book.type == "personal":
        entry.hash_value = data["hash"]
    if "password" in data and isinstance(data["password"], str) and book.type != "personal":
        entry.password_encrypted = encrypt_password(data["password"]) if data["password"] else None
    if "tags" in data and isinstance(data["tags"], list):
        sync_entry_tags(db, entry, [str(t) for t in data["tags"]])


def tag_usage(db: Session, book_id: str) -> dict[str, int]:
    rows = (
        db.query(Tag.id, func.count(EntryTag.entry_id))
        .outerjoin(EntryTag, EntryTag.tag_id == Tag.id)
        .filter(Tag.address_book_id == book_id)
        .group_by(Tag.id)
        .all()
    )
    return {tid: n for tid, n in rows}
