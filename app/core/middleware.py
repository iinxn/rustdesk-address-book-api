"""Small hardening middlewares. No new dependencies.

- BodyCap: reject requests with Content-Length above limit (413).
- RateLimit: login/sysinfo use per-IP buckets; heartbeat uses an independent
  per-device bucket plus an aggregate per-IP cap (429 + `Retry-After`).
"""
import json
import logging
import math
import threading
import time
from collections import deque

from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.validators import validate_rustdesk_id
from app.services import audit as audit_svc

log = logging.getLogger("app.access")

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


class PanelSessionMiddleware:
    """Starlette SessionMiddleware with a per-request `Secure` cookie flag.

    `SESSION_COOKIE_SECURE=auto` marks the cookie Secure whenever the request
    scheme is https: a direct TLS listener, or a reverse proxy whose
    X-Forwarded-Proto uvicorn accepted. "1" always sets it, "0" never (plain
    HTTP panel inside a trusted VPN). Two inner instances instead of one
    mutable flag, so concurrent requests cannot see each other's setting.
    """

    def __init__(self, app, secret_key: str, mode: str = "auto", **kwargs):
        from starlette.middleware.sessions import SessionMiddleware

        self.mode = mode if mode in ("auto", "1", "0") else "auto"
        self.plain = SessionMiddleware(app, secret_key=secret_key, https_only=False, **kwargs)
        self.secure = SessionMiddleware(app, secret_key=secret_key, https_only=True, **kwargs)

    def _is_secure(self, scope) -> bool:
        if self.mode == "1":
            return True
        if self.mode == "0":
            return False
        return scope.get("scheme") in ("https", "wss")

    async def __call__(self, scope, receive, send):
        inner = self.secure if self._is_secure(scope) else self.plain
        await inner(scope, receive, send)


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
                audit_svc.note_rate_limited(
                    "/api/heartbeat", client_ip(request), retry, audit_it=False
                )
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
                    audit_svc.note_rate_limited(
                        prefix, client_ip(request), _retry_after(q, now), audit_it=True
                    )
                    return _rate_limited(q, now)
                q.append(now)
                break
        return await call_next(request)


def rate_limit_rules():
    # Heartbeat has its own per-device + aggregate-IP logic in dispatch().
    # `/panel/login` is a second password entry point (legacy panel): it gets
    # the same per-IP budget as `/api/login`, in its own bucket.
    return [
        ("/api/login", ("POST",), "login_per_minute_per_ip"),
        ("/panel/login", ("POST",), "login_per_minute_per_ip"),
        ("/api/sysinfo", ("POST",), "sysinfo_per_minute_per_ip"),
    ]


# --- audit/access middleware -------------------------------------------------

# High-volume or explicitly instrumented endpoints. Heartbeats and sysinfo are
# deliberately absent: they run every ~15 s per device and already have their
# own state-transition events. The audit reader itself is skipped so browsing
# the log cannot grow the log.
_SKIP_AUDIT_PREFIXES = ("/api/heartbeat", "/api/sysinfo", "/api/v1/audit")
_SKIP_AUDIT_EXACT = {"/api/login-options"}
# POST endpoints that only read. They are access-logged only when they target a
# path parameter (e.g. tags of one book) or fail.
_READ_ONLY_ROUTES = {
    "/api/currentUser",
    "/api/ab/settings",
    "/api/ab/personal",
    "/api/ab/shared/profiles",
    "/api/ab/peers",
    "/api/ab/tags/{guid}",
    "/api/ab",
    "/api/device-group/accessible",
    "/api/users",
    "/api/peers",
}
_MUTATION_METHODS = ("POST", "PUT", "PATCH", "DELETE")
_READ_DEDUPE: dict[tuple, float] = {}
_READ_DEDUPE_LOCK = threading.Lock()
_READ_DEDUPE_MAX = 5000


def _bearer(request) -> str:
    value = request.headers.get("authorization", "")
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _read_allowed(key: tuple, window: int) -> bool:
    """Collapse repeated reads of the same resource (panel polling)."""
    if window <= 0:
        return True
    now = time.monotonic()
    with _READ_DEDUPE_LOCK:
        last = _READ_DEDUPE.get(key)
        if last is not None and now - last < window:
            return False
        _READ_DEDUPE[key] = now
        if len(_READ_DEDUPE) > _READ_DEDUPE_MAX:
            for k, ts in list(_READ_DEDUPE.items()):
                if now - ts >= window:
                    _READ_DEDUPE.pop(k, None)
    return True


