from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.application.search.hybrid_search_service import HybridSearchService


@dataclass
class FakeQdrant:
    sparse_enabled: bool = False
    calls: list[dict] = field(default_factory=list)

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return []


@dataclass
class FakeNeo4j:
    calls: list[dict] = field(default_factory=list)

    async def query_by_project(self, **kwargs):
        self.calls.append(kwargs)
        return []


@dataclass
class FakeEmbeddings:
    async def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2]


def test_hybrid_search_resolves_project_before_all_retrieval_branches(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    project_dir = tmp_path / "billing-service"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    qdrant = FakeQdrant()
    neo4j = FakeNeo4j()
    service = HybridSearchService(qdrant=qdrant, neo4j=neo4j, embeddings=FakeEmbeddings())

    result = asyncio.run(service.search(query_text="cache key convention"))

    assert result == []
    assert qdrant.calls[0]["project"] == "billing-service"
    assert neo4j.calls[0]["project"] == "billing-service"


def test_hybrid_search_resolves_project_for_dense_sparse_and_graph(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    project_dir = tmp_path / "orders-api"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    @dataclass
    class SparseQdrant:
        sparse_enabled: bool = True
        dense_calls: list[dict] = field(default_factory=list)
        sparse_calls: list[dict] = field(default_factory=list)

        async def search(self, **kwargs):
            self.dense_calls.append(kwargs)
            return []

        async def search_sparse(self, **kwargs):
            self.sparse_calls.append(kwargs)
            return []

    @dataclass
    class SparseEmbeddings:
        async def embed_query(self, query: str) -> list[float]:
            return [0.1, 0.2]

        async def embed_sparse(self, query: str):
            return {"indices": [1], "values": [1.0]}

    qdrant = SparseQdrant()
    neo4j = FakeNeo4j()
    service = HybridSearchService(
        qdrant=qdrant,
        neo4j=neo4j,
        embeddings=SparseEmbeddings(),
    )

    result = asyncio.run(service.search(query_text="order state transition"))

    assert result == []
    assert qdrant.dense_calls[0]["project"] == "orders-api"
    assert qdrant.sparse_calls[0]["project"] == "orders-api"
    assert neo4j.calls[0]["project"] == "orders-api"
