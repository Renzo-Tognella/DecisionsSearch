from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from decisionssearch.domain.shared.exceptions import BootstrapError, MemoryServiceError
from decisionssearch.domain.memory.memory_item import MemoryItem, MemoryStatus
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.infrastructure.persistence.qdrant.qdrant_service import QdrantService, SparseVector


@dataclass
class DummyCollection:
    name: str


class FakeQdrantClient:
    def __init__(self):
        self.collections = []
        self.index_calls: list[tuple[str, str, str]] = []
        self.upsert_calls = []
        self.search_calls = []

    async def get_collections(self):
        class Response:
            collections = [DummyCollection(name=item) for item in self.collections]

        return Response()

    async def create_collection(self, collection_name, vectors_config, sparse_vectors_config=None):
        self.collections.append(collection_name)
        self.created_vectors = vectors_config
        self.created_sparse_vectors = sparse_vectors_config

    async def create_payload_index(self, collection_name, field_name, field_schema):
        self.index_calls.append((collection_name, field_name, str(field_schema)))

    async def upsert(self, collection_name, points):
        self.upsert_calls.append((collection_name, points))

    async def query_points(self, **kwargs):
        self.search_calls.append(kwargs)

        class Result:
            score = 0.95
            payload = {"memory_id": "m1", "title": "Regra"}

        return SimpleNamespace(points=[Result()])


def test_qdrant_ensure_collection_and_indexes() -> None:
    fake_client = FakeQdrantClient()
    service = QdrantService(client=fake_client)

    asyncio.run(service.ensure_collection(vector_size=384))

    assert service.collection in fake_client.collections
    assert len(fake_client.index_calls) == 10
    assert (service.collection, "modules", "keyword") in fake_client.index_calls
    assert (service.collection, "memory_scope", "keyword") in fake_client.index_calls
    assert (service.collection, "canonical_store", "keyword") in fake_client.index_calls
    assert (service.collection, "valid_from", "datetime") in fake_client.index_calls


def test_qdrant_ensure_collection_rejects_dimension_mismatch() -> None:
    from types import SimpleNamespace

    class MismatchClient:
        async def get_collections(self):
            return SimpleNamespace(collections=[DummyCollection(name="memories")])

        async def get_collection(self, name):
            return SimpleNamespace(
                config=SimpleNamespace(
                    params=SimpleNamespace(vectors=SimpleNamespace(size=512))
                )
            )

        async def create_payload_index(self, **kwargs):
            raise AssertionError("não deve indexar quando a dimensão diverge")

    service = QdrantService(client=MismatchClient())
    service.collection = "memories"

    with pytest.raises(MemoryServiceError):
        asyncio.run(service.ensure_collection(vector_size=384))


def test_qdrant_ensure_collection_accepts_matching_dimension() -> None:
    from types import SimpleNamespace

    index_calls: list[str] = []

    class MatchClient:
        async def get_collections(self):
            return SimpleNamespace(collections=[DummyCollection(name="memories")])

        async def get_collection(self, name):
            return SimpleNamespace(
                config=SimpleNamespace(
                    params=SimpleNamespace(vectors=SimpleNamespace(size=384))
                )
            )

        async def create_payload_index(self, collection_name, field_name, field_schema):
            index_calls.append(field_name)

    service = QdrantService(client=MatchClient())
    service.collection = "memories"

    asyncio.run(service.ensure_collection(vector_size=384))

    assert len(index_calls) == 10


def test_qdrant_ensure_collection_without_size_skips_guard() -> None:
    # Sem vector_size explícito, "garanta que existe" NÃO deve disparar o guard,
    # mesmo se a collection existir com dimensão != default (caso da fixture e2e,
    # que chama ensure_collection() e a collection local é 384 vs default 768).
    from types import SimpleNamespace

    index_calls: list[str] = []

    class ExistingClient:
        async def get_collections(self):
            return SimpleNamespace(collections=[DummyCollection(name="memories")])

        async def get_collection(self, name):
            return SimpleNamespace(
                config=SimpleNamespace(
                    params=SimpleNamespace(vectors=SimpleNamespace(size=384))
                )
            )

        async def create_payload_index(self, collection_name, field_name, field_schema):
            index_calls.append(field_name)

    service = QdrantService(client=ExistingClient())
    service.collection = "memories"

    asyncio.run(service.ensure_collection())  # sem arg -> não levanta
    assert len(index_calls) == 10


