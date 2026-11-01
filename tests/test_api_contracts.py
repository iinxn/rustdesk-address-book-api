"""Characterisation tests for the public contracts (written before the
2026-10-31 refactoring and kept as its safety net).

* `/api/*`   — the stock RustDesk client contract: exact keys, status codes,
  `{"error": ...}` messages and empty 200 bodies.
* `/api/v1/*` — the SPA contract: response shapes, filters, sorting, paging,
  bulk partial-success reports, `{"detail": ...}` errors.
* access rules — rule 1 is read-only, rule 2 may write, invisible books are 404.

Temporary SQLite only (conftest.py).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import (
    AddressBook,
    AddressBookEntry,
    AddressBookPermission,
    DeviceInfo,
    DiscoveredDevice,
)
from app.services.auth import create_user

PASSWORD = "ContractPass1!"


def _uid(prefix: str = "c") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(client, username: str) -> str:
    r = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class World:
    """Admin, a non-admin member and three shared books with different rules."""

    def __init__(self, client):
        self.client = client
        self.admin_name, self.member_name = _uid("adm"), _uid("mem")
        with SessionLocal() as db:
            admin = create_user(db, self.admin_name, PASSWORD, is_admin=True)
            member = create_user(db, self.member_name, PASSWORD)
            self.admin_id, self.member_id = admin.id, member.id
            self.member_personal = db.query(AddressBook).filter_by(
                owner_user_id=member.id, type="personal").one().id
            self.admin_personal = db.query(AddressBook).filter_by(
                owner_user_id=admin.id, type="personal").one().id
            books = {}
            for key, rule in (("read", 1), ("write", 2), ("none", None)):
                b = AddressBook(name=f"{key}-{_uid()}", type="shared", owner_user_id=admin.id)
                db.add(b)
                db.flush()
                if rule is not None:
                    db.add(AddressBookPermission(address_book_id=b.id, user_id=member.id, rule=rule))
                books[key] = b.id
            db.commit()
        self.read, self.write, self.none = books["read"], books["write"], books["none"]
        self.admin = _h(_login(client, self.admin_name))
        self.member = _h(_login(client, self.member_name))

    def add_entry(self, book: str, rid: str | None = None, **fields) -> str:
        with SessionLocal() as db:
            e = AddressBookEntry(address_book_id=book, rustdesk_id=rid or _uid(), **fields)
            db.add(e)
            db.commit()
            return e.id


@pytest.fixture()
def w(client):
    return World(client)


# --- RustDesk client contract (/api/*) ----------------------------------------

def test_login_current_user_logout_shapes(client, w):
    r = client.post("/api/login", json={"username": w.member_name, "password": PASSWORD,
                                        "id": "123456789", "type": "account"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"access_token", "type", "user"}
    assert body["type"] == "access_token"
    assert body["user"] == {"name": w.member_name, "display_name": "", "avatar": "",
                            "email": "", "note": "", "status": 1, "is_admin": False}
    token = _h(body["access_token"])
    cur = client.post("/api/currentUser", headers=token)
    assert cur.status_code == 200
    assert cur.json() == body["user"]
    out = client.post("/api/logout", headers=token)
    assert out.status_code == 200 and out.content == b""
    assert client.post("/api/currentUser", headers=token).json() == {"error": "unauthorized"}
    assert client.post("/api/login", json={"username": w.member_name, "password": "x"}).json() == {
        "error": "Invalid username or password"}


def test_unauthenticated_client_routes(client):
    assert client.get("/api/login-options").json() == []
    r = client.post("/api/ab/personal")
    assert r.status_code == 401 and r.json() == {"error": "unauthorized"}
    assert client.post("/api/sysinfo_ver").text == "1"
    for bad in (b"", b"[1]", b"{not json"):
        r = client.post("/api/heartbeat", content=bad, headers={"Content-Type": "application/json"})
        assert r.status_code == 200 and r.json() == {}


def test_settings_personal_and_shared_profiles(client, w):
    assert client.post("/api/ab/settings", headers=w.member).json() == {
        "max_peer_one_ab": settings.max_peer_one_ab}
    assert client.post("/api/ab/personal", headers=w.member).json() == {"guid": w.member_personal}
    prof = client.post("/api/ab/shared/profiles?current=1&pageSize=100", headers=w.member).json()
    assert prof["total"] == 2
    rules = {p["guid"]: p["rule"] for p in prof["data"]}
    assert rules == {w.read: 1, w.write: 2}
    assert set(prof["data"][0]) == {"guid", "name", "owner", "note", "info", "rule"}
    admin_prof = client.post("/api/ab/shared/profiles?pageSize=1000", headers=w.admin).json()
    admin_rules = {p["guid"]: p["rule"] for p in admin_prof["data"]}
    assert admin_rules[w.none] == 3 and admin_rules[w.read] == 3


def test_peers_page_shapes_for_personal_and_shared(client, w):
    for rid in ("300", "100", "200"):
        client.post(f"/api/ab/peer/add/{w.member_personal}", headers=w.member,
                    json={"id": rid, "alias": f"a{rid}", "hash": "h", "tags": ["x"]})
    r = client.post(f"/api/ab/peers?current=1&pageSize=2&ab={w.member_personal}", headers=w.member)
    body = r.json()
    assert body["total"] == 3
    assert [p["id"] for p in body["data"]] == ["100", "200"]
    assert body["data"][0] == {"id": "100", "username": "", "hostname": "", "platform": "",
                               "alias": "a100", "tags": ["x"], "note": "", "hash": "h"}
    page2 = client.post(f"/api/ab/peers?current=2&pageSize=2&ab={w.member_personal}",
                        headers=w.member).json()
    assert [p["id"] for p in page2["data"]] == ["300"]

    client.post(f"/api/ab/peer/add/{w.write}", headers=w.member,
                json={"id": "777", "password": "pw-secret", "hash": "ignored"})
    shared = client.post(f"/api/ab/peers?ab={w.write}", headers=w.member).json()["data"]
    assert shared == [{"id": "777", "username": "", "hostname": "", "platform": "", "alias": "",
                       "tags": [], "note": "", "password": "pw-secret"}]
    assert client.post(f"/api/ab/peers?ab={w.none}", headers=w.member).json() == {
        "error": "no such address book"}


def test_peer_add_errors(client, w, monkeypatch):
    url = f"/api/ab/peer/add/{w.member_personal}"
    assert client.post(url, headers=w.member, json={"id": "555"}).status_code == 200
    dup = client.post(url, headers=w.member, json={"id": "555"})
    assert dup.status_code == 409 and dup.json() == {"error": "555 already exists"}
    missing = client.post(url, headers=w.member, json={})
    assert missing.status_code == 400 and missing.json() == {"error": "missing id"}
    assert client.post(url, headers=w.member, json={"id": "1@srv"}).status_code == 422
    bad = client.post(url, headers={**w.member, "Content-Type": "application/json"}, content=b"{")
    assert bad.status_code == 400 and bad.json() == {"error": "bad json"}
    ro = client.post(f"/api/ab/peer/add/{w.read}", headers=w.member, json={"id": "1"})
    assert ro.status_code == 403 and ro.json() == {"error": "read-only"}
    monkeypatch.setattr(settings, "max_peer_one_ab", 1)
    over = client.post(url, headers=w.member, json={"id": "556"})
    assert over.status_code == 403 and over.json() == {"error": "exceed_max_devices"}


def test_peer_update_and_delete(client, w):
    book = w.member_personal
    client.post(f"/api/ab/peer/add/{book}", headers=w.member, json={"id": "901", "tags": ["a"]})
    r = client.put(f"/api/ab/peer/update/{book}", headers=w.member,
                   json={"id": "901", "alias": "Kassa", "tags": ["b", "c"], "hash": "new"})
    assert r.status_code == 200 and r.content == b""
    peer = client.post(f"/api/ab/peers?ab={book}", headers=w.member).json()["data"][0]
    assert peer["alias"] == "Kassa" and sorted(peer["tags"]) == ["b", "c"] and peer["hash"] == "new"
    assert client.put(f"/api/ab/peer/update/{book}", headers=w.member,
                      json={"id": "nope"}).json() == {"error": "not found"}
    assert client.put(f"/api/ab/peer/update/{book}", headers=w.member,
                      json={}).json() == {"error": "missing id"}
    bad = client.request("DELETE", f"/api/ab/peer/{book}", headers=w.member, json={"id": "901"})
    assert bad.status_code == 400 and bad.json() == {"error": "expected id list"}
    ok = client.request("DELETE", f"/api/ab/peer/{book}", headers=w.member, json=["901", "absent"])
    assert ok.status_code == 200 and ok.content == b""
    assert client.post(f"/api/ab/peers?ab={book}", headers=w.member).json()["total"] == 0


def test_client_tag_operations(client, w):
    book = w.member_personal
    t = f"/api/ab/tag/add/{book}"
    assert client.post(t, headers=w.member, json={"name": "zeta", "color": 5}).status_code == 200
    assert client.post(t, headers=w.member, json={"name": "alpha"}).status_code == 200
    assert client.post(t, headers=w.member, json={"name": "zeta", "color": 9}).status_code == 200
    assert client.post(t, headers=w.member, json={"name": " "}).json() == {"error": "missing name"}
    tags = client.post(f"/api/ab/tags/{book}", headers=w.member).json()
    assert tags == [{"name": "alpha", "color": 0}, {"name": "zeta", "color": 9}]

    ren = f"/api/ab/tag/rename/{book}"
    assert client.put(ren, headers=w.member, json={"old": "alpha"}).json() == {"error": "missing names"}
    assert client.put(ren, headers=w.member, json={"old": "alpha", "new": "zeta"}).json() == {
        "error": "Tag zeta already exists"}
    assert client.put(ren, headers=w.member, json={"old": "nope", "new": "x"}).status_code == 404
    assert client.put(ren, headers=w.member, json={"old": "alpha", "new": "beta"}).status_code == 200
    assert client.put(f"/api/ab/tag/update/{book}", headers=w.member,
                      json={"name": "beta", "color": 3}).status_code == 200
    assert client.put(f"/api/ab/tag/update/{book}", headers=w.member,
                      json={"name": "nope"}).status_code == 404

    client.post(f"/api/ab/peer/add/{book}", headers=w.member, json={"id": "42", "tags": ["beta", "zeta"]})
    assert client.request("DELETE", f"/api/ab/tag/{book}", headers=w.member,
                          json="beta").json() == {"error": "expected tag list"}
    assert client.request("DELETE", f"/api/ab/tag/{book}", headers=w.member,
                          json=["beta"]).status_code == 200
    assert client.post(f"/api/ab/tags/{book}", headers=w.member).json() == [{"name": "zeta", "color": 9}]
    peer = client.post(f"/api/ab/peers?ab={book}", headers=w.member).json()["data"][0]
    assert peer["tags"] == ["zeta"]
    ro = client.post(f"/api/ab/tag/add/{w.read}", headers=w.member, json={"name": "x"})
    assert ro.status_code == 403


def test_legacy_and_group_stubs(client, w):
    r = client.get("/api/ab", headers=w.member)
    assert r.status_code == 200 and r.text == "null"
    assert client.post("/api/ab", headers=w.member).status_code == 200
    for path in ("/api/device-group/accessible", "/api/users", "/api/peers"):
        assert client.get(path, headers=w.member).json() == {"total": 0, "data": []}


# --- SPA contract (/api/v1/*) ---------------------------------------------------

ENTRY_KEYS = {
    "id", "rustdesk_id", "alias", "note", "tags", "tag_objs", "presence", "last_seen",
    "password_configured", "hostname", "username", "platform", "ip", "os", "has_info",
    "info_updated_at", "created_at", "updated_at",
}


def _seed_listing(w) -> dict:
    """Four entries named a/b/c/d + a unique suffix (the test DB is shared).

    Returns {short name: rustdesk id}; `w.rid_names` maps back for asserts.
    """
    now = datetime.utcnow()
    suffix = uuid.uuid4().hex[:6]
    rows = {
        "b-online": dict(alias="Bravo", note="first floor", last_seen=now),
        "a-offline": dict(alias="alpha", last_seen=now - timedelta(hours=1)),
        "c-unknown": dict(alias="", hostname="host-c"),
        "d-online": dict(alias="Delta", last_seen=now - timedelta(seconds=10)),
    }
    rids = {name: f"{name}-{suffix}" for name in rows}
    w.rid_names = {rid: name for name, rid in rids.items()}
    ids = {name: w.add_entry(w.write, rids[name], **fields) for name, fields in rows.items()}
    for name, tags in (("b-online", ["red", "blue"]), ("a-offline", ["red"]), ("d-online", ["blue"])):
        w.client.put(f"/api/v1/entries/{ids[name]}", headers=w.admin,
                     json={"rustdesk_id": rids[name], "alias": rows[name]["alias"],
                           "note": rows[name].get("note", ""), "tags": tags})
    with SessionLocal() as db:
        db.add(DeviceInfo(rustdesk_id=rids["c-unknown"], hostname=f"sysinfo-{suffix}",
                          os="Linux / 6.1", os_name="Linux", ip="203.0.113.10", collected_at=now))
        db.commit()
    w.suffix = suffix
    return rids


def _list(w, **params):
    tags = params.pop("tag", [])
    query = "&".join([f"{k}={v}" for k, v in params.items()] + [f"tag={t}" for t in tags])
    r = w.client.get(f"/api/v1/address-books/{w.write}/entries?{query}", headers=w.admin)
    assert r.status_code == 200, r.text
    return r.json()


def _names(w, **params) -> list[str]:
    return [w.rid_names[e["rustdesk_id"]] for e in _list(w, **params)["data"]]


def test_entries_listing_shape_sort_and_paging(client, w):
    _seed_listing(w)
    body = _list(w)
    assert body["total"] == 4
    assert set(body["data"][0]) == ENTRY_KEYS
    # alias sort falls back to the id and ignores case
    assert _names(w) == ["a-offline", "b-online", "c-unknown", "d-online"]
    assert _names(w, order="desc")[0] == "d-online"
    assert _names(w, sort="status") == ["b-online", "d-online", "c-unknown", "a-offline"]
    seen = _names(w, sort="last_seen")
    assert seen[-1] == "c-unknown" and seen[:3] == ["a-offline", "d-online", "b-online"]
    assert _names(w, sort="last_seen", order="desc")[0] == "c-unknown"
    assert _names(w, sort="rustdesk_id", order="desc")[0] == "d-online"
    page = _list(w, page=2, page_size=3)
    assert page["total"] == 4 and [w.rid_names[e["rustdesk_id"]] for e in page["data"]] == ["d-online"]
    assert len(_list(w, page_size=0)["data"]) == 1  # clamped to >= 1
    by_name = {w.rid_names[e["rustdesk_id"]]: e for e in body["data"]}
    item = by_name["c-unknown"]
    assert item["presence"] == "unknown" and item["last_seen"] is None
    assert item["hostname"] == "host-c" and item["os"] == "Linux" and item["ip"] == "203.0.113.10"
    assert item["has_info"] is True and item["tags"] == [] and item["tag_objs"] == []
    bravo = by_name["b-online"]
    assert bravo["tags"] == ["blue", "red"] and bravo["presence"] == "online"
    assert [t["name"] for t in bravo["tag_objs"]] == ["blue", "red"]
    assert by_name["a-offline"]["presence"] == "offline" and by_name["a-offline"]["has_info"] is False


def test_entries_listing_filters(client, w):
    _seed_listing(w)

    def names(**p):
        return sorted(_names(w, **p))

    assert names(search="floor") == ["b-online"]
    assert names(search=f"sysinfo-{w.suffix}") == ["c-unknown"]  # device_info hostname
    assert names(search="BRAVO") == ["b-online"]
    assert names(tag=["red"]) == ["a-offline", "b-online"]
    assert names(tag=["red", "blue"]) == ["a-offline", "b-online", "d-online"]
    assert names(tag=["red", "blue"], mode="and") == ["b-online"]
    assert names(untagged="true") == ["c-unknown"]
    assert names(presence="online") == ["b-online", "d-online"]
    assert names(presence="offline") == ["a-offline"]
    assert names(presence="bogus") == ["a-offline", "b-online", "c-unknown", "d-online"]
    assert _list(w, tag=["red"], page_size=1)["total"] == 2


def test_stats_and_books_overview(client, w):
    _seed_listing(w)
    books = client.get("/api/v1/address-books", headers=w.member).json()
    by_id = {b["id"]: b for b in books}
    assert set(by_id) == {w.member_personal, w.read, w.write}
    assert by_id[w.write] | {"name": None} == {
        "id": w.write, "name": None, "type": "shared", "rule": 2,
        "devices": 4, "online": 2, "offline": 1, "unknown": 1}
    assert by_id[w.read]["rule"] == 1 and by_id[w.member_personal]["rule"] == 3
    stats = client.get("/api/v1/stats", headers=w.member).json()
    assert set(stats) == {"devices", "online", "offline", "unknown", "discovered", "discovered_online"}
    assert (stats["devices"], stats["online"], stats["offline"], stats["unknown"]) == (4, 2, 1, 1)


def test_entry_crud_and_access_rules(client, w):
    url = f"/api/v1/address-books/{w.write}/entries"
    r = client.post(url, headers=w.member, json={"rustdesk_id": "e1", "alias": "One",
                                                 "tags": ["t1"], "password": "pw"})
    assert r.status_code == 200 and set(r.json()) == ENTRY_KEYS
    e = r.json()
    assert e["tags"] == ["t1"] and e["password_configured"] is True
    assert client.post(url, headers=w.member, json={"rustdesk_id": "e1"}).json() == {"detail": "duplicate"}
    assert client.post(url, headers=w.member, json={"rustdesk_id": "x@y"}).status_code == 422
    ro = client.post(f"/api/v1/address-books/{w.read}/entries", headers=w.member, json={"rustdesk_id": "e2"})
    assert ro.status_code == 403 and ro.json() == {"detail": "read-only"}
    hidden = client.get(f"/api/v1/address-books/{w.none}/entries", headers=w.member)
    assert hidden.status_code == 404 and hidden.json() == {"detail": "no such book"}

    assert client.get(f"/api/v1/entries/{e['id']}", headers=w.member).json()["alias"] == "One"
    other = w.add_entry(w.none, "e-hidden")
    assert client.get(f"/api/v1/entries/{other}", headers=w.member).status_code == 404
    assert client.put(f"/api/v1/entries/{other}", headers=w.member,
                      json={"rustdesk_id": "e-hidden"}).status_code == 403

    client.post(url, headers=w.member, json={"rustdesk_id": "e3"})
    dup = client.put(f"/api/v1/entries/{e['id']}", headers=w.member, json={"rustdesk_id": "e3"})
    assert dup.status_code == 409
    upd = client.put(f"/api/v1/entries/{e['id']}", headers=w.member,
                     json={"rustdesk_id": "e1b", "alias": "Uno", "tags": ["t2"]})
    assert upd.status_code == 200
    assert (upd.json()["rustdesk_id"], upd.json()["alias"], upd.json()["tags"]) == ("e1b", "Uno", ["t2"])
    assert upd.json()["password_configured"] is True  # empty password keeps the old one
    assert client.delete(f"/api/v1/entries/{e['id']}", headers=w.member).json() == {"ok": True}
    assert client.get(f"/api/v1/entries/{e['id']}", headers=w.member).status_code == 404


def test_bulk_operations_report_partial_success(client, w):
    mine = [w.add_entry(w.write) for _ in range(3)]
    ro = w.add_entry(w.read)
    bogus = str(uuid.uuid4())
    r = client.post("/api/v1/entries/bulk-tags", headers=w.member,
                    json={"ids": mine + [mine[0], ro, bogus, "nope"], "add": ["x", " ", "y"], "remove": []})
    body = r.json()
    assert body["updated"] == mine and body["added"] == ["x", "y"] and body["removed"] == []
    assert body["failed"] == [{"id": ro, "error": "forbidden"}, {"id": bogus, "error": "not found"},
                              {"id": "nope", "error": "invalid id"}]
    r = client.post("/api/v1/entries/bulk-tags", headers=w.member,
                    json={"ids": mine[:1], "add": ["y"], "remove": ["x", "y"]})
    tags = client.get(f"/api/v1/entries/{mine[0]}", headers=w.member).json()["tags"]
    assert tags == ["y"]  # remove first, then add: add wins
    assert client.post("/api/v1/entries/bulk-tags", headers=w.member,
                       json={"ids": mine, "add": [" "]}).json() == {"detail": "no valid tag names"}
    too_many = [str(uuid.uuid4()) for _ in range(501)]
    assert client.post("/api/v1/entries/bulk-delete", headers=w.member,
                       json={"ids": too_many}).status_code == 400
    d = client.post("/api/v1/entries/bulk-delete", headers=w.member, json={"ids": mine + [ro]}).json()
    assert d == {"deleted": mine, "failed": [{"id": ro, "error": "forbidden"}]}


def test_v1_tags_and_attachments(client, w):
    url = f"/api/v1/address-books/{w.write}/tags"
    t = client.post(url, headers=w.member, json={"name": "blue", "color": 7}).json()
    assert t == {"id": t["id"], "name": "blue", "color": 7, "devices": 0}
    assert client.post(url, headers=w.member, json={"name": "blue"}).status_code == 409
    other = client.post(url, headers=w.member, json={"name": "green"}).json()
    assert client.put(f"/api/v1/tags/{t['id']}", headers=w.member,
                      json={"name": "green"}).status_code == 409
    upd = client.put(f"/api/v1/tags/{t['id']}", headers=w.member, json={"name": "navy", "color": 1})
    assert upd.json() == {"id": t["id"], "name": "navy", "color": 1}
    eid = w.add_entry(w.write)
    assert client.put(f"/api/v1/entries/{eid}/tags/{t['id']}", headers=w.member).json() == {"ok": True}
    assert client.put(f"/api/v1/entries/{eid}/tags/{t['id']}", headers=w.member).json() == {"ok": True}
    rows = client.get(url, headers=w.member).json()
    assert [(r["name"], r["devices"]) for r in rows] == [("green", 0), ("navy", 1)]
    assert client.delete(f"/api/v1/entries/{eid}/tags/{t['id']}", headers=w.member).json() == {"ok": True}
    assert client.delete(f"/api/v1/tags/{other['id']}", headers=w.member).json() == {"ok": True}
    assert client.post(f"/api/v1/address-books/{w.read}/tags", headers=w.member,
                       json={"name": "x"}).status_code == 403


def test_book_management_rules(client, w):
    assert client.post("/api/v1/address-books", headers=w.member, json={"name": "x"}).status_code == 403
    assert client.post("/api/v1/address-books", headers=w.admin, json={"name": " "}).json() == {
        "detail": "missing name"}
    b = client.post("/api/v1/address-books", headers=w.admin, json={"name": "New"}).json()
    assert b == {"id": b["id"], "name": "New", "type": "shared"}
    assert client.put(f"/api/v1/address-books/{w.write}", headers=w.member,
                      json={"name": "x"}).json() == {"detail": "full control required"}
    assert client.put(f"/api/v1/address-books/{w.member_personal}", headers=w.member,
                      json={"name": "x"}).status_code == 400
    assert client.delete(f"/api/v1/address-books/{w.member_personal}", headers=w.member).status_code == 400
    assert client.put(f"/api/v1/address-books/{b['id']}", headers=w.admin,
                      json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.delete(f"/api/v1/address-books/{b['id']}", headers=w.admin).json() == {"ok": True}


def test_discovered_and_device_card(client, w):
    rid_known, rid_free = _uid("d"), _uid("d")
    now = datetime.utcnow()
    with SessionLocal() as db:
        for rid, online in ((rid_known, True), (rid_free, False)):
            db.add(DiscoveredDevice(rustdesk_id=rid, last_ip="203.0.113.10", source="udp",
                                    seen_count=1, online=online, last_seen=now))
        db.add(DeviceInfo(rustdesk_id=rid_free, hostname="kassa-7", username="op",
                          collected_at=now))
        db.commit()
    w.add_entry(w.write, rid_known, alias="Known")
    rows = client.get(f"/api/v1/discovered?search={rid_known}", headers=w.member).json()
    assert rows["total"] == 1
    row = rows["data"][0]
    assert set(row) == {"rustdesk_id", "first_seen", "last_seen", "last_connected",
                        "last_disconnected", "last_ip", "source", "online", "seen_count",
                        "in_books", "info"}
    names = {b["id"]: b["name"] for b in client.get("/api/v1/address-books", headers=w.member).json()}
    assert row["in_books"] == [{"id": w.write, "name": names[w.write]}]
    unlinked = client.get("/api/v1/discovered?only_unlinked=1&page_size=200", headers=w.member).json()
    assert rid_known not in {r["rustdesk_id"] for r in unlinked["data"]}
    offline = client.get(f"/api/v1/discovered?status=offline&search={rid_free}", headers=w.member).json()
    assert [r["rustdesk_id"] for r in offline["data"]] == [rid_free]

    add = client.post(f"/api/v1/discovered/{rid_free}/add", headers=w.member,
                      json={"book_id": w.write, "tags": ["new"]})
    assert add.status_code == 200 and add.json()["alias"] == "kassa-7"
    assert add.json()["hostname"] == "kassa-7" and add.json()["username"] == "op"
    again = client.post(f"/api/v1/discovered/{rid_free}/add", headers=w.member, json={"book_id": w.write})
    assert again.status_code == 409 and again.json() == {"detail": "already in this book"}
    assert client.post(f"/api/v1/discovered/{rid_free}/add", headers=w.member,
                       json={"book_id": w.read}).status_code == 403

    card = client.get(f"/api/v1/device-info/{rid_free}", headers=w.member).json()
    assert set(card) == {"rustdesk_id", "online", "last_seen", "last_ip", "discovered", "info",
                         "entries", "sources"}
    assert card["sources"] == ["discovery", "sysinfo", "address_book"]
    assert card["entries"][0]["book_id"] == w.write and "book_name" in card["entries"][0]
    assert card["info"]["hostname"] == "kassa-7"
    assert client.get("/api/v1/device-info/unknown123", headers=w.member).status_code == 404
    assert client.get("/api/v1/device-info/a@b", headers=w.member).status_code == 422
    ref = client.post(f"/api/v1/device-info/{rid_free}/refresh", headers=w.member).json()
    assert ref["ok"] is True and ref["expires_in"] > 0
    assert client.delete(f"/api/v1/discovered/{rid_free}", headers=w.member).status_code == 403
    assert client.delete(f"/api/v1/discovered/{rid_free}", headers=w.admin).json() == {"ok": True}
    assert client.delete(f"/api/v1/discovered/{rid_free}", headers=w.admin).status_code == 404


def test_admin_only_endpoints(client, w):
    for method, path in (("GET", "/api/v1/users"), ("POST", "/api/v1/users"),
                         ("GET", "/api/v1/audit"), ("GET", "/api/v1/audit/meta")):
        r = client.request(method, path, headers=w.member,
                           json={"username": "x", "password": "y"} if method == "POST" else None)
        assert r.status_code == 403 and r.json() == {"detail": "admin required"}, path
    assert client.get("/api/v1/me", headers=w.member).json()["username"] == w.member_name
    assert client.get("/api/v1/stats").status_code == 401


# --- legacy panel ---------------------------------------------------------------

def test_legacy_panel_pages_and_forms(client, w):
    from fastapi.testclient import TestClient

    from app.main import app

    pc = TestClient(app, follow_redirects=False)
    assert pc.get("/panel/devices").headers["location"] == "/panel/login"
    pc.post("/panel/login", data={"username": w.member_name, "password": PASSWORD})
    r = pc.post("/panel/devices/create", data={"book": w.write, "rustdesk_id": "panel-1",
                                               "alias": "From panel", "tags": "p1, p2"})
    assert r.status_code == 303
    page = pc.get(f"/panel/devices?book={w.write}&tag=p1")
    assert page.status_code == 200 and "panel-1" in page.text
    assert "panel-1" not in pc.get(f"/panel/devices?book={w.write}&untagged=true").text
    pc.post("/panel/devices/create", data={"book": w.read, "rustdesk_id": "panel-ro"})
    assert "panel-ro" not in pc.get(f"/panel/devices?book={w.read}").text
    pc.post("/panel/tags/create", data={"book": w.write, "name": "fresh", "color": "0x10"})
    tags = pc.get(f"/panel/tags?book={w.write}")
    assert tags.status_code == 200 and "fresh" in tags.text
    assert pc.get("/panel/users").headers["location"] == "/panel/devices"
