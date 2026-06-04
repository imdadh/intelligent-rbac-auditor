"""HTTP middleware for correlation ID propagation.

Every inbound request is assigned a correlation ID using the following
precedence:

1. The value of the ``X-Correlation-ID`` request header, if present and
   non-empty.  This allows upstream gateways, load balancers, or API
   clients to propagate a trace identifier across service boundaries.
2. A freshly generated UUID4, otherwise.

The resolved correlation ID is:

- Stored in the ``correlation_id_var`` ``ContextVar`` defined in
  ``app.core.logging`` so that every structured log record emitted during
  the request lifecycle automatically includes it.
- Echoed back to the caller in the ``X-Correlation-ID`` response header so
  that clients can correlate their own logs with server-side traces.

Usage — register in the FastAPI application factory::

    from app.core.middleware import CorrelationIDMiddleware
    app.add_middleware(CorrelationIDMiddleware)
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id_var

#: The canonical header name used to carry the correlation ID both inbound
#: (client → service) and outbound (service → client).
CORRELATION_ID_HEADER = "X-Correlation-ID"


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that manages per-request correlation IDs.

    The middleware is deliberately thin: it performs no logging itself and
    introduces no dependencies beyond the standard library and Starlette so
    that it can be unit-tested without standing up a full application.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Resolve or generate a correlation ID, bind it to context, and forward.

        Parameters
        ----------
        request:
            The incoming HTTP request.
        call_next:
            The next middleware or route handler in the ASGI chain.

        Returns
        -------
        Response:
            The response produced by the downstream handler, augmented with
            the ``X-Correlation-ID`` header.
        """
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())

        # Bind to the ContextVar so downstream log calls pick it up
        # automatically without any explicit threading or parameter passing.
        token = correlation_id_var.set(correlation_id)
        try:
            response: Response = await call_next(request)
        finally:
            # Always restore the previous context value, even if the handler
            # raises.  This prevents context leakage between requests on
            # re-used event loop tasks.
            correlation_id_var.reset(token)

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response


def setup_middleware(app: object, settings: object) -> None:  # type: ignore[type-arg]
    """Register application-level middleware.

    Called from the application factory.  Currently a no-op placeholder;
    CORS, rate-limiting, and other cross-cutting middleware can be added here.
    """
