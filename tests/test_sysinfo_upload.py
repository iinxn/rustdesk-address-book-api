"""Regression tests for `/api/sysinfo` write-once behaviour.

The stock client (src/hbbs_http/sync.rs) uploads sysinfo on its own at startup
and again after a Windows user logs in. On anything other than
`SYSINFO_UPDATED` it retries every ~2 minutes, so the server must acknowledge
duplicates without rewriting the database. A card is refreshed only through the
panel button, which arms a one-shot approval consumed by the next heartbeat.
"""
import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import DeviceInfo
from app.services import device_info as info_svc


def payload(rid: str, hostname: str | None = None, **overrides) -> dict:
    data = {
        "id": rid,
        "hostname": hostname or f"pc-{rid}",
        "username": "alice",
        "os": "Linux / 6.1",
        "cpu": "Example CPU, 3.2GHz, 8/4 cores",
        "memory": "16GB",
        "version": "1.4.0",
        "uuid": "must-not-be-stored",
        "preset-address-book-password": "must-not-be-stored",
    }
    data.update(overrides)
    return data


def upload(client, rid: str, hostname: str | None = None, **overrides):
    return client.post("/api/sysinfo", json=payload(rid, hostname, **overrides))


def stored(rid: str) -> DeviceInfo | None:
    with SessionLocal() as db:
        return db.get(DeviceInfo, rid)


@pytest.fixture(autouse=True)
def clean_state(seeded):
    """Isolate this file: no stale cards or refresh approvals between tests."""
    info_svc.reset_refresh_state()
    with SessionLocal() as db:
        db.execute(delete(DeviceInfo))
        db.commit()
    yield
    info_svc.reset_refresh_state()
    with SessionLocal() as db:
        db.execute(delete(DeviceInfo))
        db.commit()


def test_first_upload_is_stored_and_acknowledged(client):
    response = upload(client, "dev0000")

    assert response.status_code == 200
    assert response.text == "SYSINFO_UPDATED"

    row = stored("dev0000")
    assert row is not None
    assert row.hostname == "pc-dev0000"
    assert row.collected_at is not None
    # Whitelist: secrets from preset keys and the uuid are never persisted.
    assert "must-not-be-stored" not in (row.os or "")


def test_duplicate_auto_upload_does_not_rewrite_the_card(client):
    upload(client, "dev0000", hostname="pc-first")
    first = stored("dev0000")

    response = upload(
        client, "dev0000", hostname="pc-second", os="Windows / 11", username="bob"
    )

    assert response.status_code == 200
    assert response.text == "SYSINFO_UPDATED"
    row = stored("dev0000")
    assert row.hostname == "pc-first"
    assert row.os == "Linux / 6.1"
    assert row.username == "alice"
    assert row.collected_at == first.collected_at


def test_incomplete_card_is_completed_by_the_next_auto_upload(client):
    """Windows reports an empty username before login, then uploads again."""
    upload(client, "dev0000", username="")
    assert stored("dev0000").username == ""

    response = upload(client, "dev0000", username="alice")

    assert response.text == "SYSINFO_UPDATED"
    assert stored("dev0000").username == "alice"


def test_incomplete_card_is_not_rewritten_by_a_payload_that_lacks_the_field(client):
    upload(client, "dev0000", hostname="pc-first", username="")

    response = upload(client, "dev0000", hostname="pc-second", username="")

    assert response.text == "SYSINFO_UPDATED"
    row = stored("dev0000")
    assert row.hostname == "pc-first"
    assert row.username == ""


def test_panel_refresh_allows_exactly_one_overwrite(client):
    upload(client, "dev0000", hostname="pc-old")

    info_svc.request_refresh("dev0000")
    heartbeat = client.post("/api/heartbeat", json={"id": "dev0000", "ver": "1.4.0"})
    assert heartbeat.status_code == 200
    assert heartbeat.json() == {"sysinfo": True}

    assert upload(client, "dev0000", hostname="pc-new").text == "SYSINFO_UPDATED"
    assert stored("dev0000").hostname == "pc-new"

    # Approval is one-shot: the next automatic upload is ignored again.
    assert upload(client, "dev0000", hostname="pc-later").text == "SYSINFO_UPDATED"
    assert stored("dev0000").hostname == "pc-new"


