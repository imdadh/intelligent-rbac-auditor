"""Integration tests for the full audit pipeline.

These tests exercise the end-to-end flow:
  1. Seed the database with synthetic data (via the dataset ingestion API).
  2. Trigger an audit (POST /api/v1/audits) with a mocked LLM provider.
  3. Poll the audit status until completion.
  4. Retrieve the findings and assert that the known overprivileged and
     dormant accounts (defined in the synthetic dataset) are correctly flagged.

The LLM provider is replaced with a mock so that the pipeline produces
predictable findings regardless of external API availability.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models.base import Base, get_engine
from scripts.generate_synthetic_data import generate_dataset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_known_overprivileged(data: dict) -> set[str]:
    """Return the set of user IDs that are expected to be flagged as
    overprivileged: users with 'Global Administrator' and fewer than 10
    sign-in events."""
    signin_counts: dict[str, int] = {}
    for log in data["signInLogs"]:
        signin_counts[log["userId"]] = signin_counts.get(log["userId"], 0) + 1

    overprivileged = set()
    for ra in data["roleAssignments"]:
        if ra["roleName"] == "Global Administrator":
            uid = ra["principalId"]
            if signin_counts.get(uid, 0) < 10:
                overprivileged.add(uid)
    return overprivileged


def _compute_known_dormant(data: dict, threshold_days: int = 30) -> set[str]:
    """Return the set of user IDs that are expected to be flagged as
    dormant: users with a privileged role and no sign-in in the last
    ``threshold_days`` days, or no sign-ins at all.

    Privileged roles are those considered critical/high: Global Administrator,
    Privileged Role Administrator, Exchange Administrator, SharePoint Administrator,
    User Administrator, etc.  We use the same list as the preprocessor."""
    from app.services.preprocessor import PRIVILEGED_ROLES

    # Compute latest sign-in timestamp per user
    latest_signin: dict[str, str | None] = {}
    for log in data["signInLogs"]:
        uid = log["userId"]
        if latest_signin.get(uid) is None or log["signInTimestamp"] > latest_signin[uid]:
            latest_signin[uid] = log["signInTimestamp"]

    import datetime

    now = datetime.datetime.now(datetime.UTC)

    dormant = set()
    for user in data["users"]:
        uid = user["id"]
        # Does this user have any privileged role?
        has_privileged = any(
            ra["roleName"] in PRIVILEGED_ROLES
            for ra in data["roleAssignments"]
            if ra["principalId"] == uid
        )
        if not has_privileged:
            continue
        last = latest_signin.get(uid)
        if last is None:
            dormant.add(uid)
        else:
            last_dt = datetime.datetime.fromisoformat(last).replace(tzinfo=datetime.UTC)
            days_since = (now - last_dt).days
            if days_since >= threshold_days:
                dormant.add(uid)
    return dormant


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_data() -> dict:
    """Generate the synthetic dataset with seed 42 (deterministic)."""
    return generate_dataset(seed=42)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Any, None, None]:
    """Create tables and provide a connection for the test.

    The fixture ensures the schema exists before each test and drops it
    after, keeping tests isolated.  It uses the same DATABASE_URL as the
    application (overridden in docker-compose for integration tests).
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    yield
    # Drop all tables after test module finishes
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Generator[None, None, None]:
    """Clear the cached settings before each test so environment changes are
    picked up (e.g. if we override DATABASE_URL)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(db_session: None) -> TestClient:
    """Return a FastAPI TestClient with the application."""
    return TestClient(app)


@pytest.fixture
def dataset_id(client: TestClient, synthetic_data: dict) -> str:
    """Ingest the synthetic dataset via the API and return its ID."""
    response = client.post(
        "/api/v1/datasets",
        json=synthetic_data,
        params={"name": "test-integration-dataset"},
    )
    assert response.status_code == 201, f"Dataset ingestion failed: {response.text}"
    return response.json()["data"]["id"]


@pytest.fixture
def mock_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real LLM provider with a mock that returns a fixed set of
    findings based on the preprocessed data.

    The mock inspects the preprocessed input and returns a finding for each
    user that matches the overprivileged or dormant criteria.  This ensures
    the test verifies that the pipeline correctly feeds the preprocessed
    features to the LLM even though the LLM output is predetermined.
    """

    mock_provider = MagicMock()

    def fake_analyze_findings(preprocessed: list[dict]) -> list[dict]:
        findings = []
        for entry in preprocessed:
            # Overprivileged: Global Admin and very few sign-ins (days_since_last_signin > 30)
            if (
                "critical" in entry.get("role_tiers", [])
                and entry.get("days_since_last_signin", 0) is not None
                and entry["days_since_last_signin"] > 30
            ):
                findings.append(
                    {
                        "id": f"op-{entry['user_id']}",
                        "category": "overprivileged",
                        "severity": "high",
                        "principal_id": entry["user_id"],
                        "principal_name": entry["display_name"],
                        "role_assignments": [],  # simplified
                        "evidence": {"days_since_last_signin": entry["days_since_last_signin"]},
                        "remediation": "Review and reduce permissions.",
                        "narrative": f"{entry['display_name']} has a critical role but last signed in {entry['days_since_last_signin']} days ago.",
                    }
                )
            # Dormant: privileged role and no sign-in or very old
            if (
                len(entry.get("role_tiers", [])) > 0
                and (
                    entry.get("days_since_last_signin") is None
                    or entry["days_since_last_signin"] >= 30
                )
                and entry.get("privileged_role_count", 0) > 0
            ):
                findings.append(
                    {
                        "id": f"dp-{entry['user_id']}",
                        "category": "dormant_privileged",
                        "severity": "medium",
                        "principal_id": entry["user_id"],
                        "principal_name": entry["display_name"],
                        "role_assignments": [],
                        "evidence": {"days_since_last_signin": entry.get("days_since_last_signin")},
                        "remediation": "Remove or rotate assignment.",
                        "narrative": f"{entry['display_name']} has privileged role but is inactive.",
                    }
                )
        return findings

    def fake_answer_query(question: str, context: dict) -> dict:
        return {"structured": [], "summary": "Not implemented."}

    mock_provider.analyze_findings.side_effect = fake_analyze_findings
    mock_provider.answer_query.side_effect = fake_answer_query

    monkeypatch.setattr("app.services.pipeline.get_llm_provider", lambda: mock_provider)
    # Also patch at the API level if the audit endpoint imports differently
    monkeypatch.setattr("app.api.audits.get_llm_provider", lambda: mock_provider)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """End-to-end test that exercises dataset ingestion, audit pipeline,
    and finding retrieval."""

    def test_known_overprivileged_accounts_are_flagged(
        self,
        client: TestClient,
        dataset_id: str,
        synthetic_data: dict,
        mock_llm_provider: None,  # fixture is used for its side effect
    ) -> None:
        """Trigger an audit and verify that all known overprivileged accounts
        appear in the findings."""
        expected_overprivileged = _compute_known_overprivileged(synthetic_data)
        assert (
            len(expected_overprivileged) >= 3
        ), "Synthetic data should contain at least 3 overprivileged accounts."

        # Start the audit
        response = client.post("/api/v1/audits", json={"dataset_id": dataset_id})
        assert response.status_code == 202, f"Audit creation failed: {response.text}"
        audit_id = response.json()["data"]["id"]

        # Poll until completed (or fail after timeout)
        import time

        max_wait = 30  # seconds
        start = time.time()
        while time.time() - start < max_wait:
            status_resp = client.get(f"/api/v1/audits/{audit_id}")
            assert status_resp.status_code == 200, f"Status poll failed: {status_resp.text}"
            status_data = status_resp.json()["data"]
            if status_data["status"] == "completed":
                break
            if status_data["status"] == "failed":
                pytest.fail(
                    f"Audit {audit_id} failed: {status_data.get('error_message', 'unknown error')}"
                )
            time.sleep(1)
        else:
            pytest.fail("Audit did not complete within 30 seconds.")

        # Extract findings from the response
        findings = status_data.get("findings", [])
        flagged_ids = {f["principal_id"] for f in findings if f["category"] == "overprivileged"}

        # Assert all expected overprivileged accounts are flagged
        missing = expected_overprivileged - flagged_ids
        assert not missing, (
            f"Expected overprivileged accounts {missing} were not flagged. "
            f"Flagged: {flagged_ids}"
        )

    def test_known_dormant_accounts_are_flagged(
        self,
        client: TestClient,
        dataset_id: str,
        synthetic_data: dict,
        mock_llm_provider: None,
    ) -> None:
        """Trigger an audit and verify that all known dormant accounts
        appear in the findings."""
        expected_dormant = _compute_known_dormant(synthetic_data, threshold_days=30)
        assert (
            len(expected_dormant) >= 3
        ), "Synthetic data should contain at least 3 dormant accounts."

        # Start the audit
        response = client.post("/api/v1/audits", json={"dataset_id": dataset_id})
        assert response.status_code == 202
        audit_id = response.json()["data"]["id"]

        import time

        max_wait = 30
        start = time.time()
        while time.time() - start < max_wait:
            status_resp = client.get(f"/api/v1/audits/{audit_id}")
            assert status_resp.status_code == 200
            status_data = status_resp.json()["data"]
            if status_data["status"] == "completed":
                break
            if status_data["status"] == "failed":
                pytest.fail(
                    f"Audit {audit_id} failed: {status_data.get('error_message', 'unknown error')}"
                )
            time.sleep(1)
        else:
            pytest.fail("Audit did not complete within 30 seconds.")

        findings = status_data.get("findings", [])
        flagged_ids = {f["principal_id"] for f in findings if f["category"] == "dormant_privileged"}

        missing = expected_dormant - flagged_ids
        assert not missing, (
            f"Expected dormant accounts {missing} were not flagged. " f"Flagged: {flagged_ids}"
        )

    def test_audit_returns_pending_status_immediately(
        self,
        client: TestClient,
        dataset_id: str,
    ) -> None:
        """The POST /api/v1/audits endpoint returns 202 with status 'pending'
        before the pipeline finishes."""
        response = client.post("/api/v1/audits", json={"dataset_id": dataset_id})
        assert response.status_code == 202
        data = response.json()["data"]
        assert data["status"] == "pending"
        assert "id" in data

    def test_audit_status_polling_returns_completed(
        self,
        client: TestClient,
        dataset_id: str,
        mock_llm_provider: None,
    ) -> None:
        """The GET /api/v1/audits/{id} endpoint eventually shows 'completed'
        status and includes findings."""
        # Start audit
        resp = client.post("/api/v1/audits", json={"dataset_id": dataset_id})
        audit_id = resp.json()["data"]["id"]

        # Poll until completed or timeout
        for _ in range(30):
            poll = client.get(f"/api/v1/audits/{audit_id}")
            assert poll.status_code == 200
            status_data = poll.json()["data"]
            if status_data["status"] == "completed":
                break
        else:
            pytest.fail("Audit did not complete in time.")

        # Verify findings are present
        findings = status_data.get("findings", [])
        assert len(findings) > 0, "Expected at least one finding."
        for f in findings:
            required_keys = {
                "id",
                "category",
                "severity",
                "principal_id",
                "principal_name",
                "role_assignments",
                "evidence",
                "remediation",
                "narrative",
            }
            assert required_keys.issubset(
                f.keys()
            ), f"Finding missing keys: {required_keys - f.keys()}"
            assert f["category"] in {"overprivileged", "dormant_privileged"}
            assert f["severity"] in {"critical", "high", "medium", "low"}
