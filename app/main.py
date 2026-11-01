"""FastAPI application: routers, middleware and background jobs.

Background jobs run in the lifespan as asyncio tasks; their blocking SQLite
work goes to a worker thread, so the event loop only schedules them:

* discovery drain (shim events -> SQLite) every 2 s, when DISCOVERY_ENABLED=1;
* audit retention, shortly after start and then daily;
* shim supervisor watch every 5 s, when SHIM_ENABLED=1.
"""
import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import errors, panel, rustdesk
from app.api import v1 as api_v1
from app.core import logging as _logging  # noqa: F401
from app.core.config import BASE_DIR, settings
from app.core.middleware import (
    AuditMiddleware,
    BodyCapMiddleware,
    PanelSessionMiddleware,
    RateLimitMiddleware,
    rate_limit_rules,
)
from app.db.session import SessionLocal, check_ready
from app.services import audit as audit_svc
from app.services import discovery as discovery_svc
from app.shim_supervisor import ShimSupervisor

log = logging.getLogger(__name__)
supervisor: ShimSupervisor | None = None

SPA_DIST = BASE_DIR / "frontend" / "dist"


def _drain_discovery_once() -> None:
    with SessionLocal() as db:
        try:
            discovery_svc.drain_once(db)
        except Exception:
            db.rollback()
            raise


async def _every(name: str, interval: float, job: Callable[[], object],
                 first_delay: float | None = None) -> None:
    """Run a blocking job in a worker thread forever; a failure is logged, not fatal."""
    await asyncio.sleep(interval if first_delay is None else first_delay)
    while True:
        try:
            await asyncio.to_thread(job)
        except Exception as e:  # noqa: BLE001 - keep the loop alive, the job already logs details
            log.warning("%s failed: %r", name, e)
        await asyncio.sleep(interval)


def _start_shim() -> ShimSupervisor:
    host, _port = settings.shim_listen.rsplit(":", 1)
    if host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("shim listens on %s (external). Caps active: max_conns=%d",
                    host, settings.shim_max_conns)
    shim = ShimSupervisor(
        listen=settings.shim_listen, upstream=settings.shim_upstream,
        id_key=settings.shim_id_key, max_conns=settings.shim_max_conns,
        per_ip_per_min=settings.shim_per_ip_per_min,
        diag_msgtypes=settings.shim_diag_msgtypes == "1",
        udp_max_sessions=settings.shim_udp_max_sessions,
        udp_per_ip_per_min=settings.shim_udp_per_ip_per_min)
    shim.start()
    return shim


async def _watch_shim(shim: ShimSupervisor) -> None:
    while True:
        await asyncio.sleep(5)
        await shim.watch()


def _system_event(event_type: str, details: dict | None = None) -> None:
    if settings.audit_enabled_flag:
        audit_svc.write_event(category="system", event_type=event_type, outcome="success",
                              actor_type="system", destination="system", details=details)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global supervisor
    tasks: list[asyncio.Task] = []
    discovery_on = settings.discovery_enabled == "1"
    if discovery_on:
        # No TCP connection from a previous process can still be alive.
        try:
            with SessionLocal() as db:
                discovery_svc.reset_online(db)
        except Exception as e:  # noqa: BLE001 - startup must not fail on a stale flag
            log.warning("discovery reset failed: %r", e)

    _system_event("system.startup", {"retention_days": audit_svc.retention_days()})
    if settings.audit_enabled_flag:
        # cleanup_once() has its own non-blocking lock, so a manual run or a
        # second process cannot delete the same rows concurrently.
        tasks.append(asyncio.create_task(_every(
            "audit cleanup", max(60, settings.audit_cleanup_interval_sec),
            audit_svc.cleanup_once, first_delay=max(0, settings.audit_cleanup_initial_delay_sec))))
    if settings.shim_enabled == "1":
        supervisor = _start_shim()
        tasks.append(asyncio.create_task(_watch_shim(supervisor)))
    if discovery_on:
        tasks.append(asyncio.create_task(_every("discovery drain", 2, _drain_discovery_once)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        _system_event("system.shutdown")
        if supervisor is not None:
            supervisor.stop(timeout=10)
            supervisor = None


# SEC-008: /docs, /redoc and /openapi.json are reconnaissance material
# (full API inventory incl. /api/v1 and panel forms). Serve them only when
# explicitly enabled or in DEV_MODE; production defaults to 404.
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.add_middleware(BodyCapMiddleware)
app.add_middleware(RateLimitMiddleware, rules=rate_limit_rules())
# Panel cookie: HttpOnly, SameSite=Lax, Secure on HTTPS (SESSION_COOKIE_SECURE).
# It only carries the id of a server-side `sessions` row (see api/panel.py).
app.add_middleware(PanelSessionMiddleware, secret_key=settings.web_secret,
                   mode=settings.session_cookie_secure, same_site="lax",
                   max_age=(settings.session_days or 14) * 24 * 3600)
# Outermost: it assigns the request id and sees rate-limit/body-cap responses.
app.add_middleware(AuditMiddleware)
app.include_router(rustdesk.router)
app.include_router(api_v1.router)
app.include_router(panel.router)
errors.install(app)


@app.exception_handler(panel.LoginRedirect)
async def login_redirect(request: Request, exc: panel.LoginRedirect):
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
    try:
        check_ready()
    except Exception:  # noqa: BLE001 - any DB failure means "not ready"
        return JSONResponse(status_code=503, content={"status": "not-ready", "db": "down"})
    if supervisor is None:
        return {"status": "ready", "db": "up", "shim": {"state": "disabled"}}
    st = supervisor.status()
    if st["state"] == "down":
        return JSONResponse(status_code=503, content={"status": "not-ready", "shim": st})
    return {"status": "ready", "db": "up", "shim": st}


if SPA_DIST.is_dir():
    app.mount("/app", StaticFiles(directory=str(SPA_DIST), html=True), name="spa")
