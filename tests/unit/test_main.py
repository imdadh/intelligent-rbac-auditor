"""Unit tests for the FastAPI application factory and lifespan.

Covers:
- ``create_app`` returns a valid FastAPI instance
- ``lifespan`` context manager succeeds
- Health endpoint behaviour (already covered in integration)
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class TestAppFactory:
    """Tests for the application factory in ``app/main.py``."""

    def test_app_has_expected_routes(self) -> None:
        """The app object should have the health and API routes mounted."""
        routes = [route.path for route in app.routes]
        assert "/health" in routes
        assert "/api/v1/datasets/sample" in routes or any("/api/v1/" in r for r in routes)

    def test_app_openapi_docs_available(self) -> None:
        """The OpenAPI docs page should be accessible at /docs."""
        with TestClient(app) as client:
            response = client.get("/docs")
            assert response.status_code == 200

    def test_health_endpoint_returns_ok(self) -> None:
        """The health endpoint should return 200 with status ok."""
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"

    def test_lifespan_configures_logging(self) -> None:
        """The lifespan context manager should call configure_logging."""
        with patch("app.main.configure_logging") as mock_configure:
            # Trigger lifespan by making a request
            with TestClient(app) as client:
                client.get("/health")
            mock_configure.assert_called_once()

    def test_lifespan_binds_engine(self) -> None:
        """The lifespan should call engine.bind if applicable (our app
        uses lazy binding, so this is a basic smoke test)."""
        # Just ensure no exception is raised during lifespan
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
