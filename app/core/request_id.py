"""
Attach a request id to every request so an error shown in the UI can be
matched to a log line on the server.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        request_id = request.headers.get(HEADER) or uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[HEADER] = request_id

        return response


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")
