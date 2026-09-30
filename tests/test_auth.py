def test_login_ok(client):
    from app.services.auth import create_user
    from tests.db import TestingSession
    db = TestingSession()
    create_user(db, "u1", "pw1")
    db.close()
    r = client.post("/api/login", json={"username": "u1", "password": "pw1", "type": "account"})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "access_token" and body["access_token"]
    assert body["user"]["name"] == "u1"


def test_login_bad_password(client, user):
    r = client.post("/api/login", json={"username": "tester", "password": "wrong", "type": "account"})
    assert r.status_code == 401
    assert "error" in r.json()


def test_protected_requires_token(client):
    r = client.post("/api/ab/personal", headers={})
    assert r.status_code == 401


def test_current_user_and_logout(client, user):
    r = client.post("/api/currentUser", json={"id": "x", "uuid": "y"}, headers=user["headers"])
    assert r.status_code == 200 and r.json()["name"] == "tester"
    r = client.post("/api/logout", json={"id": "x", "uuid": "y"}, headers=user["headers"])
    assert r.status_code == 200
    r = client.post("/api/currentUser", json={"id": "x", "uuid": "y"}, headers=user["headers"])
    assert r.status_code == 401
