from __future__ import annotations

from app.core.config import get_settings
from app.llm.azure_provider import AzureOpenAIProvider
from app.llm.base import BaseLLMProvider
from app.llm.openai_provider import OpenAIProvider


def get_llm_provider() -> BaseLLMProvider:
    """Return an LLM provider instance based on the ``LLM_PROVIDER`` environment variable.

    The variable is read from the application settings (see :func:`app.core.config.get_settings`).
    Supported values are:

    - ``"openai"`` → :class:`~app.llm.openai_provider.OpenAIProvider`
    - ``"azure_openai"`` → :class:`~app.llm.azure_provider.AzureOpenAIProvider`

    Returns
    -------
    BaseLLMProvider
        Initialised provider ready to be used by the audit pipeline.

    Raises
    ------
    ValueError
        If ``LLM_PROVIDER`` is neither ``"openai"`` nor ``"azure_openai"``.
    """
    settings = get_settings()
    provider_name = settings.llm_provider
    if provider_name == "openai":
        return OpenAIProvider()
    if provider_name == "azure_openai":
        return AzureOpenAIProvider()
    raise ValueError(
        f"Unsupported LLM provider: '{provider_name}'. "
        "Set LLM_PROVIDER to 'openai' or 'azure_openai'."
    )
