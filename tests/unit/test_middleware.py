from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache on get_settings before each test to ensure
    environment changes take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    """Return a basic TestClient without modifying settings."""
    return TestClient(app)


@pytest.fixture
def client_with_low_rate_limit() -> TestClient:
    """Return a TestClient but override the rate limit to a low value
    (2 per minute) so we can test rate-limit behaviour quickly."""
    # Patch the environment variable before settings are read
    with patch.dict(os.environ, {"RATE_LIMIT_PER_MINUTE": "2"}):
        get_settings.cache_clear()
        yield TestClient(app)


@pytest.fixture
def client_with_auth_enabled() -> TestClient:
    """Return a TestClient with authentication enabled and a known key."""
    with patch.dict(
        os.environ,
        {
            "AUTH_ENABLED": "true",
            "API_KEY": "test-api-key-123",
        },
    ):
        get_settings.cache_clear()
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Rate-Limiting Tests
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Verify the slowapi rate-limiter correctly limits requests."""

    def test_rate_limit_exceeded(self, client_with_low_rate_limit):
        """When rate limit is 2/min, the third request within the same
        minute should return 429 Too Many Requests."""
        client = client_with_low_rate_limit
        # First request
        resp = client.get("/health")
        assert resp.status_code == 200

        # Second request
        resp = client.get("/health")
        assert resp.status_code == 200

        # Third request – should exceed the limit
        resp = client.get("/health")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_rate_limit_not_exceeded_when_below_limit(self, client):
        """With default limit of 60/min, one request should succeed."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_rate_limit_different_endpoints(self, client_with_low_rate_limit):
        """Rate limit is per-client IP, so hitting different endpoints
        still counts against the same bucket."""
        client = client_with_low_rate_limit
        # Two requests to different endpoints
        resp1 = client.get("/health")
        assert resp1.status_code == 200

        resp2 = client.get("/docs")
        assert resp2.status_code == 200

        # Third request should be blocked regardless of endpoint
        resp3 = client.get("/health")
        assert resp3.status_code == 429

    def test_rate_limit_resets_after_window(self, client_with_low_rate_limit):
        """After the rate-limit window (1 minute) the count resets.
        This test is intentionally brief; we verify the Retry-After header
        and rely on slowapi's internal logic."""
        client = client_with_low_rate_limit
        # Exhaust the limit
        client.get("/health")
        client.get("/health")
        resp = client.get("/health")
        assert resp.status_code == 429
        retry_after = int(resp.headers.get("Retry-After", "0"))
        # The retry-after should be >0 and <=60
        assert 0 < retry_after <= 60


# ---------------------------------------------------------------------------
# Authentication Middleware Tests
# ---------------------------------------------------------------------------


class TestAuthentication:
    """Verify the AuthenticationMiddleware correctly enforces API key auth."""

    def test_auth_disabled_no_header(self, client):
        """When AUTH_ENABLED is false, requests without an Authorization
        header should succeed."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_auth_enabled_no_header(self, client_with_auth_enabled):
        """When AUTH_ENABLED is true, requests without an Authorization
        header should receive 401."""
        resp = client_with_auth_enabled.get("/api/v1/datasets/sample")
        assert resp.status_code == 401
        assert "Missing or malformed Authorization header" in resp.text

    def test_auth_enabled_wrong_key(self, client_with_auth_enabled):
        """When AUTH_ENABLED is true, requests with an incorrect Bearer
        token should receive 401."""
        headers = {"Authorization": "Bearer wrong-key"}
        resp = client_with_auth_enabled.get("/api/v1/datasets/sample", headers=headers)
        assert resp.status_code == 401
        assert "Invalid API key" in resp.text

    def test_auth_enabled_valid_key(self, client_with_auth_enabled):
        """When AUTH_ENABLED is true, requests with the correct API key
        should succeed."""
        headers = {"Authorization": "Bearer test-api-key-123  # pragma: allowlist secret"}
        resp = client_with_auth_enabled.get("/api/v1/datasets/sample", headers=headers)
        # The endpoint might return 404 if no dataset exists (acceptable),
        # but it should NOT return 401.
        assert resp.status_code != 401

    def test_auth_enabled_public_path_no_key(self, client_with_auth_enabled):
        """The /health endpoint should be accessible without an API key
        even when AUTH_ENABLED is true."""
        resp = client_with_auth_enabled.get("/health")
        assert resp.status_code == 200

    def test_auth_enabled_docs_path_no_key(self, client_with_auth_enabled):
        """The /docs endpoint should be accessible without an API key."""
        resp = client_with_auth_enabled.get("/docs")
        assert resp.status_code == 200

    def test_auth_enabled_malformed_header(self, client_with_auth_enabled):
        """A header without 'Bearer ' should be rejected."""
        headers = {"Authorization": "Basic some-token"}
        resp = client_with_auth_enabled.get("/api/v1/datasets/sample", headers=headers)
        assert resp.status_code == 401
        assert "Missing or malformed" in resp.text

    def test_auth_enabled_empty_bearer_token(self, client_with_auth_enabled):
        """A Bearer token that is empty should be treated as invalid."""
        headers = {"Authorization": "Bearer "}
        resp = client_with_auth_enabled.get("/api/v1/datasets/sample", headers=headers)
        assert resp.status_code == 401
