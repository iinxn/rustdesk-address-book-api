from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import panel, rustdesk, webapi
from app.api.panel import _LoginRedirect
from app.core import logging as _logging  # noqa: F401  (sets up std logging)
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.web_secret)
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


@app.get("/health")
def health():
    return {"ok": True}


# Modern SPA (frontend/dist). Mounted last so /api/* and /panel/* win.
import os as _os

_DIST = _os.path.join(_os.path.dirname(__file__), "..", "frontend", "dist")
if _os.path.isdir(_DIST):
    app.mount("/app", StaticFiles(directory=_DIST, html=True), name="spa")
