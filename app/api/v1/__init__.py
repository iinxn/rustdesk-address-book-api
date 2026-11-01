"""Internal panel JSON API (`/api/v1/*`). Bearer auth, same tokens as `/api/login`.

Extended shapes (tag objects, presence, counts) live ONLY here; the
RustDesk-compatible `/api/ab/*` is untouched. Errors are `{"detail": msg}`.

    books.py    address books, entries, tags, bulk operations
    devices.py  discovered devices and merged device cards
    users.py    panel users and the caller's profile
    audit.py    admin-only audit history
"""
from fastapi import APIRouter

from app.api.v1 import audit, books, devices, users

router = APIRouter()
for module in (books, devices, users, audit):
    router.include_router(module.router)
