#!/usr/bin/env python3

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request

REDACTED = "<set>"


class DumpError(Exception):
    pass


def call(base, method, path, body=None, token=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if method == "POST" and data is None:
        headers["Content-Length"] = "0"
        data = b""
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:200]
        except Exception:
            detail = ""
        raise DumpError(f"HTTP {e.code} on {method} {path}: {detail}")
    except Exception as e:
        raise DumpError(f"request failed on {method} {path}: {e}")


def paged(base, path, token, timeout, key="data"):
    out, page, total = [], 1, 0
    while True:
        sep = "&" if "?" in path else "?"
        s, d = call(base, "POST", f"{path}{sep}current={page}&pageSize=100",
                    None, token, timeout)
        if s == 404:
            raise DumpError(f"endpoint not supported by server: {path}")
        if s != 200 or not isinstance(d, dict):
            raise DumpError(f"unexpected response {s} on {path}")
        total = d.get("total", 0)
        out.extend(d.get(key, []) or [])
        if page * 100 >= total or not d.get(key):
            break
        page += 1
    return out, total


def redact_peers(peers, enabled):
    if not enabled:
        return peers
    for p in peers:
        if p.get("password"):
            p["password"] = REDACTED
        if p.get("hash"):
            p["hash"] = REDACTED if p["hash"] else ""
    return peers


# --------------------------------------------------------------------------- #
# Dump
# --------------------------------------------------------------------------- #

def run_dump(a):
    base = a.base_url.rstrip("/")
    errors = []
    result = {"source": base, "user": a.username, "settings": None,
              "personal": None, "shared": []}

    try:
        if a.token:
            token = a.token
            print("using provided token")
        else:
            pw = a.password or getpass.getpass("password: ")
            s, d = call(base, "POST", "/api/login",
                        {"username": a.username, "password": pw, "type": "account"},
                        timeout=a.timeout)
            if s != 200 or not d or "access_token" not in d:
                raise DumpError(f"login failed: HTTP {s} {d}")
            token = d["access_token"]
            print(f"login ok, user={d.get('user', {}).get('name')}")

        try:
            s, d = call(base, "POST", "/api/ab/settings", None, token, a.timeout)
            result["settings"] = d if s == 200 else None
        except DumpError as e:
            errors.append(str(e))

        try:
            s, d = call(base, "POST", "/api/ab/personal", None, token, a.timeout)
        except DumpError as e:
            errors.append(str(e))
            d = None
        personal_guid = (d or {}).get("guid")
        if personal_guid:
            try:
                peers, total = paged(base, f"/api/ab/peers?ab={personal_guid}",
                                     token, a.timeout)
                _, tags = call(base, "POST", f"/api/ab/tags/{personal_guid}",
                               None, token, a.timeout)
                result["personal"] = {"guid": personal_guid, "total": total,
                                      "peers": redact_peers(peers, a.redact_passwords),
                                      "tags": tags}
                print(f"personal: {total} peers, {len(tags or [])} tags")
            except DumpError as e:
                errors.append(str(e))
        else:
            print("no personal book (legacy server?)")

        try:
            profiles, _ = paged(base, "/api/ab/shared/profiles", token, a.timeout)
        except DumpError as e:
            errors.append(str(e))
            profiles = []
        for p in profiles:
            g = p.get("guid")
            try:
                peers, total = paged(base, f"/api/ab/peers?ab={g}", token, a.timeout)
                _, tags = call(base, "POST", f"/api/ab/tags/{g}", None, token, a.timeout)
                result["shared"].append({"profile": p, "total": total,
                                         "peers": redact_peers(peers, a.redact_passwords),
                                         "tags": tags})
                print(f"shared {p.get('name')}: {total} peers, {len(tags or [])} tags")
            except DumpError as e:
                errors.append(str(e))
    except DumpError as e:
        errors.append(str(e))

    n_peers = (result["personal"]["total"] if result["personal"] else 0) + \
        sum(s.get("total", 0) for s in result["shared"])
    print(f"total peers collected: {n_peers}")
    if errors:
        result["_errors"] = errors
        print("ERRORS encountered (partial dump saved):")
        for e in errors:
            print(f"  - {e}")

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"written to {a.out}")
    if a.to_db:
        if errors and not a.allow_partial:
            print("dump had errors; refusing --to-db (pass --allow-partial to import anyway)",
                  file=sys.stderr)
            return 1
        return import_dump(result, a)
    return 1 if errors else 0


