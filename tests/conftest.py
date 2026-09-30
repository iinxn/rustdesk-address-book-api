import os

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
