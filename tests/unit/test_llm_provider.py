from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.llm.base import BaseLLMProvider

# ---------------------------------------------------------------------------
# Fixtures – mock the LangChain model and related components
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Clear the cached Settings singleton before and after each test.
    This ensures that tests which modify environment variables see the
    new values, and that subsequent tests start with a clean slate.
    """
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_openai_llm() -> MagicMock:
    """Return a MagicMock that imitates a LangChain ChatOpenAI instance.

    The mock returns a predictable response when invoked via
    ``model.invoke(...)``.  The response object mimics the AIMessage
    structure expected by the provider.
    """
    mock = MagicMock()
    # Simulate a successful invocation returning a message with a fixed
    # textual content.  The concrete providers typically extract the
    # content via ``.content``.
    response = MagicMock()
    response.content = '{"findings": [{"id": "f1", "category": "overprivileged", "severity": "high", "principal_id": "u1", "principal_name": "Alice", "role_assignments": [{"roleName": "Global Administrator"}], "evidence": {"days_since_last_signin": 45}, "remediation": "Revoke Global Administrator", "narrative": "Alice has Global Admin but has not used it."}]}'
    mock.invoke.return_value = response
    return mock


@pytest.fixture
def mock_azure_llm() -> MagicMock:
    """Return a MagicMock that imitates a LangChain AzureChatOpenAI instance."""
    mock = MagicMock()
    response = MagicMock()
    response.content = '{"findings": [{"id": "f2", "category": "dormant_privileged", "severity": "medium", "principal_id": "u2", "principal_name": "Bob", "role_assignments": [{"roleName": "User Administrator"}], "evidence": {"days_since_last_signin": 62}, "remediation": "Remove assignment", "narrative": "Bob's User Admin assignment is dormant."}]}'
    mock.invoke.return_value = response
    return mock


# ---------------------------------------------------------------------------
# Tests for BaseLLMProvider (abstract interface)
# ---------------------------------------------------------------------------


class TestBaseLLMProvider:
    """Ensure the abstract base class enforces the expected interface."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """BaseLLMProvider has abstract methods and cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseLLMProvider()  # type: ignore[abstract]

    def test_abstract_methods_exist(self) -> None:
        """All required methods are declared in the abstract class."""
        methods = ["analyze_findings", "answer_query"]
        for name in methods:
            assert hasattr(BaseLLMProvider, name), f"Missing abstract method {name}"


