"""Device connection reports: POST /api/audit/{conn,file,alarm}.

Payloads mirror what the stock client posts from the controlled device
(`src/server/connection.rs`: `post_conn_audit`, `post_file_audit`,
`post_alarm_audit`). Assertions read stored audit rows from the temporary
database (see conftest.py).
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import AuditEvent
from app.services import audit as audit_svc
from app.services import connections
from app.services.auth import create_user

DEVICE = "111222333"     # the device that was connected to (reporter)
CONTROLLER = "444555666"  # the connecting client
PASSWORD = "ReportPass123!"


@pytest.fixture()
def reports(client):
    connections.reset_report_state()
    with SessionLocal() as db:
        db.query(AuditEvent).delete()
        db.commit()
    yield client
    connections.reset_report_state()


def _rows() -> list[AuditEvent]:
    """Rows written by device reports (login and other events are ignored)."""
    with SessionLocal() as db:
        return list(db.scalars(
            select(AuditEvent)
            .where(AuditEvent.category.in_(("connection", "security")))
            .order_by(AuditEvent.timestamp, AuditEvent.id)))


def _details(row: AuditEvent) -> dict:
    return json.loads(row.details)


def _post(client, kind: str, body: dict, *, conn_id: int = 7):
    payload = {"id": DEVICE, "uuid": "dXVpZA==", "conn_id": conn_id, "session_id": 99,
               "nonce": uuid.uuid4().hex, **body}
    return client.post(f"/api/audit/{kind}", json=payload)


def _session(client, controller: str = CONTROLLER, conn_id: int = 7,
             name: str = "Somebody", conn_type: int = 0) -> None:
    assert _post(client, "conn", {"action": "new", "ip": "203.0.113.10"}, conn_id=conn_id).status_code == 200
    r = _post(client, "conn", {"peer": [controller, name], "type": conn_type, "primary_auth": 3},
              conn_id=conn_id)
    assert r.status_code == 200 and r.content == b""  # client: stored only on an empty 2xx
    assert _post(client, "conn", {"action": "close"}, conn_id=conn_id).status_code == 200


def _user(display_name: str = "") -> str:
    name = f"rep{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        create_user(db, name, PASSWORD, display_name=display_name)
    return name


def test_session_produces_established_and_closed_rows(reports):
    username = _user(display_name="ivan petrov")
    # The client capitalises every word of the display name it reports.
    _session(reports, name="Ivan Petrov", conn_type=1)
    established, closed = _rows()
    assert (established.event_type, closed.event_type) == ("connection.established",
                                                         "connection.closed")
    for row in (established, closed):
        d = _details(row)
        assert row.category == "connection"
        assert row.actor_type == "user" and d["username"] == username
        assert d["actor_source"] == "reported_name"
        assert d["observed"] == "device_report"
        assert row.target_id == DEVICE and d["to_id"] == DEVICE and d["from_id"] == CONTROLLER
        assert row.source_ip == "203.0.113.10"  # the connecting address from "new"
        assert d["conn_type"] == "FILE_TRANSFER"
    assert _details(established)["auth"] == "permanent_password"
    assert _details(closed)["duration_sec"] >= 0


def test_login_from_the_controller_wins_over_the_reported_name(reports):
    username = _user()
    r = reports.post("/api/login", json={"username": username, "password": PASSWORD,
                                         "id": CONTROLLER, "uuid": "x"})
    assert r.status_code == 200
    _user(display_name="Decoy")
    _session(reports, name="Decoy")
    row = _rows()[0]
    assert _details(row)["username"] == username
    assert _details(row)["actor_source"] == "session"
    assert _details(row)["peer_name"] == "Decoy"


def test_unknown_or_ambiguous_name_stays_a_device(reports):
    _user(display_name="Twin")
    _user(display_name="Twin")
    _session(reports, controller="777888999", name="Twin")
    row = _rows()[0]
    assert row.actor_type == "device" and row.actor_id == "777888999"
    assert row.actor_name == "Twin"
    assert _details(row)["actor_source"] == "device"


def test_retry_with_the_same_nonce_is_stored_once(reports):
    payload = {"id": DEVICE, "conn_id": 3, "nonce": "n-1", "action": "new", "ip": "203.0.113.10"}
    reports.post("/api/audit/conn", json=payload)
    peer = {"id": DEVICE, "conn_id": 3, "nonce": "n-2", "peer": [CONTROLLER, "x"], "type": 0}
    assert reports.post("/api/audit/conn", json=peer).status_code == 200
    assert reports.post("/api/audit/conn", json=peer).status_code == 200
    assert len(_rows()) == 1


def test_failed_write_is_not_remembered_so_the_retry_is_stored(reports, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    real = audit_svc.record
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(audit_svc, "record", flaky)
    raw = TestClient(app, raise_server_exceptions=False)
    alarm = {"id": DEVICE, "typ": 2, "nonce": "retry-me", "conn_id": 1,
             "info": json.dumps({"ip": "203.0.113.7", "id": CONTROLLER, "name": "x"})}
    assert raw.post("/api/audit/alarm", json=alarm).status_code == 500
    assert raw.post("/api/audit/alarm", json=alarm).status_code == 200
    assert len(_rows()) == 1


def test_connection_that_never_authorised_leaves_no_row(reports):
    _post(reports, "conn", {"action": "new", "ip": "203.0.113.10"}, conn_id=9)
    _post(reports, "conn", {"action": "close"}, conn_id=9)
    assert _rows() == []


def test_file_and_alarm_reports(reports):
    info = {"ip": "203.0.113.10", "name": "Somebody", "num": 12,
            "files": [["report.xlsx", 2048], ["photo.jpg", 1024]]}
    r = _post(reports, "file", {"peer_id": CONTROLLER, "type": 1, "path": "C:/Users/x/Desktop",
                                "is_file": False, "info": json.dumps(info)})
    assert r.status_code == 200
    _post(reports, "alarm", {"typ": 2, "info": json.dumps(
        {"ip": "203.0.113.7", "id": CONTROLLER, "name": "Somebody"})})
    file_row, alarm_row = _rows()
    fd = _details(file_row)
    assert file_row.event_type == "connection.file_transfer"
    assert fd["direction"] == "to_device" and fd["file_count"] == 12
    assert fd["files"] == ["report.xlsx", "photo.jpg"] and fd["listed_bytes"] == 3072
    assert alarm_row.category == "security" and alarm_row.outcome == "denied"
    assert _details(alarm_row)["alarm"] == "six_attempts_within_one_minute"
    assert alarm_row.actor_type == "device" and alarm_row.source_ip == "203.0.113.7"


@pytest.mark.parametrize("kind,body,status", [
    ("conn", {"id": "bad id", "action": "new"}, 400),
    ("conn", {"id": DEVICE, "something": 1}, 400),
    ("nope", {"id": DEVICE}, 404),
])
def test_malformed_reports(reports, kind, body, status):
    assert reports.post(f"/api/audit/{kind}", json=body).status_code == status
    assert reports.post("/api/audit/conn", json=[1, 2]).status_code == 400
    big = {"id": DEVICE, "action": "new", "pad": "x" * 20000}
    assert reports.post("/api/audit/conn", json=big).status_code == 413
    assert _rows() == []


def test_reports_are_not_access_logged_and_respect_audit_switch(reports, monkeypatch):
    _session(reports)
    assert {r.event_type for r in _rows()} == {"connection.established", "connection.closed"}
    monkeypatch.setattr(settings, "audit_enabled", "0")
    connections.reset_report_state()
    _session(reports, conn_id=8)
    assert len(_rows()) == 2


def test_reports_are_rate_limited_per_ip(reports, monkeypatch):
    monkeypatch.setattr(settings, "audit_report_per_minute_per_ip", 2)
    assert _post(reports, "conn", {"action": "new"}).status_code == 200
    assert _post(reports, "conn", {"action": "new"}).status_code == 200
    assert _post(reports, "conn", {"action": "new"}).status_code == 429
