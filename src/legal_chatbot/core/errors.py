"""Safe HTTP-facing errors."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from legal_chatbot.core.logging import get_logger


class AppError(Exception):
    """An explicitly safe error that may be returned to an API client."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(code)


def get_request_id(request: Request) -> str:
    """Return the middleware ID, creating one only for a direct handler invocation."""
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    request_id = str(uuid4())
    request.state.request_id = request_id
    return request_id


def _validation_details(errors: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep validation structure while deliberately omitting untrusted input values."""
    return [
        {
            "loc": list(error.get("loc", ())),
            "msg": str(error.get("msg", "Invalid request")),
            "type": str(error.get("type", "validation_error")),
        }
        for error in errors
    ]


def register_error_handlers(app: FastAPI) -> None:
    """Register handlers which never serialize unexpected exception data."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, error: AppError) -> JSONResponse:
        request_id = get_request_id(request)
        get_logger().warning(
            "app_error",
            extra={
                "request_id": request_id,
                "status_code": error.status_code,
                "outcome": "client_error" if error.status_code < 500 else "server_error",
            },
        )
        return JSONResponse(
            status_code=error.status_code,
            content={
                "request_id": request_id,
                "error": {"code": error.code, "message": error.message},
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        request_id = get_request_id(request)
        get_logger().warning(
            "request_validation_failed",
            extra={"request_id": request_id, "status_code": 422, "outcome": "client_error"},
        )
        return JSONResponse(
            status_code=422,
            content={
                "request_id": request_id,
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": _validation_details(error.errors()),
                },
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, __: Exception) -> JSONResponse:
        # Do not include exception text or exc_info: either can contain a DSN or request secret.
        request_id = get_request_id(request)
        get_logger().error(
            "unhandled_request_error",
            extra={"request_id": request_id, "status_code": 500, "outcome": "server_error"},
        )
        return JSONResponse(
            status_code=500,
            content={
                "request_id": request_id,
                "error": {"code": "internal_error", "message": "Internal server error"},
            },
        )
