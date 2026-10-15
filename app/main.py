import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import panel, rustdesk, webapi
from app.api.panel import _LoginRedirect
from app.core import logging as _logging  # noqa: F401
from app.core.config import settings
from app.core.middleware import BodyCapMiddleware, RateLimitMiddleware, rate_limit_rules
from app.shim_supervisor import ShimSupervisor

log = logging.getLogger(__name__)
supervisor: ShimSupervisor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global supervisor
    monitor_task = None
    if settings.shim_enabled == "1":
        host, _port = settings.shim_listen.rsplit(":", 1)
        if host not in ("127.0.0.1", "localhost", "::1"):
            log.warning("shim listens on %s (external). Caps active: max_conns=%d",
                        host, settings.shim_max_conns)
        supervisor = ShimSupervisor(
            listen=settings.shim_listen, upstream=settings.shim_upstream,
            id_key=settings.shim_id_key, max_conns=settings.shim_max_conns,
            per_ip_per_min=settings.shim_per_ip_per_min,
            diag_msgtypes=settings.shim_diag_msgtypes == "1")
        supervisor.start()

        async def _watch():
            while True:
                await asyncio.sleep(5)
                if supervisor is None:
                    return
                await supervisor.watch()

        monitor_task = asyncio.create_task(_watch())
    yield
    if monitor_task is not None:
        monitor_task.cancel()
    if supervisor is not None:
        supervisor.stop(timeout=10)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(BodyCapMiddleware)
app.add_middleware(RateLimitMiddleware, rules=rate_limit_rules())
app.add_middleware(SessionMiddleware, secret_key=settings.web_secret,
                   same_site="lax", https_only=False)
app.include_router(rustdesk.router)
app.include_router(webapi.router)
app.include_router(panel.router)


@app.exception_handler(_LoginRedirect)
async def login_redirect(request: Request, exc: _LoginRedirect):
    return RedirectResponse("/panel/login", status_code=303)


@app.exception_handler(401)
async def unauthorized_json(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return RedirectResponse("/panel/login", status_code=303)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/", status_code=303)


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "live"}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    from fastapi.responses import JSONResponse as JR
    from app.db.session import check_ready
    try:
        check_ready()
    except Exception:
        return JR(status_code=503, content={"status": "not-ready", "db": "down"})
    if supervisor is not None:
        st = supervisor.status()
        if st["state"] == "down":
            return JR(status_code=503, content={"status": "not-ready", "shim": st})
        return {"status": "ready", "db": "up", "shim": st}
    return {"status": "ready", "db": "up", "shim": {"state": "disabled"}}


import os as _os

_DIST = _os.path.join(_os.path.dirname(__file__), "..", "frontend", "dist")
if _os.path.isdir(_DIST):
    app.mount("/app", StaticFiles(directory=_DIST, html=True), name="spa")
