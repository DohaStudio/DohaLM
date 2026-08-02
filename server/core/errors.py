"""Safe structured HTTP errors without traceback or local-path exposure."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server.core.request_id import REQUEST_ID_HEADER


class APIError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: Sequence[dict[str, Any]] = (),
    ) -> None:
        super().__init__(code)
        self.code = code
        self.safe_message = message
        self.status_code = status_code
        self.details = list(details)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unavailable"))


def error_payload(error: APIError, request_id_value: str) -> dict[str, object]:
    return {
        "error": {
            "code": error.code,
            "message": error.safe_message,
            "request_id": request_id_value,
            "details": error.details,
        }
    }


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        identifier = _request_id(request)
        return JSONResponse(
            error_payload(exc, identifier),
            status_code=exc.status_code,
            headers={REQUEST_ID_HEADER: identifier},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": list(item["loc"]),
                "message": "Invalid request value.",
                "type": item["type"],
            }
            for item in exc.errors()
        ]
        error = APIError(
            "VALIDATION_ERROR",
            "Request validation failed.",
            status_code=422,
            details=details,
        )
        identifier = _request_id(request)
        return JSONResponse(
            error_payload(error, identifier),
            status_code=422,
            headers={REQUEST_ID_HEADER: identifier},
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        del exc
        error = APIError(
            "INTERNAL_SERVER_ERROR",
            "An internal server error occurred.",
            status_code=500,
        )
        identifier = _request_id(request)
        return JSONResponse(
            error_payload(error, identifier),
            status_code=500,
            headers={REQUEST_ID_HEADER: identifier},
        )
