from __future__ import annotations

import uuid
from datetime import datetime, timezone

from decisionssearch.domain.memory.memory_item import MemoryItem, MemoryStatus
from decisionssearch.application.ports.abstractions import EmbeddingProvider, VectorStore


class SemanticCacheService:
    def __init__(
        self,
        embeddings: EmbeddingProvider,
        vector_store: VectorStore,
        similarity_threshold: float = 0.95,
    ):
        self.embeddings = embeddings
        self.vector_store = vector_store
        self.similarity_threshold = similarity_threshold

    async def get(self, query: str) -> dict | None:
        embedding = await self.embeddings.embed(query)
        results = await self.vector_store.search(
            query_vector=embedding,
            top_k=1,
            min_score=self.similarity_threshold,
        )
        if not results:
            return None
        best = results[0]
        if best.get("score", 0) >= self.similarity_threshold:
            return best
        return None

    async def put(self, query: str, response: dict) -> None:
        embedding = await self.embeddings.embed(query)
        cache_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, query))
        now = datetime.now(timezone.utc)
        item = MemoryItem(
            memory_id=cache_id,
            project="_cache",
            category="QueryCache",
            domain=[],
            title=query[:80],
            summary=str(response)[:220],
            details="",
            status=MemoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        upsert_kwargs = {"memory_id": cache_id, "embedding": embedding, "item": item}
        if getattr(self.vector_store, "sparse_enabled", False):
            embed_sparse = getattr(self.embeddings, "embed_sparse", None)
            if not callable(embed_sparse):
                raise RuntimeError(
                    "O vector store está com busca sparse ativa, mas o provider do cache "
                    "não gera vetores BM25. Injete EmbeddingService no SemanticCacheService."
                )
            sparse_vector = await embed_sparse(query)
            if sparse_vector is not None:
                upsert_kwargs["sparse_vector"] = sparse_vector
        await self.vector_store.upsert(**upsert_kwargs)
