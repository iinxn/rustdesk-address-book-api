"""Audit/access log tests against the real migrations and a temporary SQLite DB.

These tests assert stored rows, not just that a helper was called. They never
touch `data/`: the shared `client` fixture already points the settings
singleton at a temporary database (see conftest.py).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.models import AddressBook, AddressBookEntry, AuditEvent, User
from app.services import audit as audit_svc


@pytest.fixture()
def audit_clean(client):
    """Start from an empty log; the app lifespan writes a startup event."""
    with SessionLocal() as db:
        db.query(AuditEvent).delete()
        db.commit()
    yield


def _events(event_type: str | None = None) -> list[AuditEvent]:
    with SessionLocal() as db:
        q = select(AuditEvent).order_by(AuditEvent.timestamp, AuditEvent.id)
        if event_type:
            q = q.where(AuditEvent.event_type == event_type)
        return list(db.scalars(q))


def _details(event: AuditEvent) -> dict:
    return json.loads(event.details or "{}")


def _make_user(name: str, password: str, is_admin: bool) -> str:
    from app.services.auth import create_user

    with SessionLocal() as db:
        u = create_user(db, name, password, is_admin=is_admin)
        return u.id


def _login(client, name: str, password: str) -> tuple[dict, str]:
    r = client.post("/api/login", json={"username": name, "password": password, "type": "account"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.headers.get("x-request-id", "")


def _admin_headers(client) -> tuple[dict, str, str]:
    name = f"audit-admin-{uuid.uuid4().hex[:8]}"
    _make_user(name, "AdminPass123!", True)
    headers, _ = _login(client, name, "AdminPass123!")
    return headers, name, "AdminPass123!"


def _user_headers(client) -> tuple[dict, str]:
    name = f"audit-user-{uuid.uuid4().hex[:8]}"
    _make_user(name, "UserPass123!", False)
    headers, _ = _login(client, name, "UserPass123!")
    return headers, name


def _personal_book(headers, client) -> str:
    me = client.get("/api/v1/me", headers=headers).json()
    with SessionLocal() as db:
        book = db.scalar(select(AddressBook).where(
            AddressBook.owner_user_id == me["id"],
            AddressBook.type == "personal",
        ))
        assert book is not None
        return book.id


def test_significant_api_access_is_recorded(client, audit_clean):
    headers, name, _ = _admin_headers(client)
    bid = _personal_book(headers, client)
    with SessionLocal() as db:
        entry = AddressBookEntry(address_book_id=bid, rustdesk_id="audit-access-device")
        db.add(entry)
        db.commit()
        eid = entry.id
    r = client.get(f"/api/v1/entries/{eid}", headers=headers)
    assert r.status_code == 200
    request_id = r.headers["x-request-id"]

    rows = _events("api.request")
    assert len(rows) == 1
    row = rows[0]
    assert row.timestamp is not None
    assert row.route == "/api/v1/entries/{eid}"
    assert row.http_method == "GET"
    assert row.actor_name == name
    assert row.source_ip == "testclient"
    assert row.status_code == 200
    assert row.duration_ms is not None and row.duration_ms >= 0
    assert row.request_id == request_id
    assert row.target_type == "entry"
    assert row.target_id == eid


def test_book_read_via_query_is_recorded_with_target(client, audit_clean):
    headers, name, _ = _admin_headers(client)
    bid = _personal_book(headers, client)
    r = client.post(
        f"/api/ab/peers?current=1&pageSize=10&ab={bid}",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    row = _events("api.request")[0]
    assert row.target_type == "book"
    assert row.target_id == bid
    assert row.actor_name == name
    assert row.route == "/api/ab/peers"


def test_failed_login_is_recorded_without_secrets(client, audit_clean):
    r = client.post(
        "/api/login",
        json={"username": "nobody", "password": "TopSecret-Do-Not-Log", "type": "account"},
    )
    assert r.status_code == 401
    rows = _events("auth.login_failed")
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "auth"
    assert row.outcome == "denied"
    assert row.actor_type == "anonymous"
    assert row.actor_id == ""
    assert row.actor_name == ""
    assert row.source_ip == "testclient"
    assert row.route == "/api/login"
    assert row.status_code == 401
    assert "TopSecret-Do-Not-Log" not in row.details
    assert "password" not in _details(row)
    assert not _events("auth.login")


def test_create_update_delete_write_business_events(client, audit_clean):
    headers, name, _ = _admin_headers(client)

    created = client.post("/api/v1/address-books", headers=headers, json={"name": "Audit book"})
    assert created.status_code == 200, created.text
    bid = created.json()["id"]

    renamed = client.put(f"/api/v1/address-books/{bid}", headers=headers, json={"name": "Audit book 2"})
    assert renamed.status_code == 200, renamed.text

    deleted = client.delete(f"/api/v1/address-books/{bid}", headers=headers)
    assert deleted.status_code == 200, deleted.text

    create = _events("book.create")
    update = _events("book.update")
    delete = _events("book.delete")
    assert len(create) == 1 and create[0].target_id == bid
    assert len(update) == 1 and update[0].target_id == bid
    assert len(delete) == 1 and delete[0].target_id == bid
    assert all(e.actor_name == name for e in (create[0], update[0], delete[0]))
    fields = _details(update[0])["fields"]
    assert fields["name"] == {"from": "Audit book", "to": "Audit book 2"}


def test_entry_changes_store_safe_field_names_only(client, audit_clean):
    headers, _, _ = _admin_headers(client)
    bid = _personal_book(headers, client)

    created = client.post(
        f"/api/v1/address-books/{bid}/entries",
        headers=headers,
        json={
            "rustdesk_id": "audit-device-1",
            "alias": "first",
            "note": "private note",
            "tags": ["one"],
            "password": "device-password-1",
        },
    )
    assert created.status_code == 200, created.text
    entry_id = created.json()["id"]

    updated = client.put(
        f"/api/v1/entries/{entry_id}",
        headers=headers,
        json={
            "rustdesk_id": "audit-device-1",
            "alias": "second",
            "note": "changed private note",
            "tags": ["one", "two"],
            "password": "device-password-2",
        },
    )
    assert updated.status_code == 200, updated.text
    assert client.delete(f"/api/v1/entries/{entry_id}", headers=headers).status_code == 200

    create = _events("entry.create")[0]
    update = _events("entry.update")[0]
    delete = _events("entry.delete")[0]
    assert create.target_id == "audit-device-1"
    assert _details(create)["password_set"] is True
    assert _details(create)["tags"] == ["one"]

    fields = _details(update)["fields"]
    assert fields["alias"] == {"from": "first", "to": "second"}
    assert fields["note"] == "changed"
    assert fields["password_changed"] is True
    assert fields["tags"]["from"] == ["one"]
    assert fields["tags"]["to"] == ["one", "two"]

    for event in (create, update, delete):
        assert "device-password" not in event.details
        assert "private note" not in event.details
    assert delete.target_id == "audit-device-1"


def test_cancelled_operation_is_not_reported_as_success(client, audit_clean):
    user_headers, _ = _user_headers(client)
    r = client.post("/api/v1/address-books", headers=user_headers, json={"name": "nope"})
    assert r.status_code == 403
    assert not _events("book.create")
    denied = _events("access.denied")
    assert len(denied) == 1 and denied[0].outcome == "denied"

    headers, _, _ = _admin_headers(client)
    bid = _personal_book(headers, client)
    bad = client.post(
        f"/api/v1/address-books/{bid}/entries",
        headers=headers,
        json={"rustdesk_id": "bad@id", "alias": "", "note": "", "tags": [], "password": ""},
    )
    assert bad.status_code == 422
    assert not _events("entry.create")


def test_request_id_links_response_and_audit_row(client, audit_clean):
    name = f"audit-rid-{uuid.uuid4().hex[:8]}"
    _make_user(name, "RidPass123!", False)
    headers, request_id = _login(client, name, "RidPass123!")
    assert request_id
    row = _events("auth.login")[0]
    assert row.request_id == request_id
    assert row.actor_name == name

    # An unauthenticated protected request is also correlatable.
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    denied = _events("access.unauthenticated")[-1]
    assert denied.request_id == r.headers["x-request-id"]


def test_unknown_client_is_not_attributed_to_a_user(client, audit_clean):
    r = client.get("/api/v1/me")
    assert r.status_code == 401
    row = _events("access.unauthenticated")[0]
    assert row.actor_type == "anonymous"
    assert row.actor_id == ""
    assert row.actor_name == ""
    assert row.source_ip == "testclient"


def test_passwords_never_reach_the_audit_log(client, audit_clean):
    headers, _, _ = _admin_headers(client)
    bid = _personal_book(headers, client)
    r = client.post(
        f"/api/v1/address-books/{bid}/entries",
        headers=headers,
        json={
            "rustdesk_id": "audit-secret-device",
            "alias": "secret",
            "note": "",
            "tags": [],
            "password": "super-secret-device-password",
        },
    )
    assert r.status_code == 200

    new_user = f"audit-secret-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": new_user, "password": "super-secret-user-password", "is_admin": False},
    )
    assert created.status_code == 200, created.text
    uid = created.json()["id"]
    changed = client.put(
        f"/api/v1/users/{uid}",
        headers=headers,
        json={"password": "another-super-secret-password"},
    )
    assert changed.status_code == 200, changed.text

    blob = json.dumps([audit_svc.serialize(e) for e in _events()])
    for secret in (
        "super-secret-device-password",
        "super-secret-user-password",
        "another-super-secret-password",
        "AdminPass123!",
    ):
        assert secret not in blob


def test_heartbeat_does_not_grow_the_audit_log(client, audit_clean):
    before = len(_events())
    for _ in range(10):
        r = client.post("/api/heartbeat", json={"id": "dev0000", "ver": "1.2.3"})
        assert r.status_code == 200
    assert len(_events()) == before


def test_repeated_429_is_throttled_not_multiplied(client, audit_clean, monkeypatch):
    from app.core import middleware

    monkeypatch.setattr(middleware.settings, "login_per_minute_per_ip", 1)
    middleware.reset_rate_limits()
    for _ in range(3):
        client.post("/api/login", json={"username": "nobody", "password": "x", "type": "account"})
    # Two 429s were produced; at most one access row and one rate-limit row.
    assert len(_events("access.denied")) <= 1
    assert len(_events("security.rate_limited")) <= 1

    before = len(_events())
    monkeypatch.setattr(middleware.settings, "heartbeat_per_minute_per_device", 1)
    middleware.reset_rate_limits()
    for _ in range(4):
        client.post("/api/heartbeat", json={"id": "dev0001", "ver": "1.2.3"})
    assert len(_events()) == before
    middleware.reset_rate_limits()


def test_audit_pagination_and_filters(client, audit_clean):
    headers, _, _ = _admin_headers(client)
    with SessionLocal() as db:
        for i in range(5):
            audit_svc.record(
                db,
                category="data" if i < 3 else "security",
                event_type="entry.update" if i < 3 else "user.update",
                outcome="success",
                actor_type="system",
                destination="api",
                target_type="device",
                target_id=f"filter-dev-{i}",
                request_id=f"filter-request-{i}",
                source_ip="203.0.113.10" if i % 2 == 0 else "203.0.113.11",
                details={"i": i},
            )
        db.commit()

    page = client.get(
        "/api/v1/audit",
        headers=headers,
        params={"category": "data", "page": 2, "page_size": 2, "sort": "asc"},
    ).json()
    assert page["total"] == 3
    assert len(page["data"]) == 1
    assert page["data"][0]["details"]["i"] == 2

    by_ip = client.get(
        "/api/v1/audit", headers=headers, params={"source_ip": "203.0.113.11"}
    ).json()
    assert by_ip["total"] == 2

    by_target = client.get(
        "/api/v1/audit", headers=headers, params={"target_id": "filter-dev-4"}
    ).json()
    assert by_target["total"] == 1

    by_request = client.get(
        "/api/v1/audit", headers=headers, params={"search": "filter-request-3"}
    ).json()
    assert by_request["total"] == 1
    assert by_request["data"][0]["request_id"] == "filter-request-3"

    by_outcome = client.get(
        "/api/v1/audit", headers=headers, params={"outcome": "success", "event_type": "user.update"}
    ).json()
    assert by_outcome["total"] == 2


def test_audit_is_admin_only(client, audit_clean):
    assert client.get("/api/v1/audit").status_code == 401
    user_headers, _ = _user_headers(client)
    assert client.get("/api/v1/audit", headers=user_headers).status_code == 403
    admin_headers, _, _ = _admin_headers(client)
    assert client.get("/api/v1/audit", headers=admin_headers).status_code == 200


def test_retention_deletes_old_events_and_keeps_fresh(client, audit_clean):
    now = datetime.utcnow()
    with SessionLocal() as db:
        audit_svc.record(
            db,
            category="system",
            event_type="test.old",
            timestamp=now - timedelta(days=200),
            actor_type="system",
            details={"marker": "old"},
        )
        audit_svc.record(
            db,
            category="system",
            event_type="test.fresh",
            timestamp=now - timedelta(days=1),
            actor_type="system",
            details={"marker": "fresh"},
        )
        db.commit()

    result = audit_svc.cleanup_once(now=now)
    assert result["deleted"] >= 1
    assert not _events("test.old")
    assert len(_events("test.fresh")) == 1
    retention = _events("audit.retention")
    assert len(retention) == 1
    assert _details(retention[0])["deleted"] >= 1
    assert _details(retention[0])["retention_days"] == 90


def test_retention_is_clamped_to_safe_range(client, audit_clean, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "audit_retention_days", "1")
    assert audit_svc.retention_days() == 30
    monkeypatch.setattr(settings, "audit_retention_days", "1000")
    assert audit_svc.retention_days() == 90
    monkeypatch.setattr(settings, "audit_retention_days", "not-a-number")
    assert audit_svc.retention_days() == 90
    monkeypatch.setattr(settings, "audit_retention_days", "45")
    assert audit_svc.retention_days() == 45


def test_migration_upgrades_existing_database_with_data(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.core.config import BASE_DIR, settings

    db_path = tmp_path / "existing.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BASE_DIR))

    command.upgrade(cfg, "0004")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, is_disabled, display_name, created_at)"
            " VALUES (?, ?, ?, 0, 0, '', ?)",
            (str(uuid.uuid4()), "existing", "hash", datetime.utcnow().isoformat(" ")),
        )
        uid = conn.execute("SELECT id FROM users WHERE username='existing'").fetchone()[0]
        conn.execute(
            "INSERT INTO address_books (id, name, type, owner_user_id, created_at, updated_at)"
            " VALUES (?, ?, 'personal', ?, ?, ?)",
            (str(uuid.uuid4()), "Existing book", uid,
             datetime.utcnow().isoformat(" "), datetime.utcnow().isoformat(" ")),
        )
        conn.commit()

    command.upgrade(cfg, "head")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "audit_events" in tables
        assert conn.execute("SELECT COUNT(*) FROM users WHERE username='existing'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM address_books WHERE name='Existing book'").fetchone()[0] == 1
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == head
        session_cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        assert "device_id" in session_cols

    command.downgrade(cfg, "0004")
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "audit_events" not in tables
        assert conn.execute("SELECT COUNT(*) FROM users WHERE username='existing'").fetchone()[0] == 1


def test_parallel_writes_are_not_lost_or_mislinked(client, audit_clean):
    def write(i: int) -> bool:
        return audit_svc.write_event(
            category="system",
            event_type="test.concurrent",
            outcome="success",
            actor_type="system",
            request_id=f"parallel-{i}",
            details={"i": i},
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(write, range(20)))

    rows = _events("test.concurrent")
    assert len(rows) == 20
    assert {row.request_id for row in rows} == {f"parallel-{i}" for i in range(20)}
    assert {_details(row)["i"] for row in rows} == set(range(20))
