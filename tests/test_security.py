"""Threat-model regression tests: authn/authz/IDOR/injection boundaries."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def user2(client: TestClient):
    from app.services.auth import create_user
    from tests.db import TestingSession
    db = TestingSession()
    create_user(db, "victim", "pw2")
    db.close()
    r = client.post("/api/login", json={"username": "victim", "password": "pw2", "type": "account"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    guid = client.post("/api/ab/personal", headers={"Authorization": f"Bearer {token}"}).json()["guid"]
    client.post(f"/api/ab/peer/add/{guid}", headers={"Authorization": f"Bearer {token}"},
                json={"id": "999", "alias": "victim-pc", "tags": []})
    return {"token": token, "guid": guid, "headers": {"Authorization": f"Bearer {token}"}}


def test_unauthenticated_api_access_denied(client):
    for method, path in (("POST", "/api/ab/personal"), ("GET", "/api/v1/address-books"),
                         ("GET", "/api/v1/stats"), ("GET", "/api/v1/users")):
        r = client.request(method, path)
        assert r.status_code == 401, (method, path, r.status_code)


def test_invalid_token_rejected(client):
    r = client.post("/api/ab/personal", headers={"Authorization": "Bearer bogus"})
    assert r.status_code == 401
    r = client.post("/api/ab/personal", headers={"Authorization": "bogus"})
    assert r.status_code == 401


def test_user_cannot_read_other_users_address_book(client, user, user2):
    guid = user2["guid"]
    r = client.post(f"/api/ab/peers?current=1&pageSize=100&ab={guid}", headers=user["headers"])
    assert r.status_code == 404
    r = client.post(f"/api/ab/tags/{guid}", headers=user["headers"])
    assert r.status_code == 404
    r = client.post(f"/api/ab/peer/add/{guid}", headers=user["headers"],
                    json={"id": "1", "alias": "x", "tags": []})
    assert r.status_code == 404


def test_user_cannot_modify_other_users_device(client, user, user2):
    guid = user2["guid"]
    r = client.put(f"/api/ab/peer/update/{guid}", headers=user["headers"],
                   json={"id": "999", "alias": "pwned"})
    assert r.status_code in (403, 404), r.status_code
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=user["headers"])
    assert r.status_code == 404


def test_user_cannot_modify_other_users_tags(client, user, user2):
    guid = user2["guid"]
    for method, path, body in (
        ("POST", f"/api/ab/tag/add/{guid}", {"name": "x", "color": 1}),
        ("PUT", f"/api/ab/tag/rename/{guid}", {"old": "a", "new": "b"}),
        ("DELETE", f"/api/ab/tag/{guid}", ["a"]),
    ):
        r = client.request(method, path, headers=user["headers"], json=body)
        assert r.status_code in (403, 404), (method, path, r.status_code)


def test_non_admin_cannot_manage_users(client, user):
    assert user  # tester is admin; make a plain user instead
    from app.services.auth import create_user
    from tests.db import TestingSession
    db = TestingSession()
    create_user(db, "plain", "pw")
    db.close()
    r = client.post("/api/login", json={"username": "plain", "password": "pw", "type": "account"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/users", headers=h).status_code == 403
    assert client.post("/api/v1/users", headers=h, json={"username": "z", "password": "z"}).status_code == 403


def test_mass_assignment_ignored(client, user):
    h, guid = user["headers"], user["guid"]
    r = client.post(f"/api/v1/address-books/{guid}/entries", headers=h,
                    json={"rustdesk_id": "777", "alias": "a", "is_admin": True,
                          "owner_user_id": "someone-else", "rule": 3})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "is_admin" not in d and "owner_user_id" not in d and "rule" not in d
    r = client.put("/api/v1/users/xxx", headers=h, json={"is_admin": True, "zzz": 1})
    assert r.status_code in (403, 404)  # unknown id, extra key ignored either way


def test_sql_injection_payload_is_not_executed(client, user):
    h, guid = user["headers"], user["guid"]
    evil = "' OR '1'='1'; DROP TABLE users; --"
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h, params={"search": evil})
    assert r.status_code == 200 and r.json()["total"] == 0
    r = client.get("/api/v1/users", headers=h)
    assert r.status_code == 200  # users table intact
    r = client.get(f"/api/v1/address-books/{guid}/entries", headers=h,
                   params={"sort": "alias; DROP TABLE users"})
    assert r.status_code == 200  # unknown sort falls back to alias, no SQL


def test_sensitive_fields_not_returned(client, user):
    h = user["headers"]
    body = client.post("/api/login", json={"username": "tester", "password": "secret123", "type": "account"}).json()
    assert "password_hash" not in body["user"] and "password" not in body["user"]
    r = client.get("/api/v1/users", headers=h).json()
    assert all("password_hash" not in u for u in r)


def test_panel_requires_login(client):
    r = client.get("/panel/devices", follow_redirects=False)
    assert r.status_code in (303, 307)
    r = client.post("/panel/devices/create", data={"book": "x", "rustdesk_id": "1"}, follow_redirects=False)
    assert r.status_code in (303, 307, 401)


def test_logout_revokes_token(client, user):
    h = dict(user["headers"])
    assert client.post("/api/logout", headers=h, json={}).status_code == 200
    assert client.post("/api/ab/personal", headers=h).status_code == 401
