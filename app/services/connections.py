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

A second, independent source are **device reports**: the stock client posts
`/api/audit/conn`, `/api/audit/file` and `/api/audit/alarm` from the device
that *was connected to* (`src/server/connection.rs`, `post_conn_audit`). They
need no shim, but they are unauthenticated and the connecting user's name is
self-reported, so the rows carry ``observed: "device_report"`` and one more
attribution, ``reported_name`` (the reported name matches exactly one user).
See `device_report()`.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.core.validators import validate_rustdesk_id
from app.db.session import SessionLocal
from app.models.models import AddressBook, AddressBookEntry, DeviceInfo
from app.models.models import Session as SessionModel
from app.models.models import User
from app.services import audit as audit_svc
from app.services.auth import session_expired

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
    return user, "token_expired" if session_expired(s) else "token", s.device_id or ""


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
    if session is not None and not session_expired(session):
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
        "timestamp": when or utcnow(),
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


# --- device reports: /api/audit/{conn,file,alarm} -----------------------------
#
# Per connection the controlled device posts, in order (one queue per
# connection on the client):
#   1. {"action": "new", "ip": <connecting address>}            TCP accepted
#   2. {"peer": [<connecting id>, <name>], "type": 0..4, ...}   authorised
#   3. {"action": "close"}                                     ended
# each with "id" (reporting device), "uuid", "conn_id", "session_id" and,
# in newer clients, a unique "nonce". Only 2 and 3 become audit rows; 1 is
# remembered so the row can name the connecting IP. Connections that never
# authorise leave no row (failed passwords arrive as alarms).

REPORT_EVENT_ESTABLISHED = "connection.established"
REPORT_EVENT_CLOSED = "connection.closed"
REPORT_EVENT_FILE = "connection.file_transfer"
REPORT_EVENT_ALARM = "security.client_alarm"
REPORT_KINDS = ("conn", "file", "alarm")

# `type` of the authorised report (connection.rs, `conn_type`).
REPORT_CONN_TYPES = {0: "DEFAULT_CONN", 1: "FILE_TRANSFER", 2: "PORT_FORWARD",
                     3: "VIEW_CAMERA", 4: "TERMINAL"}
REPORT_PRIMARY_AUTH = {1: "click", 2: "temporary_password", 3: "permanent_password",
                       4: "switch_sides"}
REPORT_TWO_FACTOR = {1: "totp", 2: "trusted_device"}
REPORT_FILE_DIRECTION = {0: "from_device", 1: "to_device"}
REPORT_ALARMS = {
    0: "ip_whitelist", 1: "exceed_thirty_attempts", 2: "six_attempts_within_one_minute",
    6: "exceed_ipv6_prefix_attempts", 7: "terminal_os_login_backoff",
    8: "terminal_os_login_concurrency", 9: "session_scope_violation", 10: "id_whitelist",
}

# The client retries a report for at most 120 s; a nonce is remembered longer.
NONCE_TTL_SEC = 600.0
# A connection that never authorises is forgotten after this; an authorised
# one is kept until "close" (or this long, for a lost close).
PENDING_TTL_SEC = 600.0
OPEN_TTL_SEC = 7 * 86400.0
STATE_MAX = 20000

_state_lock = threading.Lock()
_nonces: dict[str, float] = {}
# (reporting device id, conn_id) -> what is known about that connection.
_conns: dict[tuple[str, str], dict[str, Any]] = {}


class ReportError(ValueError):
    """Malformed device report (answered with 400; the client does not retry)."""


def reset_report_state() -> None:
    with _state_lock:
        _nonces.clear()
        _conns.clear()


def _sweep(now: float) -> None:
    if len(_nonces) > STATE_MAX:
        for key, ts in list(_nonces.items()):
            if now - ts > NONCE_TTL_SEC:
                _nonces.pop(key, None)
    if len(_conns) > STATE_MAX:
        for key, conn in list(_conns.items()):
            ttl = OPEN_TTL_SEC if conn.get("established") else PENDING_TTL_SEC
            if now - conn["seen"] > ttl:
                _conns.pop(key, None)
    # Still over the cap (flood): drop the oldest pending connections first.
    while len(_conns) > STATE_MAX:
        _conns.pop(next(iter(_conns)))


