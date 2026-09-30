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


if __name__ == "__main__":
    import sys
    cmd, rest = "create-admin", sys.argv[1:]
    if rest and rest[0] in ("create-admin", "gen-key"):
        cmd, rest = rest[0], rest[1:]
    if cmd == "gen-key":
        cmd_gen_key()
    else:
        sys.argv = [sys.argv[0], *rest]
        cmd_create_admin()
