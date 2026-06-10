"""Unit tests for the audit pipeline service.

These tests verify that ``run_audit`` and related functions work
correctly, including status transitions, error handling, and the
integration of preprocessing and the LLM provider.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.audit import Audit
from app.services.pipeline import run_audit


@pytest.fixture
def mock_session() -> MagicMock:
    """Return a mock SQLAlchemy session."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    return session


@pytest.fixture
def mock_llm_provider() -> MagicMock:
    """Return a mock LLM provider that returns empty findings."""
    provider = MagicMock()
    provider.analyze_findings.return_value = []
    return provider


@pytest.fixture
def pending_audit(mock_session: MagicMock) -> Audit:
    """Create a placeholder Audit with status 'pending'."""
    audit = Audit(
        dataset_id=uuid.uuid4(),
        status="pending",
        parameters={"dormant_threshold_days": 30},
    )
    audit.id = uuid.uuid4()
    return audit


class TestRunAudit:
    """Tests for the ``run_audit`` entry point."""

    @patch("app.services.pipeline.preprocess_dataset")
    @patch("app.services.pipeline.get_llm_provider")
    @patch("app.services.pipeline.SessionLocal")
    def test_successful_run(
        self,
        mock_session_local: MagicMock,
        mock_get_provider: MagicMock,
        mock_preprocess: MagicMock,
        pending_audit: Audit,
    ) -> None:
        """A successful pipeline run should mark the audit as completed
        and store findings."""
        # Arrange
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = pending_audit

        mock_dataset = MagicMock()
        mock_dataset.raw_data = {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []}
        mock_session.query.return_value.get.return_value = mock_dataset

        mock_preprocess.return_value = [
            {
                "user_id": "u1",
                "display_name": "Alice",
                "days_since_last_signin": 45,
                "role_tiers": ["critical"],
                "privileged_role_count": 1,
                "assignment_types": ["direct"],
            }
        ]

        mock_provider = MagicMock()
        mock_provider.analyze_findings.return_value = [
            {
                "id": "f1",
                "category": "overprivileged",
                "severity": "high",
                "principal_id": "u1",
                "principal_name": "Alice",
                "role_assignments": [],
                "evidence": {},
                "remediation": "Review permissions.",
                "narrative": "Alice is overprivileged.",
            }
        ]
        mock_get_provider.return_value = mock_provider

        # Act
        run_audit(pending_audit.id)

        # Assert
        # The audit should be updated to completed with summary
        assert pending_audit.status == "completed"
        assert pending_audit.summary is not None
        assert pending_audit.summary["total_findings"] == 1
        mock_session.commit.assert_called()

    @patch("app.services.pipeline.preprocess_dataset")
    @patch("app.services.pipeline.get_llm_provider")
    @patch("app.services.pipeline.SessionLocal")
    def test_pipeline_failure_sets_status_failed(
        self,
        mock_session_local: MagicMock,
        mock_get_provider: MagicMock,
        mock_preprocess: MagicMock,
        pending_audit: Audit,
    ) -> None:
        """If an exception occurs during preprocessing, the audit status
        becomes 'failed' and the error is recorded."""
        # Arrange
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = pending_audit

        mock_dataset = MagicMock()
        mock_dataset.raw_data = {"users": [], "roleAssignments": []}
        mock_session.query.return_value.get.return_value = mock_dataset

        mock_preprocess.side_effect = ValueError("Missing required key")

        # Act
        run_audit(pending_audit.id)

        # Assert
        assert pending_audit.status == "failed"
        assert "Missing required key" in pending_audit.error_message
        mock_session.commit.assert_called()

    @patch("app.services.pipeline.SessionLocal")
    def test_audit_not_found_leaves_no_side_effects(self, mock_session_local: MagicMock) -> None:
        """If the audit ID does not exist, the function should silently
        return (or log a warning)."""
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act (should not raise)
        run_audit(uuid.uuid4())

        # Assert no commit or change
        mock_session.commit.assert_not_called()

    @patch("app.services.pipeline.preprocess_dataset")
    @patch("app.services.pipeline.get_llm_provider")
    @patch("app.services.pipeline.SessionLocal")
    def test_audit_with_no_users_produces_no_findings(
        self,
        mock_session_local: MagicMock,
        mock_get_provider: MagicMock,
        mock_preprocess: MagicMock,
        pending_audit: Audit,
    ) -> None:
        """A dataset with no users results in an empty findings list."""
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = pending_audit

        mock_dataset = MagicMock()
        mock_dataset.raw_data = {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []}
        mock_session.query.return_value.get.return_value = mock_dataset

        mock_preprocess.return_value = []
        mock_provider = MagicMock()
        mock_provider.analyze_findings.return_value = []
        mock_get_provider.return_value = mock_provider

        run_audit(pending_audit.id)

        assert pending_audit.status == "completed"
        assert pending_audit.summary["total_findings"] == 0