# --------------------------------------------------------------------------- #
# Import (writes into this backend's database; needs the backend venv)
# --------------------------------------------------------------------------- #

def _redact_url(url: str) -> str:
    import re
    return re.sub(r"://[^/@]*@", "://***@", url)


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def _tag_pairs(raw):
    """Normalize a tag list to [(name, color)] from [{name,color,name:...}] or [name]."""
    out = []
    for t in raw or []:
        color = 0
        if isinstance(t, dict):
            name = str(t.get("name", "")).strip()
            try:
                color = int(t.get("color") or 0)
            except (TypeError, ValueError):
                color = 0
        else:
            name = str(t).strip()
        if name:
            out.append((name, color))
    return out


def _tag_names(raw):
    out = []
    for t in raw or []:
        if isinstance(t, dict):
            t = t.get("name")
        if t is None:
            continue
        t = str(t).strip()
        if t and t not in out:
            out.append(t)
    return out


def _import_book(db, book, peers, tags_raw, is_personal, a, stats, invalid,
                 select, encrypt_password, validate_rustdesk_id, ab_svc,
                 Tag, AddressBookEntry):
    # Tags first, so their colors survive (sync_entry_tags would create them at 0).
    existing_tags = {t.name: t for t in db.scalars(
        select(Tag).where(Tag.address_book_id == book.id))}
    for tname, color in _tag_pairs(tags_raw):
        t = existing_tags.get(tname)
        if t is None:
            t = Tag(address_book_id=book.id, name=tname, color=color)
            db.add(t)
            db.flush()
            existing_tags[tname] = t
        elif t.color != color:
            t.color = color

    existing = {e.rustdesk_id: e for e in db.scalars(
        select(AddressBookEntry).where(AddressBookEntry.address_book_id == book.id))}

    for p in peers:
        if not isinstance(p, dict):
            stats["skipped"] += 1
            continue
        rid = str(p.get("id", "")).strip()
        if not rid:
            stats["skipped"] += 1
            continue
        if validate_rustdesk_id(rid) is not None and not a.allow_invalid_ids:
            invalid.append((book.name, rid))
            continue

        e = existing.get(rid)
        if e is not None:
            if a.on_conflict == "skip":
                stats["skipped"] += 1
                continue
            if a.on_conflict == "fail":
                raise RuntimeError(f"device {rid!r} already exists in {book.name!r}")
            stats["updated"] += 1
        else:
            e = AddressBookEntry(address_book_id=book.id, rustdesk_id=rid)
            db.add(e)
            db.flush()
            existing[rid] = e
            stats["created"] += 1

        e.alias = _s(p.get("alias"))
        e.note = _s(p.get("note"))
        e.username = _s(p.get("username"))
        e.hostname = _s(p.get("hostname"))
        e.platform = _s(p.get("platform"))
        if is_personal:
            h = p.get("hash")
            if isinstance(h, str) and h:
                if h == REDACTED:
                    stats["redacted"] += 1
                else:
                    e.hash_value = h
        else:
            pw = p.get("password")
            if isinstance(pw, str) and pw:
                if pw == REDACTED:
                    stats["redacted"] += 1
                else:
                    e.password_encrypted = encrypt_password(pw)
        ab_svc.sync_entry_tags(db, e, _tag_names(p.get("tags")))


