"""display_name: panel editing and the value the RustDesk client uses as `my_name`.

The client caches the `/api/login` user object (local option `user_info`) and
sends `user_info.display_name` to the peer as `LoginRequest.my_name`
(rustdesk `src/client.rs::create_login_msg`). So the server contract is:
`/api/login` and `/api/currentUser` must return exactly what the panel saved.
"""
import uuid

import pytest


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_user(username: str, password: str = "secret", is_admin: bool = False, display_name: str = ""):
    from app.db.session import SessionLocal
    from app.services.auth import create_user

    with SessionLocal() as db:
        user = create_user(db, username, password, is_admin=is_admin, display_name=display_name)
        return user.id


def _login(client, username: str, password: str = "secret") -> dict:
    r = client.post(
        "/api/login",
        json={"username": username, "password": password, "type": "account"},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def admin(client):
    username = _unique("admin")
    uid = _create_user(username, is_admin=True)
    body = _login(client, username)
    return {"id": uid, "username": username, "token": body["access_token"]}


@pytest.fixture()
def member(client):
    username = _unique("user")
    uid = _create_user(username)
    body = _login(client, username)
    return {"id": uid, "username": username, "token": body["access_token"]}


def test_create_user_with_display_name_reaches_login_and_current_user(client, admin):
    username = _unique("ivan")
    r = client.post(
        "/api/v1/users",
        json={
            "username": username,
            "password": "secret",
            "is_admin": False,
            "display_name": "  Ivan   Petrov ",
        },
        headers=_auth(admin["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Ivan Petrov"

    rows = client.get("/api/v1/users", headers=_auth(admin["token"])).json()
    row = next(u for u in rows if u["username"] == username)
    assert row["display_name"] == "Ivan Petrov"

    body = _login(client, username)
    assert body["user"]["display_name"] == "Ivan Petrov"

    current = client.post("/api/currentUser", headers=_auth(body["access_token"]))
    assert current.status_code == 200
    assert current.json()["display_name"] == "Ivan Petrov"


def test_admin_can_change_another_users_display_name(client, admin, member):
    r = client.put(
        f"/api/v1/users/{member['id']}",
        json={"display_name": "Anna Smith"},
        headers=_auth(admin["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Anna Smith"
    assert _login(client, member["username"])["user"]["display_name"] == "Anna Smith"


def test_user_edits_own_display_name_via_me(client, member):
    r = client.put("/api/v1/me", json={"display_name": "Bob"}, headers=_auth(member["token"]))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": member["id"],
        "username": member["username"],
        "display_name": "Bob",
        "is_admin": False,
        "is_disabled": False,
    }
    assert client.get("/api/v1/me", headers=_auth(member["token"])).json()["display_name"] == "Bob"
    assert _login(client, member["username"])["user"]["display_name"] == "Bob"


def test_me_requires_authentication(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.put("/api/v1/me", json={"display_name": "X"}).status_code == 401


def test_member_cannot_edit_other_users(client, admin, member):
    r = client.put(
        f"/api/v1/users/{admin['id']}",
        json={"display_name": "Hacked"},
        headers=_auth(member["token"]),
    )
    assert r.status_code == 403
    assert _login(client, admin["username"])["user"]["display_name"] == ""


def test_display_name_is_validated_and_normalized(client, admin, member):
    too_long = "x" * 129
    r = client.put("/api/v1/me", json={"display_name": too_long}, headers=_auth(member["token"]))
    assert r.status_code == 400
    assert "display_name too long" in r.json()["detail"]

    r = client.put("/api/v1/me", json={"display_name": "x" * 128}, headers=_auth(member["token"]))
    assert r.status_code == 200
    assert len(r.json()["display_name"]) == 128

    # Whitespace (including newlines) collapses to single spaces: the value is
    # sent to the peer as `my_name` and rendered in its UI.
    r = client.put("/api/v1/me", json={"display_name": "  Ann\n\tLee  "}, headers=_auth(member["token"]))
    assert r.json()["display_name"] == "Ann Lee"

    r = client.post(
        "/api/v1/users",
        json={"username": _unique("long"), "password": "secret", "display_name": too_long},
        headers=_auth(admin["token"]),
    )
    assert r.status_code == 400

    r = client.put(
        f"/api/v1/users/{member['id']}",
        json={"display_name": 42},
        headers=_auth(admin["token"]),
    )
    assert r.status_code == 400
    assert "must be a string" in r.json()["detail"]


def test_empty_display_name_is_allowed(client, admin, member):
    client.put("/api/v1/me", json={"display_name": "Temporary"}, headers=_auth(member["token"]))
    r = client.put("/api/v1/me", json={"display_name": "   "}, headers=_auth(member["token"]))
    assert r.status_code == 200
    assert r.json()["display_name"] == ""
    # The client falls back to the login name when display_name is empty.
    assert _login(client, member["username"])["user"]["display_name"] == ""
