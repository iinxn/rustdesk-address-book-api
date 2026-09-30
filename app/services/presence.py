"""PresenceService: honest online/last_seen, no fakes.

Real data flow (see docs/rustdesk-api-analysis.md §presence):
- RustDesk *online* state lives on the rendezvous server (client asks hbbs
  via `query_online_states`, never the API server). We cannot see it.
- What the API server CAN see: controlled devices POST `/api/heartbeat`
  `{"id","uuid","ver",...}` every 15s, but only when the device is configured
  with a custom (non-public) api-server (src/hbbs_http/sync.rs).

Rules:
- `record_heartbeat` stamps `last_seen=now` on every entry with that rustdesk_id.
- `status_of` derives: never seen -> "unknown"; seen within ONLINE_AFTER_SEC
  -> "online"; otherwise "offline".
- Never synthesize last_seen (no `last_seen=now()` on reads).
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import AddressBookEntry

HEARTBEAT_SEC = 15
ONLINE_AFTER_SEC = 45


def record_heartbeat(db: Session, rustdesk_id: str) -> int:
    rid = (rustdesk_id or "").strip()
    if not rid:
        return 0
    now = datetime.utcnow()
    rows = db.scalars(select(AddressBookEntry).where(AddressBookEntry.rustdesk_id == rid)).all()
    for e in rows:
        e.last_seen = now
    if rows:
        db.commit()
    return len(rows)


def status_of(entry: AddressBookEntry, now: datetime | None = None) -> tuple[str, str | None]:
    """Return (state, last_seen_iso). state in online|offline|unknown."""
    if entry.last_seen is None:
        return "unknown", None
    iso = entry.last_seen.isoformat()
    if (now or datetime.utcnow()) - entry.last_seen <= timedelta(seconds=ONLINE_AFTER_SEC):
        return "online", iso
    return "offline", iso
