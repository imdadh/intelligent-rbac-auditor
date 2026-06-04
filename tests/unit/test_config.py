"""Unit tests for app/core/config.py.

All tests manipulate environment variables directly and clear the Settings
cache between cases to ensure isolation.
"""

import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure the lru_cache on get_settings doesn't leak state between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestDefaults:
    """Settings must be fully constructible with no environment at all."""

    def test_llm_provider_default(self):
        s = Settings()
        assert s.llm_provider == "openai"

    def test_rate_limit_default(self):
        s = Settings()
        assert s.rate_limit_per_minute == 60

    def test_dormant_threshold_default(self):
        s = Settings()
        assert s.dormant_threshold_days == 30

    def test_log_level_default(self):
        s = Settings()
        assert s.log_level == "INFO"

    def test_auth_disabled_by_default(self):
        s = Settings()
        assert s.auth_enabled is False

    def test_database_url_default(self):
        s = Settings()
        assert "postgresql://" in s.database_url

    def test_openai_model_default(self):
        s = Settings()
        assert s.openai_model == "gpt-4o"

    def test_azure_openai_api_version_default(self):
        s = Settings()
        assert s.azure_openai_api_version == "2024-02-01"

    def test_optional_keys_are_none_by_default(self):
        s = Settings()
        assert s.openai_api_key is None
        assert s.azure_openai_api_key is None
        assert s.azure_openai_endpoint is None
        assert s.azure_openai_deployment is None
        assert s.api_key is None


class TestLLMProviderValidation:
    """llm_provider must be constrained to the two supported literals."""

    def test_openai_is_valid(self):
        s = Settings(llm_provider="openai")
        assert s.llm_provider == "openai"

    def test_azure_openai_is_valid(self):
        s = Settings(llm_provider="azure_openai")
        assert s.llm_provider == "azure_openai"

    def test_invalid_provider_raises(self):
        with pytest.raises(Exception):
            Settings(llm_provider="anthropic")

    def test_invalid_provider_gemini_raises(self):
        with pytest.raises(Exception):
            Settings(llm_provider="gemini")


class TestLogLevelValidation:
    """log_level must be normalised to uppercase and reject unknown values."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("debug", "DEBUG"),
            ("INFO", "INFO"),
            ("Warning", "WARNING"),
            ("error", "ERROR"),
            ("CRITICAL", "CRITICAL"),
        ],
    )
    def test_normalises_to_uppercase(self, raw, expected):
        s = Settings(log_level=raw)
        assert s.log_level == expected

    def test_invalid_log_level_raises(self):
        with pytest.raises(Exception, match="log_level must be one of"):
            Settings(log_level="VERBOSE")

    def test_invalid_log_level_trace_raises(self):
        with pytest.raises(Exception, match="log_level must be one of"):
            Settings(log_level="TRACE")


class TestAuthValidation:
    """When auth is enabled an api_key must be provided."""

    def test_auth_enabled_without_key_raises(self):
        with pytest.raises(Exception, match="api_key must be set"):
            Settings(auth_enabled=True, api_key=None)

    def test_auth_enabled_with_key_is_valid(self):
        s = Settings(auth_enabled=True, api_key="secret-key-abc")
        assert s.auth_enabled is True
        assert s.api_key == "secret-key-abc"

    def test_auth_disabled_without_key_is_valid(self):
        s = Settings(auth_enabled=False, api_key=None)
        assert s.auth_enabled is False

    def test_auth_disabled_with_key_is_also_valid(self):
        """Providing a key while auth is disabled should not raise."""
        s = Settings(auth_enabled=False, api_key="unused-key")
        assert s.auth_enabled is False
        assert s.api_key == "unused-key"


class TestRateLimitBounds:
    """rate_limit_per_minute must be a positive integer."""

    def test_valid_rate_limit(self):
        s = Settings(rate_limit_per_minute=120)
        assert s.rate_limit_per_minute == 120

    def test_zero_rate_limit_raises(self):
        with pytest.raises(Exception):
            Settings(rate_limit_per_minute=0)

    def test_negative_rate_limit_raises(self):
        with pytest.raises(Exception):
            Settings(rate_limit_per_minute=-10)

    def test_minimum_valid_rate_limit(self):
        s = Settings(rate_limit_per_minute=1)
        assert s.rate_limit_per_minute == 1


class TestDormantThresholdBounds:
    """dormant_threshold_days must be a positive integer."""

    def test_valid_threshold(self):
        s = Settings(dormant_threshold_days=90)
        assert s.dormant_threshold_days == 90

    def test_zero_threshold_raises(self):
        with pytest.raises(Exception):
            Settings(dormant_threshold_days=0)

    def test_negative_threshold_raises(self):
        with pytest.raises(Exception):
            Settings(dormant_threshold_days=-1)

    def test_minimum_valid_threshold(self):
        s = Settings(dormant_threshold_days=1)
        assert s.dormant_threshold_days == 1


class TestAzureOpenAIFields:
    """Azure OpenAI-specific fields should accept valid string values."""

    def test_azure_fields_accepted(self):
        s = Settings(
            llm_provider="azure_openai",
            azure_openai_api_key="azure-key-xyz",
            azure_openai_endpoint="https://my-resource.openai.azure.com/",
            azure_openai_deployment="gpt-4o-deployment",
            azure_openai_api_version="2024-05-01",
        )
        assert s.llm_provider == "azure_openai"
        assert s.azure_openai_api_key == "azure-key-xyz"
        assert s.azure_openai_endpoint == "https://my-resource.openai.azure.com/"
        assert s.azure_openai_deployment == "gpt-4o-deployment"
        assert s.azure_openai_api_version == "2024-05-01"

    def test_azure_fields_optional_when_provider_is_openai(self):
        """Missing Azure fields must not cause a hard failure when using OpenAI provider."""
        s = Settings(llm_provider="openai")
        assert s.azure_openai_api_key is None
        assert s.azure_openai_endpoint is None
        assert s.azure_openai_deployment is None


class TestGetSettingsCaching:
    """get_settings() must return the same object on repeated calls."""

    def test_returns_same_instance(self):
        a = get_settings()
        b = get_settings()
        assert a is b

    def test_cache_clear_returns_fresh_instance(self):
        a = get_settings()
        get_settings.cache_clear()
        b = get_settings()
        # Different object identity after cache bust.
        assert a is not b

    def test_get_settings_returns_settings_instance(self):
        s = get_settings()
        assert isinstance(s, Settings)
