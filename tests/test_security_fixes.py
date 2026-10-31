"""Regression tests for the 2026-10-31 security audit fixes.

SEC-A01 login must not block the event loop; saturated bcrypt pool -> 429.
SEC-A02 /panel/login is rate limited like /api/login.
SEC-A08 shim UDP relay: own budget, unconfirmed sessions evicted first.
Password policy: no user without a password, no 500 on long passwords.
Panel cookie: server-side session (revocable), Secure flag on HTTPS.

Temporary SQLite only (conftest.py); no network beyond loopback sockets.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid

import pytest
from itsdangerous import TimestampSigner

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import auth as auth_svc


def _make_user(password: str = "UserPass123!", is_admin: bool = False) -> tuple[str, str]:
    name = f"sec-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        u = auth_svc.create_user(db, name, password, is_admin=is_admin)
        return name, u.id


def _admin_headers(client) -> dict:
    name, _ = _make_user("AdminPass123!", is_admin=True)
    r = client.post("/api/login", json={"username": name, "password": "AdminPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- SEC-A01 -----------------------------------------------------------------

def test_password_check_does_not_block_event_loop(client):
    name, _ = _make_user()

    async def scenario() -> tuple[int, bool]:
        ticks = 0
        done = False

        async def ticker():
            nonlocal ticks
            while not done:
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(ticker())
        with SessionLocal() as db:
            user = await auth_svc.authenticate_async(db, name, "wrong-password")
        done = True
        await task
        return ticks, user is None

    ticks, rejected = asyncio.run(scenario())
    assert rejected
    # bcrypt takes hundreds of ms; the loop kept running meanwhile.
    assert ticks >= 5


def test_saturated_password_pool_sheds_load(monkeypatch):
    monkeypatch.setattr(settings, "password_hash_queue", 1)
    monkeypatch.setattr(auth_svc, "verify_password", lambda p, h: time.sleep(0.3) or False)
    first = auth_svc._verify_future("x", "h")
    with pytest.raises(auth_svc.AuthBusy):
        auth_svc._verify_future("x", "h")
    assert first.result() is False
    # The slot is released when the check finishes.
    assert auth_svc._verify_future("x", "h").result() is False


def test_busy_login_answers_429(client, monkeypatch):
    name, _ = _make_user()

    def busy(*_a, **_k):
        raise auth_svc.AuthBusy()

    monkeypatch.setattr(auth_svc, "_verify_future", busy)
    r = client.post("/api/login", json={"username": name, "password": "UserPass123!"})
    assert r.status_code == 429 and r.headers["retry-after"] == "5"
    assert r.json() == {"error": "too many login attempts"}
    p = client.post("/panel/login", data={"username": name, "password": "UserPass123!"})
    assert p.status_code == 429


def test_empty_password_never_authenticates(client):
    r = client.post("/api/login", json={"username": "admin", "password": ""})
    assert r.status_code == 401


# --- SEC-A02 -----------------------------------------------------------------

def test_panel_login_is_rate_limited(client):
    statuses = [
        client.post("/panel/login", data={"username": "nobody", "password": f"x{i}"}).status_code
        for i in range(settings.login_per_minute_per_ip + 1)
    ]
    assert statuses[:-1] == [401] * settings.login_per_minute_per_ip
    assert statuses[-1] == 429
    # Separate bucket: the RustDesk login is not consumed by panel attempts.
    assert client.post("/api/login", json={"username": "nobody", "password": "x"}).status_code == 401


# --- password policy -----------------------------------------------------------

@pytest.mark.parametrize("password", ["", "   ", "A" * 73])
def test_user_cannot_be_created_without_valid_password(client, password):
    headers = _admin_headers(client)
    name = f"np-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/users", headers=headers, json={"username": name, "password": password})
    assert r.status_code == 400, r.text
    users = client.get("/api/v1/users", headers=headers).json()
    assert name not in {u["username"] for u in users}


def test_password_update_policy(client):
    headers = _admin_headers(client)
    _, uid = _make_user()
    assert client.put(f"/api/v1/users/{uid}", headers=headers, json={"password": "   "}).status_code == 400
    assert client.put(f"/api/v1/users/{uid}", headers=headers, json={"password": "B" * 80}).status_code == 400
    # Empty means "unchanged" (form contract), not "set an empty password".
    assert client.put(f"/api/v1/users/{uid}", headers=headers,
                      json={"password": "", "display_name": "x"}).status_code == 200


def test_create_user_service_rejects_empty_password(client):
    with SessionLocal() as db, pytest.raises(ValueError):
        auth_svc.create_user(db, f"svc-{uuid.uuid4().hex[:8]}", "")


def test_panel_form_does_not_create_passwordless_user(client):
    name, _ = _make_user("PanelAdmin123!", is_admin=True)
    client.post("/panel/login", data={"username": name, "password": "PanelAdmin123!"})
    victim = f"pf-{uuid.uuid4().hex[:8]}"
    client.post("/panel/users/create", data={"username": victim, "password": ""})
    headers = _admin_headers(client)
    assert victim not in {u["username"] for u in client.get("/api/v1/users", headers=headers).json()}


# --- panel cookie ----------------------------------------------------------------

def _panel_client(client, username: str, password: str):
    from fastapi.testclient import TestClient

    from app.main import app

    pc = TestClient(app, follow_redirects=False)
    r = pc.post("/panel/login", data={"username": username, "password": password})
    assert r.status_code == 303, r.text
    assert pc.get("/panel/devices").status_code == 200
    return pc


def test_panel_cookie_revoked_by_password_change(client):
    name, uid = _make_user("Before123!")
    pc = _panel_client(client, name, "Before123!")
    headers = _admin_headers(client)
    r = client.put(f"/api/v1/users/{uid}", headers=headers, json={"password": "After456!"})
    assert r.status_code == 200
    resp = pc.get("/panel/devices")
    assert resp.status_code == 303 and resp.headers["location"] == "/panel/login"


def test_copied_panel_cookie_dies_on_logout(client):
    from fastapi.testclient import TestClient

    from app.main import app

    name, _ = _make_user("Logout123!")
    pc = _panel_client(client, name, "Logout123!")
    stolen = pc.cookies.get("session")
    pc.get("/panel/logout")
    thief = TestClient(app, follow_redirects=False, cookies={"session": stolen})
    assert thief.get("/panel/devices").status_code == 303


def test_legacy_uid_cookie_is_not_accepted(client):
    from fastapi.testclient import TestClient

    from app.main import app

    _, uid = _make_user()
    data = base64.b64encode(json.dumps({"uid": uid}).encode())
    forged = TimestampSigner(str(settings.web_secret)).sign(data).decode()
    old = TestClient(app, follow_redirects=False, cookies={"session": forged})
    assert old.get("/panel/devices").status_code == 303


def test_session_cookie_secure_flag_follows_scheme(client):
    from fastapi.testclient import TestClient

    from app.main import app

    name, _ = _make_user("Secure123!")
    plain = TestClient(app, follow_redirects=False)
    r = plain.post("/panel/login", data={"username": name, "password": "Secure123!"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie

    tls = TestClient(app, base_url="https://testserver", follow_redirects=False)
    r = tls.post("/panel/login", data={"username": name, "password": "Secure123!"})
    assert "secure" in r.headers["set-cookie"].lower()


# --- SEC-A08 -----------------------------------------------------------------

def _relay_scenario(max_sessions: int, per_ip: int, steps):
    from app.shim import shim

    async def run():
        up = await asyncio.get_running_loop().create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
        upstream = up[0].get_extra_info("sockname")
        relay = shim.UdpRelay(upstream, shim.Gate(max_sessions, per_ip))
        try:
            result = await steps(relay)
        finally:
            await relay.aclose()
            up[0].close()
        return result

    return asyncio.run(run())


def test_udp_budget_is_independent_from_tcp_gate():
    async def steps(relay):
        for port in range(1000, 1050):  # 50 devices behind one NAT address
            relay._on_datagram(b"x", ("203.0.113.7", port))
        await asyncio.sleep(0)
        return len(relay.sessions)

    assert _relay_scenario(100, 600, steps) == 50


def test_udp_full_table_evicts_unconfirmed_first():
    async def steps(relay):
        a, b, c, d, e = (("203.0.113.%d" % i, 4000) for i in range(1, 6))
        for addr in (a, b, c):
            relay._on_datagram(b"x", addr)
        relay._on_datagram(b"y", a)          # a re-registers: confirmed
        relay._on_datagram(b"x", d)          # full -> evicts oldest unconfirmed (b)
        after_d = set(relay.sessions)
        relay._on_datagram(b"y", c)
        relay._on_datagram(b"y", d)          # everyone confirmed now
        relay._on_datagram(b"x", e)          # full, nothing to evict -> dropped
        await asyncio.sleep(0)
        return after_d, set(relay.sessions), (a, b, c, d, e)

    after_d, final, (a, b, c, d, e) = _relay_scenario(3, 600, steps)
    assert after_d == {a, c, d}
    assert final == {a, c, d} and e not in final


def test_udp_unconfirmed_sessions_expire_early():
    from app.shim import shim

    async def steps(relay):
        relay._on_datagram(b"x", ("203.0.113.20", 5000))
        relay._on_datagram(b"x", ("203.0.113.21", 5000))
        relay._on_datagram(b"y", ("203.0.113.21", 5000))
        now = time.monotonic() + shim.UDP_UNCONFIRMED_TIMEOUT + 1
        relay.sweep_once(now)
        return set(relay.sessions)

    assert _relay_scenario(10, 600, steps) == {("203.0.113.21", 5000)}
