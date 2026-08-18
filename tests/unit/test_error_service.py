from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from decisionssearch.domain.incidents.error_event import ErrorEvent
from decisionssearch.application.error_investigation.error_service import ErrorService


@pytest.fixture
def error_service():
    neo4j = AsyncMock()
    return ErrorService(neo4j=neo4j)


class TestErrorService:
    @pytest.mark.asyncio
    async def test_ingest_creates_error_node(self, error_service):
        event = ErrorEvent(
            error_type="ValueError",
            error_message="test error",
            service="test-svc",
            stack_trace='File "app.py", line 42, in handler',
        )
        error_service.neo4j.execute_write.return_value = None

        result = await error_service.ingest_error(event)
        assert result.error_id == event.error_id
        assert result.stack_trace_hash
        error_service.neo4j.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_duplicate_increments_count(self, error_service):
        event = ErrorEvent(
            error_type="ValueError", error_message="test",
            service="test-svc", stack_trace='File "app.py", line 1',
        )
        error_service.neo4j.execute_write.return_value = [{"outcome": "duplicate", "count": 5}]

        result = await error_service.ingest_error(event)
        assert result.count == 5

    @pytest.mark.asyncio
    async def test_find_suspect_prs(self, error_service):
        error_service.neo4j.execute_read.return_value = [
            {"file_path": "app.py", "pr_number": 42, "pr_title": "Fix", "confidence_pct": 85.0},
        ]
        results = await error_service.find_suspect_prs("err-1")
        assert len(results) == 1
        assert results[0]["pr_number"] == 42

    @pytest.mark.asyncio
    async def test_list_errors(self, error_service):
        error_service.neo4j.execute_read.return_value = [
            {"e": {"error_id": "e1", "error_type": "ValueError", "severity": "HIGH", "service": "s1", "status": "open"}},
        ]
        results = await error_service.list_errors()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_errors_with_type_filter(self, error_service):
        error_service.neo4j.execute_read.return_value = []
        await error_service.list_errors(error_type="ValueError")
        call_kwargs = error_service.neo4j.execute_read.call_args
        assert "error_type" in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_get_investigation(self, error_service):
        error_service.neo4j.execute_read.return_value = [{"inv": {"status": "completed", "findings": "root cause found"}}]
        result = await error_service.get_investigation("err-1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_investigation_not_found(self, error_service):
        error_service.neo4j.execute_read.return_value = []
        result = await error_service.get_investigation("err-nonexistent")
        assert result is None
