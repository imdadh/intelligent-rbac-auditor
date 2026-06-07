"""Application configuration loaded from environment variables.

All settings are sourced from the process environment (or a .env file when
running locally). The Settings object is instantiated once at module import
time and re-used throughout the application via the `get_settings` helper.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url


class Settings(BaseSettings):
    """Central configuration for the RBAC Policy Auditor service.

    All attributes map 1-to-1 with the environment variables documented in
    the project PRD.  Sensitive values (API keys, database credentials) are
    never logged or serialised; they are referenced only at the call-site
    where the underlying SDK is initialised.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Extra fields in the .env file are silently ignored so that local
        # developer .env files can contain convenience variables without
        # causing validation errors.
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql://rbac_user:rbac_password@localhost:5432/rbac_auditor",
        description="PostgreSQL connection string used by SQLAlchemy.",
    )

    # ------------------------------------------------------------------
    # LLM provider
    # ------------------------------------------------------------------
    llm_provider: Literal["openai", "azure_openai"] = Field(
        default="openai",
        description="LLM backend to use.  Must be 'openai' or 'azure_openai'.",
    )

    # OpenAI
    openai_base_url: str | None = Field(
        default=None,
        description="Custom base URL for OpenAI-compatible APIs (e.g. DeepSeek: https://api.deepseek.com).",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="API key for the OpenAI platform.  Required when llm_provider='openai'.",
    )
    openai_model: str = Field(
        default="gpt-4o",
        description="OpenAI model name to use for analysis and query answering.",
    )

    # Azure OpenAI
    azure_openai_api_key: str | None = Field(
        default=None,
        description="API key for Azure OpenAI.  Required when llm_provider='azure_openai'.",
    )
    azure_openai_endpoint: str | None = Field(
        default=None,
        description=(
            "Azure OpenAI resource endpoint URL " "(e.g. https://<resource>.openai.azure.com/)."
        ),
    )
    azure_openai_deployment: str | None = Field(
        default=None,
        description="Azure OpenAI deployment / model name.",
    )
    azure_openai_api_version: str = Field(
        default="2024-02-01",
        description="Azure OpenAI REST API version string.",
    )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    auth_enabled: bool = Field(
        default=False,
        description="When True all API endpoints (except /health) require a valid API key.",
    )
    api_key: str | None = Field(
        default=None,
        description="Expected API key value.  Required when auth_enabled=True.",
    )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    rate_limit_per_minute: int = Field(
        default=60,
        ge=1,
        description="Maximum number of requests per client IP per minute.",
    )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Python logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    )

    # ------------------------------------------------------------------
    # Audit pipeline
    # ------------------------------------------------------------------
    dormant_threshold_days: int = Field(
        default=30,
        ge=1,
        description=(
            "Number of days of inactivity after which a privileged assignment "
            "is considered dormant."
        ),
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Normalise and validate the log level string."""
        normalised = value.upper()
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalised not in valid_levels:
            raise ValueError(f"log_level must be one of {sorted(valid_levels)}, got '{value}'.")
        return normalised

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        """Ensure the database URL is a valid SQLAlchemy connection string.

        This catches obvious typos early (e.g., missing scheme or password
        with special characters) rather than failing at the first connection
        attempt.
        """
        try:
            parsed = make_url(value)
            if not parsed.drivername.startswith("postgresql"):
                raise ValueError(
                    f"Database URL must use the 'postgresql' scheme, got '{parsed.drivername}'."
                )
        except Exception as exc:
            raise ValueError(f"Invalid database_url '{value}': {exc}") from exc
        return value

    @model_validator(mode="after")
    def _validate_provider_credentials(self) -> Settings:
        """Enforce cross-field constraints after all individual fields are validated.

        Validates:
        - LLM provider credentials are present when the corresponding provider is selected.
        - API key is set when authentication is enabled.
        """
        # ------------------------------------------------------------------
        # LLM provider-specific credential requirements
        # ------------------------------------------------------------------
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY must be set when LLM_PROVIDER='openai'.")
        if self.llm_provider == "azure_openai":
            missing = []
            if not self.azure_openai_api_key:
                missing.append("AZURE_OPENAI_API_KEY")
            if not self.azure_openai_endpoint:
                missing.append("AZURE_OPENAI_ENDPOINT")
            if not self.azure_openai_deployment:
                missing.append("AZURE_OPENAI_DEPLOYMENT")
            if missing:
                raise ValueError(
                    f"Missing required Azure OpenAI settings: {', '.join(missing)}. "
                    "These must be set when LLM_PROVIDER='azure_openai'."
                )

        # ------------------------------------------------------------------
        # Authentication key requirement
        # ------------------------------------------------------------------
        if self.auth_enabled and not self.api_key:
            raise ValueError("API_KEY must be set when AUTH_ENABLED=True.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    The result is cached after the first call so that environment variables
    are read exactly once per process lifetime.  In tests, call
    ``get_settings.cache_clear()`` after patching environment variables to
    force a fresh read.
    """
    return Settings()
