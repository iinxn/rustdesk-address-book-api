# Architecture

Single application (`python -m app`) combining three components that share
one SQLite database (`data/base.db`).

```text
                        ┌────────────────────────────┐
                        │ RustDesk Client (unchanged)│
                        └──────┬─────────┬───────────┘
                               │         │ rendezvous TCP 21116
                    HTTPS API   │         ▼
                               │   ┌─────────────┐     ┌──────────┐
                               │   │ KX shim     │────▶│ hbbs     │
                               ▼   │ :21116      │     │ (remote) │
                     ┌──────────────────────┐     └──────────┘
                     │ FastAPI (app/)       │
                     │  /api/* RustDesk     │
                     │  /api/v1/* panel API │
                     │  /panel/* legacy UI  │
                     │  /app/* React SPA    │
                     └──────────┬───────────┘
                                │ SQLAlchemy 2.x
                                ▼
                     ┌──────────────────────┐
                     │ SQLite data/base.db  │
                     │ (Alembic migrations) │
                     └──────────────────────┘
```

## Layout

- `app/main.py` — FastAPI app, lifespan (shim supervisor), health endpoints.
- `app/__main__.py` — startup: config check → dirs/perms → `alembic upgrade head` → uvicorn.
- `app/api/` — `rustdesk.py` (client contract, untouched shapes), `webapi.py`
  (panel JSON), `panel.py` (legacy Jinja UI), `deps.py` (Bearer auth).
- `app/core/` — `config.py` (BASE_DIR-anchored paths, fail-fast secrets),
  `middleware.py` (body cap, rate limits), `security.py` (bcrypt, tokens),
  `crypto.py` (Fernet device passwords), `validators.py` (ID safety).
- `app/models/`, `app/schemas/`, `app/services/` (auth, ab, presence),
  `app/db/` (engine with FK pragma + busy timeout).
- `app/shim/` — KX rendezvous proxy (`shim.py` + generated `rendezvous_pb2.py`),
  supervised by `app/shim_supervisor.py` (bounded restarts, status).
- `app/cli.py` — `create-admin`, `gen-key`, `dump-book`, `backup`.
- `frontend/` — React SPA (`src/`), served prebuilt from `frontend/dist/`.
- `alembic/` — migrations (0001 init, 0002 last_seen).
- `data/` — `base.db` (+ backups). `logs/` — app log. `config/` — Caddy
  example, systemd unit. `scripts/` — start/stop.

## Key flows

- RustDesk login → opaque Bearer token (`sessions` table, expiry) → AB pulls.
- Device heartbeats (`POST /api/heartbeat`, unauthenticated by client design)
  stamp `last_seen`; presence derived (online ≤45s, else offline, never-seen unknown).
- Shim: secure-mode clients get a real v0 KeyExchange (spec
  `docs/kx-shim-spec.md`); plain clients pass through untouched.

## Ports (all >1024, no root needed)

- `8000` FastAPI (bind `HOST`, default 127.0.0.1; `0.0.0.0` for LAN).
- `21116` shim listen (external-facing by design; capped, see threat model).
- Upstream hbbs/relay reached directly by clients for UDP/relay as before.
