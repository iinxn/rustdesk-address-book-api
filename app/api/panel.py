"""Server-rendered legacy panel (`/panel/*`, Jinja2).

The signed cookie carries only the id of a server-side `sessions` row
(`sid`), never the user id or a Bearer token, so logout and password changes
revoke it at once (DEC-019). Access rules are the same as for the APIs:
every book is resolved through `ab.book_access()`, including the `?book=`
selector of the list pages.
"""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.core.config import BASE_DIR
from app.core.middleware import client_ip
from app.core.security import password_error
from app.db.session import get_db
from app.models.models import AddressBook, AddressBookEntry, Tag, User
from app.services import ab as ab_svc
from app.services import audit as audit_svc
from app.services.auth import AuthBusy, authenticate, create_session, create_user, panel_session

router = APIRouter(prefix="/panel")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "web" / "templates"))

SOURCE = "legacy_panel"


class LoginRedirect(Exception):
    """Raised by `require_login`; `app.main` turns it into a 303 to the login page."""


def panel_user(request: Request, db: Session) -> User | None:
    found = panel_session(db, request.session.get("sid"))
    if found is None:
        # SEC-001: a disabled/deleted user loses panel access at once; the
        # signed cookie is cleared so the stale session does not linger.
        request.session.clear()
        return None
    return found[1]


def require_login(request: Request, db: Session) -> User:
    user = panel_user(request, db)
    if user is None:
        raise LoginRedirect()
    return user


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _record(db: Session, user: User, category: str, event_type: str, *,
            target_type: str, target_id: str, **details) -> None:
    audit_svc.record(db, category=category, event_type=event_type, actor=user,
                     target_type=target_type, target_id=target_id,
                     details={**details, "source": SOURCE})


def _auth_event(request: Request, event_type: str, status: int, method: str, route: str,
                user: User | None = None, **extra) -> None:
    audit_svc.write_event(category="auth", event_type=event_type, source_ip=client_ip(request),
                          destination="panel", http_method=method, route=route,
                          status_code=status, actor=user, **extra)


def _selected_book(db: Session, user: User, requested: str) -> tuple[list[AddressBook], str]:
    """Visible books and the selected one; an inaccessible `?book=` selects nothing."""
    books = [a.book for a in ab_svc.visible_books(db, user)]
    if not requested:
        return books, books[0].id if books else ""
    return books, requested if any(b.id == requested for b in books) else ""


# --- login -------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@router.post("/login")
def login_post(request: Request, username: str = Form(""), password: str = Form(""),
               db: Session = Depends(get_db)):
    try:
        user = authenticate(db, username.strip(), password)
    except AuthBusy:
        audit_svc.note_rate_limited("/panel/login", client_ip(request), 5, audit_it=True)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Too many login attempts, retry later"},
            status_code=429, headers={"Retry-After": "5"},
        )
    if user is None:
        _auth_event(request, "auth.login_failed", 401, "POST", "/panel/login",
                    outcome="denied", actor_type="anonymous", details={"username": username})
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid login"},
                                          status_code=401)
    # Fresh cookie content on every login (no session fixation).
    request.session.clear()
    request.session["sid"] = create_session(db, user).id
    _auth_event(request, "auth.login", 303, "POST", "/panel/login", user=user, outcome="success")
    return _redirect("/panel/devices")


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    found = panel_session(db, request.session.get("sid"))
    request.session.clear()
    if found is not None:
        session, user = found
        db.delete(session)
        db.commit()
        _auth_event(request, "auth.logout", 303, "GET", "/panel/logout", user=user, outcome="success")
    return _redirect("/panel/login")


# --- devices -----------------------------------------------------------------

@router.get("/devices", response_class=HTMLResponse)
def devices_page(request: Request, book: str = "", search: str = "", mode: str = "or",
                 untagged: bool = False, db: Session = Depends(get_db)):
    user = require_login(request, db)
    books, book = _selected_book(db, user, book)
    wanted = set(request.query_params.getlist("tag"))
    entries: list[dict] = []
    all_tags: list[Tag] = []
    if book:
        all_tags = list(db.scalars(select(Tag).where(Tag.address_book_id == book).order_by(Tag.name)))
        q = select(AddressBookEntry).where(AddressBookEntry.address_book_id == book)
        if search:
            like = f"%{search}%"
            q = q.where(or_(AddressBookEntry.rustdesk_id.like(like), AddressBookEntry.alias.like(like),
                            AddressBookEntry.note.like(like)))
        rows = list(db.scalars(q.order_by(AddressBookEntry.rustdesk_id)))
        tags = ab_svc.tags_by_entry(db, entry_ids=[e.id for e in rows])
        for e in rows:
            names = {t.name for t in tags.get(e.id, [])}
            if wanted and not (wanted <= names if mode == "and" else wanted & names):
                continue
            if untagged and names:
                continue
            entries.append({"id": e.id, "rustdesk_id": e.rustdesk_id, "alias": e.alias,
                            "note": e.note, "tags": sorted(names)})
    return templates.TemplateResponse(request, "devices.html", {
        "user": user, "books": books, "book": book,
        "entries": entries, "all_tags": all_tags,
        "search": search, "sel_tags": list(wanted), "mode": mode, "untagged": untagged,
    })


