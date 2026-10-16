"""Single API error format: ``{"error": {"code", "message", "request_id"}}``."""

from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    412: "PRECONDITION_FAILED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    428: "PRECONDITION_REQUIRED",
    429: "RATE_LIMITED",
}


class AppError(Exception):
    """Expected error with a stable machine-readable code and a safe message."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """Build the error payload, always carrying the current request id."""
    error: dict[str, Any] = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details is not None:
        error["details"] = details
    return {"error": error}


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(AppError, exc)
    return JSONResponse(
        error_body(error.code, error.message, error.details), status_code=error.status_code
    )


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(StarletteHTTPException, exc)
    code = _STATUS_CODES.get(error.status_code, "ERROR")
    message = code.replace("_", " ").capitalize()
    return JSONResponse(
        error_body(code, message), status_code=error.status_code, headers=error.headers
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    # Input values are not echoed back: they may contain secrets or markup.
    details = [
        {"loc": [str(part) for part in err.get("loc", ())], "type": err.get("type")}
        for err in cast(RequestValidationError, exc).errors()
    ]
    return JSONResponse(error_body("VALIDATION_ERROR", "Invalid request", details), status_code=422)


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers for expected errors.

    Unexpected exceptions are turned into a 500 by ``RequestContextMiddleware``, which still
    knows the request id; Starlette's own catch-all runs outside it.
    """
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
