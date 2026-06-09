from __future__ import annotations

from fastapi import HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces optional API key authentication.

    When ``AUTH_ENABLED=true``, every request (except ``/health``) must
    include an ``Authorization: Bearer <key>`` header whose value matches
    the ``API_KEY`` environment variable.  Requests without a valid key
    receive a ``401 Unauthorized`` response.

    When ``AUTH_ENABLED=false`` (the default), the middleware is a no-op
    and all requests pass through unchanged.
    """

    #: Paths that are always allowed without authentication.
    PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        settings = get_settings()

        # If auth is disabled, forward immediately.
        if not settings.auth_enabled:
            return await call_next(request)

        # Allow public paths unconditionally.
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)

        # Extract the Bearer token from the Authorization header.
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or malformed Authorization header. Expected format: Bearer <api_key>",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header.removeprefix("Bearer ").strip()
        if token != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Token is valid — forward the request.
        return await call_next(request)