def _audit_significant(method: str, route: str, path: str, status: int, params: dict) -> bool:
    if not path.startswith("/api/"):
        return False
    if path in _SKIP_AUDIT_EXACT or path.startswith(_SKIP_AUDIT_PREFIXES):
        return False
    # Login/logout have explicit auth events; a validation failure (422) still
    # reaches the access log through the status check below.
    if path in ("/api/login", "/api/logout") and status in (200, 401):
        return False
    # 429 is already written once per route/IP/window by the rate limiter
    # (`note_rate_limited`); a second row here would double every throttled
    # request and defeat the storm protection.
    if status == 429:
        return False
    if status in (401, 403, 413) or status >= 500:
        return True
    if method in _MUTATION_METHODS and route not in _READ_ONLY_ROUTES:
        return True
    if method in ("GET", "POST") and params:
        return True
    return False


def _audit_params(request) -> dict:
    """Path params plus only the query keys that identify a resource.

    Query strings may contain arbitrary user data; the audit log must not
    become a copy of them. `ab`/`book` are the RustDesk address-book selectors
    and `rid` is a device id, so those are safe to use as targets.
    """
    params = dict(request.scope.get("path_params") or {})
    for key in ("ab", "book", "rid"):
        value = request.query_params.get(key)
        if value and key not in params:
            params[key] = value
    return params


class AuditMiddleware(BaseHTTPMiddleware):
    """Request id + source IP context and a bounded access/security history.

    It does not log every request. Only mutations, failures/denials and reads
    of a specific resource are stored; repeated reads of the same resource by
    the same actor are collapsed (`AUDIT_READ_DEDUPE_SEC`). Technical output
    stays on stdout/stderr and is not duplicated into SQLite.
    """

    async def dispatch(self, request, call_next):
        started = time.perf_counter()
        path = request.url.path
        source_ip = client_ip(request)
        token = _bearer(request)
        request_id = audit_svc.new_request_id()
        destination = "panel" if path.startswith("/panel") else "api"
        ctx_token = audit_svc.set_request_context(
            audit_svc.RequestContext(
                request_id=request_id,
                source_ip=source_ip,
                destination=destination,
                http_method=request.method,
                route=path,
            )
        )
        status = 500
        response = None
        try:
            try:
                response = await call_next(request)
                status = response.status_code
            except Exception:
                log.exception(
                    "unhandled error request_id=%s method=%s path=%s",
                    request_id, request.method, path,
                )
                raise
            finally:
                duration_ms = int((time.perf_counter() - started) * 1000)
                route = getattr(request.scope.get("route"), "path", None) or path
                params = _audit_params(request)
                if response is not None:
                    response.headers["X-Request-ID"] = request_id
                if _audit_significant(request.method, route, path, status, params):
                    is_mutation = (
                        request.method in _MUTATION_METHODS
                        and route not in _READ_ONLY_ROUTES
                    )
                    should_write = True
                    if not is_mutation and status < 400:
                        target_type, target_id = audit_svc.target_from_params(params)
                        actor_key = token or f"ip:{source_ip}"
                        should_write = _read_allowed(
                            (actor_key, request.method, route, target_type, target_id),
                            settings.audit_read_dedupe_sec,
                        )
                    if should_write:
                        await run_in_threadpool(
                            audit_svc.write_access,
                            method=request.method,
                            route=route,
                            path=path,
                            status_code=status,
                            duration_ms=duration_ms,
                            request_id=request_id,
                            source_ip=source_ip,
                            token=token,
                            params=params,
                        )
                if (
                    settings.audit_slow_request_ms > 0
                    and duration_ms >= settings.audit_slow_request_ms
                ):
                    log.warning(
                        "slow request request_id=%s method=%s route=%s status=%s duration_ms=%d",
                        request_id, request.method, route, status, duration_ms,
                    )
        finally:
            audit_svc.reset_request_context(ctx_token)
        return response