def test_plain_heartbeat_never_asks_for_sysinfo(client):
    response = client.post("/api/heartbeat", json={"id": "dev0000", "ver": "1.4.0"})

    assert response.status_code == 200
    assert response.json() == {}


def test_unknown_id_is_acknowledged_but_not_stored(client):
    response = upload(client, "999999999")

    assert response.status_code == 200
    assert response.text == "SYSINFO_UPDATED"
    assert stored("999999999") is None


def test_unknown_id_can_be_stored_after_panel_approval(client):
    """An admin can refresh an id that is not in a book yet (e.g. before adding)."""
    info_svc.request_refresh("999999999")
    assert client.post(
        "/api/heartbeat", json={"id": "999999999", "ver": "1.4.0"}
    ).json() == {"sysinfo": True}

    assert upload(client, "999999999").text == "SYSINFO_UPDATED"

    row = stored("999999999")
    assert row is not None
    assert row.hostname == "pc-999999999"


def test_discovered_device_is_stored_without_a_book_entry(client):
    from app.models.models import DiscoveredDevice

    with SessionLocal() as db:
        db.add(DiscoveredDevice(rustdesk_id="555555555"))
        db.commit()

    assert upload(client, "555555555").text == "SYSINFO_UPDATED"
    assert stored("555555555") is not None


def test_800_devices_can_bootstrap_behind_one_ip(client):
    """First boot after deploy: every device creates its card once."""
    for i in range(800):
        response = upload(client, f"dev{i:04d}")
        assert response.status_code == 200, (i, response.status_code, response.text)

    with SessionLocal() as db:
        rows = db.scalars(select(DeviceInfo.rustdesk_id)).all()
    assert len(rows) == 800


def test_800_repeat_uploads_do_not_write_anything(client):
    """Steady state: all cards exist, so the fleet's uploads are no-ops."""
    from datetime import datetime

    stamp = datetime(2026, 1, 1, 12, 0, 0)
    with SessionLocal() as db:
        for i in range(800):
            db.add(
                DeviceInfo(
                    rustdesk_id=f"dev{i:04d}",
                    hostname=f"pc-{i}",
                    username="alice",
                    os="Linux / 6.1",
                    collected_at=stamp,
                )
            )
        db.commit()

    for i in range(800):
        response = upload(client, f"dev{i:04d}", hostname=f"new-host-{i}")
        assert response.status_code == 200, (i, response.status_code, response.text)

    with SessionLocal() as db:
        rows = list(db.scalars(select(DeviceInfo)))
    assert len(rows) == 800
    assert all(row.hostname == f"pc-{int(row.rustdesk_id[3:])}" for row in rows)
    assert all(row.collected_at == stamp for row in rows)


def test_sysinfo_limit_remains_finite(client, monkeypatch):
    monkeypatch.setattr(settings, "sysinfo_per_minute_per_ip", 2)

    assert upload(client, "dev0000").status_code == 200
    assert upload(client, "dev0001").status_code == 200

    limited = upload(client, "dev0002")
    assert limited.status_code == 429
    assert limited.json() == {"error": "rate limited"}
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    # Rate-limited uploads are never stored.
    assert stored("dev0002") is None


def test_malformed_and_oversized_bodies_are_unchanged(client):
    bad_json = client.post("/api/sysinfo", content=b"not json")
    assert bad_json.status_code == 400
    assert bad_json.text == "ID_NOT_FOUND"

    too_big = client.post("/api/sysinfo", content=b"x" * (32 * 1024 + 1))
    assert too_big.status_code == 413
    assert too_big.text == "ID_NOT_FOUND"

    invalid_id = client.post("/api/sysinfo", json=payload("bad id"))
    assert invalid_id.status_code == 200
    assert invalid_id.text == "ID_NOT_FOUND"

    missing_id = client.post("/api/sysinfo", json={"hostname": "x"})
    assert missing_id.status_code == 200
    assert missing_id.text == "ID_NOT_FOUND"
