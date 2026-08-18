"""Serviço de embeddings que delega para um provider injetado."""

from __future__ import annotations

import os

from decisionssearch.application.ports.abstractions import EmbeddingProvider
from decisionssearch.infrastructure.ai.embeddings.embedding_providers import create_default_embedding_provider
from decisionssearch.infrastructure.ai.embeddings.sparse_embedding_service import SparseEmbeddingService, SparseVector


class EmbeddingService:
    """Facade fina para geração de embeddings via Strategy."""

    def __init__(
        self,
        provider: EmbeddingProvider | None = None,
        sparse_embeddings: SparseEmbeddingService | None = None,
    ):
        self.provider = provider
        self.sparse_embeddings = sparse_embeddings
        # Modelos assimétricos (bge/e5) exigem uma instrução no lado da QUERY
        # (não nos passages). Vazio para modelos simétricos (MiniLM).
        self.query_instruction = os.getenv("LOCAL_QUERY_INSTRUCTION", "")

    def _provider(self) -> EmbeddingProvider:
        if self.provider is None:
            self.provider = create_default_embedding_provider()
        return self.provider

    def _sparse_embeddings(self) -> SparseEmbeddingService:
        if self.sparse_embeddings is None:
            self.sparse_embeddings = SparseEmbeddingService()
        return self.sparse_embeddings

    @property
    def sparse_enabled(self) -> bool:
        """Indica se o encoder lexical está habilitado para o processo atual."""
        return self._sparse_embeddings().enabled

    async def embed(self, text: str) -> list[float]:
        """Embeda um PASSAGE/documento (sem instrução de query)."""
        return await self._provider().embed(text)

    async def embed_query(self, text: str) -> list[float]:
        """Embeda uma QUERY, prefixando a instrução assimétrica se configurada."""
        if self.query_instruction:
            text = f"{self.query_instruction}{text}"
        return await self._provider().embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._provider().embed_batch(texts)

    async def embed_sparse(self, text: str) -> SparseVector | None:
        """Gera BM25 sparse para documento ou query, sem envolver um LLM."""
        return await self._sparse_embeddings().embed(text)

    def build_text_for_embedding(
        self,
        title: str,
        summary: str,
        details: str = "",
        modules: list[str] | None = None,
        objective: str = "",
        trigger: str = "",
        business_rules: list[str] | None = None,
        architectural_rationale: str = "",
    ) -> str:
        parts = [title, summary]
        for narrative in (objective, trigger, architectural_rationale):
            if narrative:
                parts.append(narrative)
        if business_rules:
            parts.extend(business_rules[:3])
        if details:
            parts.append(details[:500])
        if modules:
            parts.append("modules: " + ", ".join(modules))
        return " | ".join(parts)
