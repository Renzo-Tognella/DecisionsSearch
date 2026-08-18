from __future__ import annotations

import pytest

from decisionssearch.domain.shared.exceptions import EmbeddingError
from decisionssearch.infrastructure.ai.embeddings.embedding_providers import (
    OpenAICompatibleEmbeddingProvider,
    create_default_embedding_provider,
)
from decisionssearch.infrastructure.ai.providers.model_provider import (
    get_embedding_settings,
    get_llm_settings,
    get_openrouter_headers,
)


def _clear_model_env(monkeypatch) -> None:
    for name in (
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_CHAT_MODEL",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS",
        "EMBEDDING_REQUEST_DIMENSIONS",
        "OPENAI_API_KEY",
        "ZAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENROUTER_EMBEDDING_ZDR",
        "GEMINI_API_KEY",
        "OPENROUTER_HTTP_REFERER",
        "OPENROUTER_SITE_URL",
        "OPENROUTER_APP_TITLE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_openrouter_key_selects_openai_compatible_embeddings(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    provider = create_default_embedding_provider()

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert provider.provider == "openrouter"
    assert provider.api_key == "sk-or-test"
    assert provider.base_url == "https://openrouter.ai/api/v1"
    assert provider.model == "openai/text-embedding-3-small"
    assert provider.dimensions == 512


def test_embedding_provider_can_use_openrouter_independently_of_chat(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.setenv("EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "4096")

    llm = get_llm_settings()
    embeddings = get_embedding_settings()

    assert llm.provider == "gemini"
    assert llm.model == "gemini-2.0-flash"
    assert embeddings.provider == "openrouter"
    assert embeddings.api_key == "embedding-key"
    assert embeddings.model == "qwen/qwen3-embedding-8b"
    assert embeddings.dimensions == 4096
    assert embeddings.base_url == "https://openrouter.ai/api/v1"


def test_openrouter_headers_are_opt_in(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://decisionssearch.example")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "DecisionsSearch")

    assert get_openrouter_headers("openrouter") == {
        "HTTP-Referer": "https://decisionssearch.example",
        "X-Title": "DecisionsSearch",
    }
    assert get_openrouter_headers("openai") == {}


def test_embedding_provider_fails_early_on_dimension_mismatch(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1024")
    provider = OpenAICompatibleEmbeddingProvider()

    with pytest.raises(EmbeddingError) as error:
        provider._validate_dimensions([0.0] * 512)

    assert error.value.provider == "openrouter"
    assert error.value.context["expected_dimensions"] == 1024
    assert error.value.context["received_dimensions"] == 512


def test_request_dimension_can_be_omitted_for_models_without_truncation(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "4096")
    monkeypatch.setenv("EMBEDDING_REQUEST_DIMENSIONS", "0")
    provider = OpenAICompatibleEmbeddingProvider()

    assert provider._request_kwargs("consulta") == {
        "input": "consulta",
        "model": "openai/text-embedding-3-small",
    }


def test_openrouter_embedding_can_enforce_zdr(monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_EMBEDDING_ZDR", "true")

    provider = OpenAICompatibleEmbeddingProvider()

    assert provider.zdr is True
    assert provider._request_kwargs("consulta")["extra_body"] == {
        "provider": {"zdr": True}
    }
