# Threat model

Scope: this app on its Debian host + LAN/WAN clients. Out of scope: RustDesk
Client internals, hbbs/hbbr themselves, physical host security.

## Assets

1. Address book data (IDs, aliases, notes, tags, customers).
2. Shared device passwords (Fernet-encrypted at rest, decryptable by the app).
3. User credentials (bcrypt hashes) and API sessions (Bearer tokens).
4. hbbs signing key (`shim-hbbs.key`, operator-provided) — lets whoever holds
   it impersonate the rendezvous server.
5. Availability of API + shim (21116/8000 face the general network).

## Actors

- Anonymous network client (can reach 8000/21116).
- Authenticated non-admin user (own books + explicitly shared books).
- Admin user (all books, user management).
- Local unprivileged OS user (same machine, no service rights).
- Passive network observer (LAN/WAN sniffer).
- Malicious/buggy RustDesk device (heartbeat sender).

## Scenarios and posture

1. **Anonymous API access** → denied 401 everywhere except login,
   login-options, heartbeat (protocol-required), health. Tested.
2. **IDOR (user A → user B objects)** → every endpoint resolves the book via
   ownership/permission (`get_book_for_user`) and enforces read/write/full
   rules. Tested (read/update/tags/peers across users).
3. **ID substitution in bodies** → server looks up objects by (book, id) pairs
   it resolved itself; `owner_user_id`/role fields are never taken from input
   (mass-assignment test). Tested.
4. **SQL injection** → ORM + bound params everywhere; `sort` whitelisted;
   `search` is a bound LIKE. Tested with hostile payloads.
5. **XSS session theft** → API uses Bearer in memory (JS), not cookies; React
   escapes by default, no `dangerouslySetInnerHTML`; Jinja autoescape on.
   Stealing `localStorage` still needs an XSS sink — none found (audit).
6. **CSRF** → API: N/A (no cookie auth). Legacy panel: cookie + SameSite=Lax
   (explicit); cross-site POSTs blocked by browsers. Accepted residual: no
   per-form CSRF tokens on the legacy panel (modern SPA is the primary UI).
7. **Local file read (base.db, keys)** → `data/` 0700, `base.db` 0600,
   backups 0600, key files must be 0600 (operator duty, checked at startup
   for data dir; key readability required, writability not needed).
8. **Command execution via shim** → no shell/subprocess in shim or app;
   fixed upstream (config, not client input) → no SSRF/command surface.
   Tested (no `shell=True` anywhere; bandit clean of Highs).
9. **Forged hbbs settings** → our API returns no server/relay/key fields
   (deny-list test); client network config comes only from its own settings.
10. **DoS** → body cap 5MB/413; login 20/min/IP, heartbeat 300/min/IP (429);
    shim: 2MB frame cap, 60s read timeouts, 200 conns, 30/min/IP, bounded
    restarts. Residual: unauthenticated heartbeat can skew presence
    (by client protocol design — no credentials exist for devices);
    mitigated to rate-limited noise, documented.

## Accepted risks (not fixed)

- HTTP (no TLS) between client and API on untrusted networks exposes
  passwords/tokens — operator must terminate TLS (Caddy example in
  `config/`, see `deployment-debian.md`). The app never sees cleartext
  behind a proxy and trusts no `X-Forwarded-*` headers.
- bcrypt (not Argon2id): appropriate, peer-reviewed, slow-hash (~300ms);
  migration would invalidate stored hashes for zero practical gain.
- Legacy `/panel` has no per-form CSRF tokens (SameSite=Lax only).
- Customers are global to all authenticated users (no per-user isolation).
