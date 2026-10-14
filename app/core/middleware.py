"""Small hardening middlewares. No new dependencies.

- BodyCap: reject requests with Content-Length above limit (413).
- RateLimit: per-IP buckets for sensitive endpoints (429).
"""
import time
from collections import deque

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

# Module-level hit store so tests (and ops) can reset it deterministically.
HITS: dict[tuple, deque] = {}


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
    """rules: list of (path_prefix, methods, settings_attr). Keyed by client IP.
    Limits resolve from settings per request (test- and env-tunable)."""

    def __init__(self, app, rules):
        super().__init__(app)
        self.rules = rules
        self.hits = HITS

    def _key(self, request, prefix: str) -> tuple:
        ip = (request.client.host if request.client else "?").split("%")[0]
        return (prefix, ip)

    async def dispatch(self, request, call_next):
        for prefix, methods, attr in self.rules:
            if request.method in methods and request.url.path.startswith(prefix):
                per_min = getattr(settings, attr)
                now = time.monotonic()
                k = self._key(request, prefix)
                q = self.hits.setdefault(k, deque())
                while q and now - q[0] > 60:
                    q.popleft()
                if len(q) >= per_min:
                    return JSONResponse(status_code=429, content={"error": "rate limited"})
                q.append(now)
                break
        return await call_next(request)


def rate_limit_rules():
    return [
        ("/api/login", ("POST",), "login_per_minute_per_ip"),
        ("/api/heartbeat", ("POST",), "heartbeat_per_minute_per_ip"),
    ]
