import pytest
import asyncio

from decisionssearch.domain.shared.exceptions import (
    AdmissionError,
    BootstrapError,
    EmbeddingError,
    ExtractionError,
    MemoryServiceError,
    SanitizationError,
    StorageConsistencyError,
)
from decisionssearch.infrastructure.ai.embeddings.embedding_providers import (
    GeminiEmbeddingProvider,
    LocalMiniLMEmbeddingProvider,
    create_default_embedding_provider,
)
from decisionssearch.infrastructure.ai.embeddings.embedding_service import EmbeddingService


class StubEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text))]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


def test_exception_hierarchy_and_context_attributes() -> None:
    base_error = MemoryServiceError("falha geral", context={"op": "test"})
    storage_error = StorageConsistencyError("inconsistente", memory_id="m1", store="qdrant")
    admission_error = AdmissionError("falha gate", gate="duplicate", candidate_title="Regra X")
    extraction_error = ExtractionError("json inválido", model="gpt-4o", retries_exhausted=True)
    embedding_error = EmbeddingError("rate limit", provider="gemini")
    sanitization_error = SanitizationError("payload inválido", reason="too_large")
    bootstrap_error = BootstrapError("neo4j indisponível")

    assert isinstance(storage_error, MemoryServiceError)
    assert isinstance(admission_error, MemoryServiceError)
    assert isinstance(extraction_error, MemoryServiceError)
    assert isinstance(embedding_error, MemoryServiceError)
    assert isinstance(sanitization_error, MemoryServiceError)
    assert isinstance(bootstrap_error, MemoryServiceError)

    assert base_error.context == {"op": "test"}
    assert storage_error.memory_id == "m1"
    assert storage_error.store == "qdrant"
    assert admission_error.gate == "duplicate"
    assert admission_error.candidate_title == "Regra X"
    assert extraction_error.model == "gpt-4o"
    assert extraction_error.retries_exhausted is True
    assert embedding_error.provider == "gemini"
    assert sanitization_error.reason == "too_large"


def test_embedding_service_uses_injected_provider() -> None:
    service = EmbeddingService(provider=StubEmbeddingProvider())

    vector = asyncio.run(service.embed("abc"))
    vectors = asyncio.run(service.embed_batch(["a", "bc"]))

    assert vector == [3.0]
    assert vectors == [[1.0], [2.0]]


def test_build_text_for_embedding_truncates_details() -> None:
    service = EmbeddingService(provider=StubEmbeddingProvider())

    details = "x" * 700
    text = service.build_text_for_embedding("Título", "Resumo", details)

    assert text == f"Título | Resumo | {'x' * 500}"


def test_default_provider_falls_back_to_local_without_gemini_key(monkeypatch) -> None:
    from decisionssearch.infrastructure.ai.embeddings import embedding_providers

    class StubLocalProvider:
        pass

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.setattr(embedding_providers, "LocalMiniLMEmbeddingProvider", StubLocalProvider)

    provider = create_default_embedding_provider()

    assert isinstance(provider, StubLocalProvider)


def test_explicit_remote_embedding_provider_fails_without_key(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    with pytest.raises(EmbeddingError, match="fallback local silencioso foi bloqueado"):
        create_default_embedding_provider()


def test_default_provider_uses_gemini_with_key(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    provider = create_default_embedding_provider()

    assert isinstance(provider, GeminiEmbeddingProvider)


def test_local_provider_raises_when_sentence_transformers_missing(monkeypatch) -> None:
    import builtins

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("missing sentence_transformers")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(EmbeddingError):
        LocalMiniLMEmbeddingProvider()
