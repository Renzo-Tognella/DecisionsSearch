from decisionssearch.application.agents.agent_loop_service import AgentLoopService
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_service():
    return AgentLoopService(
        search=MagicMock(),
        extraction=MagicMock(),
        admission=MagicMock(),
        persistence=MagicMock(),
    )


def test_compact_context_limits_items():
    svc = _make_service()
    context = {
        "design_rules": [
            {
                "memory_id": f"m{i}",
                "title": f"Rule {i}",
                "summary": "x" * 300,
                "effective_weight": 0.5 + i * 0.1,
            }
            for i in range(10)
        ]
    }
    result = svc.compact_context(context)
    assert len(result["design_rules"]) == 3


def test_compact_context_preserves_top_weights():
    svc = _make_service()
    context = {
        "rules": [
            {"memory_id": "low", "title": "Low", "summary": "s", "effective_weight": 0.1},
            {"memory_id": "high", "title": "High", "summary": "s", "effective_weight": 0.9},
            {"memory_id": "mid", "title": "Mid", "summary": "s", "effective_weight": 0.5},
        ]
    }
    result = svc.compact_context(context)
    ids = [item["memory_id"] for item in result["rules"]]
    assert ids[0] == "high"


def test_compact_context_truncates_summary():
    svc = _make_service()
    context = {
        "rules": [{"memory_id": "m1", "title": "T", "summary": "x" * 500, "effective_weight": 0.5}]
    }
    result = svc.compact_context(context)
    assert len(result["rules"][0]["summary"]) <= 200


def test_compact_context_passes_through_non_lists():
    svc = _make_service()
    context = {"key": "value"}
    result = svc.compact_context(context)
    assert result["key"] == "value"


@pytest.mark.asyncio
async def test_post_task_summary_invokes_cognitive_reflection():
    search = MagicMock()
    extraction = MagicMock()
    extraction.extract_candidates = AsyncMock(return_value=[])
    admission = MagicMock()
    persistence = MagicMock()
    
    reflection = MagicMock()
    reflection.reflect_on_task = AsyncMock(return_value={"status": "reflected", "lessons": ["L1"]})
    
    svc = AgentLoopService(
        search=search,
        extraction=extraction,
        admission=admission,
        persistence=persistence,
        reflection_service=reflection,
    )
    svc._last_task_state = MagicMock()
    
    await svc.post_task_summary(
        task_description="Refactor CCEE",
        changes="Clean code",
        project="CORE",
        outcome="failed"
    )
    
    reflection.reflect_on_task.assert_awaited_once()
