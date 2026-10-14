from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

url = settings.resolved_database_url
connect_args: dict = {}
if url.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 5}


def _sqlite_pragmas(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
if url.startswith("sqlite"):
    event.listen(engine, "connect", _sqlite_pragmas)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def check_ready() -> None:
    """Raise if the database is not reachable (used by /health/ready)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
