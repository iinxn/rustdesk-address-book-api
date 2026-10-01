"""Server-rendered Web Panel (Jinja2, no SPA). Cookie session via SessionMiddleware."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import AddressBook, AddressBookEntry, Customer, Tag, User
from app.services import ab as ab_svc
from app.services.auth import authenticate, create_user

router = APIRouter(prefix="/panel")
templates = Jinja2Templates(directory="app/web/templates")


def panel_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    return db.get(User, uid) if uid else None


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    u = panel_user(request, db)
    if u is None:
        raise _LoginRedirect()
    return u


class _LoginRedirect(Exception):
    pass


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@router.post("/login")
def login_post(request: Request, username: str = Form(""), password: str = Form(""), db: Session = Depends(get_db)):
    user = authenticate(db, username.strip(), password)
    if user is None:
        return templates.TemplateResponse(request, "login.html", {"error": "Invalid login"}, status_code=401)
    request.session["uid"] = user.id
    return RedirectResponse("/panel/devices", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/panel/login", status_code=303)


def _books(db: Session, user: User) -> list[AddressBook]:
    if user.is_admin:
        return list(db.scalars(select(AddressBook).order_by(AddressBook.name)))
    ids = {b.id for b, _ in ab_svc.shared_profiles(db, user)}
    own = list(db.scalars(select(AddressBook).where(AddressBook.owner_user_id == user.id)))
    ids.update(b.id for b in own)
    if not ids:
        return []
    return list(db.scalars(select(AddressBook).where(AddressBook.id.in_(ids)).order_by(AddressBook.name)))


@router.get("/devices", response_class=HTMLResponse)
def devices_page(
    request: Request, book: str = "", search: str = "", mode: str = "or",
    untagged: bool = False, db: Session = Depends(get_db),
):
    user = require_login(request, db)
    books = _books(db, user)
    if not book and books:
        book = books[0].id
    tags_param = request.query_params.getlist("tag")
    entries: list[dict] = []
    all_tags: list[Tag] = []
    customers = list(db.scalars(select(Customer).order_by(Customer.name)))
    if book:
        all_tags = list(db.scalars(select(Tag).where(Tag.address_book_id == book).order_by(Tag.name)))
        q = select(AddressBookEntry).where(AddressBookEntry.address_book_id == book)
        if search:
            like = f"%{search}%"
            q = q.where(or_(AddressBookEntry.rustdesk_id.like(like), AddressBookEntry.alias.like(like), AddressBookEntry.note.like(like)))
        for e in db.scalars(q.order_by(AddressBookEntry.rustdesk_id)):
            names = set(ab_svc.entry_tag_names(db, e.id))
            if tags_param:
                wanted = set(tags_param)
                if mode == "and":
                    if not (wanted <= names):
                        continue
                elif not (wanted & names):
                    continue
            if untagged and names:
                continue
            entries.append({"id": e.id, "rustdesk_id": e.rustdesk_id, "alias": e.alias, "note": e.note,
                            "tags": sorted(names), "customer_id": e.customer_id})
    return templates.TemplateResponse(request, "devices.html", {
        "user": user, "books": books, "book": book,
        "entries": entries, "all_tags": all_tags, "customers": customers,
        "search": search, "sel_tags": tags_param, "mode": mode, "untagged": untagged,
    })


@router.post("/devices/create")
def device_create(
    request: Request, book: str = Form(""), rustdesk_id: str = Form(""), alias: str = Form(""),
    note: str = Form(""), customer_id: str = Form(""), tags: str = Form(""), password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    b = ab_svc.get_book_for_user(db, user, book)
    if b is None or not ab_svc.can_write(ab_svc.rule_for(db, user, b)):
        return RedirectResponse(f"/panel/devices?book={book}", status_code=303)
    rid = rustdesk_id.strip()
    from app.core.validators import validate_rustdesk_id
    if validate_rustdesk_id(rid) is None and db.scalar(select(AddressBookEntry).where(AddressBookEntry.address_book_id == book, AddressBookEntry.rustdesk_id == rid)) is None:
        from app.core.crypto import encrypt_password
        e = AddressBookEntry(address_book_id=book, rustdesk_id=rid, alias=alias.strip(), note=note.strip(),
                             customer_id=customer_id or None,
                             password_encrypted=encrypt_password(password) if password else None)
        db.add(e)
        db.flush()
        ab_svc.sync_entry_tags(db, e, [t.strip() for t in tags.split(",") if t.strip()])
        db.commit()
    return RedirectResponse(f"/panel/devices?book={book}", status_code=303)


@router.post("/devices/{eid}/delete")
def device_delete(request: Request, eid: str, db: Session = Depends(get_db)):
    user = require_login(request, db)
    e = db.get(AddressBookEntry, eid)
    book_id = e.address_book_id if e else ""
    if e is not None:
        b = ab_svc.get_book_for_user(db, user, e.address_book_id)
        if b is not None and ab_svc.can_write(ab_svc.rule_for(db, user, b)):
            db.delete(e)
            db.commit()
    return RedirectResponse(f"/panel/devices?book={book_id}", status_code=303)


@router.get("/tags", response_class=HTMLResponse)
def tags_page(request: Request, book: str = "", db: Session = Depends(get_db)):
    user = require_login(request, db)
    books = _books(db, user)
    if not book and books:
        book = books[0].id
    tags: list[dict] = []
    if book:
        usage = ab_svc.tag_usage(db, book)
        for t in db.scalars(select(Tag).where(Tag.address_book_id == book).order_by(Tag.name)):
            tags.append({"id": t.id, "name": t.name, "color": t.color, "devices": usage.get(t.id, 0)})
    return templates.TemplateResponse(request, "tags.html", {"user": user, "books": books, "book": book, "tags": tags})


@router.post("/tags/create")
def tag_create(request: Request, book: str = Form(""), name: str = Form(""), color: str = Form("0"), db: Session = Depends(get_db)):
    user = require_login(request, db)
    b = ab_svc.get_book_for_user(db, user, book)
    if b is not None and ab_svc.can_write(ab_svc.rule_for(db, user, b)):
        name = name.strip()
        if name and db.scalar(select(Tag).where(Tag.address_book_id == book, Tag.name == name)) is None:
            try:
                c = int(color, 0)
            except ValueError:
                c = 0
            db.add(Tag(address_book_id=book, name=name, color=c))
            db.commit()
    return RedirectResponse(f"/panel/tags?book={book}", status_code=303)


@router.post("/tags/{tid}/update")
def tag_update(request: Request, tid: str, name: str = Form(""), color: str = Form("0"), db: Session = Depends(get_db)):
    user = require_login(request, db)
    t = db.get(Tag, tid)
    book_id = t.address_book_id if t else ""
    if t is not None:
        b = ab_svc.get_book_for_user(db, user, t.address_book_id)
        if b is not None and ab_svc.can_write(ab_svc.rule_for(db, user, b)):
            try:
                t.color = int(color, 0)
            except ValueError:
                pass
            name = name.strip()
            if name and name != t.name and db.scalar(select(Tag).where(Tag.address_book_id == t.address_book_id, Tag.name == name)) is None:
                t.name = name
            db.commit()
    return RedirectResponse(f"/panel/tags?book={book_id}", status_code=303)


@router.post("/tags/{tid}/delete")
def tag_delete(request: Request, tid: str, db: Session = Depends(get_db)):
    user = require_login(request, db)
    t = db.get(Tag, tid)
    book_id = t.address_book_id if t else ""
    if t is not None:
        b = ab_svc.get_book_for_user(db, user, t.address_book_id)
        if b is not None and ab_svc.can_write(ab_svc.rule_for(db, user, b)):
            db.delete(t)
            db.commit()
    return RedirectResponse(f"/panel/tags?book={book_id}", status_code=303)


@router.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    customers = list(db.scalars(select(Customer).order_by(Customer.name)))
    return templates.TemplateResponse(request, "customers.html", {"user": user, "customers": customers})


@router.post("/customers/create")
def customer_create(request: Request, name: str = Form(""), note: str = Form(""), db: Session = Depends(get_db)):
    require_login(request, db)
    if name.strip():
        db.add(Customer(name=name.strip(), note=note.strip()))
        db.commit()
    return RedirectResponse("/panel/customers", status_code=303)


@router.post("/customers/{cid}/delete")
def customer_delete(request: Request, cid: str, db: Session = Depends(get_db)):
    require_login(request, db)
    c = db.get(Customer, cid)
    if c is not None:
        db.delete(c)
        db.commit()
    return RedirectResponse("/panel/customers", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    if not user.is_admin:
        return RedirectResponse("/panel/devices", status_code=303)
    users = list(db.scalars(select(User).order_by(User.username)))
    return templates.TemplateResponse(request, "users.html", {"user": user, "users": users})


@router.post("/users/create")
def panel_user_create(request: Request, username: str = Form(""), password: str = Form(""), is_admin: bool = Form(False), db: Session = Depends(get_db)):
    admin = require_login(request, db)
    if not admin.is_admin:
        return RedirectResponse("/panel/devices", status_code=303)
    if username.strip() and password and db.scalar(select(User).where(User.username == username.strip())) is None:
        create_user(db, username.strip(), password, bool(is_admin))
    return RedirectResponse("/panel/users", status_code=303)


@router.post("/users/{uid}/delete")
def panel_user_delete(request: Request, uid: str, db: Session = Depends(get_db)):
    admin = require_login(request, db)
    if admin.is_admin:
        u = db.get(User, uid)
        if u is not None and u.id != admin.id:
            db.delete(u)
            db.commit()
    return RedirectResponse("/panel/users", status_code=303)


@router.get("/", include_in_schema=False)
def panel_root():
    return RedirectResponse("/panel/devices", status_code=303)
