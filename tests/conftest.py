"""Shared fixtures for the project test suite.

Environment is configured *before* importing the application so the settings
singleton (and therefore the SQLAlchemy engine) points at a temporary SQLite
database. Tests never touch `data/`.
"""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="rustdesk-ab-tests-"))
atexit.register(shutil.rmtree, _TMP, True)

os.environ["DEV_MODE"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["SHIM_ENABLED"] = "0"
os.environ["DISCOVERY_ENABLED"] = "0"
os.environ["TRUSTED_PROXIES"] = ""
os.environ["LOGIN_PER_MINUTE_PER_IP"] = "20"
os.environ["SYSINFO_PER_MINUTE_PER_IP"] = "6000"
os.environ["HEARTBEAT_PER_MINUTE_PER_DEVICE"] = "20"
os.environ["HEARTBEAT_PER_MINUTE_PER_IP"] = "6000"

import pytest  # noqa: E402

DEVICE_COUNT = 800


@pytest.fixture(scope="session")
def database():
    """Apply the real Alembic migrations to the temporary database."""
    from alembic import command
    from alembic.config import Config

    from app.core.config import BASE_DIR

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BASE_DIR))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def seeded(database):
    """One personal book with 800 devices (the reported production scale)."""
    from app.db.session import SessionLocal
    from app.models.models import AddressBook, AddressBookEntry, User

    with SessionLocal() as db:
        user = User(username="pytest", password_hash="not-a-real-hash")
        db.add(user)
        db.flush()
        book = AddressBook(name="pytest", type="personal", owner_user_id=user.id)
        db.add(book)
        db.flush()
        db.add_all(
            AddressBookEntry(address_book_id=book.id, rustdesk_id=f"dev{i:04d}")
            for i in range(DEVICE_COUNT)
        )
        db.commit()


@pytest.fixture()
def client(seeded):
    """Fresh in-process client with an empty rate-limit store per test."""
    from fastapi.testclient import TestClient

    from app.core.middleware import reset_rate_limits
    from app.main import app

    reset_rate_limits()
    with TestClient(app) as test_client:
        yield test_client
    reset_rate_limits()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: load/throughput checks; set RUN_LOAD_TESTS=1 to run"
    )
