from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

from decisionssearch.domain.shared.exceptions import MemoryServiceError
from decisionssearch.bootstrap.container import ServiceContainer
from decisionssearch.interfaces.mcp.tools import register_tools


@dataclass
class FakeMCPApp:
    tools: dict[str, object] = field(default_factory=dict)

    def tool(self, name: str | None = None):
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return decorator


def _make_container():
    c = MagicMock(spec=ServiceContainer)
    c.agent_loop = MagicMock()
    c.agent_loop.pre_task_context = AsyncMock(
        return_value={
            "design_rules": [{"title": "R1", "memory_id": "m1"}],
            "patterns": [],
            "architectural_decisions": [],
        }
    )
    c.agent_loop.post_task_summary = AsyncMock(
        return_value={
            "candidates_extracted": 1,
            "memories_created": 1,
            "memories_updated": 0,
            "rejected": 0,
            "details": [{"title": "T", "action": "create", "status": "active", "reason": "ok"}],
        }
    )
    c.sanitization = MagicMock()
    c.sanitization.sanitize = MagicMock(side_effect=lambda x: x)
    c.sanitization.sanitize_output = MagicMock(side_effect=lambda x: x)
    return c


def test_memory_context_tool_calls_pre_task_context():
    app = FakeMCPApp()
    c = _make_container()
    register_tools(app, c)

    result = asyncio.run(app.tools["memory.context"](project="CORE", domain="billing"))

    c.agent_loop.pre_task_context.assert_awaited_once_with(project="CORE", domain="billing")
    assert result["design_rules"] == [{"title": "R1", "memory_id": "m1"}]
    assert result["patterns"] == []
    assert result["architectural_decisions"] == []


def test_memory_context_tool_sanitizes_output():
    app = FakeMCPApp()
    c = _make_container()
    register_tools(app, c)

    asyncio.run(app.tools["memory.context"](project="CORE"))

    c.sanitization.sanitize_output.assert_called_once()


def test_memory_context_tool_handles_error():
    app = FakeMCPApp()
    c = _make_container()
    c.agent_loop.pre_task_context = AsyncMock(side_effect=MemoryServiceError("context failed"))
    register_tools(app, c)

    result = asyncio.run(app.tools["memory.context"](project="CORE"))

    assert result == {"error": "context failed", "type": "MemoryServiceError"}


def test_memory_reflect_tool_calls_post_task_summary():
    app = FakeMCPApp()
    c = _make_container()
    register_tools(app, c)

    result = asyncio.run(
        app.tools["memory.reflect"](
            task_description="Add billing endpoint",
            changes="Created /api/billing",
            project="CORE",
        )
    )

    c.agent_loop.post_task_summary.assert_awaited_once_with(
        task_description="Add billing endpoint",
        changes="Created /api/billing",
        project="CORE",
        outcome="completed",
    )
    assert result["candidates_extracted"] == 1
    assert result["memories_created"] == 1
    assert len(result["details"]) == 1


def test_memory_reflect_tool_sanitizes_input_and_output():
    app = FakeMCPApp()
    c = _make_container()
    register_tools(app, c)

    asyncio.run(
        app.tools["memory.reflect"](
            task_description="Add billing endpoint",
            changes="Created /api/billing",
            project="CORE",
        )
    )

    assert c.sanitization.sanitize.call_count == 2
    c.sanitization.sanitize_output.assert_called_once()


def test_memory_reflect_tool_handles_error():
    app = FakeMCPApp()
    c = _make_container()
    c.agent_loop.post_task_summary = AsyncMock(side_effect=MemoryServiceError("reflect failed"))
    register_tools(app, c)

    result = asyncio.run(
        app.tools["memory.reflect"](
            task_description="Add billing endpoint",
            changes="Created /api/billing",
            project="CORE",
        )
    )

    assert result == {"error": "reflect failed", "type": "MemoryServiceError"}


def test_memory_capture_commit_passes_session_and_pr_context():
    app = FakeMCPApp()
    c = _make_container()
    c.commit_memory = MagicMock()
    c.commit_memory.capture = AsyncMock(
        return_value={"status": "no_memory", "decision": "no_memory"}
    )
    register_tools(app, c)

    result = asyncio.run(
        app.tools["memory.capture_commit"](
            project="CORE",
            commit_sha="abc123",
            session_context="A decisão foi separar o filtro do ranking.",
            session_id="s-1",
            changed_files=["services/pr_memory_service.py"],
            pull_request_number=42,
            pull_request_url="https://github.com/acme/core/pull/42",
        )
    )

    assert result["decision"] == "no_memory"
    c.commit_memory.capture.assert_awaited_once()
    context = c.commit_memory.capture.await_args.args[0]
    assert context.commit.sha == "abc123"
    assert context.session_id == "s-1"
    assert context.pull_request.number == 42


def test_agent_loop_tools_are_registered():
    app = FakeMCPApp()
    c = _make_container()
    register_tools(app, c)

    assert "memory.context" in app.tools
    assert "memory.reflect" in app.tools
    assert "memory.capture_commit" in app.tools


def test_container_wires_reflection_service():
    from decisionssearch.bootstrap.container import create_container
    container = create_container()
    assert container.agent_loop.reflection_service is not None
