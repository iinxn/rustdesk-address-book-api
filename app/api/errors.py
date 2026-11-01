"""Error responses for the two JSON APIs.

Each API keeps its own error shape (AGENTS.md §4): the RustDesk client
contract uses `{"error": msg}`, the internal panel API `{"detail": msg}`.
Routes raise `ClientError`/`PanelError` instead of threading `return err(...)`
through every branch; the handlers below render the right shape.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    key = "detail"

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class ClientError(ApiError):
    """`/api/*` (stock RustDesk client): `{"error": ...}`."""
    key = "error"


class PanelError(ApiError):
    """`/api/v1/*` (SPA): `{"detail": ...}`."""
    key = "detail"


def error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={exc.key: exc.message})


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc)
