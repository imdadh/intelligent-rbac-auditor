"""FastAPI application factory for the Intelligent RBAC Policy Auditor.

This module is the single entry-point that Uvicorn targets::

    uvicorn app.main:app --host 0.0.0.0 --port 8000

Responsibilities
----------------
- Instantiate the FastAPI application with metadata used by the auto-generated
  OpenAPI documentation at ``/docs``.
- Call ``configure_logging`` so that every log record emitted after startup is
  structured JSON, regardless of which module emits it.
- Register the ``CorrelationIDMiddleware`` so all requests receive a
  correlation ID that is injected into every downstream log call.
- Register application-level exception handlers that serialise errors into the
  standard ``{ "error": { "code": "...", "message": "..." } }`` envelope.
- Mount a placeholder root route (``GET /``) that will later be replaced by
  the static-file-served web UI.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import CorrelationIDMiddleware

# ---------------------------------------------------------------------------
# Bootstrap logging before anything else so that import-time log calls from
# other modules are captured with the correct level and format.
# ---------------------------------------------------------------------------

settings = get_settings()
configure_logging(log_level=settings.log_level)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application.

    Keeping the factory as a callable (rather than module-level side effects)
    makes it straightforward to instantiate a fresh application in tests
    without re-running global setup.

    Returns
    -------
    FastAPI:
        A fully configured application instance ready to be served by an ASGI
        server.
    """
    _settings = get_settings()

    application = FastAPI(
        title="Intelligent RBAC Policy Auditor",
        description=(
            "A production-grade service that audits Azure AD role assignments "
            "using structured LLM analysis to surface overprivileged accounts "
            "and dormant privileged role assignments."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    # CorrelationIDMiddleware must be added *before* any routing middleware so
    # that the correlation ID is available to all downstream handlers and
    # exception handlers.
    application.add_middleware(CorrelationIDMiddleware)

    # ------------------------------------------------------------------
    # Exception handlers
    # ------------------------------------------------------------------

    @application.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Translate Pydantic / FastAPI validation errors into the standard envelope.

        FastAPI's default 422 response body does not match the project's error
        envelope shape.  This handler re-wraps the error details so that all
        error responses from the service are structurally consistent.
        """
        logger.warning(
            "request_validation_error",
            path=str(request.url.path),
            method=request.method,
            detail=exc.errors(),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "detail": exc.errors(),
                }
            },
        )

    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Catch-all handler for unexpected exceptions.

        Any exception that is not explicitly handled by a route or a more
        specific exception handler will be caught here, logged with full
        context, and returned as a 500 response in the standard envelope.
        Returning a structured response (rather than letting the ASGI server
        emit its own plain-text 500) ensures that clients always receive JSON,
        regardless of the error type.
        """
        logger.exception(
            "unhandled_exception",
            path=str(request.url.path),
            method=request.method,
            exc_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_server_error",
                    "message": "An unexpected error occurred. Please try again later.",
                }
            },
        )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @application.get(
        "/",
        summary="Service root",
        description=(
            "Placeholder root route.  Returns a simple status payload confirming "
            "the service is running.  This endpoint will be superseded by the "
            "static-file-served web UI in a later implementation phase."
        ),
        tags=["meta"],
    )
    async def _root() -> dict:
        return {"status": "ok"}

    logger.info(
        "application_created",
        log_level=_settings.log_level,
        llm_provider=_settings.llm_provider,
        auth_enabled=_settings.auth_enabled,
        rate_limit_per_minute=_settings.rate_limit_per_minute,
    )

    return application


# ---------------------------------------------------------------------------
# Module-level application instance
# ---------------------------------------------------------------------------

#: The application instance referenced by the Uvicorn entrypoint and by
#: FastAPI's TestClient in the test suite.
app: FastAPI = create_app()
