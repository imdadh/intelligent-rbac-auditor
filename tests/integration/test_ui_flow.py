from __future__ import annotations

import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.base import Base, get_db
from app.schemas.finding import FindingSchema

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///./test_ui_flow.db"


@pytest.fixture(scope="module")
def db_session():
    """Create a fresh SQLite database, yield a session, and clean up."""
    engine = create_engine(TEST_DB_URL, echo=False)
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        db_path = Path("./test_ui_flow.db")
        if db_path.exists():
            db_path.unlink()


@pytest.fixture(scope="module")
def test_client(db_session):
    """FastAPI TestClient with overridden database dependency."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# Test: UI Flow
# --------------------------------------------------------------------------


class TestUIFlow:
    """Simulate the complete UI flow: load data -> run audit -> view findings -> ask query."""

    def test_full_ui_flow(self, test_client, db_session):
        """
        Execute the exact steps a user would take in the web UI:
        1. Load sample data (POST /api/v1/datasets/sample)
        2. Trigger an audit (POST /api/v1/audits)
        3. Poll until completed
        4. Verify findings have severity badges (severity field)
        5. Ask a natural-language query (POST /api/v1/query)
        """
        # ------------------------------------------------------------------
        # Step 1: Load sample dataset
        # ------------------------------------------------------------------
        response = test_client.post("/api/v1/datasets/sample")
        assert response.status_code == 201, f"Load sample failed: {response.text}"
        dataset_id = response.json()["data"]["id"]
        assert dataset_id is not None

        # ------------------------------------------------------------------
        # Step 2: Trigger audit (mock LLM provider to return known findings)
        # ------------------------------------------------------------------
        # We need to mock the LLM provider inside the background task.
        # The background task uses app.llm.openai_provider or azure_provider.
        # We'll mock BaseLLMProvider.analyze_findings to return a predefined FindingSchema list.
        mock_analyze_findings = MagicMock(
            return_value=[
                FindingSchema(
                    id=uuid.uuid4(),
                    category="overprivileged",
                    severity="critical",
                    principal_id="f47ac10b-58cc-4372-a567-0e02b2c3d479",
                    principal_name="Alice Admin",
                    principal_type="Member",
                    role_assignments=[
                        {
                            "role_name": "Global Administrator",
                            "assignment_type": "direct",
                        }
                    ],
                    evidence={
                        "days_since_last_sign_in": 0.5,
                        "role_tier": "critical",
                        "assignment_type": "direct",
                        "privileged_role_count": 3,
                    },
                    remediation="Remove Global Administrator role and assign more specific roles.",
                    narrative="Alice Admin holds Global Administrator but signs in daily and rarely uses admin features.",
                ),
                FindingSchema(
                    id=uuid.uuid4(),
                    category="dormant_privileged",
                    severity="high",
                    principal_id="550e8400-e29b-41d4-a716-446655440000",
                    principal_name="Bob Backup",
                    principal_type="ServicePrincipal",
                    role_assignments=[
                        {
                            "role_name": "Privileged Role Administrator",
                            "assignment_type": "group",
                        }
                    ],
                    evidence={
                        "days_since_last_sign_in": 120.0,
                        "role_tier": "critical",
                        "assignment_type": "group",
                    },
                    remediation="Remove the service principal from the privileged group.",
                    narrative="Bob Backup has not signed in for 120 days but still holds Privileged Role Administrator.",
                ),
            ]
        )

        # Patch the analyze_findings method on the abstract base class
        # so that whatever concrete provider is instantiated in the background task, it will use this mock.
        with patch.object(
            app.llm.base.BaseLLMProvider,
            "analyze_findings",
            mock_analyze_findings,
        ):
            # Start the audit
            response = test_client.post(
                "/api/v1/audits",
                json={"dataset_id": dataset_id},
            )
            assert response.status_code == 202, f"Trigger audit failed: {response.text}"
            audit_id = response.json()["data"]["id"]
            assert audit_id is not None

        # ------------------------------------------------------------------
        # Step 3: Poll audit status until completed (or timeout)
        # ------------------------------------------------------------------
        status = "pending"
        max_retries = 30
        retries = 0
        while status != "completed" and retries < max_retries:
            time.sleep(1)
            response = test_client.get(f"/api/v1/audits/{audit_id}")
            assert response.status_code == 200, f"Poll audit failed: {response.text}"
            status = response.json()["data"]["status"]
            retries += 1

        assert status == "completed", f"Audit did not complete within time. Last status: {status}"

        # ------------------------------------------------------------------
        # Step 4: Verify findings appear with severity badges
        # ------------------------------------------------------------------
        data = response.json()["data"]
        findings = data.get("findings", [])
        assert len(findings) >= 2, f"Expected at least 2 findings, got {len(findings)}"

        for finding in findings:
            assert "severity" in finding, f"Finding missing severity badge: {finding['id']}"
            assert finding["severity"] in (
                "critical",
                "high",
                "medium",
                "low",
            ), f"Unexpected severity value: {finding['severity']}"
            assert finding["category"] in (
                "overprivileged",
                "dormant_privileged",
            ), f"Unexpected category: {finding['category']}"
            # Ensure the narrative is present for human-readable display
            assert "narrative" in finding, f"Finding missing narrative: {finding['id']}"

        # Check that we have one critical and one high as per our mock
        severities = [f["severity"] for f in findings]
        assert "critical" in severities, "No critical severity finding found"
        assert "high" in severities, "No high severity finding found"

        # ------------------------------------------------------------------
        # Step 5: Ask a test query (mock LLM provider for query)
        # ------------------------------------------------------------------
        mock_answer_query = MagicMock(
            return_value={
                "question": "Show users with Global Admin",
                "structured_data": [
                    {
                        "displayName": "Alice Admin",
                        "principal_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
                    }
                ],
                "natural_language_summary": "Alice Admin has Global Administrator.",
                "answerable": True,
            }
        )

        with patch.object(
            app.llm.base.BaseLLMProvider,
            "answer_query",
            mock_answer_query,
        ):
            payload = {
                "dataset_id": dataset_id,
                "question": "Show users with Global Admin",
            }
            response = test_client.post("/api/v1/query", json=payload)
        assert response.status_code == 200, f"Query failed: {response.text}"
        query_data = response.json()["data"]
        assert query_data["answerable"] is True, "Query reported as unanswerable"
        assert len(query_data["structured_data"]) > 0, "Query returned no data"
        assert "Alice Admin" in query_data["natural_language_summary"]

        # Optional: verify query was logged (we can check via the db if needed)
        # For now we just check the API response is well-formed.

    def test_ui_flow_with_load_data_button(self, test_client, db_session):
        """
        Simulate clicking 'Load Sample Data' button: the endpoint returns dataset ID.
        This is a minimal verification without mocking LLM.
        """
        response = test_client.post("/api/v1/datasets/sample")
        assert response.status_code == 201
        dataset_id = response.json()["data"]["id"]
        # Verify the dataset exists
        response = test_client.get(f"/api/v1/datasets/{dataset_id}")
        assert response.status_code == 200
        assert response.json()["data"]["id"] == dataset_id
