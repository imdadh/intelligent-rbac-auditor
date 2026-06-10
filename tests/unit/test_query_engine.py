"""Unit tests for the natural-language query engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.query import QueryResponse
from app.services.query_engine import answer_query


@pytest.fixture
def mock_llm_provider() -> MagicMock:
    """Return a mock LLM provider."""
    provider = MagicMock()
    provider.answer_query.return_value = QueryResponse(
        question="test",
        structured_data=[{"userId": "u1"}],
        natural_language_summary="Found 1 user.",
        answerable=True,
    )
    return provider


@pytest.fixture
def mock_session() -> MagicMock:
    """Return a mock DB session that yields a dataset with sample data."""
    session = MagicMock()
    dataset = MagicMock()
    dataset.raw_data = {
        "users": [{"id": "u1", "displayName": "Alice"}],
        "roleAssignments": [],
        "signInLogs": [],
        "groups": [],
    }
    session.query.return_value.get.return_value = dataset
    return session


class TestAnswerQuery:
    """Tests for the top-level ``answer_query`` function."""

    @patch("app.services.query_engine.QueryLog")
    @patch("app.services.query_engine.get_llm_provider")
    def test_answerable_query(
        self,
        mock_get_provider: MagicMock,
        mock_query_log: MagicMock,
        mock_llm_provider: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """An answerable query returns structured data and a summary."""
        mock_get_provider.return_value = mock_llm_provider

        response = answer_query(
            db=mock_session,
            dataset_id="some-uuid",
            question="Show users with Global Admin",
        )

        assert response.answerable is True
        assert len(response.structured_data) == 1
        assert "Found 1" in response.summary
        # A QueryLog should be persisted
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @patch("app.services.query_engine.get_llm_provider")
    def test_dataset_not_found(self, mock_get_provider: MagicMock, mock_session: MagicMock) -> None:
        """If the dataset does not exist, a 404-style exception should be
        raised (or the function returns a graceful error)."""
        mock_session.query.return_value.get.return_value = None

        with pytest.raises(Exception) as excinfo:
            answer_query(
                db=mock_session,
                dataset_id="nonexistent",
                question="Any admins?",
            )
        assert "Dataset not found" in str(excinfo.value)

    @patch("app.services.query_engine.get_llm_provider")
    def test_llm_failure_is_handled(
        self, mock_get_provider: MagicMock, mock_session: MagicMock
    ) -> None:
        """If the LLM call fails, the query should still return a graceful
        error rather than crashing."""
        mock_provider = MagicMock()
        mock_provider.answer_query.side_effect = RuntimeError("API failure")
        mock_get_provider.return_value = mock_provider

        response = answer_query(
            db=mock_session,
            dataset_id="some-uuid",
            question="Test",
        )
        assert response.answerable is False
        assert "error" in response.summary.lower()
