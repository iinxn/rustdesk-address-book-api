"""Thread-safe discovery event queue (shim -> API).

The KX shim runs in its own thread/event loop (see ShimSupervisor). It must
never touch an ORM session from that thread, so it only enqueues small tuples
here. The FastAPI lifespan owns a drain task that writes them to SQLite.

This module intentionally imports nothing heavy: the standalone shim can use
it without pulling in SQLAlchemy.
"""
from __future__ import annotations

import queue
import time

MAX_EVENTS = 20_000

# (kind, rustdesk_id, ip, source, unix_ts)
# kind: "seen" | "connect" | "disconnect" | "reset"
_q: queue.Queue = queue.Queue(maxsize=MAX_EVENTS)
_dropped = 0


def publish(kind: str, rustdesk_id: str, ip: str = "", source: str = "",
            ts: float | None = None) -> bool:
    """Enqueue an event. Never raises, drops on overflow (bounded memory)."""
    global _dropped
    rid = (rustdesk_id or "").strip()
    if not rid:
        return False
    item = (
        kind,
        rid[:64],
        (ip or "")[:64],
        (source or "")[:16],
        float(ts if ts is not None else time.time()),
    )
    try:
        _q.put_nowait(item)
        return True
    except queue.Full:
        _dropped += 1
        return False


def drain(max_items: int = 5_000) -> list[tuple]:
    out: list[tuple] = []
    for _ in range(max_items):
        try:
            out.append(_q.get_nowait())
        except queue.Empty:
            break
    return out


def qsize() -> int:
    return _q.qsize()


def dropped_count() -> int:
    return _dropped
