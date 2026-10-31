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
from app.core.middleware import (
    AuditMiddleware,
    BodyCapMiddleware,
    RateLimitMiddleware,
    rate_limit_rules,
)
from app.db.session import SessionLocal
from app.services import audit as audit_svc
from app.services import discovery as discovery_svc
from app.shim_supervisor import ShimSupervisor

log = logging.getLogger(__name__)
supervisor: ShimSupervisor | None = None


def _drain_discovery_once() -> None:
    db = SessionLocal()
    try:
        discovery_svc.drain_once(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global supervisor
    monitor_task = None
    discovery_task = None
    audit_task = None
    # No TCP connection from a previous process can still be alive.
    if settings.discovery_enabled == "1":
        try:
            with SessionLocal() as db:
                discovery_svc.reset_online(db)
        except Exception as e:
            log.warning("discovery reset failed: %r", e)

    if settings.audit_enabled_flag:
        audit_svc.write_event(
            category="system",
            event_type="system.startup",
            outcome="success",
            actor_type="system",
            destination="system",
            details={"retention_days": audit_svc.retention_days()},
        )

        async def _audit_loop():
            # First run soon after start, then daily. cleanup_once() has its own
            # non-blocking lock, so a manual run or a second process cannot
            # delete the same rows concurrently.
            await asyncio.sleep(max(0, settings.audit_cleanup_initial_delay_sec))
            while True:
                try:
                    await asyncio.to_thread(audit_svc.cleanup_once)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # cleanup_once already logs; keep loop alive
                    log.warning("audit cleanup loop failed: %r", e)
                await asyncio.sleep(max(60, settings.audit_cleanup_interval_sec))

        audit_task = asyncio.create_task(_audit_loop())

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

    if settings.discovery_enabled == "1":
        async def _drain_loop():
            while True:
                await asyncio.sleep(2)
                try:
                    await asyncio.to_thread(_drain_discovery_once)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("discovery drain failed: %r", e)

        discovery_task = asyncio.create_task(_drain_loop())
    yield
    if monitor_task is not None:
        monitor_task.cancel()
    if discovery_task is not None:
        discovery_task.cancel()
    if audit_task is not None:
        audit_task.cancel()
    if settings.audit_enabled_flag:
        audit_svc.write_event(
            category="system",
            event_type="system.shutdown",
            outcome="success",
            actor_type="system",
            destination="system",
        )
    if supervisor is not None:
        supervisor.stop(timeout=10)


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
app.add_middleware(SessionMiddleware, secret_key=settings.web_secret,
                   same_site="lax", https_only=False)
# Outermost: it assigns the request id and sees rate-limit/body-cap responses.
app.add_middleware(AuditMiddleware)
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