# ---------------------------------------------------------------------------
# Helper to instantiate OpenAIProvider with minimal mocked dependencies
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    """Unit tests for the OpenAI LLM provider using a mocked LangChain model."""

    @pytest.fixture(autouse=True)
    def _setup_env(self) -> None:
        """Set required environment variables for the OpenAI provider."""
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
        """Create an OpenAIProvider instance, replacing the internal
        LangChain model with a mock."""
        # Import here so that env variables are set before the module is
        # loaded for the first time.
        from app.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
        # Replace the provider's LangChain model attribute with the mock.
        # The concrete class stores the model as `self._model`.
        provider._model = mock_model
        return provider

    def test_instantiation_succeeds(self) -> None:
        """Provider can be created when environment variables are set."""
        from app.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
        assert provider is not None
        assert provider._model is not None

    def test_analyze_findings_returns_expected_structure(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """The provider returns a list of findings with the correct keys."""
        provider = self._make_provider(mock_openai_llm)

        # Provide a minimal preprocessed dataset (list of dicts)
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

        # Ensure we got a list
        assert isinstance(findings, list)
        assert len(findings) == 1
        finding = findings[0]

        # Check required keys per FR-13
        assert "id" in finding
        assert "category" in finding
        assert "severity" in finding
        assert "principal_id" in finding
        assert "principal_name" in finding
        assert "role_assignments" in finding
        assert "evidence" in finding
        assert "remediation" in finding
        assert "narrative" in finding

        # Verify concrete values from our mock response
        assert finding["principal_id"] == "u1"
        assert finding["category"] == "overprivileged"

    def test_analyze_findings_handles_empty_input(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """Empty list of preprocessed data returns an empty list."""
        provider = self._make_provider(mock_openai_llm)
        findings = provider.analyze_findings([])
        assert findings == []

    def test_answer_query_returns_structured_response(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """The answer_query method returns a dict with 'structured' and 'summary' keys."""
        provider = self._make_provider(mock_openai_llm)

        # The mock response for answer_query is different; we need to mock
        # the invoke call again with a custom response. We'll override the
        # mock's return_value for this call.
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

    def test_answer_query_handles_unanswerable(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """When the LLM indicates it cannot answer, the provider returns
        a graceful error-like summary."""
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
    """Unit tests for the Azure OpenAI LLM provider using a mocked model."""

    @pytest.fixture(autouse=True)
    def _setup_env(self) -> None:
        """Set required environment variables for the Azure OpenAI provider."""
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
        """Create an AzureOpenAIProvider instance, replacing the internal
        LangChain model with a mock."""
        from app.llm.azure_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider()
        provider._model = mock_model
        return provider

    def test_instantiation_succeeds(self) -> None:
        """Provider can be created when all Azure environment variables are set."""
        from app.llm.azure_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider()
        assert provider is not None
        assert provider._model is not None

    def test_analyze_findings_returns_expected_structure(
        self, mock_azure_llm: MagicMock
    ) -> None:
        """Returns findings list with correct keys from mocked response."""
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
        assert finding["narrative"].startswith("Bob")

    def test_analyze_findings_handles_empty_input(
        self, mock_azure_llm: MagicMock
    ) -> None:
        """Empty list returns empty list."""
        provider = self._make_provider(mock_azure_llm)
        findings = provider.analyze_findings([])
        assert findings == []

    def test_answer_query_returns_structured_response(
        self, mock_azure_llm: MagicMock
    ) -> None:
        """answer_query returns dict with structured and summary keys."""
        provider = self._make_provider(mock_azure_llm)

        answer_response = MagicMock()
        answer_response.content = (
            '{"structured": [], '
            '"summary": "No results found."}'
        )
        mock_azure_llm.invoke.return_value = answer_response

        result = provider.answer_query(
            "List inactive admins",
            {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []},
        )

        assert "structured" in result
        assert "summary" in result
        assert result["summary"] == "No results found."

    def test_answer_query_handles_unanswerable(
        self, mock_azure_llm: MagicMock
    ) -> None:
        """Graceful handling when the LLM cannot answer."""
        provider = self._make_provider(mock_azure_llm)

        no_answer_response = MagicMock()
        no_answer_response.content = (
            '{"structured": [], "summary": "I am unable to answer this '
            'question with the available data."}'
        )
        mock_azure_llm.invoke.return_value = no_answer_response

        result = provider.answer_query(
            "What is the meaning of life?",
            {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []},
        )

        assert "unable" in result["summary"]


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestProviderErrorHandling:
    """Test how providers behave when the underlying LLM call fails or returns
    malformed output."""

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

    def test_analyze_findings_raises_on_missing_content(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """If the LLM response does not contain parsable JSON, the provider
        raises a ValueError (or appropriate error).
        """
        provider = self._make_openai_provider(mock_openai_llm)

        bad_response = MagicMock()
        bad_response.content = "not valid json"
        mock_openai_llm.invoke.return_value = bad_response

        preprocessed = [{"user_id": "u1", "display_name": "A"}]

        with pytest.raises((ValueError, Exception)):
            provider.analyze_findings(preprocessed)

    def test_analyze_findings_raises_on_llm_exception(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """If the LangChain call itself fails (e.g., network error), the
        provider should propagate the exception.
        """
        provider = self._make_openai_provider(mock_openai_llm)

        mock_openai_llm.invoke.side_effect = RuntimeError("API call failed")

        with pytest.raises(RuntimeError, match="API call failed"):
            provider.analyze_findings([{"user_id": "u1"}])

    def test_answer_query_raises_on_llm_exception(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """LLM failure during query answering raises an exception."""
        provider = self._make_openai_provider(mock_openai_llm)

        mock_openai_llm.invoke.side_effect = ConnectionError("Timeout")

        with pytest.raises(ConnectionError, match="Timeout"):
            provider.answer_query(
                "test",
                {"users": [], "roleAssignments": [], "signInLogs": [], "groups": []},
            )

    def test_analyze_findings_empty_results_on_null_principal_id(
        self, mock_openai_llm: MagicMock
    ) -> None:
        """A finding with a null principal_id may be flagged; we trust the LLM.
        This test just confirms no crash.
        """
        provider = self._make_openai_provider(mock_openai_llm)

        strange_response = MagicMock()
        strange_response.content = (
            '{"findings": [{"id": "f-null", "category": "overprivileged", '
            '"severity": "low", "principal_id": null, "principal_name": "Unknown", '
            '"role_assignments": [], "evidence": {}, "remediation": "", '
            '"narrative": ""}]}'
        )
        mock_openai_llm.invoke.return_value = strange_response

        findings = provider.analyze_findings([{"user_id": "u99"}])
        assert len(findings) == 1
        assert findings[0]["principal_id"] is None
