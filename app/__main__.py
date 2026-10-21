"""Single-command startup: python -m app

1. validate config (fail fast on missing secrets), 2. ensure dirs + perms,
3. run Alembic migrations, 4. serve FastAPI (+ supervised shim via lifespan).
"""
import logging
import os
import sys
from pathlib import Path

# Make `python -m app` work from any directory: anchor imports at project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = logging.getLogger("app.boot")


def ensure_dirs() -> None:
    from app.core.config import DATA_DIR, LOGS_DIR, settings
    for d in (DATA_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    # Tighten whichever SQLite database the configured URL actually uses
    # (installations may keep data in data/pc-service.db, not only base.db).
    url = settings.resolved_database_url
    if url.startswith("sqlite:///"):
        db = Path(url[len("sqlite:///"):])
        if db.exists() and db.is_file():
            os.chmod(db, 0o600)


def run_migrations() -> None:
    from alembic.config import Config
    from alembic import command
    from app.core.config import BASE_DIR
    cfg = Config()
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BASE_DIR))
    command.upgrade(cfg, "head")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # 1-2. config (validates secrets) + dirs/perms
    from app.core.config import settings  # noqa: F401  (fail fast here)
    ensure_dirs()
    # 3. migrations
    run_migrations()
    # The SQLite file may have been created by Alembic just now; tighten it.
    ensure_dirs()
    log.info("migrations ok")
    # 4. serve
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port,
                log_level=settings.log_level.lower(), reload=False)


if __name__ == "__main__":
    main()
