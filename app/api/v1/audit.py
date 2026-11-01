"""`/api/v1/audit*`: admin-only, server-side filtered audit history."""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.errors import PanelError
from app.api.v1.common import PREFIX, page_window, require_admin
from app.core.config import settings
from app.core.timeutil import to_naive_utc
from app.db.session import get_db
from app.models.models import AuditEvent, User
from app.services import audit as audit_svc

router = APIRouter(prefix=PREFIX)


def _filter_time(raw: str) -> datetime | None:
    """ISO timestamp from a filter, as naive UTC; '' means no bound."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return to_naive_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        raise PanelError(400, "invalid date filter") from None


def _contains(column, raw: str, limit: int):
    return column.like(f"%{raw.strip()[:limit]}%")


@router.get("/audit/meta")
def audit_meta(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Filter vocabulary for the UI. Admin-only, like the log itself."""
    require_admin(user)
    event_types = db.scalars(select(AuditEvent.event_type).distinct().order_by(AuditEvent.event_type))
    target_types = db.scalars(select(AuditEvent.target_type).distinct().order_by(AuditEvent.target_type))
    return {
        "categories": list(audit_svc.CATEGORIES),
        "outcomes": list(audit_svc.OUTCOMES),
        "event_types": [v for v in event_types if v],
        "target_types": [v for v in target_types if v],
        "retention_days": audit_svc.retention_days(),
        "enabled": settings.audit_enabled_flag,
    }


@router.get("/audit")
def list_audit(
    page: int = 1,
    page_size: int = 50,
    sort: str = "desc",
    category: str = "",
    event_type: str = "",
    actor: str = "",
    source_ip: str = "",
    target_type: str = "",
    target_id: str = "",
    outcome: str = "",
    search: str = "",
    since: str = "",
    until: str = "",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Server-side filtered, paginated audit history. Admin only.

    The response never contains raw request bodies or secrets: details were
    redacted and bounded when the row was written. Unknown fields are returned
    as empty strings, so the UI can show "unknown" instead of inventing an
    actor.
    """
    require_admin(user)
    since_dt, until_dt = _filter_time(since), _filter_time(until)

    q = select(AuditEvent)
    if since_dt is not None:
        q = q.where(AuditEvent.timestamp >= since_dt)
    if until_dt is not None:
        q = q.where(AuditEvent.timestamp <= until_dt)
    for column, value in ((AuditEvent.category, category), (AuditEvent.event_type, event_type),
                          (AuditEvent.outcome, outcome), (AuditEvent.target_type, target_type)):
        if value:
            q = q.where(column == value)
    if target_id.strip():
        q = q.where(_contains(AuditEvent.target_id, target_id, 128))
    if source_ip.strip():
        q = q.where(_contains(AuditEvent.source_ip, source_ip, 64))
    if actor.strip():
        q = q.where(or_(_contains(AuditEvent.actor_name, actor, 128),
                        _contains(AuditEvent.actor_id, actor, 128)))
    if search.strip():
        q = q.where(or_(*(_contains(c, search, 128) for c in (
            AuditEvent.id, AuditEvent.request_id, AuditEvent.route,
            AuditEvent.target_id, AuditEvent.actor_name))))

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    offset, limit = page_window(page, page_size)
    order = AuditEvent.timestamp.asc() if sort == "asc" else AuditEvent.timestamp.desc()
    rows = db.scalars(q.order_by(order, AuditEvent.id.desc()).offset(offset).limit(limit))
    return {"total": total, "data": [audit_svc.serialize(e) for e in rows]}


@router.get("/audit/{eid}")
def get_audit_event(eid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    event = db.get(AuditEvent, eid)
    if event is None:
        raise PanelError(404, "not found")
    return audit_svc.serialize(event)