def _text(value: Any, limit: int = 128) -> str:
    return audit_svc.clean_text(value, limit)


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _rid(value: Any) -> str:
    rid = _text(value, 64)
    return rid if rid and validate_rustdesk_id(rid) is None else ""


def _json_object(value: Any) -> dict:
    """`info` arrives as a JSON string inside the JSON body."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _norm_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def resolve_reported(db: Session, from_id: str, name: str) -> tuple[User | None, str]:
    """User behind a device report: login from that device, then the reported name.

    The stock client reports the `display_name` (else `name`) that our
    `/api/login` returned, with every word capitalised, or the OS user name
    when it is not logged in. A name is accepted only if it matches exactly
    one active user (display name or username, case-insensitive).
    """
    user, source = resolve_user(db, from_id)
    if source == "session":
        return user, source
    wanted = _norm_name(name)
    if wanted:
        matches = {
            u.id: u for u in db.scalars(select(User).where(User.is_disabled.is_(False)))
            if wanted in (_norm_name(u.display_name or ""), _norm_name(u.username))
        }
        if len(matches) == 1:
            return next(iter(matches.values())), "reported_name"
    return user, source


def _report_event(db: Session, *, event_type: str, category: str, outcome: str,
                  device_id: str, from_id: str, peer_name: str, source_ip: str,
                  details: dict, resolve: bool = True) -> dict:
    user: User | None = None
    actor_source = "device"
    if resolve:
        user, actor_source = resolve_reported(db, from_id, peer_name)
    user_id = user.id if user is not None else None
    from_name = device_label(db, from_id, user_id) or peer_name
    event: dict = {
        "category": category,
        "event_type": event_type,
        "outcome": outcome,
        "source_ip": source_ip,
        "destination": "api",
        "target_type": "device",
        "target_id": device_id,
        "details": {
            "username": user.username if user is not None else "",
            "from_id": from_id,
            "from_name": from_name,
            "peer_name": peer_name,
            "to_id": device_id,
            "to_name": device_label(db, device_id, user_id),
            "actor_source": actor_source,
            # Unauthenticated statement of the device that was connected to.
            "observed": "device_report",
            **details,
        },
    }
    if user is not None:
        event["actor"] = user
    else:
        event["actor_type"] = "device"
        event["actor_id"] = from_id
        event["actor_name"] = from_name or from_id
    return event


def _conn_report(db: Session, data: dict, device_id: str, conn_key: tuple[str, str],
                 now: float) -> dict | None:
    with _state_lock:
        conn = _conns.setdefault(conn_key, {"seen": now, "started": now})
        conn["seen"] = now
        action = _text(data.get("action"), 16)
        if action == "new":
            conn["ip"] = _text(data.get("ip"), 64)
            conn["started"] = now
            return None
        if action == "close":
            _conns.pop(conn_key, None)
            if not conn.get("established"):
                return None  # never authorised: nothing was recorded for it
        elif isinstance(data.get("peer"), (list, tuple)):
            peer = list(data["peer"]) + ["", ""]
            conn.update(
                established=now,
                from_id=_rid(peer[0]),
                peer_name=_text(peer[1]),
                conn_type=REPORT_CONN_TYPES.get(_int(data.get("type")) or 0, "DEFAULT_CONN"),
            )
            action = "established"
        else:
            raise ReportError("unknown conn report")
        snapshot = dict(conn)

    details: dict = {"conn_type": snapshot.get("conn_type", ""), "conn_id": conn_key[1]}
    if action == "established":
        auth = REPORT_PRIMARY_AUTH.get(_int(data.get("primary_auth")) or 0)
        two_factor = REPORT_TWO_FACTOR.get(_int(data.get("two_factor")) or 0)
        if auth:
            details["auth"] = auth
        if two_factor:
            details["two_factor"] = two_factor
        event_type = REPORT_EVENT_ESTABLISHED
    else:
        details["duration_sec"] = int(now - snapshot.get("established", now))
        event_type = REPORT_EVENT_CLOSED
    return _report_event(
        db, event_type=event_type, category="connection", outcome="success",
        device_id=device_id, from_id=snapshot.get("from_id", ""),
        peer_name=snapshot.get("peer_name", ""), source_ip=snapshot.get("ip", ""),
        details=details,
    )


def _file_report(db: Session, data: dict, device_id: str) -> dict:
    info = _json_object(data.get("info"))
    files = []
    total = 0
    raw_files = info.get("files") if isinstance(info.get("files"), list) else []
    for item in raw_files[:10]:
        if isinstance(item, (list, tuple)) and item:
            size = _int(item[1]) if len(item) > 1 else None
            files.append(_text(item[0], 128))
            total += max(size or 0, 0)
    details = {
        "direction": REPORT_FILE_DIRECTION.get(_int(data.get("type")) or 0, "from_device"),
        "files": files,
        "file_count": _int(info.get("num")) or len(files),
        "listed_bytes": total,
        "path": _text(data.get("path"), 255),
        "conn_id": _text(data.get("conn_id"), 32),
    }
    return _report_event(
        db, event_type=REPORT_EVENT_FILE, category="connection", outcome="success",
        device_id=device_id, from_id=_rid(data.get("peer_id")),
        peer_name=_text(info.get("name")), source_ip=_text(info.get("ip"), 64),
        details=details,
    )


def _alarm_report(db: Session, data: dict, device_id: str) -> dict:
    info = _json_object(data.get("info"))
    typ = _int(data.get("typ"))
    details = {
        "alarm": REPORT_ALARMS.get(typ if typ is not None else -1, f"type_{typ}"),
        "conn_id": _text(data.get("conn_id"), 32),
    }
    if info.get("conn_type"):
        details["conn_type"] = _text(info.get("conn_type"), 32)
    if info.get("message"):
        details["message"] = _text(info.get("message"), 255)
    # The other side is whoever tripped the alarm: never resolved to a user.
    return _report_event(
        db, event_type=REPORT_EVENT_ALARM, category="security", outcome="denied",
        device_id=device_id, from_id=_rid(info.get("id")),
        peer_name=_text(info.get("name")), source_ip=_text(info.get("ip"), 64),
        details=details, resolve=False,
    )


def _is_duplicate(nonce: str, now: float) -> bool:
    with _state_lock:
        _sweep(now)
        seen = _nonces.get(nonce)
        return seen is not None and now - seen <= NONCE_TTL_SEC


def device_report(db: Session, kind: str, data: dict, reporter_ip: str) -> bool:
    """Add one `/api/audit/<kind>` report to the caller's transaction.

    True when an audit row was added. Raises ReportError for a malformed
    report. Duplicate detection and nonce bookkeeping are done by
    `store_device_report()`, which also commits.
    """
    if kind not in REPORT_KINDS:
        raise ReportError("unknown report kind")
    device_id = _rid(data.get("id"))
    if not device_id:
        raise ReportError("invalid id")
    now = time.monotonic()
    if kind == "conn":
        conn_key = (device_id, _text(data.get("conn_id"), 32))
        event = _conn_report(db, data, device_id, conn_key, now)
    elif kind == "file":
        event = _file_report(db, data, device_id)
    else:
        event = _alarm_report(db, data, device_id)
    if event is None:
        return False
    event["details"]["reported_from"] = reporter_ip
    return audit_svc.record(db, **event) is not None


def store_device_report(kind: str, data: dict, reporter_ip: str) -> bool:
    """Validate, store and commit one device report; never stores a retry twice.

    The nonce is remembered only after a successful commit: when the write
    fails the caller answers 500 and the client's retry is stored normally.
    """
    nonce = _text(data.get("nonce"), 64)
    now = time.monotonic()
    if nonce and _is_duplicate(nonce, now):
        return False
    with SessionLocal() as db:
        try:
            stored = device_report(db, kind, data, reporter_ip)
            db.commit()
        except Exception:
            db.rollback()
            raise
    if nonce:
        with _state_lock:
            _nonces[nonce] = now
    return stored
