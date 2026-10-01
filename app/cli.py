"""CLI: create-admin, gen-key."""
import argparse
import getpass

from cryptography.fernet import Fernet


def cmd_create_admin():
    from app.db.session import SessionLocal
    from app.services.auth import create_user
    from sqlalchemy import select
    from app.models.models import User

    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="")
    ap.add_argument("--admin", action="store_true", default=True)
    args = ap.parse_args()
    username = args.username or input("username: ").strip()
    password = getpass.getpass("password: ")
    if not username or not password:
        raise SystemExit("username/password required")
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("user already exists")
        create_user(db, username, password, is_admin=True)
        print(f"admin '{username}' created")
    finally:
        db.close()


def cmd_gen_key():
    print(Fernet.generate_key().decode())


def cmd_dump_book(book_id: str):
    """Print redacted peer payloads exactly as /api/ab/peers would return them
    (password/hash values replaced with presence flags). Safe to paste into tickets."""
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
        import json
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


if __name__ == "__main__":
    import sys
    cmd, rest = "create-admin", sys.argv[1:]
    if rest and rest[0] in ("create-admin", "gen-key", "dump-book"):
        cmd, rest = rest[0], rest[1:]
    if cmd == "gen-key":
        cmd_gen_key()
    elif cmd == "dump-book":
        if not rest:
            raise SystemExit("usage: python -m app.cli dump-book <book-id>")
        cmd_dump_book(rest[0])
    else:
        sys.argv = [sys.argv[0], *rest]
        cmd_create_admin()
