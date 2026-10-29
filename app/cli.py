"""CLI: create-admin, gen-key, dump-book, backup. Lazy imports: gen-key and
backup work without a configured environment; db commands need settings."""
import argparse
import getpass


def cmd_gen_key():
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())


def cmd_create_admin(args):
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.models import User
    from app.services.auth import DISPLAY_NAME_MAX, clean_display_name, create_user
    username = args.username or input("username: ").strip()
    password = getpass.getpass("password: ")
    if not username or not password:
        raise SystemExit("username/password required")
    if len(clean_display_name(args.display_name)) > DISPLAY_NAME_MAX:
        raise SystemExit(f"display-name too long (max {DISPLAY_NAME_MAX})")
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("user already exists")
        create_user(db, username, password, is_admin=True, display_name=args.display_name)
        print(f"admin '{username}' created")
    finally:
        db.close()


def cmd_dump_book(book_id: str):
    import json
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models.models import AddressBook, AddressBookEntry
    from app.services import ab as ab_svc
    db = SessionLocal()
    try:
        book = db.get(AddressBook, book_id)
        if book is None:
            raise SystemExit("no such book")
        entries = db.scalars(select(AddressBookEntry).where(
            AddressBookEntry.address_book_id == book.id).order_by(AddressBookEntry.rustdesk_id)).all()
        out = []
        for e in entries:
            d = ab_svc.peer_out(db, e, book)
            if "password" in d:
                d["password"] = "<set>" if d["password"] else "<empty>"
            if "hash" in d:
                d["hash"] = "<set>" if d["hash"] else "<empty>"
            out.append(d)
        print(json.dumps({"book": book.name, "type": book.type, "total": len(out), "data": out},
                         ensure_ascii=False, indent=1))
    finally:
        db.close()


def cmd_backup(dest: str = ""):
    from app.core.config import DATA_DIR
    from app.db.session import engine
    import sqlite3
    from datetime import datetime, timezone
    from pathlib import Path
    url = str(engine.url)
    if not url.startswith("sqlite"):
        raise SystemExit("backup command supports sqlite only")
    src = Path(url.split("sqlite:///", 1)[1])
    out = Path(dest) if dest else DATA_DIR / f"backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(src), timeout=30) as s, sqlite3.connect(str(out)) as d:
        s.backup(d)
    with sqlite3.connect(str(out)) as d:
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
    out.chmod(0o600)
    if ok != "ok":
        raise SystemExit(f"backup verification failed: {ok}")
    print(f"backup ok: {out} (integrity ok)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("create-admin")
    c.add_argument("--username", default="")
    c.add_argument("--display-name", default="")
    sub.add_parser("gen-key")
    d = sub.add_parser("dump-book")
    d.add_argument("book_id")
    b = sub.add_parser("backup")
    b.add_argument("--dest", default="")
    args = ap.parse_args(argv)
    if args.cmd == "gen-key":
        cmd_gen_key()
    elif args.cmd == "create-admin":
        cmd_create_admin(args)
    elif args.cmd == "dump-book":
        cmd_dump_book(args.book_id)
    elif args.cmd == "backup":
        cmd_backup(args.dest)
    else:
        ap.print_help()
        raise SystemExit(2)


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
