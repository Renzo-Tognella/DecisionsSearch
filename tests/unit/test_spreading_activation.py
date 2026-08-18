import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from decisionssearch.application.search.spreading_activation_service import SpreadingActivationService
from decisionssearch.domain.memory_ledger import RelationState


def _make_service(neighbors=None):
    neo4j = MagicMock()
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    neo4j.driver = driver

    records = []
    for source, nbs in (neighbors or {}).items():
        records.append({"source": source, "neighbors": nbs})

    async def fake_run(query, **kwargs):
        class FakeResult:
            async def __aiter__(self_inner):
                for r in records:
                    yield MagicMock(data=lambda r=r: r)

        return FakeResult()

    session.run = MagicMock(side_effect=fake_run)
    return SpreadingActivationService(neo4j=neo4j, decay=0.5, max_depth=2)


def test_empty_seeds_returns_empty():
    svc = _make_service()
    result = asyncio.run(svc.activate([], project="CORE"))
    assert result == []


def test_seeds_without_neighbors_returns_seeds():
    svc = _make_service(neighbors={"m1": []})
    result = asyncio.run(svc.activate(["m1"], project="CORE"))
    assert "m1" in result


def test_propagates_to_neighbors():
    svc = _make_service(neighbors={"m1": ["m2", "m3"]})
    result = asyncio.run(svc.activate(["m1"], project="CORE", top_k=10))
    assert "m1" in result
    assert "m2" in result
    assert "m3" in result


def test_respects_top_k():
    svc = _make_service(neighbors={"m1": ["m2", "m3", "m4", "m5"]})
    result = asyncio.run(svc.activate(["m1"], project="CORE", top_k=2))
    assert len(result) <= 2


def test_decay_reduces_score():
    svc = _make_service(neighbors={"m1": ["m2"], "m2": ["m3"]})
    result = asyncio.run(svc.activate(["m1"], project="CORE", top_k=10))
    assert "m1" in result
    assert "m2" in result


def test_ledger_activation_does_not_follow_deprecates():
    source = uuid.uuid4()
    obsolete = uuid.uuid4()

    class Ledger:
        async def resolve_alias(self, value):
            return SimpleNamespace(family_id=source if value == "source" else obsolete)

        async def list_relations(self, state=RelationState.ACTIVE):
            assert state is RelationState.ACTIVE
            return [
                SimpleNamespace(
                    relation_type="DEPRECATES",
                    source_family_id=source,
                    target_family_id=obsolete,
                )
            ]

        async def get_family(self, family_id):
            return SimpleNamespace(project="CORE", legacy_memory_id=str(family_id))

    service = SpreadingActivationService(neo4j=MagicMock(), ledger=Ledger())

    result = asyncio.run(service.activate(["source"], project="CORE"))

    assert str(source) in result
    assert str(obsolete) not in result
