import asyncio

from decisionssearch.application.search.hybrid_search_service import HybridSearchService
from decisionssearch.infrastructure.persistence.qdrant.qdrant_service import SparseVector

rrf = HybridSearchService.reciprocal_rank_fusion


def test_weighted_rrf_downweights_query_blind_list():
    # 'a' é #1 numa lista de peso 1.0 (vetorial); 'b' é #1 numa lista de peso 0.4
    # (grafo cego à query). O rebaixamento faz 'a' ganhar.
    fused = rrf([["a"], ["b"]], k=60, weights=[1.0, 0.4])
    assert fused["a"] > fused["b"]


def test_unweighted_rrf_is_backward_compatible():
    fused = rrf([["a", "b"], ["b", "a"]], k=60)
    assert abs(fused["a"] - fused["b"]) < 1e-9


def test_doc_in_both_lists_beats_single_list():
    fused = rrf([["x", "y"], ["x"]], k=60, weights=[1.0, 0.4])
    assert fused["x"] > fused["y"]


def test_blend_rerank_combines_rerank_and_composite():
    svc = HybridSearchService(qdrant=None, neo4j=None, embeddings=None)
    svc.rerank_blend_alpha = 0.5
    docs = [
        {"memory_id": "a", "rerank_score": 5.0, "composite_score": 0.1},
        {"memory_id": "b", "rerank_score": 1.0, "composite_score": 0.9},
    ]
    out = svc._blend_rerank(docs)
    # a: 0.5*1.0 + 0.5*0.1 = 0.55 ; b: 0.5*0.0 + 0.5*0.9 = 0.45 -> a primeiro
    assert out[0]["memory_id"] == "a"
    assert all("final_score" in d for d in out)


def test_blend_rerank_noop_without_rerank_scores():
    svc = HybridSearchService(qdrant=None, neo4j=None, embeddings=None)
    docs = [{"memory_id": "a"}, {"memory_id": "b"}]
    assert svc._blend_rerank(docs) == docs


def test_search_fuses_dense_and_sparse_with_rrf() -> None:
    class FakeQdrant:
        sparse_enabled = True

        async def search(self, **kwargs):
            assert kwargs["query_vector"] == [0.1, 0.2]
            return [
                {
                    "memory_id": "both",
                    "project": "CORE",
                    "title": "invoice.created contract",
                    "effective_weight": 0.8,
                    "score": 0.9,
                },
                {
                    "memory_id": "dense",
                    "project": "CORE",
                    "title": "semantic billing rule",
                    "effective_weight": 0.8,
                    "score": 0.8,
                },
            ]

        async def search_sparse(self, **kwargs):
            assert kwargs["query_vector"].indices == [4]
            return [
                {
                    "memory_id": "both",
                    "project": "CORE",
                    "title": "invoice.created contract",
                    "effective_weight": 0.8,
                    "score": 12.0,
                },
                {
                    "memory_id": "sparse",
                    "project": "CORE",
                    "title": "invoice.created exact event",
                    "effective_weight": 0.8,
                    "score": 9.0,
                },
            ]

    class FakeNeo4j:
        async def query_by_project(self, **kwargs):
            return []

    class FakeEmbeddings:
        async def embed_query(self, text):
            assert text == "where is invoice.created?"
            return [0.1, 0.2]

        async def embed_sparse(self, text):
            assert text == "where is invoice.created?"
            return SparseVector(indices=[4], values=[1.0])

    service = HybridSearchService(
        qdrant=FakeQdrant(),
        neo4j=FakeNeo4j(),
        embeddings=FakeEmbeddings(),
    )
    results = asyncio.run(
        service.search(query_text="where is invoice.created?", project="CORE", top_k=3)
    )

    assert [result["memory_id"] for result in results] == ["both", "dense", "sparse"]
    assert results[0]["retrieval_source"] == "dense+sparse"
    assert results[1]["retrieval_source"] == "vector"
    assert results[2]["retrieval_source"] == "sparse"


def test_search_drops_cross_project_candidates_before_rrf() -> None:
    class FakeQdrant:
        sparse_enabled = True

        async def search(self, **kwargs):
            assert kwargs["project"] == "CORE"
            return [
                {
                    "memory_id": "allowed",
                    "project": "CORE",
                    "title": "Allowed rule",
                    "summary": "Allowed rule",
                    "effective_weight": 0.8,
                    "score": 0.9,
                },
                {
                    "memory_id": "foreign-dense",
                    "project": "OTHER",
                    "title": "Foreign dense rule",
                    "effective_weight": 1.0,
                    "score": 1.0,
                },
            ]

        async def search_sparse(self, **kwargs):
            assert kwargs["project"] == "CORE"
            return [
                {
                    "memory_id": "foreign-sparse",
                    "project": "OTHER",
                    "title": "Foreign sparse rule",
                    "effective_weight": 1.0,
                    "score": 20.0,
                }
            ]

    class FakeNeo4j:
        async def query_by_project(self, **kwargs):
            assert kwargs["project"] == "CORE"
            return [
                {
                    "memory": {
                        "memory_id": "foreign-graph",
                        "project": "OTHER",
                        "title": "Foreign graph rule",
                        "effective_weight": 1.0,
                    },
                    "related_titles": [],
                }
            ]

    class FakeEmbeddings:
        async def embed_query(self, text):
            return [0.1, 0.2]

        async def embed_sparse(self, text):
            return SparseVector(indices=[4], values=[1.0])

    service = HybridSearchService(
        qdrant=FakeQdrant(),
        neo4j=FakeNeo4j(),
        embeddings=FakeEmbeddings(),
    )

    results = asyncio.run(service.search(query_text="billing rule", project="CORE"))

    assert [result["memory_id"] for result in results] == ["allowed"]
    assert all(result["project"] == "CORE" for result in results)
