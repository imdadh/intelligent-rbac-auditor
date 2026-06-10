"""Unit tests for LLM provider interface and concrete implementations."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.llm import get_llm_provider
from app.llm.base import BaseLLMProvider

# ---------------------------------------------------------------------------
# Fixtures – mock the LangChain model and related components
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_openai_llm() -> MagicMock:
    mock = MagicMock()
    response = MagicMock()
    response.content = '{"findings": [{"id": "f1", "category": "overprivileged", "severity": "high", "principal_id": "u1", "principal_name": "Alice", "role_assignments": [{"roleName": "Global Administrator"}], "evidence": {"days_since_last_signin": 45}, "remediation": "Revoke Global Administrator", "narrative": "Alice has Global Admin but has not used it."}]}'
    mock.invoke.return_value = response
    return mock


@pytest.fixture
def mock_azure_llm() -> MagicMock:
    mock = MagicMock()
    response = MagicMock()
    response.content = '{"findings": [{"id": "f2", "category": "dormant_privileged", "severity": "medium", "principal_id": "u2", "principal_name": "Bob", "role_assignments": [{"roleName": "User Administrator"}], "evidence": {"days_since_last_signin": 62}, "remediation": "Remove assignment", "narrative": "Bob\'s User Admin assignment is dormant."}]}'
    mock.invoke.return_value = response
    return mock


# ---------------------------------------------------------------------------
# Tests for BaseLLMProvider (abstract interface)
# ---------------------------------------------------------------------------


class TestBaseLLMProvider:
    def test_cannot_instantiate_abstract_class(self) -> None:
        with pytest.raises(TypeError):
            BaseLLMProvider()  # type: ignore[abstract]

    def test_abstract_methods_exist(self) -> None:
        methods = ["analyze_findings", "answer_query"]
        for name in methods:
            assert hasattr(BaseLLMProvider, name), f"Missing abstract method {name}"


# ---------------------------------------------------------------------------
# Tests for get_llm_provider factory
# ---------------------------------------------------------------------------


class TestGetLLMProvider:
    def test_get_llm_provider_returns_openai_provider(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            clear_settings_cache()
            provider = get_llm_provider()
            from app.llm.openai_provider import OpenAIProvider

            assert isinstance(provider, OpenAIProvider)

    def test_get_llm_provider_returns_azure_provider(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "azure_openai",
                "AZURE_OPENAI_API_KEY": "key",
                "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "gpt-4",
            },
            clear=True,
        ):
            clear_settings_cache()
            provider = get_llm_provider()
            from app.llm.azure_provider import AzureOpenAIProvider

            assert isinstance(provider, AzureOpenAIProvider)

    def test_get_llm_provider_raises_on_unknown_provider(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "unknown", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            clear_settings_cache()
            with pytest.raises(ValueError):
                get_llm_provider()


# ---------------------------------------------------------------------------
# Tests for OpenAIProvider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    @pytest.fixture(autouse=True)
    def _setup_env(self) -> None:
        env_patch = patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test-key",
                "OPENAI_MODEL": "gpt-4o-mini",
            },
            clear=True,
        )
        env_patch.start()
        yield
        env_patch.stop()

    def _make_provider(self, mock_model: MagicMock) -> BaseLLMProvider:
        from app.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
        provider._model = mock_model
        return provider

    def test_instantiation_succeeds(self) -> None:
        from app.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
        assert provider is not None
        assert provider._model is not None

    def test_analyze_findings_returns_expected_structure(self, mock_openai_llm: MagicMock) -> None:
        provider = self._make_provider(mock_openai_llm)
        preprocessed = [
            {
                "user_id": "u1",
                "display_name": "Alice",
                "days_since_last_signin": 45,
                "role_tiers": ["critical"],
                "privileged_role_count": 1,
                "assignment_types": ["direct"],
            }
        ]
        findings = provider.analyze_findings(preprocessed)
        assert isinstance(findings, list)
        assert len(findings) == 1
        finding = findings[0]
        assert "id" in finding
        assert "category" in finding
        assert "severity" in finding
        assert "principal_id" in finding
        assert "principal_name" in finding
        assert finding["principal_id"] == "u1"
        assert finding["category"] == "overprivileged"

    def test_analyze_findings_handles_empty_input(self, mock_openai_llm: MagicMock) -> None:
        provider = self._make_provider(mock_openai_llm)
        findings = provider.analyze_findings([])
        assert findings == []

    def test_answer_query_returns_structured_response(self, mock_openai_llm: MagicMock) -> None:
        provider = self._make_provider(mock_openai_llm)
        answer_response = MagicMock()
        answer_response.content = (
            '{"structured": [{"userId": "u1", "roleName": "Global Admin"}], '
            '"summary": "Found 1 user."}'
        )
        mock_openai_llm.invoke.return_value = answer_response
        result = provider.answer_query(
            "Show users with Global Admin",
            {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []},
        )
        assert isinstance(result, dict)
        assert "structured" in result
        assert "summary" in result
        assert result["summary"] == "Found 1 user."

    def test_answer_query_handles_unanswerable(self, mock_openai_llm: MagicMock) -> None:
        provider = self._make_provider(mock_openai_llm)
        no_answer_response = MagicMock()
        no_answer_response.content = (
            '{"structured": [], "summary": "I cannot answer this question '
            'based on the provided dataset."}'
        )
        mock_openai_llm.invoke.return_value = no_answer_response
        result = provider.answer_query(
            "What color is the sky?",
            {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []},
        )
        assert "cannot answer" in result["summary"]


# ---------------------------------------------------------------------------
# Tests for AzureOpenAIProvider
# ---------------------------------------------------------------------------


class TestAzureOpenAIProvider:
    @pytest.fixture(autouse=True)
    def _setup_env(self) -> None:
        env_patch = patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "azure_openai",
                "AZURE_OPENAI_API_KEY": "azure-key",
                "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "gpt-4",
                "AZURE_OPENAI_API_VERSION": "2024-02-01",
            },
            clear=True,
        )
        env_patch.start()
        yield
        env_patch.stop()

    def _make_provider(self, mock_model: MagicMock) -> BaseLLMProvider:
        from app.llm.azure_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider()
        provider._model = mock_model
        return provider

    def test_instantiation_succeeds(self) -> None:
        from app.llm.azure_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider()
        assert provider is not None
        assert provider._model is not None

    def test_analyze_findings_returns_expected_structure(self, mock_azure_llm: MagicMock) -> None:
        provider = self._make_provider(mock_azure_llm)
        preprocessed = [
            {
                "user_id": "u2",
                "display_name": "Bob",
                "days_since_last_signin": 62,
                "role_tiers": ["high"],
                "privileged_role_count": 1,
                "assignment_types": ["direct"],
            }
        ]
        findings = provider.analyze_findings(preprocessed)
        assert isinstance(findings, list)
        assert len(findings) == 1
        finding = findings[0]
        assert finding["category"] == "dormant_privileged"
        assert finding["severity"] == "medium"
        assert finding["principal_id"] == "u2"

    def test_analyze_findings_handles_empty_input(self, mock_azure_llm: MagicMock) -> None:
        provider = self._make_provider(mock_azure_llm)
        findings = provider.analyze_findings([])
        assert findings == []

    def test_answer_query_returns_structured_response(self, mock_azure_llm: MagicMock) -> None:
        provider = self._make_provider(mock_azure_llm)
        answer_response = MagicMock()
        answer_response.content = '{"structured": [], "summary": "No results found."}'
        mock_azure_llm.invoke.return_value = answer_response
        result = provider.answer_query(
            "List inactive admins",
            {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []},
        )
        assert "structured" in result
        assert "summary" in result
        assert result["summary"] == "No results found."


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestProviderErrorHandling:
    @pytest.fixture(autouse=True)
    def _setup_openai_env(self) -> None:
        env_patch = patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-test-key",
            },
            clear=True,
        )
        env_patch.start()
        yield
        env_patch.stop()

    def _make_openai_provider(self, mock_model: MagicMock) -> BaseLLMProvider:
        from app.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
        provider._model = mock_model
        return provider

    def test_analyze_findings_raises_on_missing_content(self, mock_openai_llm: MagicMock) -> None:
        provider = self._make_openai_provider(mock_openai_llm)
        bad_response = MagicMock()
        bad_response.content = "not valid json"
        mock_openai_llm.invoke.return_value = bad_response
        preprocessed = [{"user_id": "u1", "display_name": "A"}]
        with pytest.raises((ValueError, Exception)):
            provider.analyze_findings(preprocessed)

    def test_analyze_findings_raises_on_llm_exception(self, mock_openai_llm: MagicMock) -> None:
        provider = self._make_openai_provider(mock_openai_llm)
        mock_openai_llm.invoke.side_effect = RuntimeError("API call failed")
        with pytest.raises(RuntimeError, match="API call failed"):
            provider.analyze_findings([{"user_id": "u1"}])

    def test_answer_query_raises_on_llm_exception(self, mock_openai_llm: MagicMock) -> None:
        provider = self._make_openai_provider(mock_openai_llm)
        mock_openai_llm.invoke.side_effect = ConnectionError("Timeout")
        with pytest.raises(ConnectionError, match="Timeout"):
            provider.answer_query(
                "test",
                {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []},
            )
