import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("DEVICE_SECRET", "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=")

engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})


def _pragmas(dbapi_conn, _rec):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


event.listen(engine, "connect", _pragmas)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
