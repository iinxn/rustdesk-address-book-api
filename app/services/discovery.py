"""Discovery registry: drain shim events into SQLite.

Semantics (deliberately honest):
- a row means the KX shim saw this RustDesk ID identify itself while talking
  to our rendezvous endpoint (`register_peer` / `register_pk`);
- `online` comes from clean TCP connection close or from the staleness sweep,
  not from the address book and not from /api/heartbeat;
- rows survive disconnects (last_seen/last_ip kept), so a flapping client does
  not create duplicates and history is not lost.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.validators import validate_rustdesk_id
from app.models.models import DiscoveredDevice
from app.services import audit as audit_svc
from app.services import connections as connection_svc
from app.services import discovery_events

MAX_SEEN = 2_147_483_647


def _dt(ts: float | None) -> datetime:
    try:
        return datetime.utcfromtimestamp(float(ts))
    except (TypeError, ValueError, OSError):
        return datetime.utcnow()


def _merge_source(old: str, new: str) -> str:
    parts = {p for p in (old or "").replace(",", " ").split() if p}
    if new:
        parts.add(new)
    return ",".join(sorted(parts))[:16]


def reset_online(db: Session) -> None:
    """Called once at process start: no connection from a previous run is live."""
    db.execute(update(DiscoveredDevice).values(online=False))
    db.commit()


def _transition(
    *,
    category: str,
    event_type: str,
    outcome: str = "success",
    rid: str = "",
    ip: str = "",
    source: str = "",
    when: datetime | None = None,
    details: dict | None = None,
) -> dict:
    return {
        "category": category,
        "event_type": event_type,
        "outcome": outcome,
        "actor_type": "shim" if category == "device" else "system",
        "actor_id": rid,
        "source_ip": ip,
        "destination": "shim",
        "target_type": "device" if rid else "",
        "target_id": rid,
        "timestamp": when or datetime.utcnow(),
        "details": {**(details or {}), "source": source} if source else (details or {}),
        "flush": False,
    }


def drain_once(db: Session, max_items: int = 5_000) -> int:
    events = discovery_events.drain(max_items)

    rows: dict[str, DiscoveredDevice] = {}
    transitions: list[dict] = []
    # token digest -> session, built lazily once per batch (connection events).
    sessions = None
    for kind, rid, ip, source, ts, extra in events:
        extra = extra or {}
        if kind == "reset" or rid == "*":
            db.execute(update(DiscoveredDevice).values(online=False))
            rows.clear()
            transitions.append(_transition(
                category="system", event_type="system.shim_reset",
                when=datetime.utcnow(),
                details={"reason": "shim reset"},
            ))
            continue
        # Defence in depth: the shim already validates, but the queue is the
        # trust boundary between the public-facing listener and the DB.
        if validate_rustdesk_id(rid) is not None:
            continue

        when = _dt(ts)
        if kind == "connection":
            # Rendezvous request: the shim saw the initiator's id and the
            # target id, not the remote session. Do not touch discovery rows.
            from_id = str(extra.get("from_id") or "").strip()
            if from_id and validate_rustdesk_id(from_id) is not None:
                from_id = ""
            token_hash = str(extra.get("token_hash") or "")
            if token_hash and sessions is None:
                sessions = connection_svc.token_index(db)
            transitions.append(connection_svc.build_event(
                db,
                from_id=from_id,
                to_id=rid,
                ip=ip,
                via=str(extra.get("via") or ""),
                conn_type=str(extra.get("conn_type") or ""),
                token_hash=token_hash,
                sessions=sessions,
                when=when,
            ))
            continue

        row = rows.get(rid)
        is_new = False
        if row is None:
            row = db.scalar(select(DiscoveredDevice).where(DiscoveredDevice.rustdesk_id == rid))
            if row is None:
                row = DiscoveredDevice(
                    rustdesk_id=rid,
                    first_seen=when,
                    last_seen=when,
                    last_ip=ip or "",
                    source=source or "",
                    seen_count=0,
                    online=False,
                )
                db.add(row)
                is_new = True
            rows[rid] = row

        was_online = bool(row.online)
        if row.last_seen is None or when > row.last_seen:
            row.last_seen = when
        if ip:
            row.last_ip = ip
        row.source = _merge_source(row.source, source)
        row.seen_count = min((row.seen_count or 0) + 1, MAX_SEEN)

        if kind == "connect":
            row.last_connected = when
            row.online = True
        elif kind == "disconnect":
            row.last_disconnected = when
            row.online = False
        else:  # "seen"
            row.online = True

        if is_new:
            transitions.append(_transition(
                category="device", event_type="device.discovered",
                rid=rid, ip=ip, source=source, when=when,
                details={"first_seen": when.isoformat(timespec="seconds")},
            ))
        if not was_online and row.online:
            transitions.append(_transition(
                category="device", event_type="device.online",
                rid=rid, ip=ip, source=source, when=when,
            ))
        elif was_online and not row.online:
            transitions.append(_transition(
                category="device", event_type="device.offline",
                rid=rid, ip=ip, source=source, when=when,
                details={"last_seen": row.last_seen.isoformat(timespec="seconds")
                         if row.last_seen else ""},
            ))

    # Fallback for UDP-only clients (no close event) and crashed connections.
    # This must run even when the queue is empty: otherwise a row that went
    # silent after its last event could stay online forever. Only real
    # online -> offline transitions are recorded, not every heartbeat.
    cutoff = datetime.utcnow() - timedelta(seconds=max(30, settings.discovery_online_sec))
    stale = list(db.scalars(
        select(DiscoveredDevice).where(
            DiscoveredDevice.online.is_(True),
            DiscoveredDevice.last_seen < cutoff,
        )
    ))
    for row in stale:
        row.online = False
        transitions.append(_transition(
            category="device", event_type="device.offline",
            rid=row.rustdesk_id, ip=row.last_ip, source="stale_sweep",
            details={
                "last_seen": row.last_seen.isoformat(timespec="seconds")
                if row.last_seen else "",
                "detected": True,
            },
        ))

    for item in transitions:
        audit_svc.record(db, **item)
    db.commit()
    return len(events)