@router.post("/devices/create")
def device_create(
    request: Request, book: str = Form(""), rustdesk_id: str = Form(""), alias: str = Form(""),
    note: str = Form(""), tags: str = Form(""), password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    access = ab_svc.writable_book(db, user, book)
    if access is not None:
        try:
            e = ab_svc.add_entry(db, access.book, rustdesk_id, alias=alias.strip(),
                                 note=note.strip(), password=password,
                                 tags=[t for t in tags.split(",") if t.strip()])
        except ab_svc.EntryError:
            pass  # form contract: invalid/duplicate input just re-renders the list
        else:
            _record(db, user, "data", "entry.create", target_type="device", target_id=e.rustdesk_id,
                    entry_id=e.id, book_id=book, alias=e.alias, password_set=bool(password))
            db.commit()
    return _redirect(f"/panel/devices?book={book}")


@router.post("/devices/{eid}/delete")
def device_delete(request: Request, eid: str, db: Session = Depends(get_db)):
    user = require_login(request, db)
    e = db.get(AddressBookEntry, eid)
    book_id = e.address_book_id if e else ""
    if e is not None and ab_svc.writable_book(db, user, e.address_book_id) is not None:
        _record(db, user, "data", "entry.delete", target_type="device", target_id=e.rustdesk_id,
                entry_id=e.id, book_id=e.address_book_id, alias=e.alias)
        db.delete(e)
        db.commit()
    return _redirect(f"/panel/devices?book={book_id}")


# --- tags --------------------------------------------------------------------

def _tag_name_free(db: Session, book_id: str, name: str) -> bool:
    return db.scalar(select(Tag.id).where(Tag.address_book_id == book_id, Tag.name == name)) is None


@router.get("/tags", response_class=HTMLResponse)
def tags_page(request: Request, book: str = "", db: Session = Depends(get_db)):
    user = require_login(request, db)
    books, book = _selected_book(db, user, book)
    tags: list[dict] = []
    if book:
        usage = ab_svc.tag_usage(db, book)
        tags = [{"id": t.id, "name": t.name, "color": t.color, "devices": usage.get(t.id, 0)}
                for t in db.scalars(select(Tag).where(Tag.address_book_id == book).order_by(Tag.name))]
    return templates.TemplateResponse(request, "tags.html",
                                      {"user": user, "books": books, "book": book, "tags": tags})


@router.post("/tags/create")
def tag_create(request: Request, book: str = Form(""), name: str = Form(""), color: str = Form("0"),
               db: Session = Depends(get_db)):
    user = require_login(request, db)
    name = name.strip()
    if ab_svc.writable_book(db, user, book) is not None and name and _tag_name_free(db, book, name):
        t = Tag(address_book_id=book, name=name, color=ab_svc.parse_color(color) or 0)
        db.add(t)
        db.flush()
        _record(db, user, "data", "tag.create", target_type="tag", target_id=t.id,
                book_id=book, name=t.name, color=t.color)
        db.commit()
    return _redirect(f"/panel/tags?book={book}")


@router.post("/tags/{tid}/update")
def tag_update(request: Request, tid: str, name: str = Form(""), color: str = Form("0"),
               db: Session = Depends(get_db)):
    user = require_login(request, db)
    t = db.get(Tag, tid)
    book_id = t.address_book_id if t else ""
    if t is not None and ab_svc.writable_book(db, user, t.address_book_id) is not None:
        old = {"name": t.name, "color": str(t.color)}
        new_color = ab_svc.parse_color(color)
        if new_color is not None:  # an invalid colour keeps the old one
            t.color = new_color
        name = name.strip()
        if name and name != t.name and _tag_name_free(db, t.address_book_id, name):
            t.name = name
        _record(db, user, "data", "tag.update", target_type="tag", target_id=t.id,
                book_id=t.address_book_id,
                fields=audit_svc.diff_fields(old, {"name": t.name, "color": str(t.color)}))
        db.commit()
    return _redirect(f"/panel/tags?book={book_id}")


@router.post("/tags/{tid}/delete")
def tag_delete(request: Request, tid: str, db: Session = Depends(get_db)):
    user = require_login(request, db)
    t = db.get(Tag, tid)
    book_id = t.address_book_id if t else ""
    if t is not None and ab_svc.writable_book(db, user, t.address_book_id) is not None:
        _record(db, user, "data", "tag.delete", target_type="tag", target_id=t.id,
                book_id=t.address_book_id, name=t.name)
        db.delete(t)
        db.commit()
    return _redirect(f"/panel/tags?book={book_id}")


# --- users -------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if not user.is_admin:
        return _redirect("/panel/devices")
    users = list(db.scalars(select(User).order_by(User.username)))
    return templates.TemplateResponse(request, "users.html", {"user": user, "users": users})


@router.post("/users/create")
def panel_user_create(request: Request, username: str = Form(""), password: str = Form(""),
                      is_admin: bool = Form(False), db: Session = Depends(get_db)):
    admin = require_login(request, db)
    if not admin.is_admin:
        return _redirect("/panel/devices")
    username = username.strip()
    if (username and password_error(password) is None
            and db.scalar(select(User.id).where(User.username == username)) is None):
        u = create_user(db, username, password, bool(is_admin), commit=False)
        _record(db, admin, "security", "user.create", target_type="user", target_id=u.id,
                username=u.username, is_admin=u.is_admin)
        db.commit()
    return _redirect("/panel/users")


@router.post("/users/{uid}/delete")
def panel_user_delete(request: Request, uid: str, db: Session = Depends(get_db)):
    admin = require_login(request, db)
    if admin.is_admin:
        u = db.get(User, uid)
        if u is not None and u.id != admin.id:
            _record(db, admin, "security", "user.delete", target_type="user", target_id=u.id,
                    username=u.username)
            db.delete(u)
            db.commit()
    return _redirect("/panel/users")


@router.get("/", include_in_schema=False)
def panel_root():
    return _redirect("/panel/devices")
