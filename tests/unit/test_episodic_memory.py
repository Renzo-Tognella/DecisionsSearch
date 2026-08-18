import asyncio
from unittest.mock import AsyncMock, MagicMock

from decisionssearch.domain.episodic.episodic_memory import EpisodicMemory, EpisodeStatus
from decisionssearch.application.memory.episodic_memory_service import EpisodicMemoryService


def _make_service():
    neo4j = MagicMock()
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    neo4j.driver = driver
    session.run = AsyncMock()
    return EpisodicMemoryService(neo4j=neo4j)


def test_create_episode():
    svc = _make_service()
    episode = EpisodicMemory(
        episode_id="ep1",
        project="CORE",
        task_description="Fix auth bug",
        approach="Added JWT validation",
        outcome=EpisodeStatus.COMPLETED,
        lessons=["Always validate tokens server-side"],
    )
    result = asyncio.run(svc.create_episode(episode))
    assert result["episode_id"] == "ep1"
    assert result["status"] == "created"


def test_query_episodes():
    svc = _make_service()
    records = [{"episode": {"episode_id": "ep1", "task_description": "T"}}]

    async def fake_run(query, **kwargs):
        class FakeResult:
            async def __aiter__(self):
                for r in records:
                    yield MagicMock(data=lambda r=r: r)

        return FakeResult()

    svc.neo4j.driver.session.return_value.__aenter__.return_value.run = MagicMock(
        side_effect=fake_run
    )
    result = asyncio.run(svc.query_episodes(project="CORE"))
    assert len(result) == 1


def test_episode_model_defaults():
    ep = EpisodicMemory(episode_id="ep1", project="CORE", task_description="T")
    assert ep.outcome == EpisodeStatus.COMPLETED
    assert ep.lessons == []
    assert ep.related_memory_ids == []
