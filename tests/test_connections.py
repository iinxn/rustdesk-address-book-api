"""Connection audit: "user X asked to connect to device Y".

The shim parser is fed real protobuf frames as the stock client builds them
(PunchHoleRequest/RequestRelay with the API access token), the event goes
through the real discovery queue and drain, and the assertions read stored
audit rows from the temporary database (see conftest.py).
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.models import AddressBook, AddressBookEntry, AuditEvent, DeviceInfo, User
from app.services import discovery, discovery_events
from app.services.connections import token_digest
from app.shim import rendezvous_pb2 as rz
from app.shim import shim

TARGET = "123456789"
INITIATOR = "987654321"


@pytest.fixture()
def conn_clean(client, monkeypatch):
    monkeypatch.setattr(shim, "CONNECTION_DEDUPE_SEC", 60.0)
    shim._CONN_LAST.clear()
    discovery_events.drain(100_000)
    with SessionLocal() as db:
        db.query(AuditEvent).delete()
        db.commit()
    yield
    shim._CONN_LAST.clear()


def _user_with_login(client, device_id: str = INITIATOR) -> tuple[str, str]:
    from app.services.auth import create_user

    name = f"conn-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        create_user(db, name, "ConnPass123!", is_admin=False)
    r = client.post("/api/login", json={
        "username": name, "password": "ConnPass123!", "type": "account",
        "id": device_id, "uuid": uuid.uuid4().hex,
    })
    assert r.status_code == 200, r.text
    return name, r.json()["access_token"]


def _add_alias(username: str, rid: str, alias: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        book = db.scalar(select(AddressBook).where(
            AddressBook.owner_user_id == user.id, AddressBook.type == "personal",
        ))
        db.add(AddressBookEntry(address_book_id=book.id, rustdesk_id=rid, alias=alias))
        db.commit()


def _punch(target: str, token: str = "", conn_type: int = 0) -> bytes:
    m = rz.RendezvousMessage()
    m.punch_hole_request.id = target
    m.punch_hole_request.token = token
    m.punch_hole_request.conn_type = conn_type
    m.punch_hole_request.licence_key = "server-public-key"
    return m.SerializeToString()


def _relay(target: str, token: str = "") -> bytes:
    m = rz.RendezvousMessage()
    m.request_relay.id = target
    m.request_relay.token = token
    m.request_relay.uuid = uuid.uuid4().hex
    return m.SerializeToString()


def _observe(*frames: bytes, ip: str = "203.0.113.10") -> None:
    tracker = shim._ConnTracker(ip)
    for f in frames:
        tracker.observe(f)


def _drain() -> list[AuditEvent]:
    with SessionLocal() as db:
        discovery.drain_once(db)
        db.commit()
    with SessionLocal() as db:
        return list(db.scalars(
            select(AuditEvent)
            .where(AuditEvent.category == "connection")
            .order_by(AuditEvent.timestamp, AuditEvent.id)
        ))


def test_parser_returns_token_digest_not_token():
    info = shim._parse_control(_punch(TARGET, "secret-access-token", conn_type=1))
    assert info["target_id"] == TARGET
    assert info["conn_type"] == "FILE_TRANSFER"
    assert info["token_hash"] == token_digest("secret-access-token")
    assert "secret-access-token" not in json.dumps(info)

    assert shim._parse_control(_punch(TARGET))["token_hash"] == ""


def test_logged_in_user_is_named_with_target_alias(client, conn_clean):
    name, token = _user_with_login(client)
    _add_alias(name, TARGET, "касса")

    _observe(_punch(TARGET, token))
    rows = _drain()

    assert len(rows) == 1
    e = rows[0]
    assert e.event_type == "connection.request"
    assert e.actor_type == "user" and e.actor_name == name
    assert e.target_type == "device" and e.target_id == TARGET
    d = json.loads(e.details)
    assert d["username"] == name
    assert d["to_id"] == TARGET and d["to_name"] == "касса"
    # The login that issued the token named the initiating device.
    assert d["from_id"] == INITIATOR
    assert d["actor_source"] == "token"
    assert d["via"] == "direct"
    stored = e.details + e.actor_name + e.actor_id
    assert token not in stored and token_digest(token) not in stored


def test_hostname_is_used_when_no_alias(client, conn_clean):
    _, token = _user_with_login(client)
    rid = "555000111"
    with SessionLocal() as db:
        db.add(DeviceInfo(rustdesk_id=rid, hostname="kassa-pc"))
        db.commit()

    _observe(_punch(rid, token))
    d = json.loads(_drain()[0].details)
    assert d["to_name"] == "kassa-pc"


def test_unknown_token_and_no_token_stay_unattributed(client, conn_clean):
    _observe(_punch(TARGET, "not-a-session-token"), ip="203.0.113.11")
    _observe(_punch("111111111"), ip="203.0.113.12")
    rows = _drain()

    assert len(rows) == 2
    for e in rows:
        assert e.actor_type == "device"
        assert json.loads(e.details)["actor_source"] == "device"


def test_logout_revokes_attribution(client, conn_clean):
    _, token = _user_with_login(client)
    r = client.post("/api/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text

    _observe(_punch(TARGET, token))
    assert _drain()[0].actor_type == "device"


def test_retries_collapse_but_users_stay_separate(client, conn_clean):
    alice, alice_token = _user_with_login(client, "100000001")
    bob, bob_token = _user_with_login(client, "100000002")

    # One attempt: punch retries, then relay fallback -> one row.
    _observe(_punch(TARGET, alice_token), _punch(TARGET, alice_token), _relay(TARGET, alice_token))
    # A different user to the same device in the same window -> own row.
    _observe(_punch(TARGET, bob_token))
    # A different connection type is a separate request.
    _observe(_punch(TARGET, alice_token, conn_type=1))
    rows = _drain()

    by_user = sorted((e.actor_name, json.loads(e.details)["conn_type"]) for e in rows)
    assert by_user == sorted([
        (alice, "DEFAULT_CONN"), (alice, "FILE_TRANSFER"), (bob, "DEFAULT_CONN"),
    ])


def test_connections_filter_in_audit_api(client, conn_clean):
    from app.services.auth import create_user

    name, token = _user_with_login(client)
    _add_alias(name, TARGET, "касса")
    _observe(_punch(TARGET, token))
    _drain()

    admin = f"conn-admin-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        create_user(db, admin, "AdminPass123!", is_admin=True)
    r = client.post("/api/login", json={"username": admin, "password": "AdminPass123!", "type": "account"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/api/v1/audit", headers=headers, params={"category": "connection"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["actor_name"] == name
    assert data[0]["details"]["to_name"] == "касса"
    assert "connection.request" in client.get("/api/v1/audit/meta", headers=headers).json()["event_types"]
