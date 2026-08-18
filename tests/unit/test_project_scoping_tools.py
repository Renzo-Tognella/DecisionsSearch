from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from decisionssearch.interfaces.mcp.tools import register_tools


@dataclass
class FakeMCPApp:
    tools: dict[str, object] = field(default_factory=dict)

    def tool(self, name: str | None = None):
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return decorator


@dataclass
class FakeManualAuthoring:
    calls: list[object] = field(default_factory=list)

    async def create_manual_memory(self, command):
        self.calls.append(command)
        return {"project": command.project, "status": "proposed"}


@dataclass
class FakeSearch:
    calls: list[dict] = field(default_factory=list)

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return []


@dataclass
class FakeTelemetry:
    retrievals: list[str] = field(default_factory=list)

    def record_retrieval(self, memory_id: str) -> None:
        self.retrievals.append(memory_id)


@dataclass
class FakeContainer:
    manual_memory_authoring: FakeManualAuthoring
    search: FakeSearch
    telemetry: FakeTelemetry


def test_memory_manual_create_uses_workspace_folder_as_project(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    project_dir = tmp_path / "billing-service"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    container = FakeContainer(FakeManualAuthoring(), FakeSearch(), FakeTelemetry())
    app = FakeMCPApp()
    register_tools(app, container)

    result = asyncio.run(
        app.tools["memory.manual.create"](
            category="DesignRule",
            title="Cache key",
            summary="Use the tenant in the cache key",
        )
    )

    assert result["project"] == "billing-service"
    assert container.manual_memory_authoring.calls[0].project == "billing-service"


def test_memory_query_filters_by_workspace_before_hybrid_search(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISIONSSEARCH_PROJECT", raising=False)
    project_dir = tmp_path / "billing-service"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    container = FakeContainer(FakeManualAuthoring(), FakeSearch(), FakeTelemetry())
    app = FakeMCPApp()
    register_tools(app, container)

    result = asyncio.run(
        app.tools["memory.query"](query_text="cache key convention")
    )

    assert result == []
    assert container.search.calls[0]["project"] == "billing-service"
