"""Connection evidence: which user asked to connect to which device.

The KX shim sees rendezvous control frames only. PunchHoleRequest/RequestRelay
name the *target* device and, when the client is logged in to this API, carry
its API `access_token` (stock client, `client.rs/_start_inner`). The shim
passes only the token's SHA-256; here it is matched against `sessions.token`,
so the user is the account that is logged in on the initiating client.

The remote session itself (direct P2P or hbbr relay) never passes through this
project, so an audit row records an observed **connection request**, not a
confirmed remote session. The UI labels it accordingly.

How the user was found is explicit in `details.actor_source`:

* ``token``         — the request carried the token of a live API session;
* ``token_expired`` — same, but that session has expired (not yet purged);
* ``session``       — no token; last login from the initiator's device id
  (`sessions.device_id`, set by ``POST /api/login``);
* ``book_owner``    — no token; exactly one user has the initiator in a
  personal book;
* ``device``        — unresolved; the row still names the target device.

A client that is not logged in sends no token (and usually a plain, not
encrypted, rendezvous request), so its rows stay ``device``.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import AddressBook, AddressBookEntry, DeviceInfo
from app.models.models import Session as SessionModel
from app.models.models import User

CONNECTION_VIA = ("direct", "relay")
EVENT_TYPE = "connection.request"


def token_digest(token: str) -> str:
    """Same digest the shim computes for PunchHoleRequest/RequestRelay.token."""
    return hashlib.sha256((token or "").encode("utf-8", "replace")).hexdigest()


def token_index(db: Session) -> dict[str, SessionModel]:
    """digest -> session row. Built once per drain batch, kept in memory only."""
    return {token_digest(s.token): s for s in db.scalars(select(SessionModel))}


def device_label(db: Session, rid: str, user_id: str | None = None) -> str:
    """Human label for a device id, or '' when nothing is known.

    Alias from the user's own personal book first (that is the name the user
    gave it), then any alias, then a hostname from a book entry or sysinfo.
    """
    rid = (rid or "").strip()
    if not rid:
        return ""
    base = (
        select(AddressBookEntry.alias)
        .where(AddressBookEntry.rustdesk_id == rid, AddressBookEntry.alias != "")
        .order_by(AddressBookEntry.created_at, AddressBookEntry.id)
        .limit(1)
    )
    if user_id:
        alias = db.scalar(
            base.join(AddressBook, AddressBook.id == AddressBookEntry.address_book_id)
            .where(AddressBook.type == "personal", AddressBook.owner_user_id == user_id)
        )
        if alias:
            return alias
    alias = db.scalar(base)
    if alias:
        return alias
    hostname = db.scalar(
        select(DeviceInfo.hostname)
        .where(DeviceInfo.rustdesk_id == rid, DeviceInfo.hostname != "")
        .limit(1)
    )
    if hostname:
        return hostname
    return db.scalar(
        select(AddressBookEntry.hostname)
        .where(AddressBookEntry.rustdesk_id == rid, AddressBookEntry.hostname != "")
        .order_by(AddressBookEntry.created_at, AddressBookEntry.id)
        .limit(1)
    ) or ""


def _active(user: User | None) -> User | None:
    return user if user is not None and not user.is_disabled else None


def resolve_by_token(
    db: Session, token_hash: str, sessions: dict[str, SessionModel] | None,
) -> tuple[User | None, str, str]:
    """(user, actor_source, device_id of that login) for a token digest."""
    if not token_hash:
        return None, "", ""
    if sessions is None:
        sessions = token_index(db)
    s = sessions.get(token_hash)
    if s is None:
        return None, "", ""
    user = _active(db.get(User, s.user_id))
    if user is None:
        return None, "", ""
    expired = s.expires_at is not None and s.expires_at < datetime.utcnow()
    return user, "token_expired" if expired else "token", s.device_id or ""


def resolve_user(db: Session, rid: str) -> tuple[User | None, str]:
    """Fallback without a token: best-effort user behind a device id."""
    rid = (rid or "").strip()
    if not rid:
        return None, "device"

    session = db.scalar(
        select(SessionModel)
        .where(SessionModel.device_id == rid)
        .order_by(SessionModel.created_at.desc())
        .limit(1)
    )
    if session is not None and (
        session.expires_at is None or session.expires_at >= datetime.utcnow()
    ):
        user = _active(db.get(User, session.user_id))
        if user is not None:
            return user, "session"

    owners = list(db.scalars(
        select(AddressBook.owner_user_id)
        .join(AddressBookEntry, AddressBookEntry.address_book_id == AddressBook.id)
        .where(
            AddressBookEntry.rustdesk_id == rid,
            AddressBook.type == "personal",
        )
        .distinct()
    ))
    if len(owners) == 1:
        user = _active(db.get(User, owners[0]))
        if user is not None:
            return user, "book_owner"
    return None, "device"


def build_event(
    db: Session,
    *,
    from_id: str,
    to_id: str,
    ip: str,
    via: str,
    conn_type: str,
    token_hash: str = "",
    sessions: dict[str, SessionModel] | None = None,
    when: datetime | None = None,
) -> dict:
    """Audit kwargs for one observed connection request."""
    from_id = (from_id or "").strip()
    to_id = (to_id or "").strip()
    via = via if via in CONNECTION_VIA else "request"

    user, actor_source, login_device = resolve_by_token(db, token_hash, sessions)
    if user is not None:
        # The login that issued the token names the initiating device.
        from_id = from_id or login_device
    else:
        user, actor_source = resolve_user(db, from_id)

    user_id = user.id if user is not None else None
    from_name = device_label(db, from_id, user_id)
    to_name = device_label(db, to_id, user_id)

    details = {
        "username": user.username if user is not None else "",
        "from_id": from_id,
        "from_name": from_name,
        "to_id": to_id,
        "to_name": to_name,
        "via": via,
        "conn_type": conn_type or "",
        "actor_source": actor_source,
        # Honest scope marker: the shim saw the rendezvous request, not the
        # remote session that may or may not follow.
        "observed": "rendezvous",
    }

    event: dict = {
        "category": "connection",
        "event_type": EVENT_TYPE,
        "outcome": "unknown",
        "source_ip": ip,
        "destination": "shim",
        "http_method": "",
        "route": "",
        "request_id": "",
        "target_type": "device",
        "target_id": to_id,
        "timestamp": when or datetime.utcnow(),
        "details": details,
        "flush": False,
    }
    if user is not None:
        event["actor"] = user
    else:
        event["actor_type"] = "device"
        event["actor_id"] = from_id
        event["actor_name"] = from_name or from_id
    return event
