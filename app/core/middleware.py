"""Small hardening middlewares. No new dependencies.

- BodyCap: reject requests with Content-Length above limit (413).
- RateLimit: login/sysinfo use per-IP buckets; heartbeat uses an independent
  per-device bucket plus an aggregate per-IP cap (429 + `Retry-After`).
"""
import json
import math
import time
from collections import deque

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.validators import validate_rustdesk_id

WINDOW_SEC = 60.0
# Heartbeat payloads are tiny (id/uuid/ver). Parse the body in middleware only
# when Content-Length is present and small, so a chunked/oversized request can
# never make the limiter buffer it; such requests are keyed by IP only.
HEARTBEAT_BODY_LIMIT = 8 * 1024
_SWEEP_INTERVAL = 60.0

# Shared hit store so tests (and ops) can reset it deterministically.
HITS: dict[tuple, deque] = {}
_last_sweep = 0.0


def reset_rate_limits() -> None:
    """Forget all buckets. Used by tests and after deliberate reconfiguration."""
    global _last_sweep
    HITS.clear()
    _last_sweep = 0.0


def _prune(q: deque, now: float) -> None:
    cutoff = now - WINDOW_SEC
    while q and q[0] <= cutoff:
        q.popleft()


def _retry_after(q: deque, now: float) -> int:
    """Seconds until the oldest hit leaves the sliding window."""
    if not q:
        return 1
    return max(1, int(math.ceil(q[0] + WINDOW_SEC - now)))


def _maybe_sweep(now: float) -> None:
    """Drop stale keys so per-device buckets cannot grow without bound."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    for key, q in list(HITS.items()):
        _prune(q, now)
        if not q:
            HITS.pop(key, None)


def _rate_limited(q: deque, now: float) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate limited"},
        headers={"Retry-After": str(_retry_after(q, now))},
    )


async def _heartbeat_id(request) -> str | None:
    """Validated device id from a small JSON heartbeat body, else None."""
    raw_len = request.headers.get("content-length")
    try:
        length = int(raw_len) if raw_len else 0
    except ValueError:
        return None
    if length <= 0 or length > HEARTBEAT_BODY_LIMIT:
        return None
    try:
        data = json.loads((await request.body()).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    rid = str(data.get("id", "")).strip()
    if not rid or validate_rustdesk_id(rid) is not None:
        return None
    return rid


def heartbeat_allow(rid: str | None, ip: str, now: float | None = None) -> tuple[bool, int]:
    """Apply per-device then aggregate-per-IP limits for one heartbeat.

    The device bucket is keyed by `(device id, client IP)`: independent devices
    behind one NAT do not evict each other, and a spoofed id from another IP
    cannot consume a real device's budget. When the device is already over its
    limit the request is rejected *before* consuming the shared IP budget, so
    a retrying device cannot crowd out its neighbours. Requests without a
    trustworthy id are limited by the aggregate IP cap only.
    """
    now = time.monotonic() if now is None else now
    _maybe_sweep(now)

    dev_q: deque | None = None
    dev_key: tuple | None = None
    if rid:
        dev_key = ("heartbeat:dev", ip, rid)
        dev_q = HITS.setdefault(dev_key, deque())
        _prune(dev_q, now)
        if len(dev_q) >= settings.heartbeat_per_minute_per_device:
            return False, _retry_after(dev_q, now)

    ip_key = ("heartbeat:ip", ip)
    ip_q = HITS.setdefault(ip_key, deque())
    _prune(ip_q, now)
    if len(ip_q) >= settings.heartbeat_per_minute_per_ip:
        if dev_key is not None and dev_q is not None and not dev_q:
            HITS.pop(dev_key, None)
        return False, _retry_after(ip_q, now)

    if dev_q is not None:
        dev_q.append(now)
    ip_q.append(now)
    return True, 0


def client_ip(request) -> str:
    """Real client IP for rate-limit keying.

    The direct peer address is used by default. `X-Forwarded-For` is honored
    ONLY when the immediate peer is a configured trusted proxy
    (`TRUSTED_PROXIES`, e.g. Caddy on 127.0.0.1): we then walk the chain from
    right to left and take the first hop that is not itself a trusted proxy.
    Without a trusted proxy the header is ignored entirely, so a spoofed XFF
    can neither dodge the limiter nor pin a victim into a shared bucket.
    """
    direct = (request.client.host if request.client else "?").split("%")[0]
    trusted = settings.trusted_proxies_set
    if not trusted or direct not in trusted:
        return direct
    xff = request.headers.get("x-forwarded-for", "")
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        ip = hop.split("%")[0]
        if ip not in trusted:
            return ip
    return direct


class BodyCapMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            length = 0
        if length > settings.max_body_bytes:
            return JSONResponse(status_code=413, content={"detail": "body too large"})
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP buckets for login/sysinfo, per-device + per-IP for heartbeat.

    Limits resolve from settings per request (test- and env-tunable).
    """

    def __init__(self, app, rules):
        super().__init__(app)
        self.rules = rules
        self.hits = HITS

    def _key(self, request, prefix: str) -> tuple:
        return (prefix, client_ip(request))

    async def dispatch(self, request, call_next):
        if request.method == "POST" and request.url.path.startswith("/api/heartbeat"):
            rid = await _heartbeat_id(request)
            allowed, retry = heartbeat_allow(rid, client_ip(request))
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"error": "rate limited"},
                    headers={"Retry-After": str(retry)},
                )
            return await call_next(request)

        for prefix, methods, attr in self.rules:
            if request.method in methods and request.url.path.startswith(prefix):
                per_min = getattr(settings, attr)
                now = time.monotonic()
                _maybe_sweep(now)
                k = self._key(request, prefix)
                q = self.hits.setdefault(k, deque())
                _prune(q, now)
                if len(q) >= per_min:
                    return _rate_limited(q, now)
                q.append(now)
                break
        return await call_next(request)


def rate_limit_rules():
    # Heartbeat has its own per-device + aggregate-IP logic in dispatch().
    return [
        ("/api/login", ("POST",), "login_per_minute_per_ip"),
        ("/api/sysinfo", ("POST",), "sysinfo_per_minute_per_ip"),
    ]
