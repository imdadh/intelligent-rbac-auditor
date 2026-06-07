from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Clear the cached Settings singleton before and after each test.

    This ensures that tests which modify environment variables see the
    new values, and that subsequent tests start with a clean slate.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    """Verify that the Settings class applies the correct defaults when no
    environment variables are set (beyond those that are always required for
    the chosen provider).

    The default provider is 'openai', which normally requires OPENAI_API_KEY.
    To test defaults in isolation we temporarily set a dummy key.
    """

    def test_default_database_url(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.database_url == (
                "postgresql://rbac_user:rbac_password@localhost:5432/rbac_auditor"
            )

    def test_default_llm_provider(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.llm_provider == "openai"

    def test_default_openai_model(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.openai_model == "gpt-4o"

    def test_default_openai_api_key(self) -> None:
        """When OPENAI_API_KEY is not set but provider is openai, validation
        will fail. We test the default value by using the azure provider first."""
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
            settings = get_settings()
            assert settings.openai_api_key is None

    def test_default_auth_enabled(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.auth_enabled is False

    def test_default_api_key(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.api_key is None

    def test_default_rate_limit(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.rate_limit_per_minute == 60

    def test_default_log_level(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.log_level == "INFO"

    def test_default_dormant_threshold_days(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            settings = get_settings()
            assert settings.dormant_threshold_days == 30

    def test_default_azure_openai_api_version(self) -> None:
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
            settings = get_settings()
            assert settings.azure_openai_api_version == "2024-02-01"


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestEnvironmentOverrides:
    """Each setting must be overridable via the corresponding environment
    variable.  We use patch.dict with ``clear=False`` so that the default
    OpenAI key (required by the model validator) can be inherited from the
    test environment or explicitly set.
    """

    def test_database_url_override(self) -> None:
        custom_url = "postgresql://user:pass@host:5432/db"
        with patch.dict(
            os.environ,
            {"DATABASE_URL": custom_url, "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.database_url == custom_url

    def test_llm_provider_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "azure_openai",
                "AZURE_OPENAI_API_KEY": "azure-key",
                "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "gpt-4",
            },
            clear=True,
        ):
            settings = get_settings()
            assert settings.llm_provider == "azure_openai"

    def test_openai_model_override(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_MODEL": "gpt-4-turbo", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.openai_model == "gpt-4-turbo"

    def test_auth_enabled_override(self) -> None:
        with patch.dict(
            os.environ,
            {"AUTH_ENABLED": "true", "API_KEY": "mykey", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.auth_enabled is True
            assert settings.api_key == "mykey"

    def test_rate_limit_override(self) -> None:
        with patch.dict(
            os.environ,
            {"RATE_LIMIT_PER_MINUTE": "120", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.rate_limit_per_minute == 120

    def test_log_level_override(self) -> None:
        with patch.dict(
            os.environ,
            {"LOG_LEVEL": "DEBUG", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.log_level == "DEBUG"

    def test_dormant_threshold_override(self) -> None:
        with patch.dict(
            os.environ,
            {"DORMANT_THRESHOLD_DAYS": "45", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.dormant_threshold_days == 45

    def test_azure_openai_api_version_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AZURE_OPENAI_API_VERSION": "2023-12-01-preview",
                "LLM_PROVIDER": "azure_openai",
                "AZURE_OPENAI_API_KEY": "key",
                "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "gpt-4",
            },
            clear=True,
        ):
            settings = get_settings()
            assert settings.azure_openai_api_version == "2023-12-01-preview"


# ---------------------------------------------------------------------------
# Validator: log_level
# ---------------------------------------------------------------------------


class TestLogLevelValidator:
    """The ``log_level`` validator must normalise casing and reject invalid
    values."""

    def test_lowercase_level_normalised(self) -> None:
        with patch.dict(
            os.environ,
            {"LOG_LEVEL": "debug", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.log_level == "DEBUG"

    def test_mixed_case_normalised(self) -> None:
        with patch.dict(
            os.environ,
            {"LOG_LEVEL": "Warn", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.log_level == "WARNING"

    def test_invalid_level_raises(self) -> None:
        with patch.dict(
            os.environ,
            {"LOG_LEVEL": "TRACE", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with pytest.raises(ValidationError):
                get_settings()


# ---------------------------------------------------------------------------
# Validator: database_url
# ---------------------------------------------------------------------------


class TestDatabaseURLValidator:
    """The ``database_url`` validator must reject non-PostgreSQL schemes and
    syntactically invalid URLs."""

    def test_sqlite_scheme_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "sqlite:///test.db", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with pytest.raises(ValidationError, match="postgresql"):
                get_settings()

    def test_mysql_scheme_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "mysql://user:pass@host/db", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with pytest.raises(ValidationError, match="postgresql"):
                get_settings()

    def test_postgresql_asyncpg_scheme_accepted(self) -> None:
        """The validator should accept asyncpg-style URLs."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+asyncpg://user:pass@host/db",
                "OPENAI_API_KEY": "sk-test",
            },
            clear=True,
        ):
            settings = get_settings()
            # The URL is not modified by the validator; the raw value is preserved.
            assert "asyncpg" in settings.database_url

    def test_missing_drivername_raises(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "not-a-url", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with pytest.raises(ValidationError):
                get_settings()


# ---------------------------------------------------------------------------
# Model validator: provider credentials
# ---------------------------------------------------------------------------


class TestProviderCredentialValidator:
    """The model validator must enforce that the required credentials are
    present for the selected LLM provider."""

    def test_openai_provider_requires_api_key(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}, clear=True):
            with pytest.raises(ValidationError, match="OPENAI_API_KEY must be set"):
                get_settings()

    def test_openai_provider_with_key_succeeds(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-valid"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.llm_provider == "openai"
            assert settings.openai_api_key == "sk-valid"

    def test_azure_provider_requires_all_credentials(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "azure_openai"},
            clear=True,
        ):
            with pytest.raises(ValidationError) as excinfo:
                get_settings()
            err_msg = str(excinfo.value)
            assert "AZURE_OPENAI_API_KEY" in err_msg
            assert "AZURE_OPENAI_ENDPOINT" in err_msg
            assert "AZURE_OPENAI_DEPLOYMENT" in err_msg

    def test_azure_provider_with_all_credentials_succeeds(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "azure_openai",
                "AZURE_OPENAI_API_KEY": "azure-key",
                "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
                "AZURE_OPENAI_DEPLOYMENT": "gpt-4",
            },
            clear=True,
        ):
            settings = get_settings()
            assert settings.llm_provider == "azure_openai"
            assert settings.azure_openai_api_key == "azure-key"

    def test_azure_missing_endpoint_raises(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "azure_openai",
                "AZURE_OPENAI_API_KEY": "azure-key",
                "AZURE_OPENAI_DEPLOYMENT": "gpt-4",
            },
            clear=True,
        ):
            with pytest.raises(ValidationError, match="AZURE_OPENAI_ENDPOINT"):
                get_settings()


# ---------------------------------------------------------------------------
# Model validator: authentication
# ---------------------------------------------------------------------------


class TestAuthValidator:
    """When ``auth_enabled`` is True, ``api_key`` must be set."""

    def test_auth_enabled_requires_api_key(self) -> None:
        with patch.dict(
            os.environ,
            {"AUTH_ENABLED": "true", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with pytest.raises(ValidationError, match="API_KEY must be set"):
                get_settings()

    def test_auth_enabled_with_key_succeeds(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUTH_ENABLED": "true",
                "API_KEY": "my-secret-key",
                "OPENAI_API_KEY": "sk-test",
            },
            clear=True,
        ):
            settings = get_settings()
            assert settings.auth_enabled is True
            assert settings.api_key == "my-secret-key"


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------


class TestGetSettingsCaching:
    """``get_settings`` must return the same object on repeated calls and
    reflect environment changes only after a cache clear."""

    def test_singleton_after_first_call(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            s1 = get_settings()
            s2 = get_settings()
            assert s1 is s2

    def test_cache_clear_forces_reload(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            s1 = get_settings()
            assert s1.log_level == "INFO"

        # Change environment after first call but before cache clear.
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            # Without clearing the cache the old value is returned.
            s2 = get_settings()
            assert s2.log_level == "INFO"
            get_settings.cache_clear()
            s3 = get_settings()
            assert s3.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# Edge cases: optional fields and extreme values
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Corner cases for settings fields with constraints."""

    def test_rate_limit_minimum_one(self) -> None:
        with patch.dict(
            os.environ,
            {"RATE_LIMIT_PER_MINUTE": "1", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.rate_limit_per_minute == 1

    def test_rate_limit_zero_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"RATE_LIMIT_PER_MINUTE": "0", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with pytest.raises(ValidationError):
                get_settings()

    def test_dormant_threshold_minimum_one(self) -> None:
        with patch.dict(
            os.environ,
            {"DORMANT_THRESHOLD_DAYS": "1", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            settings = get_settings()
            assert settings.dormant_threshold_days == 1

    def test_dormant_threshold_zero_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"DORMANT_THRESHOLD_DAYS": "0", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            with pytest.raises(ValidationError):
                get_settings()
