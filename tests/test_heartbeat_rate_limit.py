"""Regression tests for the heartbeat rate limiter.

The production symptom: ~800 devices behind one NAT each post /api/heartbeat
every ~15s (≈3200 req/min), while the old limiter allowed 300 req/min per IP.
These tests pin the fixed behaviour: independent per-device buckets, a finite
aggregate per-IP cap, and unchanged protection for other endpoints.
"""
import asyncio
import os

import httpx
import pytest
from sqlalchemy import select

from app.core import middleware
from app.core.config import settings

TEST_IP = "testclient"  # Starlette TestClient's default direct peer
slow = pytest.mark.skipif(
    os.environ.get("RUN_LOAD_TESTS") != "1",
    reason="set RUN_LOAD_TESTS=1 to run load checks",
)


def heartbeat(client, rid: str, **kwargs):
    return client.post("/api/heartbeat", json={"id": rid, "ver": "1.0"}, **kwargs)


def dev_key(rid: str, ip: str = TEST_IP) -> tuple:
    return ("heartbeat:dev", ip, rid)


def ip_key(ip: str = TEST_IP) -> tuple:
    return ("heartbeat:ip", ip)


def test_heartbeat_is_processed_and_updates_last_seen(client):
    from app.db.session import SessionLocal
    from app.models.models import AddressBookEntry

    response = heartbeat(client, "dev0000")
    assert response.status_code == 200
    assert response.json() == {}

    with SessionLocal() as db:
        entry = db.scalar(
            select(AddressBookEntry).where(AddressBookEntry.rustdesk_id == "dev0000")
        )
        assert entry is not None
        assert entry.last_seen is not None


def test_devices_sharing_one_ip_have_independent_buckets(client, monkeypatch):
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 3)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 1000)

    for rid in ("dev0001", "dev0002"):
        for _ in range(3):
            assert heartbeat(client, rid).status_code == 200
        assert heartbeat(client, rid).status_code == 429, rid


def test_device_limit_is_enforced_and_does_not_block_neighbour(client, monkeypatch):
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 2)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 1000)

    assert heartbeat(client, "dev0001").status_code == 200
    assert heartbeat(client, "dev0001").status_code == 200

    limited = heartbeat(client, "dev0001")
    assert limited.status_code == 429
    assert limited.json() == {"error": "rate limited"}
    assert 1 <= int(limited.headers["Retry-After"]) <= 60

    # A retrying device must not consume the shared IP budget.
    assert heartbeat(client, "dev0002").status_code == 200

    # Rejected requests are not appended to the bucket.
    assert len(middleware.HITS[dev_key("dev0001")]) == 2
    assert len(middleware.HITS[ip_key()]) == 3


def test_aggregate_ip_limit_still_rejects_floods(client, monkeypatch):
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 100)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 5)

    for i in range(5):
        assert heartbeat(client, f"dev{i:04d}").status_code == 200

    rejected = heartbeat(client, "dev0005")
    assert rejected.status_code == 429
    assert rejected.json() == {"error": "rate limited"}
    assert 1 <= int(rejected.headers["Retry-After"]) <= 60
    # The rejected device never entered its own bucket.
    assert dev_key("dev0005") not in middleware.HITS


def test_repeated_429_requests_do_not_grow_state(client, monkeypatch):
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 2)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 1000)

    assert heartbeat(client, "dev0001").status_code == 200
    assert heartbeat(client, "dev0001").status_code == 200
    for _ in range(20):
        assert heartbeat(client, "dev0001").status_code == 429

    assert len(middleware.HITS[dev_key("dev0001")]) == 2
    assert len(middleware.HITS[ip_key()]) == 2


def test_spoofed_xff_cannot_evade_the_aggregate_cap(client, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", "")
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 100)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 2)

    for i in range(2):
        response = client.post(
            "/api/heartbeat",
            json={"id": f"dev{i:04d}"},
            headers={"X-Forwarded-For": f"198.51.100.{i + 1}"},
        )
        assert response.status_code == 200

    assert heartbeat(client, "dev0002").status_code == 429


def test_chunked_heartbeat_is_still_limited_by_ip(client, monkeypatch):
    """No Content-Length means no per-device key, but the IP cap still applies."""
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 100)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 2)

    def body(rid: str):
        yield f'{{"id":"{rid}"}}'.encode()

    for i in range(2):
        response = client.post("/api/heartbeat", content=body(f"dev{i:04d}"))
        assert response.status_code == 200

    assert client.post("/api/heartbeat", content=body("dev0002")).status_code == 429


