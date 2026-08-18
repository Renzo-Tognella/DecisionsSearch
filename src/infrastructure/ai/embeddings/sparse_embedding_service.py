"""Embeddings lexicais sparse para recuperação híbrida dense + BM25.

O encoder é local e determinístico: ele não passa por LLM nem por um provedor de
chat. Isso é intencional — BM25 preserva identificadores, paths, nomes de eventos
e outros termos exatos que um embedding denso pode diluir. O FastEmbed é carregado
sob demanda, portanto instalações que ainda não ativaram busca sparse não pagam o
custo de modelo ou download.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

from decisionssearch.domain.shared.exceptions import EmbeddingError
from decisionssearch.infrastructure.config.env_utils import env_bool

try:
    from qdrant_client.models import SparseVector
except Exception:  # pragma: no cover

    class SparseVector:  # type: ignore[override]
        def __init__(self, indices: list[int], values: list[float]):
            self.indices = indices
            self.values = values


class SparseEmbeddingService:
    """Gera ``SparseVector`` com o modelo BM25 leve do FastEmbed.

    ``enabled`` pode ser injetado pelos scripts de migração sem exigir mutação do
    ambiente. Em runtime, a flag vem de ``SPARSE_SEARCH_ENABLED`` e permanece
    desligada por padrão para não alterar coleções existentes silenciosamente.
    """

    def __init__(self, enabled: bool | None = None, encoder: Any | None = None):
        self.enabled = env_bool("SPARSE_SEARCH_ENABLED", False) if enabled is None else enabled
        self.model_name = (
            os.getenv("SPARSE_EMBEDDING_MODEL", "Qdrant/bm25").strip() or "Qdrant/bm25"
        )
        self._encoder = encoder
        self._lock = threading.Lock()

    def _load_encoder(self) -> Any:
        if self._encoder is not None:
            return self._encoder
        try:
            from fastembed import SparseTextEmbedding
        except ImportError as error:
            raise EmbeddingError(
                "Busca sparse foi ativada, mas fastembed não está instalado. "
                "Rode `uv sync` para instalar as dependências do projeto.",
                provider="fastembed",
                context={"model": self.model_name},
            ) from error
        try:
            self._encoder = SparseTextEmbedding(model_name=self.model_name)
        except Exception as error:
            raise EmbeddingError(
                f"Falha ao carregar encoder sparse {self.model_name}: {error}",
                provider="fastembed",
                context={"model": self.model_name},
            ) from error
        return self._encoder

    @staticmethod
    def _as_list(values: Any, caster) -> list:
        if hasattr(values, "tolist"):
            values = values.tolist()
        return [caster(value) for value in values]

    def _embed_sync(self, text: str) -> SparseVector:
        encoder = self._load_encoder()
        # A inicialização e inferência do ONNX podem receber chamadas concorrentes
        # de ingestão e query. Serializamos apenas o encoder local; a busca no
        # Qdrant e o embedding denso continuam concorrentes no pipeline.
        with self._lock:
            embeddings = list(encoder.embed([text]))
        if not embeddings:
            return SparseVector(indices=[], values=[])

        result = embeddings[0]
        indices = self._as_list(getattr(result, "indices", []), int)
        values = self._as_list(getattr(result, "values", []), float)
        if len(indices) != len(values):
            raise EmbeddingError(
                "Encoder sparse retornou índices e pesos com tamanhos diferentes.",
                provider="fastembed",
                context={"model": self.model_name},
            )
        return SparseVector(indices=indices, values=values)

    async def embed(self, text: str) -> SparseVector | None:
        """Gera vetor sparse; retorna ``None`` quando a feature está desligada."""
        if not self.enabled:
            return None
        try:
            return await asyncio.to_thread(self._embed_sync, text)
        except EmbeddingError:
            raise
        except Exception as error:
            raise EmbeddingError(
                f"Erro ao gerar embedding sparse: {error}",
                provider="fastembed",
                context={"model": self.model_name},
            ) from error
