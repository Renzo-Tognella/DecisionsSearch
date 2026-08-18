import asyncio
from unittest.mock import AsyncMock, MagicMock

from decisionssearch.application.governance.weight_propagation_service import WeightPropagationService


def _make_service():
    neo4j = MagicMock()
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    neo4j.driver = driver

    async def fake_run(query, **kwargs):
        class FakeResult:
            async def __aiter__(self):
                pass

            async def single(self):
                return MagicMock(data=lambda: {"updated": 5})

        return FakeResult()

    session.run = MagicMock(side_effect=fake_run)
    return WeightPropagationService(neo4j=neo4j)


def test_propagate_weights():
    svc = _make_service()
    result = asyncio.run(svc.propagate_weights(project="CORE"))
    assert result["project"] == "CORE"
    assert result["iterations"] == 3


def test_get_top_propagated():
    svc = _make_service()
    records = [{"memory_id": "m1", "title": "T1", "original_weight": 0.5, "propagated_weight": 0.8}]

    async def fake_run(query, **kwargs):
        class FakeResult:
            async def __aiter__(self):
                for r in records:
                    yield MagicMock(data=lambda r=r: r)

        return FakeResult()

    svc.neo4j.driver.session.return_value.__aenter__.return_value.run = MagicMock(
        side_effect=fake_run
    )
    result = asyncio.run(svc.get_top_propagated(project="CORE"))
    assert len(result) == 1
    assert result[0]["propagated_weight"] == 0.8


def test_damping_factor():
    svc = WeightPropagationService(neo4j=MagicMock())
    assert svc.DAMPING == 0.85
