"""Engine, session factory and the FastAPI `get_db` dependency.

SQLite settings (applied to every new connection):

* `foreign_keys=ON` — cascades and FK checks are off by default in SQLite;
* `busy_timeout=5000` — wait for a competing writer instead of failing;
* `journal_mode=WAL` — readers never block on the writer and a commit is one
  append to the WAL instead of a rollback-journal round trip. The mode is
  stored in the database file; `-wal`/`-shm` files appear next to it and are
  part of the database (`python -m app.cli backup` handles them).
  `synchronous` stays at SQLite's default (FULL): durability of audit rows
  and edits is not traded for speed.
"""
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

url = settings.resolved_database_url
is_sqlite = url.startswith("sqlite")
connect_args: dict = {"check_same_thread": False, "timeout": 5} if is_sqlite else {}


def _sqlite_pragmas(dbapi_conn, _rec) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    if ":memory:" not in url:
        cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
if is_sqlite:
    event.listen(engine, "connect", _sqlite_pragmas)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def check_ready() -> None:
    """Raise if the database is not reachable (used by /health/ready)."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