def test_other_endpoint_limits_are_unchanged(client, monkeypatch):
    monkeypatch.setattr(settings, "login_per_minute_per_ip", 2)

    for _ in range(2):
        # Bad credentials are fine here: the limiter runs before the handler.
        assert client.post("/api/login", json={"username": "", "password": ""}).status_code != 429

    limited = client.post("/api/login", json={"username": "", "password": ""})
    assert limited.status_code == 429
    assert limited.json() == {"error": "rate limited"}
    assert "Retry-After" in limited.headers

    # Heartbeat buckets are independent from login buckets.
    assert heartbeat(client, "dev0001").status_code == 200


def test_parallel_heartbeats_from_one_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 20)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 6000)

    from app.main import app

    async def run():
        transport = httpx.ASGITransport(
            app=app, client=("198.51.100.10", 12345)
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            return await asyncio.wait_for(
                asyncio.gather(
                    *[
                        async_client.post(
                            "/api/heartbeat",
                            json={"id": f"dev{i:04d}", "ver": "1.0"},
                        )
                        for i in range(200)
                    ]
                ),
                timeout=60,
            )

    responses = asyncio.run(run())
    assert [r.status_code for r in responses] == [200] * 200


def test_same_device_from_two_ips_has_independent_buckets(client, monkeypatch):
    """Per-device keys include the client IP, so one peer cannot lock another out."""
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 2)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 1000)

    from app.main import app

    async def run(ip: str):
        transport = httpx.ASGITransport(app=app, client=(ip, 12345))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            return [
                await async_client.post("/api/heartbeat", json={"id": "dev0001"})
                for _ in range(3)
            ]

    first = asyncio.run(run("198.51.100.20"))
    second = asyncio.run(run("198.51.100.21"))
    assert [r.status_code for r in first] == [200, 200, 429]
    assert [r.status_code for r in second] == [200, 200, 429]


def test_stale_device_buckets_are_swept(monkeypatch):
    middleware.reset_rate_limits()
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 20)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 6000)

    assert middleware.heartbeat_allow("dev0001", TEST_IP, now=100.0) == (True, 0)
    assert middleware.heartbeat_allow("dev0002", TEST_IP, now=100.0) == (True, 0)

    # >60s later the periodic sweep drops the old keys before adding a new one.
    assert middleware.heartbeat_allow("dev0003", TEST_IP, now=200.0) == (True, 0)
    assert dev_key("dev0001") not in middleware.HITS
    assert dev_key("dev0002") not in middleware.HITS
    assert dev_key("dev0003") in middleware.HITS


def test_800_devices_behind_one_ip_are_not_rejected(client):
    """The regression: one heartbeat from each of 800 devices on one IP."""
    for i in range(800):
        response = heartbeat(client, f"dev{i:04d}")
        assert response.status_code == 200, (i, response.status_code)


@slow
@pytest.mark.slow
def test_expected_load_800_devices_at_15s_interval(client):
    """800 devices × 4 heartbeats = one simulated minute (3200 requests)."""
    for _round in range(4):
        for i in range(800):
            response = heartbeat(client, f"dev{i:04d}")
            assert response.status_code == 200, (i, response.status_code)


@slow
@pytest.mark.slow
def test_mass_reconnect_800_devices_in_parallel(client, monkeypatch):
    """All devices reconnect at once; the aggregate cap must still fit them."""
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_device", 20)
    monkeypatch.setattr(settings, "heartbeat_per_minute_per_ip", 6000)

    from app.main import app

    async def run():
        transport = httpx.ASGITransport(app=app, client=("198.51.100.30", 12345))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as async_client:
            return await asyncio.wait_for(
                asyncio.gather(
                    *[
                        async_client.post(
                            "/api/heartbeat",
                            json={"id": f"dev{i:04d}", "ver": "1.0"},
                        )
                        for i in range(800)
                    ]
                ),
                timeout=120,
            )

    responses = asyncio.run(run())
    codes = {}
    for response in responses:
        codes[response.status_code] = codes.get(response.status_code, 0) + 1
    assert codes == {200: 800}
