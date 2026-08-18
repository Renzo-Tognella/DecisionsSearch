from unittest.mock import AsyncMock, MagicMock
import pytest
from decisionssearch.application.agents.cognitive_reflection_service import CognitiveReflectionService

@pytest.mark.asyncio
async def test_reflection_updates_procedural_usage():
    neo4j = MagicMock()
    procedural = MagicMock()
    procedural.record_usage = AsyncMock(return_value={"status": "updated"})
    weight = MagicMock()
    telemetry = MagicMock()
    extraction = MagicMock()
    
    service = CognitiveReflectionService(
        neo4j=neo4j,
        procedural_memory=procedural,
        weight_service=weight,
        telemetry=telemetry,
        extraction=extraction
    )
    
    state = MagicMock()
    state.served_procedure_ids = ["proc-123"]
    state.retrieved_memory_ids = []
    
    await service.reflect_on_task(state, "completed", "Task", "Changes")
    procedural.record_usage.assert_awaited_once_with("proc-123", success=True)

@pytest.mark.asyncio
async def test_reflection_calibrates_memory_weights():
    neo4j = MagicMock()
    neo4j.get_memory = AsyncMock(return_value={
        "memory_id": "mem-1",
        "category": "DesignPattern",
        "weight_manual": 0.5,
        "weight_usage": 0.2,
        "weight_confidence": 0.5,
        "weight_feedback": 0.5,
    })
    neo4j.set_weight = AsyncMock()
    
    weight = MagicMock()
    weight.reinforce_on_retrieval.return_value = (0.6, 0.25)
    weight.update_on_feedback.return_value = 0.3
    weight.get_priority_config.return_value = MagicMock()
    weight.calculate_effective_weight.return_value = 0.7
    
    telemetry = MagicMock()
    procedural = MagicMock()
    
    service = CognitiveReflectionService(
        neo4j=neo4j,
        procedural_memory=procedural,
        weight_service=weight,
        telemetry=telemetry,
    )
    
    state = MagicMock()
    state.served_procedure_ids = []
    state.retrieved_memory_ids = ["mem-1"]
    
    await service.reflect_on_task(state, "completed", "Task", "Changes")
    weight.reinforce_on_retrieval.assert_called_once()
    neo4j.set_weight.assert_awaited_once_with("mem-1", 0.6, 0.7)
    
    neo4j.set_weight.reset_mock()
    weight.update_on_feedback.reset_mock()
    weight.calculate_effective_weight.return_value = 0.4
    await service.reflect_on_task(state, "failed", "Task", "Changes")
    weight.update_on_feedback.assert_called_once_with(0.5, 0.0)
    neo4j.set_weight.assert_awaited_once_with("mem-1", 0.5, 0.4)

@pytest.mark.asyncio
async def test_extracts_lessons_learned():
    neo4j = MagicMock()
    extraction = MagicMock()
    extraction._structured_client = MagicMock()
    
    mock_choice = MagicMock()
    mock_choice.message.content = '{"lessons": ["lesson one", "lesson two"]}'
    mock_result = MagicMock()
    mock_result.choices = [mock_choice]
    extraction.client = MagicMock()
    extraction.client.chat.completions.create = AsyncMock(return_value=mock_result)
    extraction.model = "gpt-4o-mini"
    
    service = CognitiveReflectionService(
        neo4j=neo4j,
        extraction=extraction
    )
    
    lessons = await service.extract_lessons("Fix sazonalizacao MWh calculation", "Changed rounding rules", "failed")
    assert "lesson one" in lessons
