import os

# Test-only secrets, set before any app import (config fail-fast otherwise).
os.environ.setdefault("DEVICE_SECRET", "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=")
os.environ.setdefault("WEB_SECRET", "test-only-web-secret-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
# Suite-wide: many logins per minute from one test IP; the limiter itself is
# covered by tests/test_ratelimit.py with temporarily lowered thresholds.
os.environ.setdefault("LOGIN_PER_MINUTE_PER_IP", "1000")
os.environ.setdefault("HEARTBEAT_PER_MINUTE_PER_IP", "100000")

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from tests.db import TestingSession, engine


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


@pytest.fixture()
def client():
    engine.dispose()
    if os.path.exists("./test.db"):
        os.remove("./test.db")
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c
    engine.dispose()
    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest.fixture()
def user(client: TestClient):
    from app.services.auth import create_user
    db = TestingSession()
    create_user(db, "tester", "secret123", is_admin=True)
    db.close()
    r = client.post("/api/login", json={"username": "tester", "password": "secret123", "type": "account"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    guid = client.post("/api/ab/personal", headers={"Authorization": f"Bearer {token}"}).json()["guid"]
    return {"token": token, "guid": guid, "headers": {"Authorization": f"Bearer {token}"}}
