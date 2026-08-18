"""Configuração central para capacidades de LLM e embeddings.

As capacidades de chat e de embedding podem usar provedores diferentes. Isso é
útil, por exemplo, para usar um modelo de chat via OpenRouter e manter um
modelo de embedding local durante uma migração — ou para rotear ambos pelo
OpenRouter com uma única chave.

O módulo deliberadamente lê o ambiente a cada chamada. Assim, o comportamento
existente de permitir trocar provider/modelo sem reiniciar o processo é
preservado, sem espalhar regras de precedência entre os componentes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from decisionssearch.infrastructure.config.env_utils import env_int


PROVIDER_CONFIGS: dict[str, dict[str, str | int]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "chat_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 512,
    },
    "zai": {
        "base_url": "https://api.z.ai/api/paas/v4",
        "chat_model": "glm-5.1",
        "embedding_model": "embedding-3",
        "embedding_dimensions": 1024,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "chat_model": "openai/gpt-4o-mini",
        "embedding_model": "openai/text-embedding-3-small",
        "embedding_dimensions": 512,
    },
    "gemini": {
        "base_url": "",
        "chat_model": "gemini-2.0-flash",
        "embedding_model": "text-embedding-004",
        "embedding_dimensions": 768,
    },
    "local": {
        "base_url": "",
        "chat_model": "",
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dimensions": 384,
    },
}

_API_KEY_ENV_BY_PROVIDER = {
    "openai": "OPENAI_API_KEY",
    "zai": "ZAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@dataclass(frozen=True)
class ModelProviderSettings:
    """Resolved settings for one capability (chat or embeddings)."""

    capability: str
    provider: str
    api_key: str
    base_url: str
    model: str
    dimensions: int | None = None
    default_headers: dict[str, str] | None = None


def get_llm_provider() -> str:
    return os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini"


def get_embedding_provider() -> str:
    """Resolve o provider de embedding; por padrão, acompanha o provider de LLM."""
    configured = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
    return configured or get_llm_provider()


def _provider_config(provider: str) -> dict[str, str | int]:
    return PROVIDER_CONFIGS.get(provider, {})


def _provider_api_key(provider: str, *, capability: str) -> str:
    # Um override específico da capacidade evita obrigar o chat e o embedding a
    # compartilhar credenciais. A chave específica do provider continua tendo
    # precedência sobre LLM_API_KEY, como já fazia a configuração anterior.
    if capability == "embedding":
        explicit_embedding_key = os.getenv("EMBEDDING_API_KEY", "").strip()
        if explicit_embedding_key:
            return explicit_embedding_key

    provider_key = os.getenv(_API_KEY_ENV_BY_PROVIDER.get(provider, ""), "").strip()
    if provider_key:
        return provider_key
    return os.getenv("LLM_API_KEY", "").strip()


def get_llm_api_key() -> str:
    return _provider_api_key(get_llm_provider(), capability="llm")


def get_embedding_api_key() -> str:
    return _provider_api_key(get_embedding_provider(), capability="embedding")


def _base_url(provider: str, *, capability: str) -> str:
    if capability == "embedding":
        custom = os.getenv("EMBEDDING_BASE_URL", "").strip()
    else:
        custom = os.getenv("LLM_BASE_URL", "").strip()
    if custom:
        return custom

    provider_custom = os.getenv(f"{provider.upper()}_BASE_URL", "").strip()
    if provider_custom:
        return provider_custom

    if provider == "gemini":
        if capability == "embedding":
            return os.getenv(
                "GEMINI_EMBEDDING_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta",
            ).strip()
        return os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ).strip()

    return str(_provider_config(provider).get("base_url", ""))


def get_llm_base_url() -> str:
    """Base URL de chat para clientes OpenAI-compatible (inclui Gemini)."""
    return _base_url(get_llm_provider(), capability="llm")


def get_embedding_base_url() -> str:
    return _base_url(get_embedding_provider(), capability="embedding")


def get_llm_chat_model() -> str:
    custom = os.getenv("LLM_CHAT_MODEL", "").strip()
    if custom:
        return custom
    return str(_provider_config(get_llm_provider()).get("chat_model", "gpt-4o-mini"))


def get_embedding_model() -> str:
    custom = os.getenv("EMBEDDING_MODEL", "").strip()
    if custom:
        return custom
    provider = get_embedding_provider()
    if provider == "local":
        return os.getenv("LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2").strip() or "all-MiniLM-L6-v2"
    return str(_provider_config(provider).get("embedding_model", "text-embedding-3-small"))


def get_embedding_dimensions() -> int:
    provider = get_embedding_provider()
    provider_default = int(_provider_config(provider).get("embedding_dimensions", 768))
    explicit = os.getenv("EMBEDDING_DIMENSIONS", "").strip()
    if explicit:
        return env_int("EMBEDDING_DIMENSIONS", provider_default)
    if provider == "local":
        return env_int("LOCAL_EMBEDDING_DIMENSIONS", provider_default)
    return provider_default


def get_openrouter_headers(provider: str) -> dict[str, str]:
    """Retorna headers opcionais de atribuição sem vazar configuração a outros providers."""
    if provider != "openrouter":
        return {}

    headers: dict[str, str] = {}
    referer = (
        os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
        or os.getenv("OPENROUTER_SITE_URL", "").strip()
    )
    title = os.getenv("OPENROUTER_APP_TITLE", "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-Title"] = title
    return headers


def get_llm_settings() -> ModelProviderSettings:
    provider = get_llm_provider()
    return ModelProviderSettings(
        capability="llm",
        provider=provider,
        api_key=get_llm_api_key(),
        base_url=get_llm_base_url(),
        model=get_llm_chat_model(),
        default_headers=get_openrouter_headers(provider),
    )


def get_embedding_settings() -> ModelProviderSettings:
    provider = get_embedding_provider()
    return ModelProviderSettings(
        capability="embedding",
        provider=provider,
        api_key=get_embedding_api_key(),
        base_url=get_embedding_base_url(),
        model=get_embedding_model(),
        dimensions=get_embedding_dimensions(),
        default_headers=get_openrouter_headers(provider),
    )
