"""Address books: access rules, entries and tags (shared by every router).

Access model (DEC-003): a user sees their own personal book, any book they
hold an `address_book_permissions` row for, and — when admin — every shared
book with `rule=3`. Admins get no implicit access to other users' personal
books. `book_access()` is the single place that decides this; listing
(`visible_books()`) and per-request checks use the same rule, so a book that
appears in a list can always be opened and vice versa.

Entries are created only through `add_entry()` (RustDesk client, SPA,
discovered devices, legacy panel), so validation, the duplicate check and
`MAX_PEER_ONE_AB` behave identically on every path.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_password, encrypt_password
from app.core.timeutil import utcnow
from app.core.validators import validate_rustdesk_id
from app.models.models import (
    AddressBook,
    AddressBookEntry,
    AddressBookPermission,
    EntryTag,
    Tag,
    User,
)
from app.services.presence import ONLINE_AFTER_SEC

RULE_READ, RULE_WRITE, RULE_FULL = 1, 2, 3
TAG_NAME_MAX = 64
TAG_COLOR_MAX = 0xFFFFFFFF  # ARGB as an unsigned 32-bit integer


def can_write(rule: int) -> bool:
    return rule >= RULE_WRITE


@dataclass(frozen=True)
class BookAccess:
    book: AddressBook
    rule: int

    @property
    def writable(self) -> bool:
        return can_write(self.rule)

    @property
    def full_control(self) -> bool:
        return self.rule >= RULE_FULL


def _access(book: AddressBook, user: User, perm_rule: int | None) -> BookAccess | None:
    if book.type == "personal" and book.owner_user_id == user.id:
        return BookAccess(book, RULE_FULL)
    if perm_rule is not None:
        return BookAccess(book, perm_rule)
    if user.is_admin and book.type == "shared":
        return BookAccess(book, RULE_FULL)
    return None


def book_access(db: Session, user: User, book: AddressBook | str | None) -> BookAccess | None:
    """The caller's rule on one book, or None when the book is not visible."""
    if isinstance(book, str):
        book = db.get(AddressBook, book) if book else None
    if book is None:
        return None
    perm_rule = db.scalar(
        select(AddressBookPermission.rule).where(
            AddressBookPermission.address_book_id == book.id,
            AddressBookPermission.user_id == user.id,
        )
    )
    return _access(book, user, perm_rule)


def writable_book(db: Session, user: User, book: AddressBook | str | None) -> BookAccess | None:
    access = book_access(db, user, book)
    return access if access is not None and access.writable else None


def visible_books(db: Session, user: User) -> list[BookAccess]:
    """Every book the user may open, ordered by name (two queries)."""
    perms = dict(db.execute(
        select(AddressBookPermission.address_book_id, AddressBookPermission.rule)
        .where(AddressBookPermission.user_id == user.id)
    ).all())
    conditions = [AddressBook.owner_user_id == user.id]
    if perms:
        conditions.append(AddressBook.id.in_(list(perms)))
    if user.is_admin:
        conditions.append(AddressBook.type == "shared")
    books = db.scalars(
        select(AddressBook).where(or_(*conditions)).order_by(AddressBook.name, AddressBook.id)
    )
    out = []
    for book in books:
        access = _access(book, user, perms.get(book.id))
        if access is not None:
            out.append(access)
    return out


def personal_book(db: Session, user: User) -> AddressBook | None:
    return db.scalar(
        select(AddressBook).where(
            AddressBook.owner_user_id == user.id, AddressBook.type == "personal"
        )
    )


def shared_profiles(db: Session, user: User) -> list[BookAccess]:
    """Books for the RustDesk client's "shared" tab (`/api/ab/shared/profiles`).

    Admin: every shared book with full control. Others: books granted by a
    permission row. Name order keeps client-side paging stable.
    """
    if user.is_admin:
        books = db.scalars(
            select(AddressBook).where(AddressBook.type == "shared")
            .order_by(AddressBook.name, AddressBook.id)
        )
        return [BookAccess(b, RULE_FULL) for b in books]
    rows = db.execute(
        select(AddressBook, AddressBookPermission.rule)
        .join(AddressBookPermission, AddressBookPermission.address_book_id == AddressBook.id)
        .where(AddressBookPermission.user_id == user.id)
        .order_by(AddressBook.name, AddressBook.id)
    ).all()
    return [BookAccess(book, rule) for book, rule in rows]


# --- presence counters ------------------------------------------------------

def book_counts(db: Session, book_ids: Iterable[str]) -> dict[str, dict[str, int]]:
    """{book_id: {devices, online, offline, unknown}} in one aggregate query."""
    ids = list(book_ids)
    counts = {bid: {"devices": 0, "online": 0, "offline": 0, "unknown": 0} for bid in ids}
    if not ids:
        return counts
    cutoff = utcnow() - timedelta(seconds=ONLINE_AFTER_SEC)
    last_seen = AddressBookEntry.last_seen
    rows = db.execute(
        select(
            AddressBookEntry.address_book_id,
            func.count(),
            func.sum(case((last_seen >= cutoff, 1), else_=0)),
            func.sum(case((last_seen.is_(None), 1), else_=0)),
        )
        .where(AddressBookEntry.address_book_id.in_(ids))
        .group_by(AddressBookEntry.address_book_id)
    ).all()
    for bid, total, online, unknown in rows:
        online, unknown = int(online or 0), int(unknown or 0)
        counts[bid] = {"devices": total, "online": online,
                       "offline": total - online - unknown, "unknown": unknown}
    return counts


