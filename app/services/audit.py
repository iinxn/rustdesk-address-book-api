"""Persistent audit log: who did what, when, from where and with what result.

Two very different streams are kept apart on purpose:

* **Technical logs** go to stdout/stderr (`logging`) and are rotated by the
  container runtime. They are for diagnosis and may contain identifiers, but
  never secrets.
* **Audit events** go to SQLite (`audit_events`) and answer questions like
  "who logged in from which IP", "who deleted this device" or "who was denied
  access to that book". They are append-only for normal users; the only
  deletion path is the retention job (`cleanup_once`).

Design decisions (see `docs/knowledge/DECISIONS.md` DEC-017):

* Mutating business operations write their audit row into the **same**
  transaction as the change (`record()` + `db.flush()`). If the audit row
  cannot be written the transaction fails and the API returns 500 — a
  security-relevant change must never commit silently without a trace.
* Access events, authentication failures and device-state transitions are
  written **best-effort** (`write_event()` / `write_events()` with their own
  session): they must not turn a successful request into a failure, and a
  failure there is logged loudly.
* Heartbeats and sysinfo uploads are excluded by the middleware. A single
  state transition is recorded, not every request, so ~800 devices posting
  every 15 s cannot grow the table.
* Every stored string is bounded and stripped of control characters; JSON
  details are redacted by key name and capped in size.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import AuditEvent
from app.models.models import Session as SessionModel
from app.models.models import User

log = logging.getLogger("app.audit")

CATEGORIES = ("access", "auth", "connection", "device", "data", "security", "system")
OUTCOMES = ("success", "denied", "error", "partial", "unknown")
ACTOR_TYPES = ("user", "device", "shim", "system", "anonymous")

MAX_TEXT = 255
MAX_NAME = 128
MAX_ID = 128
MAX_ROUTE = 255
MAX_DETAILS_BYTES = 4096
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 90
CLEANUP_BATCH = 500
CLEANUP_MAX_BATCHES = 200  # 100k rows per run; the rest goes on the next run

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENSITIVE_KEYS = {
    "password", "password_hash", "passwd", "secret", "token", "access_token",
    "refresh_token", "authorization", "cookie", "set-cookie", "session",
    "session_id", "api_key", "apikey", "private_key", "id_key", "hash",
    "hash_value", "web_secret", "device_secret", "shim_id_key",
}

_CLEANUP_LOCK = threading.Lock()
_warned_retention: set[str] = set()


# --- request context -------------------------------------------------------

@dataclass
class RequestContext:
    request_id: str = ""
    source_ip: str = ""
    destination: str = "api"
    http_method: str = ""
    route: str = ""


_ctx: ContextVar[RequestContext] = ContextVar("audit_request_context", default=RequestContext())


def set_request_context(ctx: RequestContext):
    return _ctx.set(ctx)


def reset_request_context(token) -> None:
    _ctx.reset(token)


def current_request_id() -> str:
    return _ctx.get().request_id


def new_request_id() -> str:
    return uuid.uuid4().hex


# --- sanitising ------------------------------------------------------------

def clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    """Single-line, control-character free, bounded string."""
    if value is None:
        return ""
    text = _CONTROL.sub(" ", str(value))
    return " ".join(text.split())[:limit]


def _is_sensitive(key: str) -> bool:
    k = key.strip().lower().replace("-", "_")
    if k in _SENSITIVE_KEYS:
        return True
    # Only suffix matches are secrets. Flags such as `password_set` or
    # `password_configured` describe state and must stay visible.
    return k.endswith((
        "_password", "_token", "_secret", "_authorization", "_cookie",
        "_api_key", "_private_key", "_session_id",
    ))


def redact(value: Any, key: str = "") -> Any:
    """Recursively drop secret-looking keys and bound every value.

    Never used to store request bodies; callers pass explicit, small dicts.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            name = clean_text(raw_key, 64)
            if not name:
                continue
            out[name] = "<redacted>" if _is_sensitive(name) else redact(raw_value, name)
        return out
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in list(value)[:50]]
    if isinstance(value, str):
        return clean_text(value, 512)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return clean_text(value, 512)


