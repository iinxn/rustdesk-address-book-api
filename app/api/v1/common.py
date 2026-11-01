"""Helpers shared by the `/api/v1` routers: access checks, serializers, paging."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import PanelError
from app.core.timeutil import iso
from app.core.validators import validate_rustdesk_id
from app.models.models import AddressBookEntry, DeviceInfo, DiscoveredDevice, Tag, User
from app.services import ab as ab_svc
from app.services import audit as audit_svc
from app.services import device_info as info_svc
from app.services.ab import BookAccess
from app.services.auth import DISPLAY_NAME_MAX, clean_display_name
from app.services.presence import status_of

# Each sub-router carries the prefix itself: FastAPI resolves included routers
# lazily, and `scope["route"].path` (used by the access log) is the path as
# declared on the innermost router.
PREFIX = "/api/v1"
MAX_PAGE_SIZE = 200


def require_admin(user: User) -> None:
    if not user.is_admin:
        raise PanelError(403, "admin required")


def book_or_404(db: Session, user: User, book_id: str) -> BookAccess:
    access = ab_svc.book_access(db, user, book_id)
    if access is None:
        raise PanelError(404, "no such book")
    return access


def writable_or_403(access: BookAccess | None) -> BookAccess:
    if access is None or not access.writable:
        raise PanelError(403, "read-only")
    return access


def entry_for_write(db: Session, user: User, entry_id: str) -> tuple[AddressBookEntry, BookAccess]:
    entry = db.get(AddressBookEntry, entry_id)
    if entry is None:
        raise PanelError(404, "not found")
    return entry, writable_or_403(ab_svc.book_access(db, user, entry.address_book_id))


def valid_rid(raw: str) -> str:
    rid = raw.strip()
    if validate_rustdesk_id(rid) is not None:
        raise PanelError(422, "invalid id")
    return rid


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def page_window(page: int, page_size: int) -> tuple[int, int]:
    """(offset, limit) with page >= 1 and 1 <= page_size <= MAX_PAGE_SIZE."""
    size = min(max(page_size, 1), MAX_PAGE_SIZE)
    return (max(page, 1) - 1) * size, size


def check_display_name(raw: str) -> str:
    name = clean_display_name(raw)
    if len(name) > DISPLAY_NAME_MAX:
        raise PanelError(400, f"display_name too long (max {DISPLAY_NAME_MAX})")
    return name


def record(db: Session, user: User, category: str, event_type: str, *,
           target_type: str, target_id: str = "", outcome: str = "success",
           details: dict | None = None) -> None:
    audit_svc.record(db, category=category, event_type=event_type, outcome=outcome, actor=user,
                     target_type=target_type, target_id=target_id, details=details)


def infos_for(db: Session, rids: list[str]) -> dict[str, DeviceInfo]:
    if not rids:
        return {}
    return {i.rustdesk_id: i for i in db.scalars(
        select(DeviceInfo).where(DeviceInfo.rustdesk_id.in_(rids)))}


# --- serializers ------------------------------------------------------------

def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or "",
        "is_admin": u.is_admin,
        "is_disabled": u.is_disabled,
    }


def entry_out(e: AddressBookEntry, tags: list[Tag], info: DeviceInfo | None = None) -> dict:
    """Extended entry shape for the SPA (never sent to the RustDesk client)."""
    return {
        "id": e.id,
        "rustdesk_id": e.rustdesk_id,
        "alias": e.alias,
        "note": e.note,
        "tags": [t.name for t in tags],
        "tag_objs": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
        "presence": status_of(e.last_seen),
        "last_seen": iso(e.last_seen),
        "password_configured": bool(e.password_encrypted),
        # Address-book metadata augmented by a client-uploaded report when one
        # exists. Fields stay empty/null when the source did not provide them.
        "hostname": e.hostname or (info.hostname if info else ""),
        "username": e.username or (info.username if info else ""),
        "platform": e.platform,
        "ip": (info.ip or None) if info else None,
        "os": (info.os_name or info.os or None) if info else None,
        "has_info": bool(info and info.collected_at),
        "info_updated_at": iso(info.collected_at) if info else None,
        "created_at": iso(e.created_at),
        "updated_at": iso(e.updated_at),
    }


def one_entry_out(db: Session, e: AddressBookEntry, info: DeviceInfo | None = None) -> dict:
    return entry_out(e, ab_svc.tags_by_entry(db, entry_ids=[e.id]).get(e.id, []), info)


def discovered_out(row: DiscoveredDevice, info: DeviceInfo | None, in_books: list[dict]) -> dict[str, Any]:
    return {
        "rustdesk_id": row.rustdesk_id,
        "first_seen": iso(row.first_seen),
        "last_seen": iso(row.last_seen),
        "last_connected": iso(row.last_connected),
        "last_disconnected": iso(row.last_disconnected),
        "last_ip": row.last_ip,
        "source": row.source,
        "online": bool(row.online),
        "seen_count": row.seen_count,
        "in_books": in_books,
        "info": info_svc.info_out(info),
    }
