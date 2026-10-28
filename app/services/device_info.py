"""Client-uploaded system information (`POST /api/sysinfo`).

Source of truth is the stock RustDesk client (`src/hbbs_http/sync.rs`): when a
custom (non-public) API server is configured it uploads a JSON object with
`cpu`, `memory`, `os`, `hostname`, optionally `username`, plus `version`, `id`
and `uuid`. There is no GPU/disk/network/RAM-usage data in that payload, so we
never invent it.

Security: the endpoint is unauthenticated by design (the stock client sends no
credentials). We whitelist fields and deliberately drop `uuid` and every
preset/option key (some contain address-book passwords).
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import AddressBookEntry, DeviceInfo, DiscoveredDevice

SYSINFO_VER = "1"
REFRESH_TTL_SEC = 30 * 60
# The stock client uploads within ~3 s of a heartbeat that asked for sysinfo.
# Approval is one-shot and short-lived so a stray/duplicated upload cannot
# overwrite a card long after the operator pressed the button.
APPROVAL_TTL_SEC = 120

# Fields that make a card useful. A row missing any of them may still be
# completed by the client's automatic upload (e.g. Windows reports an empty
# username before login, then uploads again after login).
_REQUIRED_FIELDS = ("hostname", "os", "username")

_CPU_RE = re.compile(
    r"^(?:(?P<model>.*),\s*)?(?P<freq>\d+(?:\.\d+)?)GHz,\s*"
    r"(?P<logical>\d+)/(?P<physical>\d+) cores$"
)
_CPU_CORES_RE = re.compile(r"^(?P<logical>\d+)/(?P<physical>\d+) cores$")
_MEM_RE = re.compile(r"^(?P<gb>\d+(?:\.\d+)?)GB$")

_refresh: dict[str, float] = {}
# rid -> unix deadline, set only when the panel asked for a re-upload and the
# heartbeat delivered that request.
_approved: dict[str, float] = {}
_refresh_lock = threading.Lock()


def _text(payload: dict, key: str, limit: int) -> str | None:
    if key not in payload:
        return None
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    return value.strip()[:limit]


def parse_cpu(raw: str) -> dict:
    out = {"cpu_model": "", "cpu_freq_ghz": None, "cpu_logical": None, "cpu_physical": None}
    s = (raw or "").strip()
    m = _CPU_RE.match(s) or _CPU_CORES_RE.match(s)
    if not m:
        return out
    model = (m.groupdict().get("model") or "").strip()
    freq = m.groupdict().get("freq")
    logical = int(m.group("logical"))
    physical = int(m.group("physical"))
    out["cpu_model"] = model[:255]
    if freq is not None:
        value = float(freq)
        out["cpu_freq_ghz"] = value if value > 0 else None
    out["cpu_logical"] = logical if logical > 0 else None
    out["cpu_physical"] = physical if physical > 0 else None
    return out


def parse_memory(raw: str) -> float | None:
    m = _MEM_RE.match((raw or "").strip())
    if not m:
        return None
    value = float(m.group("gb"))
    return value if value > 0 else None


def parse_os(raw: str) -> dict:
    s = (raw or "").strip()
    out = {"os_name": "", "os_version": ""}
    if not s:
        return out
    if " / " in s:
        name, rest = s.split(" / ", 1)
        out["os_name"] = name.strip()[:128]
        out["os_version"] = rest.strip()[:255]
    else:
        out["os_name"] = s[:128]
    return out


def device_known(db: Session, rustdesk_id: str) -> bool:
    """True when the panel can already see this id (book entry or discovery).

    `/api/sysinfo` is unauthenticated, so row creation is restricted to ids the
    operator actually manages. Unknown ids still get `SYSINFO_UPDATED` (the
    client must not retry), but nothing is written: this keeps a flood of
    random ids from growing the database.
    """
    if db.scalar(
        select(AddressBookEntry.id)
        .where(AddressBookEntry.rustdesk_id == rustdesk_id)
        .limit(1)
    ) is not None:
        return True
    return db.scalar(
        select(DiscoveredDevice.id)
        .where(DiscoveredDevice.rustdesk_id == rustdesk_id)
        .limit(1)
    ) is not None


def missing_fields(row: DeviceInfo) -> list[str]:
    return [name for name in _REQUIRED_FIELDS if not getattr(row, name, "")]


def _fills(payload: dict, fields: list[str]) -> bool:
    """True only if the payload supplies a non-empty value for every field."""
    for name in fields:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            return False
    return True


def save_sysinfo(
    db: Session, rustdesk_id: str, payload: dict, ip: str = "", force: bool = False
) -> bool:
    """Whitelist + persist one report. Never raises on missing/odd fields.

    Automatic uploads are intentionally write-once: once a card is complete,
    only a panel-approved refresh (`force=True`) may overwrite it. The client
    re-sends sysinfo on its own at startup and after a Windows user logs in, so
    ignoring unchanged reports is what keeps 800 devices from rewriting the DB
    every time they start. Returns True when a row was actually written.
    """
    row = db.get(DeviceInfo, rustdesk_id)

    if row is not None and not force:
        missing = missing_fields(row)
        if not missing:
            return False
        # Let the client finish a card (e.g. username appears after login), but
        # do not rewrite an incomplete card with fields it still lacks.
        if not _fills(payload, missing):
            return False

    if row is None:
        if not force and not device_known(db, rustdesk_id):
            return False
        row = DeviceInfo(rustdesk_id=rustdesk_id)
        db.add(row)

    hostname = _text(payload, "hostname", 128)
    username = _text(payload, "username", 128)
    os_raw = _text(payload, "os", 255)
    cpu_raw = _text(payload, "cpu", 255)
    memory_raw = _text(payload, "memory", 64)
    version = _text(payload, "version", 32)

    if hostname is not None:
        row.hostname = hostname
    if username is not None:
        row.username = username
    if os_raw is not None:
        row.os = os_raw
        parsed = parse_os(os_raw)
        row.os_name, row.os_version = parsed["os_name"], parsed["os_version"]
    if cpu_raw is not None:
        row.cpu = cpu_raw
        parsed = parse_cpu(cpu_raw)
        row.cpu_model = parsed["cpu_model"]
        row.cpu_freq_ghz = parsed["cpu_freq_ghz"]
        row.cpu_logical = parsed["cpu_logical"]
        row.cpu_physical = parsed["cpu_physical"]
    if memory_raw is not None:
        row.memory = memory_raw
        row.memory_gb = parse_memory(memory_raw)
    if version is not None:
        row.version = version

    if ip:
        row.ip = ip[:64]
    row.collected_at = datetime.utcnow()
    db.commit()
    return True


def record_heartbeat(db: Session, rustdesk_id: str, version: str = "", ip: str = "") -> None:
    """Track liveness of the API channel (does not create an info row)."""
    row = db.get(DeviceInfo, rustdesk_id)
    if row is None:
        return
    row.last_heartbeat_at = datetime.utcnow()
    if version:
        row.version = version[:32]
    if ip:
        row.ip = ip[:64]
    db.commit()


def request_refresh(rustdesk_id: str) -> None:
    """Ask the client to re-upload on its next heartbeat (consumed once)."""
    now = time.time()
    with _refresh_lock:
        if len(_refresh) > 1_000:
            for rid, exp in list(_refresh.items()):
                if exp < now:
                    _refresh.pop(rid, None)
        _refresh[rustdesk_id] = now + REFRESH_TTL_SEC


def take_refresh(rustdesk_id: str) -> bool:
    """Consume the panel flag and grant one approved overwrite.

    The heartbeat is what delivers `{"sysinfo": true}` to the client, so the
    approval is armed here and consumed by the `/api/sysinfo` request the
    client sends a few seconds later.
    """
    now = time.time()
    with _refresh_lock:
        exp = _refresh.pop(rustdesk_id, None)
        valid = exp is not None and exp >= now
        if valid:
            if len(_approved) > 1_000:
                for rid, deadline in list(_approved.items()):
                    if deadline < now:
                        _approved.pop(rid, None)
            _approved[rustdesk_id] = now + APPROVAL_TTL_SEC
        return valid


def take_approval(rustdesk_id: str) -> bool:
    """One-shot permission for an explicit (panel-initiated) overwrite."""
    now = time.time()
    with _refresh_lock:
        exp = _approved.pop(rustdesk_id, None)
        return exp is not None and exp >= now


def reset_refresh_state() -> None:
    """Forget pending refreshes. Used by tests and after reconfiguration."""
    with _refresh_lock:
        _refresh.clear()
        _approved.clear()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def info_out(info: DeviceInfo | None) -> dict | None:
    if info is None:
        return None
    return {
        "rustdesk_id": info.rustdesk_id,
        "hostname": info.hostname,
        "username": info.username,
        "os": info.os,
        "os_name": info.os_name,
        "os_version": info.os_version,
        "cpu": info.cpu,
        "cpu_model": info.cpu_model,
        "cpu_freq_ghz": info.cpu_freq_ghz,
        "cpu_logical": info.cpu_logical,
        "cpu_physical": info.cpu_physical,
        "memory": info.memory,
        "memory_gb": info.memory_gb,
        "version": info.version,
        "ip": info.ip,
        "collected_at": _iso(info.collected_at),
        "last_heartbeat_at": _iso(info.last_heartbeat_at),
    }