def safe_details(details: dict | None) -> str:
    """Redacted, size-capped JSON for the `details` column."""
    if not details:
        return "{}"
    cleaned = redact(details)
    try:
        raw = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        raw = json.dumps({"error": "unserialisable"})
    if len(raw.encode("utf-8")) > MAX_DETAILS_BYTES:
        return json.dumps({"truncated": True, "bytes": len(raw.encode("utf-8"))})
    return raw


def parse_details(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def diff_fields(before: dict, after: dict) -> dict:
    """Only changed keys, with bounded old/new values.

    Callers pass short, non-secret fields (alias, name, flags). Passwords and
    tokens must never be included; report them as `{"password_changed": True}`.
    """
    out: dict[str, dict] = {}
    for key in sorted(set(before) | set(after)):
        old = clean_text(before.get(key), 200)
        new = clean_text(after.get(key), 200)
        if old != new:
            out[clean_text(key, 32)] = {"from": old, "to": new}
    return out


# --- writing ---------------------------------------------------------------

def record(
    db: Session,
    *,
    category: str,
    event_type: str,
    outcome: str = "success",
    actor: User | None = None,
    actor_type: str | None = None,
    actor_id: str = "",
    actor_name: str = "",
    source_ip: str | None = None,
    destination: str | None = None,
    http_method: str | None = None,
    route: str | None = None,
    target_type: str = "",
    target_id: str = "",
    status_code: int | None = None,
    duration_ms: int | None = None,
    request_id: str | None = None,
    details: dict | None = None,
    timestamp: datetime | None = None,
    flush: bool = True,
) -> AuditEvent | None:
    """Add one audit row to the caller's transaction (flushed, not committed).

    `flush()` raises if the row cannot be stored: callers that mutate data rely
    on this to roll the whole operation back instead of reporting success
    without an audit trail.
    """
    if not settings.audit_enabled_flag:
        return None

    if actor is not None:
        actor_type = "user"
        actor_id = actor.id
        actor_name = actor.display_name or actor.username
    elif actor_type is None:
        actor_type = "system"

    ctx = _ctx.get()
    event = AuditEvent(
        timestamp=timestamp or datetime.utcnow(),
        category=category if category in CATEGORIES else "system",
        event_type=clean_text(event_type, 48) or "unknown",
        actor_type=actor_type if actor_type in ACTOR_TYPES else "system",
        actor_id=clean_text(actor_id, 64),
        actor_name=clean_text(actor_name, MAX_NAME),
        source_ip=clean_text(source_ip if source_ip is not None else ctx.source_ip, 64),
        destination=clean_text(destination if destination is not None else ctx.destination, 32),
        http_method=clean_text(http_method if http_method is not None else ctx.http_method, 8).upper(),
        route=clean_text(route if route is not None else ctx.route, MAX_ROUTE),
        target_type=clean_text(target_type, 32),
        target_id=clean_text(target_id, MAX_ID),
        outcome=outcome if outcome in OUTCOMES else "unknown",
        status_code=status_code,
        duration_ms=duration_ms,
        request_id=clean_text(request_id if request_id is not None else ctx.request_id, 36),
        details=safe_details(details),
    )
    db.add(event)
    if flush:
        db.flush()
    return event


def write_event(**kwargs) -> bool:
    """Best-effort isolated write: own session, own commit, never raises."""
    if not settings.audit_enabled_flag:
        return False
    try:
        with SessionLocal() as db:
            record(db, **kwargs)
            db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - audit must never break the caller
        log.error("audit write failed (%s)", type(exc).__name__)
        return False


def write_events(items: Iterable[dict]) -> int:
    """Best-effort batch write; one failing batch is logged, not raised."""
    written = 0
    try:
        with SessionLocal() as db:
            for kwargs in items:
                if record(db, **kwargs) is not None:
                    written += 1
            db.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("audit batch write failed (%s)", type(exc).__name__)
        return 0
    return written


def user_for_token(db: Session, token: str) -> User | None:
    """Read-only actor lookup for the access middleware (never mutates)."""
    if not token:
        return None
    s = db.scalar(select(SessionModel).where(SessionModel.token == token))
    if s is None:
        return None
    if s.expires_at is not None and s.expires_at < datetime.utcnow():
        return None
    user = db.get(User, s.user_id)
    if user is None or user.is_disabled:
        return None
    return user


def write_access(
    *,
    method: str,
    route: str,
    path: str,
    status_code: int,
    duration_ms: int,
    request_id: str,
    source_ip: str,
    token: str,
    params: dict,
) -> bool:
    """One access/security row for a significant API request."""
    try:
        with SessionLocal() as db:
            actor = user_for_token(db, token)
            if status_code == 401:
                category, event_type, outcome = "security", "access.unauthenticated", "denied"
            elif status_code == 403:
                category, event_type, outcome = "security", "access.denied", "denied"
            elif status_code == 429:
                category, event_type, outcome = "security", "security.rate_limited", "denied"
            elif status_code >= 500:
                category, event_type, outcome = "access", "api.request", "error"
            elif status_code >= 400:
                category, event_type, outcome = "access", "api.request", "error"
            else:
                category, event_type, outcome = "access", "api.request", "success"

            target_type, target_id = target_from_params(params)
            record(
                db,
                category=category,
                event_type=event_type,
                outcome=outcome,
                actor=actor,
                actor_type=None if actor is not None else "anonymous",
                source_ip=source_ip,
                destination="api",
                http_method=method,
                route=route,
                target_type=target_type,
                target_id=target_id,
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                details=None,
            )
            db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("audit access write failed (%s)", type(exc).__name__)
        return False


def target_from_params(params: dict) -> tuple[str, str]:
    """Map path parameters to (target_type, target_id)."""
    mapping = (
        ("eid", "entry"),   # address-book entry id; explicit events carry the rustdesk id
        ("bid", "book"),
        ("guid", "book"),
        ("ab", "book"),
        ("book", "book"),
        ("tid", "tag"),
        ("uid", "user"),
        ("rid", "device"),
    )
    for key, target_type in mapping:
        value = params.get(key)
        if value:
            return target_type, clean_text(value, MAX_ID)
    return "", ""


# --- rate-limit diagnostics ------------------------------------------------

_LIMIT_LOCK = threading.Lock()
_LIMIT_STATE: dict[str, tuple[float, int, str]] = {}
_LIMIT_AUDIT: dict[tuple[str, str], float] = {}
_LIMIT_LOG_SEC = 60.0
_LIMIT_AUDIT_SEC = 300.0
_LIMIT_MAX_KEYS = 2000


def note_rate_limited(route: str, ip: str, retry_after: int = 0, audit_it: bool = False) -> None:
    """Throttled diagnostics for HTTP 429.

    One log line per route per minute with a suppressed counter and a sample
    IP: a mass 429 storm stays diagnosable without producing a line per
    request. Heartbeats/sysinfo pass `audit_it=False` and never create rows.
    """
    now = time.monotonic()
    key = route[:80] or "/"
    with _LIMIT_LOCK:
        last, suppressed, sample = _LIMIT_STATE.get(key, (0.0, 0, ""))
        suppressed += 1
        sample = sample or ip
        if now - last < _LIMIT_LOG_SEC:
            _LIMIT_STATE[key] = (last, suppressed, sample)
            do_log = False
        else:
            _LIMIT_STATE[key] = (now, 0, "")
            do_log = True
        if len(_LIMIT_STATE) > _LIMIT_MAX_KEYS:
            for k in [k for k, (ts, _, _) in _LIMIT_STATE.items() if now - ts > _LIMIT_LOG_SEC]:
                _LIMIT_STATE.pop(k, None)

        do_audit = False
        if audit_it:
            audit_key = (key, ip[:64])
            prev = _LIMIT_AUDIT.get(audit_key)
            if prev is None or now - prev >= _LIMIT_AUDIT_SEC:
                _LIMIT_AUDIT[audit_key] = now
                do_audit = True
            if len(_LIMIT_AUDIT) > _LIMIT_MAX_KEYS:
                for k, ts in list(_LIMIT_AUDIT.items()):
                    if now - ts >= _LIMIT_AUDIT_SEC:
                        _LIMIT_AUDIT.pop(k, None)

    if do_log:
        log.warning(
            "rate limited: route=%s suppressed=%d sample_ip=%s retry_after=%s",
            key, suppressed, sample, retry_after,
        )
    if do_audit:
        write_event(
            category="security",
            event_type="security.rate_limited",
            outcome="denied",
            actor_type="anonymous",
            source_ip=ip,
            destination="api",
            route=route,
            status_code=429,
            details={"route": route, "retry_after": retry_after},
        )


def reset_rate_limit_diagnostics() -> None:
    """Test hook: forget throttling state."""
    with _LIMIT_LOCK:
        _LIMIT_STATE.clear()
        _LIMIT_AUDIT.clear()


# --- retention -------------------------------------------------------------

def retention_days() -> int:
    """Clamp the configured retention to [30, 90]; invalid values fall back."""
    raw = str(settings.audit_retention_days or "").strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_RETENTION_DAYS
        if raw not in _warned_retention:
            _warned_retention.add(raw)
            log.warning("AUDIT_RETENTION_DAYS=%r is not a number; using %d", raw, value)
        return value
    if value < MIN_RETENTION_DAYS:
        if raw not in _warned_retention:
            _warned_retention.add(raw)
            log.warning("AUDIT_RETENTION_DAYS=%s below minimum; using %d", value, MIN_RETENTION_DAYS)
        return MIN_RETENTION_DAYS
    if value > MAX_RETENTION_DAYS:
        if raw not in _warned_retention:
            _warned_retention.add(raw)
            log.warning("AUDIT_RETENTION_DAYS=%s above maximum; using %d", value, MAX_RETENTION_DAYS)
        return MAX_RETENTION_DAYS
    return value


def cleanup_once(now: datetime | None = None) -> dict:
    """Delete events older than the retention window in bounded batches.

    Runs at most once concurrently (`_CLEANUP_LOCK`). Never drops the table and
    never runs VACUUM. A summary row is written after a successful run, so the
    log itself records that retention happened.
    """
    if not _CLEANUP_LOCK.acquire(blocking=False):
        return {"skipped": True, "deleted": 0}
    started = time.monotonic()
    days = retention_days()
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    deleted = 0
    try:
        with SessionLocal() as db:
            while deleted < CLEANUP_BATCH * CLEANUP_MAX_BATCHES:
                ids = list(db.scalars(
                    select(AuditEvent.id)
                    .where(AuditEvent.timestamp < cutoff)
                    .limit(CLEANUP_BATCH)
                ))
                if not ids:
                    break
                db.execute(delete(AuditEvent).where(AuditEvent.id.in_(ids)))
                db.commit()
                deleted += len(ids)
                if len(ids) < CLEANUP_BATCH:
                    break
            record(
                db,
                category="system",
                event_type="audit.retention",
                outcome="success",
                actor_type="system",
                destination="system",
                details={
                    "deleted": deleted,
                    "retention_days": days,
                    "cutoff": cutoff.isoformat(timespec="seconds"),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            db.commit()
        log.info(
            "audit retention removed %d event(s) older than %s (retention=%d days)",
            deleted, cutoff.isoformat(timespec="seconds"), days,
        )
        return {"deleted": deleted, "cutoff": cutoff.isoformat(timespec="seconds"),
                "days": days, "skipped": False}
    except Exception as exc:  # noqa: BLE001
        log.error("audit retention failed (%s), deleted=%d so far", type(exc).__name__, deleted)
        return {"deleted": deleted, "days": days, "skipped": False,
                "error": type(exc).__name__}
    finally:
        _CLEANUP_LOCK.release()


# --- serialisation ---------------------------------------------------------

def serialize(event: AuditEvent) -> dict:
    return {
        "id": event.id,
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "category": event.category,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "actor_name": event.actor_name,
        "source_ip": event.source_ip,
        "destination": event.destination,
        "http_method": event.http_method,
        "route": event.route,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "outcome": event.outcome,
        "status_code": event.status_code,
        "duration_ms": event.duration_ms,
        "request_id": event.request_id,
        "details": parse_details(event.details),
    }