def test_qdrant_upsert_and_search() -> None:
    fake_client = FakeQdrantClient()
    service = QdrantService(client=fake_client)

    item = MemoryItem(
        memory_id="abc",
        project="CORE",
        category="DesignRule",
        domain=["Billing"],
        title="Regra de Arredondamento",
        summary="Resumo",
        details="Detalhes",
        status=MemoryStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    asyncio.run(service.upsert("abc", [0.1, 0.2], item))
    results = asyncio.run(service.search([0.1, 0.2], project="CORE", type="DesignRule"))

    assert len(fake_client.upsert_calls) == 1
    assert results[0]["memory_id"] == "m1"
    assert results[0]["score"] == 0.95
    assert fake_client.upsert_calls[0][1][0].payload["project"] == "CORE"


def test_qdrant_search_binds_project_filter_before_retrieval() -> None:
    fake_client = FakeQdrantClient()
    service = QdrantService(client=fake_client)

    asyncio.run(service.search([0.1, 0.2], project="billing-service"))

    query_filter = fake_client.search_calls[0]["query_filter"]
    project_conditions = [
        condition
        for condition in query_filter.must
        if getattr(condition, "key", None) == "project"
    ]

    assert len(project_conditions) == 1
    assert project_conditions[0].match.value == "billing-service"


def test_qdrant_search_can_filter_temporal_validity() -> None:
    fake_client = FakeQdrantClient()
    service = QdrantService(client=fake_client)
    point_in_time = datetime.now(timezone.utc)

    asyncio.run(service.search([0.1, 0.2], project="CORE", valid_at=point_in_time))

    query_filter = fake_client.search_calls[-1]["query_filter"]
    assert any(getattr(condition, "should", None) for condition in query_filter.must)


def test_qdrant_payload_validity_handles_open_and_expired_bounds() -> None:
    point_in_time = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)

    assert QdrantService._payload_is_valid_at(
        {"valid_from": None, "valid_to": None}, point_in_time
    )
    assert QdrantService._payload_is_valid_at(
        {"valid_from": "2026-08-15T11:00:00+00:00", "valid_to": "2026-08-15T13:00:00+00:00"},
        point_in_time,
    )
    assert not QdrantService._payload_is_valid_at(
        {"valid_from": "2026-08-15T13:00:00+00:00"}, point_in_time
    )
    assert not QdrantService._payload_is_valid_at(
        {"valid_to": "2026-08-15T12:00:00+00:00"}, point_in_time
    )


