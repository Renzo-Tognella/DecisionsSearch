import asyncio
from unittest.mock import AsyncMock, MagicMock

from decisionssearch.domain.procedural.procedural_memory import ProceduralMemory
from decisionssearch.application.memory.procedural_memory_service import ProceduralMemoryService


def _make_service():
    neo4j = MagicMock()
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    neo4j.driver = driver
    session.run = AsyncMock()
    return ProceduralMemoryService(neo4j=neo4j)


def test_create_procedure():
    svc = _make_service()
    proc = ProceduralMemory(
        procedure_id="proc1",
        project="CORE",
        task_type="bug_fix",
        steps=["Reproduce", "Fix", "Test"],
        tools_required=["pytest"],
    )
    result = asyncio.run(svc.create_procedure(proc))
    assert result["procedure_id"] == "proc1"


def test_query_procedures():
    svc = _make_service()
    records = [{"procedure": {"procedure_id": "proc1", "task_type": "bug_fix"}}]

    async def fake_run(query, **kwargs):
        class FakeResult:
            async def __aiter__(self):
                for r in records:
                    yield MagicMock(data=lambda r=r: r)

        return FakeResult()

    svc.neo4j.driver.session.return_value.__aenter__.return_value.run = MagicMock(
        side_effect=fake_run
    )
    result = asyncio.run(svc.query_procedures(project="CORE"))
    assert len(result) == 1


def test_record_usage():
    svc = _make_service()
    procedure_data = {"procedure_id": "proc1", "usage_count": 5}

    async def fake_run(query, **kwargs):
        class FakeResult:
            async def __aiter__(self):
                pass

            async def single(self):
                m = MagicMock()
                m.__getitem__ = lambda self, key: procedure_data if key == "procedure" else None
                return m

        return FakeResult()

    svc.neo4j.driver.session.return_value.__aenter__.return_value.run = MagicMock(
        side_effect=fake_run
    )
    result = asyncio.run(svc.record_usage("proc1", success=True))
    assert result["procedure_id"] == "proc1"


def test_procedure_model_defaults():
    proc = ProceduralMemory(
        procedure_id="p1", project="CORE", task_type="refactor", steps=["step1"]
    )
    assert proc.success_rate == 1.0
    assert proc.usage_count == 0
