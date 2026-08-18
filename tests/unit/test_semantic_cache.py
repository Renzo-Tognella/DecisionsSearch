import asyncio

from decisionssearch.application.search.semantic_cache_service import SemanticCacheService


class StubEmbeddings:
    async def embed(self, text: str) -> list[float]:
        return [float(len(text))] * 3


class StubVectorStore:
    def __init__(self):
        self.stored = []

    async def search(self, **kwargs):
        if self.stored and kwargs.get("min_score", 0) <= 0.95:
            return self.stored
        return []

    async def upsert(self, memory_id, embedding, item):
        self.stored.append({"memory_id": memory_id, "score": 0.97})


class SparseStubEmbeddings(StubEmbeddings):
    async def embed_sparse(self, text: str):
        return {"indices": [1], "values": [1.0]}


class SparseStubVectorStore(StubVectorStore):
    sparse_enabled = True

    async def upsert(self, memory_id, embedding, item, sparse_vector=None):
        self.stored.append(
            {"memory_id": memory_id, "score": 0.97, "sparse_vector": sparse_vector}
        )


def test_cache_miss_returns_none():
    cache = SemanticCacheService(
        embeddings=StubEmbeddings(),
        vector_store=StubVectorStore(),
        similarity_threshold=0.95,
    )
    result = asyncio.run(cache.get("new query"))
    assert result is None


def test_cache_hit_returns_result():
    vs = StubVectorStore()
    vs.stored = [{"memory_id": "q1", "score": 0.97, "response": "cached answer"}]
    cache = SemanticCacheService(
        embeddings=StubEmbeddings(),
        vector_store=vs,
        similarity_threshold=0.95,
    )
    result = asyncio.run(cache.get("existing query"))
    assert result is not None


def test_cache_put_stores_result():
    vs = StubVectorStore()
    cache = SemanticCacheService(
        embeddings=StubEmbeddings(),
        vector_store=vs,
        similarity_threshold=0.95,
    )
    asyncio.run(cache.put("my query", {"answer": "result"}))
    assert len(vs.stored) == 1


def test_cache_put_generates_sparse_vector_when_store_requires_it():
    vs = SparseStubVectorStore()
    cache = SemanticCacheService(
        embeddings=SparseStubEmbeddings(),
        vector_store=vs,
        similarity_threshold=0.95,
    )

    asyncio.run(cache.put("my query", {"answer": "result"}))

    assert vs.stored[0]["sparse_vector"] == {"indices": [1], "values": [1.0]}


def test_cache_miss_below_threshold():
    vs = StubVectorStore()
    vs.stored = [{"memory_id": "q1", "score": 0.80}]
    cache = SemanticCacheService(
        embeddings=StubEmbeddings(),
        vector_store=vs,
        similarity_threshold=0.95,
    )
    result = asyncio.run(cache.get("vague query"))
    assert result is None
