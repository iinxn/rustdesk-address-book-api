"""PresenceService + /api/heartbeat + extended /api/v1 (sort/filter/users)."""
from datetime import datetime, timedelta


def test_heartbeat_stamps_last_seen(client, user):
    h, guid = user["headers"], user["guid"]
    r = client.post(f"/api/ab/peer/add/{guid}", headers=h, json={"id": "555", "alias": "hb", "tags": []})
    assert r.status_code == 200
    # unauthenticated device heartbeat, like RustDesk controlled side
    r = client.post("/api/heartbeat", json={"id": "555", "uuid": "x", "ver": 123})
    assert r.status_code == 200
    r = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h)
    assert r.json()["total"] == 1
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h)
    d = r.json()["data"][0]
    assert d["presence"] == "online" and d["last_seen"]


def test_unknown_without_heartbeat(client, user):
    h, guid = user["headers"], user["guid"]
    client.post(f"/api/ab/peer/add/{guid}", headers=h, json={"id": "556", "alias": "nohb", "tags": []})
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h)
    d = r.json()["data"][0]
    assert d["presence"] == "unknown" and d["last_seen"] is None


def test_offline_when_stale(client, user):
    from tests.db import TestingSession
    from sqlalchemy import select
    from app.models.models import AddressBookEntry
    h, guid = user["headers"], user["guid"]
    client.post(f"/api/ab/peer/add/{guid}", headers=h, json={"id": "557", "alias": "old", "tags": []})
    db = TestingSession()
    e = db.scalar(select(AddressBookEntry).where(AddressBookEntry.rustdesk_id == "557"))
    e.last_seen = datetime.utcnow() - timedelta(minutes=10)
    db.commit()
    db.close()
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"presence": "offline"})
    assert r.json()["total"] == 1
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"presence": "online"})
    assert r.json()["total"] == 0


def test_sort_and_stats(client, user):
    h, guid = user["headers"], user["guid"]
    for rid, alias in (("1", "Zulu"), ("2", "Alpha")):
        client.post(f"/api/ab/peer/add/{guid}", headers=h, json={"id": rid, "alias": alias, "tags": []})
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"sort": "alias"})
    assert [d["alias"] for d in r.json()["data"]] == ["Alpha", "Zulu"]
    r = client.get(f"/api/v1/stats", headers=h)
    assert r.json()["devices"] == 2 and r.json()["unknown"] == 2
    r = client.get("/api/v1/address-books", headers=h)
    assert r.json()[0]["devices"] == 2


def test_user_update_and_protect_self(client, user):
    h = user["headers"]
    uid = [u for u in client.get("/api/v1/users", headers=h).json() if u["username"] == "tester"][0]["id"]
    r = client.put(f"/api/v1/users/{uid}", headers=h, json={"password": "newpass"})
    assert r.status_code == 200
    r = client.post("/api/login", json={"username": "tester", "password": "newpass", "type": "account"})
    assert r.status_code == 200
    r = client.put(f"/api/v1/users/{uid}", headers=h, json={"is_disabled": True})
    assert r.status_code == 400  # cannot disable self
