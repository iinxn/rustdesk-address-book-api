"""Connection-safety regression tests.

The rendezvous secure-tcp stage (client/src/client.rs) takes NO input from
Address Book peer data — but if our API ever started emitting transport
fields (server/relay/key/...) or corrupted password/hash, connections could
break. These tests lock the safe contract in.
"""
from sqlalchemy import select

ALLOWED_PEER_KEYS = {
    "id", "username", "hostname", "platform", "alias", "tags",
    "note", "hash", "password",
}
TRANSPORT_KEYS = {
    "server", "relay", "relay_server", "relay-server", "rendezvous",
    "rendezvous_server", "rendezvous-server", "key", "public_key", "url",
    "host", "port", "endpoint", "id_server", "id-server", "ws", "websocket",
    "proxy", "force_relay", "forceAlwaysRelay", "switch_code", "switch_uuid",
}


def _personal(client, headers):
    return client.post("/api/ab/personal", headers=headers).json()["guid"]


def _shared_book(client, headers):
    from tests.db import TestingSession
    from app.models.models import AddressBook, AddressBookPermission, User
    db = TestingSession()
    me = db.scalar(select(User).where(User.username == "tester"))
    owner = db.scalar(select(User).where(User.username != "tester"))
    if owner is None:
        from app.services.auth import create_user
        owner = create_user(db, "owner", "pw")
    book = AddressBook(name="Shared", type="shared", owner_user_id=owner.id)
    db.add(book)
    db.flush()
    if db.scalar(select(AddressBookPermission).where(
            AddressBookPermission.address_book_id == book.id,
            AddressBookPermission.user_id == me.id)) is None:
        db.add(AddressBookPermission(address_book_id=book.id, user_id=me.id, rule=3))
    db.commit()
    gid = book.id
    db.close()
    return gid


def test_login_response_has_no_config_fields(client, user):
    r = client.post("/api/login", json={"username": "tester", "password": "secret123", "type": "account"})
    body = r.json()
    assert set(body) <= {"access_token", "type", "user", "tfa_type", "secret"}
    assert set(body["user"]) <= {"name", "display_name", "avatar", "email", "note", "status", "is_admin"}


def test_personal_peers_have_no_transport_fields(client, user):
    h, guid = user["headers"], user["guid"]
    client.post(f"/api/ab/peer/add/{guid}", headers=h,
                json={"id": "123456789", "alias": "A", "tags": ["T"], "note": "n"})
    data = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h).json()["data"]
    assert len(data) == 1
    assert not (set(data[0]) & TRANSPORT_KEYS), set(data[0]) & TRANSPORT_KEYS
    assert set(data[0]) <= ALLOWED_PEER_KEYS


def test_shared_peers_have_no_transport_fields(client, user):
    h = user["headers"]
    gid = _shared_book(client, h)
    client.post(f"/api/ab/peer/add/{gid}", headers=h,
                json={"id": "123456789", "alias": "A", "tags": [], "password": "s3cret!"})
    data = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={gid}", headers=h).json()["data"]
    assert len(data) == 1
    assert not (set(data[0]) & TRANSPORT_KEYS)
    assert set(data[0]) <= ALLOWED_PEER_KEYS


def test_shared_password_roundtrip_byte_identical(client, user):
    h = user["headers"]
    gid = _shared_book(client, h)
    secret = "p@ss w0rd!/#?&="
    client.post(f"/api/ab/peer/add/{gid}", headers=h,
                json={"id": "123456789", "alias": "A", "tags": [], "password": secret})
    data = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={gid}", headers=h).json()["data"]
    assert data[0]["password"] == secret


def test_personal_hash_roundtrip_identical(client, user):
    h, guid = user["headers"], user["guid"]
    client.post(f"/api/ab/peer/add/{guid}", headers=h, json={"id": "123456789", "alias": "A", "tags": []})
    hv = "a" * 64
    r = client.put(f"/api/ab/peer/update/{guid}", headers=h, json={"id": "123456789", "hash": hv})
    assert r.status_code == 200
    data = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=h).json()["data"]
    assert data[0]["hash"] == hv
