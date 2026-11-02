"""HTTP middleware: audit context, panel cookie, rate limits, body cap.

All of them are plain ASGI callables. `BaseHTTPMiddleware` ran every request
through an extra task and memory stream per layer, and the access log write
delayed the response; here the access row is written after the response has
been sent. Order (outermost first, see `app/main.py`):

    AuditMiddleware -> PanelSessionMiddleware -> RateLimitMiddleware -> BodyCapMiddleware

- BodyCap: `Content-Length` above `MAX_BODY_BYTES` -> 413; a chunked body is
  buffered up to the same limit before the app sees it (SEC-013).
- RateLimit: login/sysinfo use per-IP buckets; heartbeat uses an independent
  per-device bucket plus an aggregate per-IP cap (429 + `Retry-After`).
- Audit: request id, source IP context and a bounded access/security history.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qs

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders

from app.core.config import settings
from app.core.validators import validate_rustdesk_id
from app.services import audit as audit_svc

log = logging.getLogger("app.access")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

WINDOW_SEC = 60.0
# Heartbeat payloads are tiny (id/uuid/ver). The limiter reads the body only
# when Content-Length is present and small, so a chunked/oversized request can
# never make it buffer much; such requests are keyed by IP only.
HEARTBEAT_BODY_LIMIT = 8 * 1024
_SWEEP_INTERVAL = 60.0

# Shared hit store so tests (and ops) can reset it deterministically.
HITS: dict[tuple, deque] = {}
_last_sweep = 0.0


# --- small ASGI helpers --------------------------------------------------------

async def _send_json(send: Send, status: int, content: dict, headers: dict | None = None) -> None:
    body = json.dumps(content).encode()
    raw = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    raw += [(k.lower().encode(), str(v).encode()) for k, v in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive: Receive, limit: int) -> bytes | None:
    """Whole request body, or None as soon as it exceeds `limit` bytes."""
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":  # client went away
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    """A `receive` that yields an already-read body once, then delegates."""
    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


def _content_length(headers: Headers) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return 0


def scope_client_ip(scope: Scope) -> str:
    """Real client IP for rate-limit keying and audit rows.

    The direct peer address is used by default. `X-Forwarded-For` is honored
    ONLY when the immediate peer is a configured trusted proxy
    (`TRUSTED_PROXIES`, e.g. Caddy on 127.0.0.1): we then walk the chain from
    right to left and take the first hop that is not itself a trusted proxy.
    Without a trusted proxy the header is ignored entirely, so a spoofed XFF
    can neither dodge the limiter nor pin a victim into a shared bucket.
    """
    client = scope.get("client")
    direct = (client[0] if client else "?").split("%")[0]
    trusted = settings.trusted_proxies_set
    if not trusted or direct not in trusted:
        return direct
    xff = Headers(scope=scope).get("x-forwarded-for", "")
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        ip = hop.split("%")[0]
        if ip not in trusted:
            return ip
    return direct


def client_ip(request) -> str:
    """`scope_client_ip` for a Starlette `Request`."""
    return scope_client_ip(request.scope)


def bearer_from_headers(headers: Headers) -> str:
    value = headers.get("authorization", "")
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


# --- rate limiting -------------------------------------------------------------

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


def _heartbeat_rid(body: bytes) -> str | None:
    """Validated device id from a small JSON heartbeat body, else None."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
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


def rate_limit_rules() -> list[tuple[str, tuple[str, ...], str]]:
    # Heartbeat has its own per-device + aggregate-IP logic.
    # `/panel/login` is a second password entry point (legacy panel): it gets
    # the same per-IP budget as `/api/login`, in its own bucket.
    return [
        ("/api/login", ("POST",), "login_per_minute_per_ip"),
        ("/panel/login", ("POST",), "login_per_minute_per_ip"),
        ("/api/sysinfo", ("POST",), "sysinfo_per_minute_per_ip"),
        ("/api/audit/", ("POST",), "audit_report_per_minute_per_ip"),
    ]


async def _too_many(send: Send, retry: int) -> None:
    await _send_json(send, 429, {"error": "rate limited"}, {"Retry-After": retry})


class RateLimitMiddleware:
    """Per-IP buckets for login/sysinfo, per-device + per-IP for heartbeat.

    Limits resolve from settings per request (test- and env-tunable).
    """

    def __init__(self, app: ASGIApp, rules):
        self.app = app
        self.rules = rules

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method, path = scope["method"], scope["path"]
        ip = scope_client_ip(scope)

        if method == "POST" and path.startswith("/api/heartbeat"):
            rid = None
            length = _content_length(Headers(scope=scope))
            if length is not None and 0 < length <= HEARTBEAT_BODY_LIMIT:
                body = await _read_body(receive, HEARTBEAT_BODY_LIMIT)
                if body is not None:
                    receive = _replay(body, receive)
                    rid = _heartbeat_rid(body)
            allowed, retry = heartbeat_allow(rid, ip)
            if not allowed:
                # Log-only (no DB write): cheap enough for the event loop.
                audit_svc.note_rate_limited("/api/heartbeat", ip, retry, audit_it=False)
                await _too_many(send, retry)
                return
            await self.app(scope, receive, send)
            return

        for prefix, methods, attr in self.rules:
            if method in methods and path.startswith(prefix):
                now = time.monotonic()
                _maybe_sweep(now)
                q = HITS.setdefault((prefix, ip), deque())
                _prune(q, now)
                if len(q) >= getattr(settings, attr):
                    retry = _retry_after(q, now)
                    # May write one throttled audit row: keep SQLite off the loop.
                    await run_in_threadpool(audit_svc.note_rate_limited, prefix, ip, retry, True)
                    await _too_many(send, retry)
                    return
                q.append(now)
                break
        await self.app(scope, receive, send)


class BodyCapMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = settings.max_body_bytes
        headers = Headers(scope=scope)
        length = _content_length(headers)
        if length is not None:
            if length > limit:
                await _send_json(send, 413, {"detail": "body too large"})
                return
        elif "chunked" in headers.get("transfer-encoding", "").lower():
            # SEC-013: no declared length — buffer at most `limit` bytes first.
            body = await _read_body(receive, limit)
            if body is None:
                await _send_json(send, 413, {"detail": "body too large"})
                return
            receive = _replay(body, receive)
        await self.app(scope, receive, send)


class PanelSessionMiddleware:
    """Starlette SessionMiddleware with a per-request `Secure` cookie flag.

    `SESSION_COOKIE_SECURE=auto` marks the cookie Secure whenever the request
    scheme is https: a direct TLS listener, or a reverse proxy whose
    X-Forwarded-Proto uvicorn accepted. "1" always sets it, "0" never (plain
    HTTP panel inside a trusted VPN). Two inner instances instead of one
    mutable flag, so concurrent requests cannot see each other's setting.
    """

    def __init__(self, app: ASGIApp, secret_key: str, mode: str = "auto", **kwargs):
        from starlette.middleware.sessions import SessionMiddleware

        self.mode = mode if mode in ("auto", "1", "0") else "auto"
        self.plain = SessionMiddleware(app, secret_key=secret_key, https_only=False, **kwargs)
        self.secure = SessionMiddleware(app, secret_key=secret_key, https_only=True, **kwargs)

    def _is_secure(self, scope: Scope) -> bool:
        if self.mode == "1":
            return True
        if self.mode == "0":
            return False
        return scope.get("scheme") in ("https", "wss")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        inner = self.secure if self._is_secure(scope) else self.plain
        await inner(scope, receive, send)


# --- audit/access middleware -------------------------------------------------

# High-volume or explicitly instrumented endpoints. Heartbeats and sysinfo are
# deliberately absent: they run every ~15 s per device and already have their
# own state-transition events. The audit reader itself is skipped so browsing
# the log cannot grow the log. Device connection reports (/api/audit/*) write
# their own explicit events.
_SKIP_AUDIT_PREFIXES = ("/api/heartbeat", "/api/sysinfo", "/api/v1/audit", "/api/audit/")
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


def _is_mutation(method: str, route: str) -> bool:
    return method in _MUTATION_METHODS and route not in _READ_ONLY_ROUTES


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
    if _is_mutation(method, route):
        return True
    return method in ("GET", "POST") and bool(params)


def _audit_params(scope: Scope) -> dict:
    """Path params plus only the query keys that identify a resource.

    Query strings may contain arbitrary user data; the audit log must not
    become a copy of them. `ab`/`book` are the RustDesk address-book selectors
    and `rid` is a device id, so those are safe to use as targets.
    """
    params = dict(scope.get("path_params") or {})
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    for key in ("ab", "book", "rid"):
        values = query.get(key)
        if values and values[0] and key not in params:
            params[key] = values[0]
    return params


class AuditMiddleware:
    """Request id + source IP context and a bounded access/security history.

    It does not log every request. Only mutations, failures/denials and reads
    of a specific resource are stored; repeated reads of the same resource by
    the same actor are collapsed (`AUDIT_READ_DEDUPE_SEC`). Technical output
    stays on stdout/stderr and is not duplicated into SQLite.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        path, method = scope["path"], scope["method"]
        source_ip = scope_client_ip(scope)
        token = bearer_from_headers(Headers(scope=scope))
        request_id = audit_svc.new_request_id()
        ctx_token = audit_svc.set_request_context(audit_svc.RequestContext(
            request_id=request_id,
            source_ip=source_ip,
            destination="panel" if path.startswith("/panel") else "api",
            http_method=method,
            route=path,
        ))
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled error request_id=%s method=%s path=%s",
                          request_id, method, path)
            raise
        finally:
            try:
                # The response is already on the wire: the access row and the
                # slow-request warning no longer add latency for the client.
                duration_ms = int((time.perf_counter() - started) * 1000)
                route = getattr(scope.get("route"), "path", None) or path
                await self._record(method, route, path, status, duration_ms,
                                   request_id, source_ip, token, _audit_params(scope))
                if 0 < settings.audit_slow_request_ms <= duration_ms:
                    log.warning(
                        "slow request request_id=%s method=%s route=%s status=%s duration_ms=%d",
                        request_id, method, route, status, duration_ms,
                    )
            finally:
                audit_svc.reset_request_context(ctx_token)

    @staticmethod
    async def _record(method: str, route: str, path: str, status: int, duration_ms: int,
                      request_id: str, source_ip: str, token: str, params: dict) -> None:
        if not _audit_significant(method, route, path, status, params):
            return
        if not _is_mutation(method, route) and status < 400:
            target_type, target_id = audit_svc.target_from_params(params)
            if not _read_allowed((token or f"ip:{source_ip}", method, route, target_type, target_id),
                                 settings.audit_read_dedupe_sec):
                return
        await run_in_threadpool(
            audit_svc.write_access,
            method=method,
            route=route,
            status_code=status,
            duration_ms=duration_ms,
            request_id=request_id,
            source_ip=source_ip,
            token=token,
            params=params,
        )
