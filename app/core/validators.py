"""Validation helpers for connection-path safety.

Why rustdesk_id is validated: the client's LoginConfigHandler treats an ID
containing "@" as `id@server?key=...` and silently redirects the transport to
another server/key, and a trailing "/r" forces relay (client.rs:1811-1846).
An Address Book entry with such an ID would connect somewhere unexpected
while the same bare numeric ID typed manually works fine. So we accept only
plain device IDs.
"""
import re

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_rustdesk_id(rid: str) -> str | None:
    """Return error message if the ID is unsafe/invalid, else None."""
    v = (rid or "").strip()
    if not v:
        return "missing id"
    if "@" in v or "/" in v or "\\" in v or "?" in v or "&" in v or "=" in v:
        return "invalid id: server-redirect characters are not allowed"
    if any(c.isspace() for c in v):
        return "invalid id: whitespace is not allowed"
    if not _ID_RE.match(v):
        return "invalid id"
    return None
