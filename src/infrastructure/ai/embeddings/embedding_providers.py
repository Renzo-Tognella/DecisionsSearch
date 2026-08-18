from __future__ import annotations

import asyncio
import os
from threading import Lock

import httpx

from decisionssearch.domain.shared.exceptions import EmbeddingError
from decisionssearch.application.ports.abstractions import EmbeddingProvider
from decisionssearch.infrastructure.ai.providers.model_provider import (
    get_embedding_api_key,
    get_embedding_base_url,
    get_embedding_dimensions,
    get_embedding_model,
    get_embedding_provider,
    get_openrouter_headers,
)


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.provider = get_embedding_provider()
        self.api_key = get_embedding_api_key()
        self.model = get_embedding_model()
        self.dimensions = get_embedding_dimensions()
        base = get_embedding_base_url()
        self.base_url = base if base else "https://api.openai.com/v1"
        self.default_headers = get_openrouter_headers(self.provider)
        self.zdr = (
            self.provider == "openrouter"
            and os.getenv("OPENROUTER_EMBEDDING_ZDR", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.request_dimensions = self._request_dimensions()

        if not self.api_key:
            raise EmbeddingError("API key ausente para embeddings", provider=self.provider)

    def _request_dimensions(self) -> int | None:
        """Permite omitir ``dimensions`` para modelos que não suportam truncation."""
        configured = os.getenv("EMBEDDING_REQUEST_DIMENSIONS", "").strip()
        if not configured:
            return self.dimensions
        try:
            value = int(configured)
        except ValueError:
            return self.dimensions
        return value if value > 0 else None

    def _client_kwargs(self) -> dict:
        kwargs = {"api_key": self.api_key, "base_url": self.base_url}
        if self.default_headers:
            kwargs["default_headers"] = self.default_headers
        return kwargs

    def _request_kwargs(self, input_value: str | list[str]) -> dict:
        kwargs = {"input": input_value, "model": self.model}
        if self.request_dimensions is not None:
            kwargs["dimensions"] = self.request_dimensions
        if self.zdr:
            kwargs["extra_body"] = {"provider": {"zdr": True}}
        return kwargs

    def _validate_dimensions(self, embedding: list[float]) -> list[float]:
        if len(embedding) != self.dimensions:
            raise EmbeddingError(
                "Dimensão retornada pelo modelo não confere com EMBEDDING_DIMENSIONS. "
                "Ajuste a configuração e recrie/reindexe a collection Qdrant antes de continuar.",
                provider=self.provider,
                context={
                    "model": self.model,
                    "expected_dimensions": self.dimensions,
                    "received_dimensions": len(embedding),
                },
            )
        return embedding

    async def embed(self, text: str) -> list[float]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(**self._client_kwargs())
            response = await client.embeddings.create(**self._request_kwargs(text))
            await client.close()
            return self._validate_dimensions(response.data[0].embedding)
        except ImportError:
            raise EmbeddingError(
                "openai package necessário para embeddings via API",
                provider=self.provider,
            )
        except EmbeddingError:
            raise
        except Exception as error:
            raise EmbeddingError(
                f"Erro ao gerar embedding: {error}",
                provider=self.provider,
            ) from error

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(**self._client_kwargs())
            response = await client.embeddings.create(**self._request_kwargs(texts))
            await client.close()
            return [self._validate_dimensions(item.embedding) for item in response.data]
        except ImportError:
            return [await self.embed(text) for text in texts]
        except EmbeddingError:
            raise
        except Exception as error:
            raise EmbeddingError(
                f"Erro no batch embedding: {error}",
                provider=self.provider,
            ) from error


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.provider = get_embedding_provider()
        self.api_key = get_embedding_api_key()
        self.model = get_embedding_model()
        self.dimensions = get_embedding_dimensions()
        self.task_type = os.getenv("GEMINI_EMBEDDING_TASK", "RETRIEVAL_DOCUMENT")
        self.base_url = get_embedding_base_url()

        if not self.api_key:
            raise EmbeddingError("GEMINI_API_KEY ausente", provider="gemini")

    def _endpoint(self) -> str:
        return f"{self.base_url}/models/{self.model}:embedContent"

    async def embed(self, text: str) -> list[float]:
        payload = {
            "content": {"parts": [{"text": text}]},
            "taskType": self.task_type,
            "outputDimensionality": self.dimensions,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._endpoint(),
                    params={"key": self.api_key},
                    json=payload,
                )

            if response.status_code in (401, 403):
                raise EmbeddingError("API key Gemini inválida", provider=self.provider)
            if response.status_code == 429:
                raise EmbeddingError("Rate limit Gemini atingido", provider=self.provider)

            response.raise_for_status()
            data = response.json()
            values = data.get("embedding", {}).get("values")
            if not isinstance(values, list) or not values:
                raise EmbeddingError(
                    "Resposta de embedding Gemini inválida",
                    provider=self.provider,
                    context={"response": data},
                )
            return values
        except EmbeddingError:
            raise
        except httpx.HTTPError as error:
            raise EmbeddingError(
                f"Erro HTTP ao gerar embedding Gemini: {error}",
                provider=self.provider,
            ) from error
        except Exception as error:
            raise EmbeddingError(
                f"Erro ao gerar embedding Gemini: {error}",
                provider=self.provider,
            ) from error

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


class LocalMiniLMEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.model_name = get_embedding_model()
        self.dimensions = get_embedding_dimensions()
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as error:
            raise EmbeddingError(
                "sentence-transformers não disponível para fallback local",
                provider="local",
                context={"model": self.model_name},
            ) from error

        try:
            self.model = SentenceTransformer(self.model_name)
        except Exception as error:
            raise EmbeddingError(
                f"Falha ao carregar modelo local {self.model_name}: {error}",
                provider="local",
            ) from error
        # The fast tokenizer used by SentenceTransformer is not safe to call
        # concurrently from multiple worker threads (it can raise
        # ``RuntimeError: Already borrowed``). Async callers still use
        # ``to_thread`` below, so serialize access to the shared model.
        self._encode_lock = Lock()

    def _encode_one(self, text: str) -> list[float]:
        with self._encode_lock:
            vector = self.model.encode(
                text,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        values = vector.tolist()
        return values[: self.dimensions]

    def _encode_batch(self, texts: list[str]) -> list[list[float]]:
        with self._encode_lock:
            vectors = self.model.encode(
                texts,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        return [vector.tolist()[: self.dimensions] for vector in vectors]

    async def embed(self, text: str) -> list[float]:
        try:
            return await asyncio.to_thread(self._encode_one, text)
        except Exception as error:
            raise EmbeddingError(
                f"Erro no embedding local ({self.model_name}): {error}",
                provider="local",
            ) from error

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            return await asyncio.to_thread(self._encode_batch, texts)
        except Exception as error:
            raise EmbeddingError(
                f"Erro no batch embedding local ({self.model_name}): {error}",
                provider="local",
            ) from error


def create_default_embedding_provider() -> EmbeddingProvider:
    provider = get_embedding_provider()
    api_key = get_embedding_api_key()

    if provider in ("openai", "zai", "openrouter"):
        if not api_key:
            raise EmbeddingError(
                "API key ausente para o provider de embeddings configurado; "
                "fallback local silencioso foi bloqueado",
                provider=provider,
            )
        return OpenAICompatibleEmbeddingProvider()

    if provider == "gemini" and api_key:
        return GeminiEmbeddingProvider()

    return LocalMiniLMEmbeddingProvider()