# --- tags -----------------------------------------------------------------

def clean_tag_names(
    raw: Iterable[object], limit: int | None = None, max_len: int | None = TAG_NAME_MAX
) -> list[str]:
    """Trimmed, non-empty, unique (first occurrence wins) tag names.

    Bulk edits skip names longer than `max_len`; full replacement
    (`set_entry_tags`) historically accepts any length and passes None.
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip()
        if not name or (max_len is not None and len(name) > max_len) or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if limit is not None and len(out) >= limit:
            break
    return out


def parse_color(value: object) -> int | None:
    """Tag colour as sent by clients/forms; None when invalid (SEC-004)."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            text = value.strip()
            # "0xFF00FF00" from forms; plain decimal (incl. "010") from clients.
            color = int(text, 16) if text.lower().startswith("0x") else int(text)
        elif isinstance(value, (int, float)):
            color = int(value)
        else:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return color if 0 <= color <= TAG_COLOR_MAX else None


def tags_by_entry(
    db: Session, *, entry_ids: Iterable[str] | None = None, book_id: str | None = None
) -> dict[str, list[Tag]]:
    """{entry_id: tags sorted by name} for many entries in one query."""
    q = select(EntryTag.entry_id, Tag).join(Tag, Tag.id == EntryTag.tag_id)
    if book_id is not None:
        q = q.join(AddressBookEntry, AddressBookEntry.id == EntryTag.entry_id).where(
            AddressBookEntry.address_book_id == book_id)
    else:
        ids = list(entry_ids or ())
        if not ids:
            return {}
        q = q.where(EntryTag.entry_id.in_(ids))
    out: dict[str, list[Tag]] = defaultdict(list)
    for entry_id, tag in db.execute(q.order_by(Tag.name)).all():
        out[entry_id].append(tag)
    return out


def entry_tag_names(db: Session, entry_id: str) -> list[str]:
    return [t.name for t in tags_by_entry(db, entry_ids=[entry_id]).get(entry_id, [])]


def _book_tags(db: Session, book_id: str) -> dict[str, Tag]:
    return {t.name: t for t in db.scalars(select(Tag).where(Tag.address_book_id == book_id))}


def _ensure_tags(db: Session, book_id: str, names: Iterable[str], existing: dict[str, Tag]) -> list[Tag]:
    """Tags for `names`, creating missing ones (colour 0) in the entry's book."""
    out = []
    for name in names:
        tag = existing.get(name)
        if tag is None:
            tag = Tag(address_book_id=book_id, name=name, color=0)
            db.add(tag)
            db.flush()
            existing[name] = tag
        out.append(tag)
    return out


def _links(db: Session, entry_id: str) -> dict[str, EntryTag]:
    return {link.tag_id: link for link in db.scalars(select(EntryTag).where(EntryTag.entry_id == entry_id))}


def set_entry_tags(db: Session, entry: AddressBookEntry, names: Iterable[str]) -> None:
    """Replace the entry's tags with exactly `names` (missing tags are created)."""
    wanted = _ensure_tags(db, entry.address_book_id,
                          sorted(clean_tag_names(names, max_len=None)), _book_tags(db, entry.address_book_id))
    wanted_ids = {t.id for t in wanted}
    links = _links(db, entry.id)
    for tag_id, link in links.items():
        if tag_id not in wanted_ids:
            db.delete(link)
    for tag_id in wanted_ids - set(links):
        db.add(EntryTag(entry_id=entry.id, tag_id=tag_id))
    db.flush()


def change_tags(
    db: Session, entries: list[AddressBookEntry], *, add: Iterable[str] = (), remove: Iterable[str] = ()
) -> None:
    """Detach `remove` and attach `add` on many entries; other tags are untouched.

    A name present in both lists ends up attached ("add" wins). Cost is a
    fixed number of statements per book, not per entry: one link lookup for
    all entries, one DELETE and one batched INSERT.
    """
    add_names = clean_tag_names(add)
    remove_names = set(clean_tag_names(remove)) - set(add_names)
    if not entries or not (add_names or remove_names):
        return
    ids = [e.id for e in entries]
    links: dict[str, set[str]] = defaultdict(set)
    for entry_id, tag_id in db.execute(
            select(EntryTag.entry_id, EntryTag.tag_id).where(EntryTag.entry_id.in_(ids))).all():
        links[entry_id].add(tag_id)
    by_book: dict[str, list[AddressBookEntry]] = defaultdict(list)
    for e in entries:
        by_book[e.address_book_id].append(e)
    for book_id, group in by_book.items():
        book_tags = _book_tags(db, book_id)
        remove_ids = [book_tags[n].id for n in remove_names if n in book_tags]
        if remove_ids:
            db.execute(delete(EntryTag).where(
                EntryTag.entry_id.in_([e.id for e in group]), EntryTag.tag_id.in_(remove_ids)))
        for tag in _ensure_tags(db, book_id, add_names, book_tags):
            db.add_all(EntryTag(entry_id=e.id, tag_id=tag.id)
                       for e in group if tag.id not in links[e.id])
    db.flush()


