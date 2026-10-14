"""Rate limiting + body cap + DB hardening regression tests."""


def test_login_rate_limited(client):
    from app.core import middleware as mw
    from app.services.auth import create_user
    from tests.db import TestingSession
    mw.HITS.clear()
    mw_settings_login = 3
    import app.core.config as config_mod
    old = config_mod.settings.login_per_minute_per_ip
    config_mod.settings.login_per_minute_per_ip = mw_settings_login
    try:
        db = TestingSession()
        create_user(db, "rl", "pw")
        db.close()
        codes = [client.post("/api/login", json={"username": "rl", "password": "bad", "type": "account"}).status_code
                 for _ in range(5)]
        assert codes[:3] == [401, 401, 401], codes
        assert codes[3:] == [429, 429], codes
    finally:
        config_mod.settings.login_per_minute_per_ip = old
        mw.HITS.clear()


def test_oversized_request_rejected(client):
    r = client.post("/api/login", content=b"x" * (6 * 1024 * 1024),
                    headers={"Content-Type": "application/json", "Content-Length": str(6 * 1024 * 1024)})
    assert r.status_code == 413


def test_database_foreign_keys_enabled():
    from sqlalchemy import text
    from tests.db import TestingSession
    db = TestingSession()
    try:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        db.close()


def test_database_path_is_stable():
    from app.core.config import DATA_DIR, settings
    url = settings.resolved_database_url
    assert url.startswith("sqlite:////"), url  # absolute, never CWD-relative
    # relative sqlite URLs are re-anchored under DATA_DIR, never CWD
    old = settings.database_url
    try:
        settings.database_url = "sqlite:///./stray.db"
        assert settings.resolved_database_url == f"sqlite:///{DATA_DIR / 'stray.db'}"
    finally:
        settings.database_url = old
