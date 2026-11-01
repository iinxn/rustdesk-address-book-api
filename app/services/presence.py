"""Presence: honest online/last_seen from `/api/heartbeat`, no fakes.

Real data flow (see docs/en.md §5):
- RustDesk *online* state lives on the rendezvous server (client asks hbbs
  via `query_online_states`, never the API server). We cannot see it.
- What the API server CAN see: controlled devices POST `/api/heartbeat`
  `{"id","uuid","ver",...}` every 15s, but only when the device is configured
  with a custom (non-public) api-server (src/hbbs_http/sync.rs).

Rules:
- `HeartbeatWriter.record` stamps `last_seen=now` on every entry with that id and
  refreshes liveness of an existing `device_info` row (never creates one).
- `status_of` derives: never seen -> "unknown"; seen within ONLINE_AFTER_SEC
  -> "online"; otherwise "offline". `ab.book_counts` applies the same rule
  in SQL.
- Never synthesize last_seen (no `last_seen=now()` on reads).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import bindparam, case, update
from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models.models import AddressBookEntry, DeviceInfo

log = logging.getLogger(__name__)

# The stock client heartbeats every 15 s; three missed beats = offline.
ONLINE_AFTER_SEC = 45

_entries = AddressBookEntry.__table__
_infos = DeviceInfo.__table__

# executemany statements: one round trip per batch, not per device.
# `updated_at` is pinned: a heartbeat is liveness, not an edit.
_ENTRY_STMT = (
    update(_entries)
    .where(_entries.c.rustdesk_id == bindparam("b_rid"))
    .values(last_seen=bindparam("b_now"), updated_at=_entries.c.updated_at)
)
_INFO_STMT = (
    update(_infos)
    .where(_infos.c.rustdesk_id == bindparam("b_rid"))
    .values(
        last_heartbeat_at=bindparam("b_now"),
        version=case((bindparam("b_ver") != "", bindparam("b_ver")), else_=_infos.c.version),
        ip=case((bindparam("b_ip") != "", bindparam("b_ip")), else_=_infos.c.ip),
    )
)


class HeartbeatWriter:
    """Group commit for heartbeats.

    Each heartbeat used to be its own transaction, i.e. one fsync, so the
    disk — not Python or SQL — capped throughput (~200/s with second-long
    tails when the fleet came back at once). Here concurrent callers park
    their update in `_pending`; whoever holds the write lock commits
    everything pending in one transaction, and callers whose update was
    included return without writing. Under low load a batch is one row and
    nothing waits; under a burst batches grow by themselves. `record()`
    returns only after the caller's update is committed (or after the
    batch that contained it failed — heartbeats are liveness data and the
    device repeats them every 15 s, so that failure is logged, not raised to
    every waiter).
    """

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory
        self._mutex = threading.Lock()   # guards the fields below
        self._write = threading.Lock()   # one writer at a time
        self._pending: dict[str, dict] = {}
        self._batch_no = 0               # batch currently being collected
        self._done_no = 0                # highest batch that finished

    def record(self, rustdesk_id: str, version: str = "", ip: str = "") -> None:
        rid = (rustdesk_id or "").strip()
        if not rid:
            return
        with self._mutex:
            self._pending[rid] = {"b_rid": rid, "b_now": utcnow(),
                                  "b_ver": version[:32], "b_ip": ip[:64]}
            mine = self._batch_no
        with self._write:
            with self._mutex:
                if self._done_no > mine:
                    return  # an earlier writer committed our update
                batch, self._pending = list(self._pending.values()), {}
                self._batch_no += 1
                number = self._batch_no
            try:
                self._flush(batch)
            finally:
                with self._mutex:
                    self._done_no = number

    def _flush(self, batch: list[dict]) -> None:
        if not batch:
            return
        with self._session_factory() as db:
            try:
                db.execute(_ENTRY_STMT, batch)
                db.execute(_INFO_STMT, batch)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("heartbeat batch of %d device(s) was not stored", len(batch))
                raise


def status_of(last_seen: datetime | None, now: datetime | None = None) -> str:
    """online | offline | unknown for one `last_seen` value."""
    if last_seen is None:
        return "unknown"
    if (now or utcnow()) - last_seen <= timedelta(seconds=ONLINE_AFTER_SEC):
        return "online"
    return "offline"
