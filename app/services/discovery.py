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


def drain_once(db: Session, max_items: int = 5_000) -> int:
    events = discovery_events.drain(max_items)

    rows: dict[str, DiscoveredDevice] = {}
    for kind, rid, ip, source, ts in events:
        if kind == "reset" or rid == "*":
            db.execute(update(DiscoveredDevice).values(online=False))
            rows.clear()
            continue
        # Defence in depth: the shim already validates, but the queue is the
        # trust boundary between the public-facing listener and the DB.
        if validate_rustdesk_id(rid) is not None:
            continue

        when = _dt(ts)
        row = rows.get(rid)
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
            rows[rid] = row

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

    # Fallback for UDP-only clients (no close event) and crashed connections.
    # This must run even when the queue is empty: otherwise a row that went
    # silent after its last event could stay online forever.
    cutoff = datetime.utcnow() - timedelta(seconds=max(30, settings.discovery_online_sec))
    db.execute(
        update(DiscoveredDevice)
        .where(DiscoveredDevice.online.is_(True), DiscoveredDevice.last_seen < cutoff)
        .values(online=False)
    )
    db.commit()
    return len(events)