def test_qdrant_sparse_collection_upsert_and_search() -> None:
    fake_client = FakeQdrantClient()
    service = QdrantService(client=fake_client, sparse_enabled=True)
    item = MemoryItem(
        memory_id="abc",
        project="CORE",
        category="DesignRule",
        domain=["Billing"],
        title="Evento de faturamento-v2",
        summary="Resumo",
        details="Detalhes",
        status=MemoryStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    sparse = SparseVector(indices=[42, 99], values=[0.8, 0.2])

    asyncio.run(service.ensure_collection(vector_size=2))
    asyncio.run(service.upsert("abc", [0.1, 0.2], item, sparse_vector=sparse))
    results = asyncio.run(service.search_sparse(sparse, project="CORE", type="DesignRule"))

    assert "bm25" in fake_client.created_sparse_vectors
    point = fake_client.upsert_calls[0][1][0]
    assert point.vector[""] == [0.1, 0.2]
    assert point.vector["bm25"].indices == [42, 99]
    assert fake_client.search_calls[-1]["using"] == "bm25"
    assert results[0]["memory_id"] == "m1"


def test_qdrant_sparse_refuses_unmigrated_existing_collection() -> None:
    class DenseOnlyClient:
        async def get_collections(self):
            return SimpleNamespace(collections=[DummyCollection(name="memories")])

        async def get_collection(self, name):
            return SimpleNamespace(
                config=SimpleNamespace(
                    params=SimpleNamespace(
                        vectors=SimpleNamespace(size=384),
                        sparse_vectors={},
                    )
                )
            )

        async def create_payload_index(self, **kwargs):
            raise AssertionError("não deve criar índices antes de validar a migração")

    service = QdrantService(client=DenseOnlyClient(), sparse_enabled=True)

    with pytest.raises(MemoryServiceError, match="collection nova com sparse habilitado"):
        asyncio.run(service.ensure_collection(vector_size=384))


class FakeSession:
    def __init__(self, should_fail: bool = False):
        self.calls = []
        self.should_fail = should_fail

    async def run(self, query, **params):
        if self.should_fail:
            raise RuntimeError("neo4j down")
        self.calls.append((query, params))

        class FakeResult:
            def __aiter__(self):
                self._done = False
                return self

            async def __anext__(self):
                if self._done:
                    raise StopAsyncIteration
                self._done = True

                class FakeRecord:
                    def data(self):
                        return {"memory": {"memory_id": "m1"}, "related_titles": []}

                return FakeRecord()

        return FakeResult()


class FakeSessionContext:
    def __init__(self, session: FakeSession):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeDriver:
    def __init__(self, should_fail: bool = False):
        self.session_instance = FakeSession(should_fail=should_fail)

    def session(self):
        return FakeSessionContext(self.session_instance)

    async def close(self):
        return None


def test_neo4j_bootstrap_upsert_link_and_query(monkeypatch) -> None:
    fake_driver = FakeDriver()
    monkeypatch.setattr("decisionssearch.infrastructure.persistence.neo4j.neo4j_service.AsyncGraphDatabase.driver", lambda *a, **k: fake_driver)

    service = Neo4jService()

    asyncio.run(service.bootstrap(["CORE"], ["Billing"]))
    asyncio.run(
        service.upsert_memory(
            memory_id="m1",
            project="CORE",
            category="DesignPattern",
            domains=["Billing"],
            title="Pattern",
            summary="Resumo",
            details="Detalhes",
            status="active",
            weight=0.9,
        )
    )
    asyncio.run(service.link_memories("m1", "RELATED_TO", "m2"))
    result = asyncio.run(service.query_by_project("CORE"))

    assert len(fake_driver.session_instance.calls) >= 4
    assert result[0]["memory"]["memory_id"] == "m1"


def test_neo4j_query_by_project_binds_project_partition(monkeypatch) -> None:
    fake_driver = FakeDriver()
    monkeypatch.setattr(
        "decisionssearch.infrastructure.persistence.neo4j.neo4j_service.AsyncGraphDatabase.driver",
        lambda *a, **k: fake_driver,
    )
    service = Neo4jService()

    asyncio.run(service.query_by_project("billing-service"))

    query, params = fake_driver.session_instance.calls[0]
    assert "IN_PROJECT" in query
    assert "Project {name: $project}" in query
    assert params["project"] == "billing-service"


def test_neo4j_invalid_relationship_raises(monkeypatch) -> None:
    monkeypatch.setattr("decisionssearch.infrastructure.persistence.neo4j.neo4j_service.AsyncGraphDatabase.driver", lambda *a, **k: FakeDriver())
    service = Neo4jService()

    with pytest.raises(MemoryServiceError):
        asyncio.run(service.link_memories("a", "INVALID_REL", "b"))


def test_neo4j_catalog_whitelist_is_exposed(monkeypatch) -> None:
    monkeypatch.setattr("decisionssearch.infrastructure.persistence.neo4j.neo4j_service.AsyncGraphDatabase.driver", lambda *a, **k: FakeDriver())
    service = Neo4jService()

    relations = asyncio.run(service.list_allowed_relations())

    assert relations == sorted(
        [
            "CONFLICTS_WITH",
            "DEPRECATES",
            "DEPENDS_ON",
            "EVOLVES_FROM",
            "HAS_CATEGORY",
            "HAS_DOMAIN",
            "RELATED_TO",
            "REFINES",
        ]
    )


def test_neo4j_bootstrap_wraps_failure(monkeypatch) -> None:
    failing_driver = FakeDriver(should_fail=True)
    monkeypatch.setattr(
        "decisionssearch.infrastructure.persistence.neo4j.neo4j_service.AsyncGraphDatabase.driver",
        lambda *a, **k: failing_driver,
    )
    service = Neo4jService()

    with pytest.raises(BootstrapError):
        asyncio.run(service.bootstrap(["CORE"]))
