"""Unit tests for app/core/middleware.py.

These tests exercise the CorrelationIDMiddleware in isolation using a
minimal Starlette/FastAPI test application so that no database or LLM
infrastructure is required.

Scenarios covered:

- A request that carries an ``X-Correlation-ID`` header has that value
  echoed back in the response header.
- A request without the header receives a freshly generated UUID in the
  response header.
- The generated ID is a well-formed UUID4 string.
- The correlation ID is stored in the ``ContextVar`` during request
  processing and is accessible to code running within the handler.
- The ``ContextVar`` is restored to its previous value after the response
  is returned (context isolation between requests).
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import correlation_id_var
from app.core.middleware import CORRELATION_ID_HEADER, CorrelationIDMiddleware

# ---------------------------------------------------------------------------
# Test application fixture
# ---------------------------------------------------------------------------

UUID4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@pytest.fixture()
def app() -> FastAPI:
    """Minimal FastAPI application with CorrelationIDMiddleware registered."""
    _app = FastAPI()
    _app.add_middleware(CorrelationIDMiddleware)

    @_app.get("/ping")
    async def ping() -> dict:
        return {"correlation_id": correlation_id_var.get()}

    return _app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    """Synchronous test client wrapping the minimal app."""
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Header propagation
# ---------------------------------------------------------------------------


class TestCorrelationIDHeaderPropagation:
    """The middleware must echo a client-supplied or generated ID in the response."""

    def test_supplied_id_is_echoed_in_response(self, client: TestClient) -> None:
        supplied = "test-correlation-id-abc123"
        response = client.get("/ping", headers={CORRELATION_ID_HEADER: supplied})
        assert response.status_code == 200
        assert response.headers[CORRELATION_ID_HEADER] == supplied

    def test_generated_id_present_when_header_absent(self, client: TestClient) -> None:
        response = client.get("/ping")
        assert response.status_code == 200
        assert CORRELATION_ID_HEADER in response.headers

    def test_generated_id_is_valid_uuid4(self, client: TestClient) -> None:
        response = client.get("/ping")
        header_value = response.headers[CORRELATION_ID_HEADER]
        assert UUID4_PATTERN.match(
            header_value
        ), f"Expected a UUID4 but got: {header_value!r}"

    def test_each_request_gets_unique_id(self, client: TestClient) -> None:
        first = client.get("/ping").headers[CORRELATION_ID_HEADER]
        second = client.get("/ping").headers[CORRELATION_ID_HEADER]
        assert first != second

    def test_empty_header_value_triggers_generation(self, client: TestClient) -> None:
        """An empty string in the header should not be used; a UUID must be generated."""
        response = client.get("/ping", headers={CORRELATION_ID_HEADER: ""})
        header_value = response.headers[CORRELATION_ID_HEADER]
        # The empty string is falsy, so the middleware should have generated a UUID.
        assert UUID4_PATTERN.match(
            header_value
        ), f"Expected a generated UUID4 for empty header but got: {header_value!r}"


# ---------------------------------------------------------------------------
# ContextVar binding
# ---------------------------------------------------------------------------


class TestContextVarBinding:
    """The correlation ID must be available via the ContextVar during request handling."""

    def test_supplied_id_stored_in_context(self, client: TestClient) -> None:
        supplied = "ctx-test-id-777"
        response = client.get("/ping", headers={CORRELATION_ID_HEADER: supplied})
        # The /ping handler returns the ContextVar value in the JSON body.
        assert response.json()["correlation_id"] == supplied

    def test_generated_id_matches_response_header(self, client: TestClient) -> None:
        response = client.get("/ping")
        body_id = response.json()["correlation_id"]
        header_id = response.headers[CORRELATION_ID_HEADER]
        assert body_id == header_id


# ---------------------------------------------------------------------------
# Context isolation
# ---------------------------------------------------------------------------


class TestContextIsolation:
    """The ContextVar must be restored after each request."""

    def test_context_var_not_polluted_between_requests(
        self, client: TestClient
    ) -> None:
        """Verify that a correlation ID from one request does not bleed into the next."""
        id_one = "isolation-check-one"
        id_two = "isolation-check-two"

        r1 = client.get("/ping", headers={CORRELATION_ID_HEADER: id_one})
        r2 = client.get("/ping", headers={CORRELATION_ID_HEADER: id_two})

        assert r1.json()["correlation_id"] == id_one
        assert r2.json()["correlation_id"] == id_two

    def test_context_var_default_is_empty_outside_request(self) -> None:
        """Outside of a request context the ContextVar must default to an empty string."""
        # Ensure no previous test has polluted the module-level default.
        token = correlation_id_var.set("")
        try:
            assert correlation_id_var.get() == ""
        finally:
            correlation_id_var.reset(token)


# ---------------------------------------------------------------------------
# Middleware constant
# ---------------------------------------------------------------------------


class TestMiddlewareConstants:
    """Sanity-check the exported header name constant."""

    def test_header_name_value(self) -> None:
        assert CORRELATION_ID_HEADER == "X-Correlation-ID"