def run_import(a):
    try:
        with open(a.import_file, encoding="utf-8") as f:
            dump = json.load(f)
    except Exception as e:
        print(f"ERROR: cannot read {a.import_file}: {e}", file=sys.stderr)
        return 2
    return import_dump(dump, a)


def import_dump(dump, a):
    import os
    import secrets as _secrets

    # Make `import app...` work when invoked as `python scripts/dump_ab.py`.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from sqlalchemy import inspect, select
        from app.core.config import settings
        from app.core.crypto import encrypt_password
        from app.core.validators import validate_rustdesk_id
        from app.db.session import SessionLocal
        from app.models.models import (
            AddressBook,
            AddressBookEntry,
            AddressBookPermission,
            Tag,
            User,
        )
        from app.services import ab as ab_svc
    except Exception as e:
        print(f"ERROR: cannot import backend modules: {e}\n"
              "Run from the repository root with its virtualenv, e.g.\n"
              "  .venv/bin/python scripts/dump_ab.py --import pro-ab.json --user NAME --dry-run",
              file=sys.stderr)
        return 2

    name = (a.user or a.username or "").strip()
    if not name:
        print("ERROR: --user (local username) is required for import", file=sys.stderr)
        return 2
    if not isinstance(dump, dict):
        print("ERROR: dump root is not a JSON object", file=sys.stderr)
        return 2
    if dump.get("_errors"):
        print(f"WARNING: source dump is partial ({len(dump['_errors'])} recorded errors)")

    print(f"target DB: {_redact_url(settings.resolved_database_url)}")
    db = SessionLocal()
    if not inspect(db.get_bind()).has_table("users"):
        print("ERROR: database has no schema (users table missing). "
              "Start the app once or run `alembic upgrade head` first.", file=sys.stderr)
        db.close()
        return 2
    stats = {"created": 0, "updated": 0, "skipped": 0, "redacted": 0, "books": 0}
    invalid: list[tuple[str, str]] = []
    try:
        user = db.scalar(select(User).where(User.username == name))
        if user is None:
            if not a.create_user:
                print(f"ERROR: local user {name!r} does not exist "
                      f"(pass --create-user to create it)", file=sys.stderr)
                return 2
            from app.core.security import hash_password
            pw = a.password or _secrets.token_urlsafe(12)
            user = User(username=name, password_hash=hash_password(pw),
                        is_admin=bool(a.admin))
            db.add(user)
            db.flush()
            db.add(AddressBook(name="My address book", type="personal",
                               owner_user_id=user.id))
            db.flush()
            if a.password:
                print(f"created local user {name!r}")
            else:
                print(f"created local user {name!r} with password: {pw}")
        else:
            print(f"target user: {name} (id={user.id})")

        owner = user
        if a.owner and a.owner != name:
            owner = db.scalar(select(User).where(User.username == a.owner))
            if owner is None:
                print(f"ERROR: --owner user {a.owner!r} does not exist", file=sys.stderr)
                return 2

        if not a.no_personal and dump.get("personal"):
            personal = dump["personal"]
            book = ab_svc.personal_book(db, user)
            if book is None:
                book = AddressBook(name="My address book", type="personal",
                                   owner_user_id=user.id)
                db.add(book)
                db.flush()
            print(f"personal book: {book.name} ({book.id})")
            _import_book(db, book, personal.get("peers") or [],
                         personal.get("tags") or [], True, a, stats, invalid,
                         select, encrypt_password, validate_rustdesk_id,
                         ab_svc, Tag, AddressBookEntry)
            stats["books"] += 1

        if not a.no_shared:
            for entry in dump.get("shared") or []:
                prof = entry.get("profile") or {}
                bname = str(prof.get("name") or "").strip() or "Shared book"
                try:
                    rule = int(prof.get("rule") or 1)
                except (TypeError, ValueError):
                    rule = 1
                if rule not in (1, 2, 3):
                    rule = 1
                if owner is user:
                    rule = 3  # the owner of a shared book gets full control here
                book = db.scalar(select(AddressBook).where(
                    AddressBook.type == "shared",
                    AddressBook.owner_user_id == owner.id,
                    AddressBook.name == bname))
                if book is None:
                    book = AddressBook(name=bname, type="shared", owner_user_id=owner.id)
                    db.add(book)
                    db.flush()
                perm = db.scalar(select(AddressBookPermission).where(
                    AddressBookPermission.address_book_id == book.id,
                    AddressBookPermission.user_id == user.id))
                if perm is None:
                    db.add(AddressBookPermission(address_book_id=book.id,
                                                 user_id=user.id, rule=rule))
                else:
                    perm.rule = rule
                print(f"shared book: {bname} ({book.id}) rule={rule} owner={owner.username}")
                _import_book(db, book, entry.get("peers") or [],
                             entry.get("tags") or [], False, a, stats, invalid,
                             select, encrypt_password, validate_rustdesk_id,
                             ab_svc, Tag, AddressBookEntry)
                stats["books"] += 1

        if invalid:
            print("skipped invalid device ids (use --allow-invalid-ids to include them):")
            for b, rid in invalid[:50]:
                print(f"  - {b}: {rid!r}")
            if len(invalid) > 50:
                print(f"  ... and {len(invalid) - 50} more")

        if a.dry_run:
            db.rollback()
            print("[dry-run] rolled back; nothing written")
        else:
            db.commit()
        print(f"done: books={stats['books']} created={stats['created']} "
              f"updated={stats['updated']} skipped={stats['skipped']} "
              f"redacted-secrets={stats['redacted']}")
        return 0
    except Exception as e:
        db.rollback()
        print(f"ERROR: import failed, rolled back: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(
        description="Dump a RustDesk address book, or import a dump into this backend's DB.")
    # dump (Pro login / source)
    ap.add_argument("--base-url", default="", help="dump: RustDesk server base URL")
    ap.add_argument("--username", default="", help="dump: source account username")
    ap.add_argument("--password", default="",
                    help="dump: source password (else prompted); "
                         "import: password for --create-user (else generated)")
    ap.add_argument("--token", default="", help="dump: skip login, use an access_token")
    ap.add_argument("--out", default="", help="dump: output JSON file")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--redact-passwords", action="store_true",
                    help="dump: replace password/hash values with <set>")
    # import (into this backend's database)
    ap.add_argument("--import", dest="import_file", default="", metavar="FILE",
                    help="import a dump JSON into this backend's database")
    ap.add_argument("--to-db", action="store_true",
                    help="after dumping, import the result straight into the database")
    ap.add_argument("--allow-partial", action="store_true",
                    help="allow --to-db even if the dump recorded errors")
    ap.add_argument("--user", default="", help="import: local username to receive the data")
    ap.add_argument("--create-user", action="store_true",
                    help="import: create the local user if it does not exist")
    ap.add_argument("--admin", action="store_true",
                    help="import: make a newly created user an admin")
    ap.add_argument("--owner", default="",
                    help="import: local owner of shared books (default: --user)")
    ap.add_argument("--on-conflict", choices=("skip", "update", "fail"), default="skip",
                    help="import: what to do when a device already exists (default: skip)")
    ap.add_argument("--dry-run", action="store_true",
                    help="import: do everything, then roll back")
    ap.add_argument("--no-personal", action="store_true", help="import: skip the personal book")
    ap.add_argument("--no-shared", action="store_true", help="import: skip shared books")
    ap.add_argument("--allow-invalid-ids", action="store_true",
                    help="import: keep ids our validator rejects (see app/core/validators.py)")
    a = ap.parse_args()

    if a.import_file:
        return run_import(a)
    if not (a.base_url and a.username and a.out):
        ap.error("dump mode needs --base-url, --username and --out "
                 "(or use --import FILE for import mode)")
    return run_dump(a)


if __name__ == "__main__":
    sys.exit(main())
