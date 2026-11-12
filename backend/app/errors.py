import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger("proofbridge.errors")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_server_error",
    501: "not_implemented",
    502: "bad_gateway",
    503: "service_unavailable",
}


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details=None,
    headers: dict[str, str] | None = None
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message
        }
    }

    if details is not None:
        body["error"]["details"] = details

    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException
    ):
        code = _STATUS_CODES.get(exc.status_code, "http_error")

        if isinstance(exc.detail, str):
            message = exc.detail
            details = None
        else:
            message = "Request failed."
            details = exc.detail

        return _error_response(
            exc.status_code,
            code,
            message,
            details,
            exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError
    ):
        # Field values are intentionally omitted so sensitive input
        # (for example passwords) is never echoed back to the client.
        details = [
            {
                "type": error.get("type"),
                "loc": [str(part) for part in error.get("loc", ())],
                "msg": error.get("msg")
            }
            for error in exc.errors()
        ]

        return _error_response(
            422,
            "validation_error",
            "Request validation failed.",
            details
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception
    ):
        logger.exception(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path
        )

        return _error_response(
            500,
            "internal_server_error",
            "An unexpected error occurred."
        )
