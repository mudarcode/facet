"""Structured API errors: every error response is ``{"error": {code, message, details}}``."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class FacetError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFound(FacetError):
    status_code = 404
    code = "not_found"


class Conflict(FacetError):
    status_code = 409
    code = "conflict"


class Unauthorized(FacetError):
    status_code = 401
    code = "unauthorized"


class PayloadTooLarge(FacetError):
    status_code = 413
    code = "payload_too_large"


class InvalidInput(FacetError):
    status_code = 422
    code = "invalid_input"


class QueryRejected(FacetError):
    """SQL failed the read-only/authorization checks before execution."""

    status_code = 400
    code = "query_rejected"


class QueryFailed(FacetError):
    """SQL passed validation but DuckDB raised an error while executing."""

    status_code = 400
    code = "query_failed"


class QueryTimeout(FacetError):
    status_code = 408
    code = "query_timeout"


class Busy(FacetError):
    status_code = 503
    code = "busy"


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(FacetError)
    async def _facet(_: Request, exc: FacetError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            _body("invalid_input", "Request validation failed", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code)
