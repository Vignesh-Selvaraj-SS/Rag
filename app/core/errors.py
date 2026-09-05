"""
Application errors and the FastAPI handlers that turn them into a single,
predictable JSON shape: {"detail": "...", "request_id": "..."}.

User-facing messages are plain English; the technical cause is logged with
the request id so it can be found later without leaking it to the client.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.core.request_id import get_request_id

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """Base for errors that map to a specific HTTP status."""

    status_code = 500
    message = "Something went wrong."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message


class IndexEmptyError(AppError):
    status_code = 503
    message = "The knowledge base has not been indexed yet. Rebuild the index first."


class LLMNotConfiguredError(AppError):
    status_code = 503
    message = (
        "Answer generation is not configured on the server. "
        "Set GROQ_API_KEY to enable it."
    )


class LLMUpstreamError(AppError):
    status_code = 502
    message = "The language model service returned an error. Please try again."


class NotFoundError(AppError):
    status_code = 404
    message = "The requested item was not found."


class BadRequestError(AppError):
    status_code = 400
    message = "The request could not be processed."


def _payload(request: Request, detail: str) -> dict:
    return {"detail": detail, "request_id": get_request_id(request)}


def register_error_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppError)
    async def _app_error(request: Request, error: AppError):
        if error.status_code >= 500:
            logger.warning("%s: %s", type(error).__name__, error.message)
        return JSONResponse(
            status_code=error.status_code,
            content=_payload(request, error.message),
        )

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, error: HTTPException):
        detail = error.detail if isinstance(error.detail, str) else "Request failed."
        return JSONResponse(
            status_code=error.status_code,
            content=_payload(request, detail),
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, error: RequestValidationError):
        first = error.errors()[0] if error.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = first.get("msg", "Invalid request.")
        detail = f"{location}: {message}" if location else message
        return JSONResponse(status_code=422, content=_payload(request, detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, error: Exception):
        logger.exception(
            "Unhandled error on %s %s (request %s)",
            request.method,
            request.url.path,
            get_request_id(request),
        )
        return JSONResponse(
            status_code=500,
            content=_payload(request, "Something went wrong on the server."),
        )
