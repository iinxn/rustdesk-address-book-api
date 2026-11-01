"""Regressions found and fixed during the 2026-10-31 refactoring.

* access: listings obey the same rule as per-request checks (admins get no
  implicit view of other users' personal books, DEC-003); the legacy panel's
  `?book=` selector is authorised (SEC-026/027);
* entries: `MAX_PEER_ONE_AB` applies to every creation path (TODO-005);
* tags: colours are validated, no 500 (SEC-004 / TODO-006);
* client payloads of the wrong JSON type answer 400, not 500;
* body cap: a chunked body without Content-Length is limited (SEC-013);
* heartbeat: concurrent group commit stores every device.
"""
from __future__ import annotations

import threading
import uuid

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import AddressBook, AddressBookEntry, DeviceInfo, DiscoveredDevice
from app.services.auth import create_user

PASSWORD = "RegressionPass1!"


def _user(client, is_admin: bool = False) -> tuple[dict, str, str]:
    name = f"rg{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        u = create_user(db, name, PASSWORD, is_admin=is_admin)
        personal = db.query(AddressBook).filter_by(owner_user_id=u.id, type="personal").one().id
    r = client.post("/api/login", json={"username": name, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, name, personal


def test_admin_does_not_see_other_personal_books(client):
    admin, _, _ = _user(client, is_admin=True)
    _, _, foreign = _user(client)
    rid = f"p{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        db.add(AddressBookEntry(address_book_id=foreign, rustdesk_id=rid, alias="private"))
        db.add(DeviceInfo(rustdesk_id=rid, hostname="h"))
        db.commit()
    books = {b["id"] for b in client.get("/api/v1/address-books", headers=admin).json()}
    assert foreign not in books
    assert client.get(f"/api/v1/address-books/{foreign}/entries", headers=admin).status_code == 404
    card = client.get(f"/api/v1/device-info/{rid}", headers=admin).json()
    assert card["entries"] == []  # the private alias/note/tags are not exposed


def test_legacy_panel_book_selector_is_authorised(client):
    from fastapi.testclient import TestClient

    from app.main import app

    _, _, foreign = _user(client)
    with SessionLocal() as db:
        db.add(AddressBookEntry(address_book_id=foreign, rustdesk_id="secret-device"))
        db.commit()
    _, name, _ = _user(client)
    pc = TestClient(app, follow_redirects=False)
    pc.post("/panel/login", data={"username": name, "password": PASSWORD})
    page = pc.get(f"/panel/devices?book={foreign}")
    assert page.status_code == 200 and "secret-device" not in page.text
    assert pc.get(f"/panel/tags?book={foreign}").status_code == 200


def test_book_limit_applies_to_every_creation_path(client, monkeypatch):
    headers, _, personal = _user(client)
    monkeypatch.setattr(settings, "max_peer_one_ab", 1)
    url = f"/api/v1/address-books/{personal}/entries"
    assert client.post(url, headers=headers, json={"rustdesk_id": "lim1"}).status_code == 200
    over = client.post(url, headers=headers, json={"rustdesk_id": "lim2"})
    assert over.status_code == 403 and over.json() == {"detail": "exceed_max_devices"}
    with SessionLocal() as db:
        db.add(DiscoveredDevice(rustdesk_id="lim3", seen_count=1))
        db.commit()
    disc = client.post("/api/v1/discovered/lim3/add", headers=headers, json={"book_id": personal})
    assert disc.status_code == 403


def test_tag_colors_are_validated(client):
    headers, _, personal = _user(client)
    url = f"/api/ab/tag/add/{personal}"
    for bad in ("red", -1, 2**32, 10**30, True):
        r = client.post(url, headers=headers, json={"name": "c", "color": bad})
        assert r.status_code == 400 and r.json() == {"error": "invalid color"}, bad
    assert client.post(url, headers=headers, json={"name": "c", "color": 0xFF00FF00}).status_code == 200
    assert client.post(url, headers=headers, json={"name": "c", "color": "16"}).status_code == 200
    assert client.post(f"/api/ab/tags/{personal}", headers=headers).json() == [{"name": "c", "color": 16}]
    bad = client.put(f"/api/ab/tag/update/{personal}", headers=headers, json={"name": "c", "color": "x"})
    assert bad.status_code == 400
    v1 = client.post(f"/api/v1/address-books/{personal}/tags", headers=headers,
                     json={"name": "big", "color": 2**40})
    assert v1.status_code == 422


def test_non_object_client_payload_is_400(client):
    headers, _, personal = _user(client)
    for path, method in ((f"/api/ab/peer/add/{personal}", "POST"),
                         (f"/api/ab/peer/update/{personal}", "PUT"),
                         (f"/api/ab/tag/add/{personal}", "POST")):
        r = client.request(method, path, headers=headers, json=[1, 2])
        assert r.status_code == 400 and r.json() == {"error": "bad json"}, path


def test_chunked_body_without_length_is_capped(client, monkeypatch):
    monkeypatch.setattr(settings, "max_body_bytes", 1024)

    def chunks():
        for _ in range(4):
            yield b"x" * 512

    r = client.post("/api/sysinfo", content=chunks())
    assert r.status_code == 413
    ok = client.post("/api/sysinfo", content=iter([b'{"id": "1"}']))
    assert ok.status_code == 200


def test_concurrent_heartbeats_are_all_stored(client):
    from sqlalchemy import select

    from app.api.rustdesk import _heartbeats

    rids = [f"dev{i:04d}" for i in range(200)]  # seeded by conftest
    with SessionLocal() as db:
        for e in db.scalars(select(AddressBookEntry).where(AddressBookEntry.rustdesk_id.in_(rids))):
            e.last_seen = None
        db.commit()
    threads = [threading.Thread(target=_heartbeats.record, args=(rid, "1.4.2", "203.0.113.10"))
               for rid in rids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with SessionLocal() as db:
        missing = db.scalars(select(AddressBookEntry.rustdesk_id).where(
            AddressBookEntry.rustdesk_id.in_(rids), AddressBookEntry.last_seen.is_(None))).all()
    assert missing == []