def tag_usage(db: Session, book_id: str) -> dict[str, int]:
    rows = db.execute(
        select(Tag.id, func.count(EntryTag.entry_id))
        .outerjoin(EntryTag, EntryTag.tag_id == Tag.id)
        .where(Tag.address_book_id == book_id)
        .group_by(Tag.id)
    ).all()
    return dict(rows)


# --- entries ----------------------------------------------------------------

class EntryError(Exception):
    """Domain error from `add_entry`/`rename_entry`; routers map `code` to their contract."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code  # "invalid_id" | "duplicate" | "limit"
        self.message = message or code


def find_entry(db: Session, book_id: str, rustdesk_id: str) -> AddressBookEntry | None:
    return db.scalar(select(AddressBookEntry).where(
        AddressBookEntry.address_book_id == book_id,
        AddressBookEntry.rustdesk_id == rustdesk_id,
    ))


def add_entry(
    db: Session,
    book: AddressBook,
    rustdesk_id: str,
    *,
    alias: str = "",
    note: str = "",
    username: str = "",
    hostname: str = "",
    platform: str = "",
    hash_value: str = "",
    password: str = "",
    tags: Iterable[str] | None = None,
) -> AddressBookEntry:
    """Validate and add one device to a book (flushed, not committed)."""
    rid = (rustdesk_id or "").strip()
    if (problem := validate_rustdesk_id(rid)) is not None:
        raise EntryError("invalid_id", problem)
    if find_entry(db, book.id, rid) is not None:
        raise EntryError("duplicate")
    if settings.max_peer_one_ab > 0:
        count = db.scalar(select(func.count()).select_from(AddressBookEntry).where(
            AddressBookEntry.address_book_id == book.id)) or 0
        if count >= settings.max_peer_one_ab:
            raise EntryError("limit", "exceed_max_devices")
    entry = AddressBookEntry(
        address_book_id=book.id, rustdesk_id=rid, alias=alias, note=note,
        username=username, hostname=hostname, platform=platform, hash_value=hash_value,
        password_encrypted=encrypt_password(password) if password else None,
    )
    db.add(entry)
    db.flush()
    if tags:
        set_entry_tags(db, entry, tags)
    return entry


def rename_entry(db: Session, entry: AddressBookEntry, rustdesk_id: str) -> None:
    if rustdesk_id == entry.rustdesk_id:
        return
    if (problem := validate_rustdesk_id(rustdesk_id)) is not None:
        raise EntryError("invalid_id", problem)
    if find_entry(db, entry.address_book_id, rustdesk_id) is not None:
        raise EntryError("duplicate")
    entry.rustdesk_id = rustdesk_id


def peer_out(entry: AddressBookEntry, book: AddressBook, tag_names: list[str]) -> dict:
    """RustDesk client peer object: `hash` for personal books, `password` for shared."""
    d = {
        "id": entry.rustdesk_id,
        "username": entry.username,
        "hostname": entry.hostname,
        "platform": entry.platform,
        "alias": entry.alias,
        "tags": tag_names,
        "note": entry.note,
    }
    if book.type == "personal":
        d["hash"] = entry.hash_value or ""
    else:
        d["password"] = decrypt_password(entry.password_encrypted) if entry.password_encrypted else ""
    return d


def peers_page(db: Session, book: AddressBook, offset: int, limit: int) -> tuple[int, list[dict]]:
    total = db.scalar(select(func.count()).select_from(AddressBookEntry).where(
        AddressBookEntry.address_book_id == book.id)) or 0
    rows = list(db.scalars(
        select(AddressBookEntry)
        .where(AddressBookEntry.address_book_id == book.id)
        .order_by(AddressBookEntry.rustdesk_id)
        .offset(offset)
        .limit(limit)
    ))
    tags = tags_by_entry(db, entry_ids=[e.id for e in rows])
    return total, [peer_out(e, book, [t.name for t in tags.get(e.id, [])]) for e in rows]


_PEER_TEXT_FIELDS = ("alias", "note", "username", "hostname", "platform")


def apply_peer_update(db: Session, entry: AddressBookEntry, data: dict, book: AddressBook) -> None:
    """Partial update from the RustDesk client; unknown or mistyped keys are ignored."""
    for field in _PEER_TEXT_FIELDS:
        if isinstance(data.get(field), str):
            setattr(entry, field, data[field])
    if isinstance(data.get("hash"), str) and book.type == "personal":
        entry.hash_value = data["hash"]
    if isinstance(data.get("password"), str) and book.type != "personal":
        entry.password_encrypted = encrypt_password(data["password"]) if data["password"] else None
    if isinstance(data.get("tags"), list):
        set_entry_tags(db, entry, [str(t) for t in data["tags"]])
